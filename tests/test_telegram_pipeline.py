"""Offline approval workflow: isolated SQLite, fake Telegram updates, no network."""
import asyncio
import json
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import unittest
import test_system as system
from bureau.config import Config
from bureau.content import everyday_candidates, relevant_news, validate_candidates, validate_draft
from bureau.store import Store
from bureau.telegram_app import build_app
from bureau.telegram_identity import exported_user_id
from bot import scheduled_window


class TelegramPipelineTests(unittest.TestCase):
    setUp=system.SystemTest.setUp
    tearDown=system.SystemTest.tearDown
    q=system.SystemTest.q
    candidates=system.SystemTest.candidates
    preview=system.SystemTest.preview

    def app(self):
        config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1','TELEGRAM_BOT_TOKEN':'123456:OFFLINE_ONLY_012345678901234567890123456789','TELEGRAM_CHAT_ID':'22','TELEGRAM_ALLOWED_USER_IDS':'11'})
        app=build_app(config)
        self.callback=next(h.callback for h in app.handlers[0] if h.__class__.__name__=='CallbackQueryHandler')
        self.message=next(h.callback for h in app.handlers[0] if h.__class__.__name__=='MessageHandler')
        self.commands={next(iter(h.commands)):h.callback for h in app.handlers[0] if getattr(h,'commands',None)}
        return app

    def click(self,data,uid=11,update_id=100):
        update=NS(effective_user=NS(id=uid),effective_chat=NS(id=22,type='private'),update_id=update_id,
                  callback_query=NS(data=data,answer=AsyncMock()))
        asyncio.run(self.callback(update,NS()))
        return update

    def send(self,text,update_id=101,uid=11):
        update=NS(effective_user=NS(id=uid),effective_chat=NS(id=22,type='private'),update_id=update_id,message=NS(text=text))
        asyncio.run(self.message(update,NS()))

    def test_buttons_plan_revision_render_image_revision_and_publish(self):
        self.app();cid=self.candidates()
        self.click(f'candidate:{cid}');self.click(f'candidate:{cid}')
        rid=self.q('SELECT id FROM selections')[0]['id']
        self.engine.run_one()
        self.assertEqual(self.store.row(rid)['status'],'planning_review')
        self.assertFalse(self.q("SELECT * FROM jobs WHERE kind='render'"))
        self.click(f'approve:{rid}:1')
        self.assertFalse(self.q("SELECT * FROM jobs WHERE kind='publish'"))
        self.click(f'planedit:{rid}:1')
        # Simulate process restart: state exists independently of app memory.
        self.store=Store(self.path);self.app()
        self.send('마지막 판정을 한 문장으로 줄여주세요.');self.send('마지막 판정을 한 문장으로 줄여주세요.')
        self.assertEqual(self.store.row(rid)['revision'],2)
        self.engine.run_one();self.click(f'planapprove:{rid}:1')
        self.assertFalse(self.q("SELECT * FROM jobs WHERE kind='render'"))
        self.click(f'planapprove:{rid}:2');self.click(f'planapprove:{rid}:2')
        self.assertEqual(len(self.q("SELECT * FROM jobs WHERE kind='render'")),1)
        self.engine.run_one();self.assertEqual(self.store.row(rid)['status'],'preview_ready')
        previous=json.loads(self.store.row(rid)['draft_json'])
        self.click(f'imageedit:{rid}:2');self.send('텅 빈 책상 사진으로 변경해주세요.',102)
        self.assertEqual(self.store.row(rid)['revision'],3)
        self.assertEqual(json.loads(self.store.row(rid)['draft_json'])['slides'],previous['slides'])
        calls=self.claude.calls;self.engine.run_one();self.assertEqual(self.claude.calls,calls)
        self.click(f'approve:{rid}:2');self.assertFalse(self.q("SELECT * FROM jobs WHERE kind='publish'"))
        self.click(f'approve:{rid}:3');self.click(f'approve:{rid}:3')
        self.assertEqual(len(self.q("SELECT * FROM jobs WHERE kind='publish'")),1)
        self.instagram.active=True;self.engine.run_one()
        self.assertEqual(self.instagram.published,1)
        texts=' '.join(json.loads(r['payload']).get('text','') for r in self.q('SELECT payload FROM outbox'))
        self.assertIn('https://www.instagram.com/p/offline-only/',texts)

    def test_cancel_and_allowlist(self):
        self.app();rid=self.preview()
        self.click(f'approve:{rid}:1',uid=99)
        self.assertEqual(self.store.row(rid)['status'],'preview_ready')
        self.click(f'reject:{rid}:1');self.click(f'approve:{rid}:1')
        self.assertEqual(self.store.row(rid)['status'],'rejected')
        self.assertFalse(self.q("SELECT * FROM jobs WHERE kind='publish'"))

    def test_pending_revision_cannot_override_approval(self):
        self.app();rid=self.preview()
        self.click(f'planedit:{rid}:1');self.click(f'approve:{rid}:1');self.send('새로운 수정 요청')
        self.assertEqual(self.store.row(rid)['revision'],1)
        self.assertEqual(self.store.row(rid)['status'],'approved')

    def test_return_to_candidates_and_batch_regeneration(self):
        self.app();cid=self.candidates();rid=self.store.select(cid);self.engine.run_one()
        self.click(f'back:{rid}:1');self.assertEqual(self.store.row(rid)['status'],'rejected')
        batch=self.q('SELECT id FROM batches')[0]['id']
        self.click(f'batchregen:{batch}');self.click(f'batchregen:{batch}',update_id=200)
        self.assertEqual(len(self.q('SELECT * FROM batches')),2)

    def test_curated_no_news_no_model_and_rubric(self):
        self.engine.config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1'})
        with patch.object(self.engine,'news',side_effect=AssertionError('RSS forbidden')),patch.object(self.claude,'generate',side_effect=AssertionError('Claude forbidden')):
            self.store.schedule();self.engine.run_one()
        rows=self.q('SELECT payload FROM candidates')
        self.assertEqual(len(rows),3)
        values=[json.loads(r['payload']) for r in rows]
        self.assertEqual(len({r['situation_key'] for r in values}),3)
        self.assertTrue(all(r['source_url'] is None and r['quality']['score']==100 for r in values))
        d=system.draft('');d['source_url']=None;validate_draft(d,None)

    def test_bad_news_and_repeated_situations_rejected(self):
        news=[{'title':'증시 전망','url':'https://example.org/1'}, {'title':'엘리베이터 사망 참사','url':'https://example.org/2'}]
        self.assertEqual(relevant_news(news),[])
        d=everyday_candidates('2026-10-30');d['candidates'][1]=dict(d['candidates'][0])
        with self.assertRaises(ValueError):validate_candidates(d,[])

    def test_scheduled_window_and_audit(self):
        self.assertTrue(scheduled_window(dt.datetime(2026,10,30,9,0,tzinfo=dt.timezone.utc)))
        for hour,minute in [(15,56),(0,56),(9,5),(8,59)]:
            self.assertFalse(scheduled_window(dt.datetime(2026,10,30,hour,minute,tzinfo=dt.timezone.utc)))
        self.store.schedule(source='vm_timer');self.store.schedule(source='vm_timer')
        events=self.q("SELECT detail FROM events WHERE action='scheduled'")
        self.assertEqual(len(events),1);self.assertEqual(json.loads(events[0]['detail'])['source'],'vm_timer')

    def test_local_identity_extract_never_exposes_other_fields(self):
        path=self.path.parent/'export.json'
        path.write_text(json.dumps({'personal_information':{'user_id':123,'phone_number':'PRIVATE'}}))
        self.assertEqual(exported_user_id(path),'123')
        path.write_text('PRIVATE')
        with self.assertRaises(ValueError) as exc:exported_user_id(path)
        self.assertNotIn('PRIVATE',str(exc.exception))

    def test_missing_permalink_resume_never_republishes(self):
        rid=self.preview();self.store.decide(rid,1,True,confirm_review=True);self.instagram.active=True
        with patch.object(self.instagram,'permalink',side_effect=TimeoutError('SECRET')):self.engine.run_one()
        self.assertEqual(self.store.row(rid)['status'],'published')
        from bureau.cli import resume
        job=self.q("SELECT id FROM jobs WHERE kind='publish'")[0]['id']
        resume(self.store,job);self.engine.run_one()
        self.assertEqual(self.instagram.published,1)

    def test_model_timeout_falls_back_without_repeated_paid_request(self):
        self.engine.config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1','CANDIDATE_GENERATION_MODE':'model'})
        self.claude.fail=True;self.store.schedule();self.engine.run_one()
        self.assertEqual(len(self.q('SELECT * FROM candidates')),3)
        self.assertEqual(self.q('SELECT state FROM checkpoints')[0]['state'],'uncertain')
        self.assertFalse(self.engine.run_one());self.assertEqual(self.claude.calls,1)

    def test_expired_scheduled_delivery_does_not_send_at_midnight(self):
        with self.store.tx() as c:
            self.store.notify(c,'expired-daily',{'text':'daily candidates','expires_at':'2000-01-01T09:05:00+00:00'})
        self.assertTrue(self.engine.deliver_one())
        self.assertEqual(self.telegram.calls,0)
        self.assertEqual(self.q('SELECT state FROM outbox')[0]['state'],'expired')

    def test_three_seed_batches_have_distinct_situations(self):
        keys=[]
        for generation in range(3):
            keys.extend(c['situation_key'] for c in everyday_candidates('2026-10-30',generation)['candidates'])
        self.assertEqual(len(set(keys)),9)


if __name__=='__main__':unittest.main()
