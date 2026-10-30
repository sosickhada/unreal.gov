import asyncio
import concurrent.futures
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch, AsyncMock
from types import SimpleNamespace as NS
import test_system as system
from bureau.config import Config
from bureau.store import Store
from bureau.engine import Engine
from bureau.content import distinct_news, draft_quality, fetch_news, NewsFailure
from bureau.adapters import Media, ExternalError
from bureau.operations import backup_database,readiness
from bureau.cli import resume


class ProductionPipelineTests(unittest.TestCase):
    setUp=system.SystemTest.setUp
    tearDown=system.SystemTest.tearDown
    q=system.SystemTest.q
    candidates=system.SystemTest.candidates
    preview=system.SystemTest.preview
    approve=system.SystemTest.approve

    def test_streamed_rss_to_three_saved_candidate_buttons(self):
        import datetime as dt
        import email.utils
        from bureau.engine import candidate_message
        stamp=email.utils.format_datetime(dt.datetime.now(dt.timezone.utc))
        xml='<rss><channel>'+''.join(f'<item><title>{n["title"]}</title><link>{n["url"]}</link><pubDate>{stamp}</pubDate></item>' for n in system.NEWS)+'</channel></rss>'
        response=Mock();response.iter_content.return_value=iter([xml.encode()[:50],xml.encode()[50:]])
        http=Mock();http.get.return_value=response
        self.engine.news=lambda:fetch_news(http)
        self.store.schedule();self.engine.run_one()
        rows=self.q('SELECT * FROM candidates ORDER BY position');self.assertEqual(len(rows),3)
        with self.store.tx() as c:message=candidate_message(c,rows[0]['batch_id'])
        buttons=message['reply_markup']['inline_keyboard'][:3]
        self.assertEqual([b[0]['callback_data'] for b in buttons],[f'candidate:{r["id"]}' for r in rows])
        self.assertTrue(all(r['created_at'] and r['status']=='available' for r in rows))
        response.close.assert_called_once()

    def test_streamed_rss_rejects_oversized_response(self):
        http=Mock();http.get.return_value.iter_content.return_value=iter([b'x'*2_000_001])
        with self.assertRaises(NewsFailure):fetch_news(http)
        http.get.return_value.close.assert_called_once()

    def test_duplicate_feed_items_do_not_consume_diversity_limit(self):
        import datetime as dt
        import email.utils
        from bureau.content import parse_news
        stamp=email.utils.format_datetime(dt.datetime.now(dt.timezone.utc))
        titles=['퇴근 뒤 업무 연락 차단 논의가 계속됩니다']*25+['대학생 도서관 좌석 예약 방식 조정 안내','생활비 부담으로 달라지는 주거비 지출 현황']
        xml='<rss><channel>'+''.join(f'<item><title>{title}</title><link>https://news.example/{i}</link><pubDate>{stamp}</pubDate></item>' for i,title in enumerate(titles))+'</channel></rss>'
        self.assertEqual(len(parse_news(xml,limit=3)),3)

    def test_finite_topic_fallback_supplies_three_fresh_stories(self):
        import datetime as dt
        import email.utils
        stamp=email.utils.format_datetime(dt.datetime.now(dt.timezone.utc))
        responses=[]
        for news in [system.NEWS[:1],system.NEWS[1:]]:
            xml='<rss><channel>'+''.join(f'<item><title>{n["title"]}</title><link>{n["url"]}</link><pubDate>{stamp}</pubDate></item>' for n in news)+'</channel></rss>'
            response=Mock();response.iter_content.return_value=iter([xml.encode()]);responses.append(response)
        http=Mock();http.get.side_effect=responses
        self.assertEqual(len(fetch_news(http)),3);self.assertEqual(http.get.call_count,2)

    def test_long_source_links_keep_all_candidate_text_visible(self):
        from bureau.engine import candidate_message
        self.candidates()
        with self.store.tx() as c:
            rows=c.execute('SELECT id,payload,batch_id FROM candidates ORDER BY position').fetchall()
            for row in rows:
                payload=json.loads(row['payload']);payload['source_url']='https://news.example/'+('a'*1800)
                c.execute('UPDATE candidates SET payload=? WHERE id=?',(json.dumps(payload),row['id']))
            message=candidate_message(c,rows[0]['batch_id'])
        self.assertLess(len(message['text']),4000)
        self.assertEqual(len(message['reply_markup']['inline_keyboard'][0][1]['url']),1821)

    def test_similar_news_and_tracking_urls_removed(self):
        items=[{'title':'직장인 퇴근 뒤 업무 연락 금지 논의 확대 - 가신문','url':'https://news.example/a?utm_source=one'},
               {'title':'직장인 퇴근 뒤 업무 연락 금지 논의 확대 - 나신문','url':'https://news.example/b'},
               {'title':'완전히 다른 제목','url':'https://news.example/a?utm_source=two#fragment'},
               {'title':'대학생 시험 기간 도서관 이용 현황','url':'https://news.example/c'}]
        self.assertEqual(len(distinct_news(items)),2)

    def test_rss_failure_is_redacted_and_distinct(self):
        http=Mock();http.get.side_effect=TimeoutError('secret provider URL')
        with self.assertRaises(NewsFailure) as ctx:fetch_news(http)
        self.assertNotIn('secret',str(ctx.exception))
        self.engine.news=lambda:fetch_news(http)
        self.store.schedule();self.engine.run_one()
        self.assertEqual(self.q('SELECT state FROM jobs')[0]['state'],'succeeded')
        self.assertEqual(len(self.q('SELECT * FROM candidates')),3)

    def test_invalid_candidate_response_saved_without_paid_retry(self):
        original=self.claude.generate
        def invalid(*args):
            r=original(*args);r['raw']='not JSON';return r
        self.claude.generate=invalid
        self.store.schedule();self.engine.run_one()
        job=self.q('SELECT * FROM jobs')[0]
        self.assertEqual(job['state'],'succeeded')
        self.assertEqual(len(self.q('SELECT * FROM candidates')),3)
        self.assertFalse(self.engine.run_one())
        self.assertEqual(self.claude.calls,1)

    def test_quality_gate_acceptance_and_revision(self):
        cid=self.candidates();rid=self.store.select(cid)
        original=self.claude.generate
        def poor(*args):
            r=original(*args);d=json.loads(r['raw']);d['slides'][1]['body']='가상 사건은 시사하는 바가 큽니다.';r['raw']=json.dumps(d);return r
        self.claude.generate=poor;self.engine.run_one()
        self.assertEqual(self.store.row(rid)['status'],'draft_review')
        self.assertFalse(self.q("SELECT * FROM jobs WHERE kind='render'"))
        with self.assertRaises(ValueError):self.store.decide(rid,1,True)
        self.store.accept_draft(rid,1)
        with self.assertRaises(ValueError): self.store.accept_draft(rid,1)
        self.assertEqual(len(self.q("SELECT * FROM jobs WHERE kind='render'")),1)
        self.engine.run_one();self.assertEqual(self.store.row(rid)['status'],'preview_ready')
        self.assertEqual(self.claude.calls,2)
        self.assertFalse(self.q("SELECT * FROM jobs WHERE kind='draft' AND state='waiting'"))

    def test_new_revision_never_labels_previous_draft_as_current(self):
        rid=self.preview();previous=self.store.row(rid)['draft_json']
        self.store.revise(rid,'결의문을 짧게 수정')
        self.assertIsNone(self.store.row(rid)['draft_json'])
        self.assertIsNone(self.store.row(rid)['image_paths'])
        history=self.q('SELECT payload FROM draft_versions WHERE selection_id=? AND revision=1',(rid,))
        self.assertEqual(history[0]['payload'],previous)

    def test_invalid_draft_remains_reviewable_without_new_call(self):
        cid=self.candidates();rid=self.store.select(cid)
        original=self.claude.generate
        def invalid(*args):
            result=original(*args);result['raw']='invalid response';return result
        self.claude.generate=invalid;self.engine.run_one()
        self.assertEqual(self.store.row(rid)['status'],'draft_invalid')
        self.assertFalse(self.q("SELECT * FROM jobs WHERE kind='render'"))
        with self.assertRaises(ValueError):self.store.accept_draft(rid,1)
        self.assertEqual(self.claude.calls,2)
        self.store.revise(rid,'출처를 유지하고 문장 수정')

    def test_quality_detects_repetition_long_sentences_and_fiction_boundary(self):
        d=system.draft(system.NEWS[0]['url'])
        d['slides'][1]['body']='같은 문장을 반복합니다. 같은 문장을 반복합니다.'
        self.assertIn('repeated_sentence',draft_quality(d))
        self.assertIn('fiction_boundary_unclear',draft_quality(d))
        d['slides'][1]['body']='가상 '+('긴 문장 '*30)+'.'
        self.assertIn('long_sentence',draft_quality(d))

    def test_concurrent_approvals_enqueue_one_publication(self):
        rid=self.preview();self.store.review(rid,1)
        def approve(_):
            try:self.store.decide(rid,1,True);return True
            except ValueError:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(approve,range(16))),1)
        self.assertEqual(len(self.q("SELECT * FROM jobs WHERE kind='publish'")),1)
        self.instagram.active=True;self.engine.run_one()
        self.assertEqual(self.instagram.published,1)
        self.assertEqual(self.q('SELECT state FROM publications')[0]['state'],'published')

    def test_publication_uncertainty_preserves_write_state(self):
        self.approve();self.instagram.active=True;self.instagram.fail=True;self.engine.run_one()
        self.assertEqual(self.q('SELECT state FROM publications')[0]['state'],'uncertain')
        self.assertFalse(self.engine.run_one());self.assertEqual(self.instagram.published,1)

    def test_private_preview_does_not_expose_or_fetch_public_assets(self):
        self.engine.config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1','REQUIRE_TOPIC_IMAGE':'0','RENDER_DIR':'private'})
        rid=self.preview()
        self.assertEqual(self.media.verifications,0)
        self.assertEqual(self.store.row(rid)['status'],'preview_ready')

    def test_approval_delivery_waits_for_successful_album(self):
        self.preview()
        self.engine.deliver_one();self.engine.deliver_one()
        self.telegram.fail=True;self.engine.deliver_one()
        self.assertFalse(self.engine.deliver_one())
        approval=self.q("SELECT state FROM outbox WHERE delivery_key LIKE 'approval:%'")[0]
        self.assertEqual(approval['state'],'queued')
        self.telegram.fail=False
        with self.store.tx() as c:c.execute("UPDATE outbox SET state='queued' WHERE delivery_key LIKE 'media:%'")
        self.engine.deliver_one();self.engine.deliver_one()
        self.assertEqual(self.q("SELECT state FROM outbox WHERE delivery_key LIKE 'approval:%'")[0]['state'],'sent')
        self.assertEqual(self.claude.calls,2)

    def test_telegram_full_commands_and_duplicate_approval(self):
        from bureau.telegram_app import build_app
        rid=self.preview()
        config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1','TELEGRAM_BOT_TOKEN':'123456:OFFLINE_ONLY_012345678901234567890123456789','TELEGRAM_CHAT_ID':'22','TELEGRAM_ALLOWED_USER_IDS':'11'})
        app=build_app(config)
        handlers={next(iter(h.commands)):h.callback for h in app.handlers[0] if getattr(h,'commands',None)}
        callback=next(h.callback for h in app.handlers[0] if h.__class__.__name__=='CallbackQueryHandler')
        update=NS(effective_chat=NS(id=22),effective_user=NS(id=11),update_id=300,message=NS(text=f'/review {rid} 1'))
        asyncio.run(handlers['review'](update,NS(args=[str(rid),'1'])))
        update.callback_query=NS(data=f'approve:{rid}:1',answer=AsyncMock())
        asyncio.run(callback(update,NS()));asyncio.run(callback(update,NS()))
        self.assertEqual(len(self.q("SELECT * FROM jobs WHERE kind='publish'")),1)
        for i,name in enumerate(('candidates','preview','status')):
            update.update_id=301+i;update.message.text='/'+name
            asyncio.run(handlers[name](update,NS(args=[str(rid)])))
        self.assertEqual(self.store.row(rid)['status'],'approved')
        self.assertEqual(self.telegram.calls,0)

    def test_telegram_batch_rejection_and_idempotent_regeneration(self):
        from bureau.telegram_app import build_app
        self.candidates();batch=self.q('SELECT id FROM batches')[0]['id']
        config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1','TELEGRAM_BOT_TOKEN':'123456:OFFLINE_ONLY_012345678901234567890123456789','TELEGRAM_CHAT_ID':'22','TELEGRAM_ALLOWED_USER_IDS':'11'})
        app=build_app(config)
        callback=next(h.callback for h in app.handlers[0] if h.__class__.__name__=='CallbackQueryHandler')
        command=next(h.callback for h in app.handlers[0] if getattr(h,'commands',None) and 'newcandidates' in h.commands)
        update=NS(effective_chat=NS(id=22),effective_user=NS(id=11),update_id=500,message=NS(text='/newcandidates'),callback_query=NS(data=f'batchreject:{batch}',answer=AsyncMock()))
        asyncio.run(callback(update,NS()));asyncio.run(callback(update,NS()))
        self.assertTrue(all(r['status']=='rejected' for r in self.q('SELECT status FROM candidates')))
        update.update_id=501
        asyncio.run(command(update,NS(args=[])));asyncio.run(command(update,NS(args=[])))
        self.assertEqual(len(self.q('SELECT * FROM batches')),2)
        self.assertEqual(self.claude.calls,1)


class OperationalTests(unittest.TestCase):
    def test_changed_preview_cannot_be_sent(self):
        from bureau.adapters import Telegram
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'changed.jpg';path.write_bytes(b'changed')
            config=Config(Path(tmp)/'db',{'ENABLE_EXTERNAL_CALLS':'1','TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'1'})
            with patch('bureau.adapters.requests.post') as post:
                with self.assertRaises(ExternalError):Telegram(config).send({'files':[str(path)],'sha256':['original']})
                post.assert_not_called()

    def test_public_files_require_permission_and_never_overwrite(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'private'/'a.jpg';source.parent.mkdir();source.write_bytes(b'approved bytes')
            public=root/'public';media={'files':[str(source)],'sha256':[hashlib.sha256(source.read_bytes()).hexdigest()]}
            config=Config(root/'db',{'ENABLE_EXTERNAL_CALLS':'1','IMAGE_DIR':str(public)})
            with self.assertRaises(ExternalError):Media(config).expose(media)
            self.assertFalse(public.exists())
            config=Config(root/'db',dict(config.env,ENABLE_PUBLIC_MEDIA='1'))
            Media(config).expose(media);Media(config).expose(media)
            self.assertEqual((public/'a.jpg').read_bytes(),source.read_bytes())
            (public/'a.jpg').write_bytes(b'other version')
            with self.assertRaises(ValueError):Media(config).expose(media)
            self.assertEqual((public/'a.jpg').read_bytes(),b'other version')

    def test_backup_and_migration_preserve_source_and_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'live.db'
            with sqlite3.connect(source) as c:c.execute('CREATE TABLE original(x)');c.execute("INSERT INTO original VALUES('approved')")
            before=source.read_bytes();target=backup_database(source,root/'backups')
            self.assertEqual(target.stat().st_mode&0o777,0o600)
            Store(target).migrate();Store(target).migrate()
            self.assertEqual(source.read_bytes(),before)
            with sqlite3.connect(target) as c:self.assertEqual(c.execute('SELECT x FROM original').fetchone()[0],'approved')
            report=readiness(Config(source,{}))
            self.assertFalse(report['ready_for_worker']);self.assertEqual(source.read_bytes(),before)
