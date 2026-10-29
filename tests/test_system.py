import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from bureau.config import Config
from bureau.store import Store,kst_day,now
from bureau.engine import Engine
from bureau.content import validate_candidates,validate_draft,parse_news
from bureau.cli import resume


NEWS=[{'title':f'기사 {i}','url':f'https://news.example/{i}','published_at':now(),'publisher':'언론사'} for i in range(3)]
CANDIDATES={'candidates':[{'title':f'가상 사건 {i}','summary':'기사 제목에서 확인한 주제','satire_angle':'가상 일상 상황을 풍자','hook':'짧은 훅','source_url':n['url']} for i,n in enumerate(NEWS)]}


def draft(url):
    return {'title':'가상 사건','source_url':url,'claims':[],'caption':'허구 기관의 풍자 창작입니다. 출처: '+url,'slides':[{'eyebrow':'사건 접수','headline':'퇴근 앞의 질문','body':''},{'eyebrow':'가상 사건 경위','headline':'핵심 쟁점','body':'이 가상 사건은 퇴근 직전의 질문을 다룹니다.','emphasis':[]},{'eyebrow':'처분/판정안','headline':'최종 판정','body':'가상 심의 경과입니다.\n\n퇴근 뒤 답변을 허용합니다.','emphasis':[]},{}]}


class FakeClaude:
    def __init__(self): self.calls=0;self.fail=False
    def generate(self,prompt,maximum):
        self.calls+=1
        if self.fail: raise TimeoutError('DO_NOT_EXPOSE_SECRET')
        data=CANDIDATES if maximum==3000 else draft(NEWS[0]['url'])
        return {'raw':json.dumps(data,ensure_ascii=False),'input_tokens':120,'output_tokens':180}


class FakeMedia:
    def __init__(self):self.renders=0;self.verifications=0;self.fail=False
    def render(self,d,r,v):
        self.renders+=1
        return {'files':['/tmp/fake.jpg']*5,'urls':['https://media.example/image.jpg']*5,'sha256':['fake']*5}
    def verify(self,m):
        self.verifications+=1
        if self.fail:raise ConnectionError('PRIVATE_KEY')
        return {'verified':True}


class FakeTelegram:
    def __init__(self):self.calls=0;self.fail=False
    def send(self,p):
        self.calls+=1
        if self.fail:raise TimeoutError('BOT_TOKEN_SECRET')
        return [self.calls]


class FakeInstagram:
    def __init__(self):self.active=False;self.published=0;self.created=0;self.fail=False;self.notready=False
    def enabled(self):return self.active
    def preflight(self):return {'valid':True}
    def child(self,u):self.created+=1;return {'id':str(self.created)}
    def carousel(self,ch,caption):return {'id':'container'}
    def ready(self,c):
        if self.notready:raise RuntimeError('not ready')
        return {'ready':True}
    def publish(self,c):
        self.published+=1
        if self.fail:raise TimeoutError('META_TOKEN')
        return {'id':'published-media'}


class SystemTest(unittest.TestCase):
    def setUp(self):
        self.net=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN'));self.net.start()
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.db'
        self.config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1','REQUIRE_TOPIC_IMAGE':'0'})
        self.store=Store(self.path);self.store.migrate()
        self.claude=FakeClaude();self.media=FakeMedia();self.telegram=FakeTelegram();self.instagram=FakeInstagram()
        self.engine=Engine(self.config,self.claude,self.media,self.telegram,self.instagram,lambda:NEWS)
    def tearDown(self):self.net.stop();self.tmp.cleanup()
    def q(self,sql,args=()):
        with self.store.tx() as c:return [dict(r) for r in c.execute(sql,args)]
    def candidates(self):
        self.store.schedule();self.assertTrue(self.engine.run_one())
        return self.q('SELECT id FROM candidates ORDER BY position')[0]['id']
    def preview(self):
        cid=self.candidates();rid=self.store.select(cid)
        self.assertTrue(self.engine.run_one());self.assertTrue(self.engine.run_one())
        self.assertEqual(self.store.row(rid)['status'],'preview_ready')
        return rid
    def approve(self):
        rid=self.preview();self.store.review(rid,1);self.store.decide(rid,1,True);return rid
    def test_full_pipeline_without_publication_credentials(self):
        rid=self.approve();self.engine.run_one()
        self.assertEqual(self.store.row(rid)['status'],'publish_waiting')
        self.assertEqual(self.instagram.published,0)
        self.assertEqual(self.claude.calls,2)
        self.assertEqual(self.media.renders,1)
        self.assertEqual(len(json.loads(self.q('SELECT payload FROM assets')[0]['payload'])['files']),5)
    def test_official_publication_once(self):
        rid=self.approve();self.instagram.active=True;self.engine.run_one()
        self.assertEqual(self.store.row(rid)['published_id'],'published-media')
        self.assertEqual(self.instagram.published,1)
        self.assertFalse(self.engine.run_one())
        with self.assertRaises(ValueError):self.store.decide(rid,1,True)
        self.assertEqual(self.instagram.published,1)
    def test_parallel_daily_schedule(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            ids=list(pool.map(lambda _:self.store.schedule(),range(24)))
        self.assertEqual(len(set(ids)),1)
        self.assertEqual(len(self.q('SELECT * FROM batches')),1)
    def test_parallel_claim(self):
        self.store.schedule()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rows=list(pool.map(lambda _:self.store.claim(),range(16)))
        self.assertEqual(sum(bool(r) for r in rows),1)
    def test_duplicate_selection_single_draft(self):
        cid=self.candidates()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            ids=list(pool.map(lambda _:self.store.select(cid),range(12)))
        self.assertEqual(len(set(ids)),1)
        self.engine.run_one();self.assertEqual(self.claude.calls,2)
    def test_telegram_failure_no_paid_regeneration(self):
        self.preview();calls=self.claude.calls
        self.telegram.fail=True;self.engine.deliver_one()
        row=self.q('SELECT * FROM outbox ORDER BY id LIMIT 1')[0]
        self.assertEqual(row['state'],'uncertain')
        self.telegram.fail=False
        with self.store.tx() as c:c.execute("UPDATE outbox SET state='queued' WHERE id=?",(row['id'],))
        self.engine.deliver_one();self.assertEqual(self.claude.calls,calls)
    def test_partial_render_failure_resumes_saved_files(self):
        cid=self.candidates();rid=self.store.select(cid);self.engine.run_one()
        self.media.fail=True;self.engine.run_one()
        self.assertEqual(self.media.renders,1);self.assertEqual(len(self.q('SELECT * FROM assets')),1)
        job=self.q("SELECT id FROM jobs WHERE kind='render'")[0]['id']
        self.media.fail=False;resume(self.store,job);self.engine.run_one()
        self.assertEqual(self.media.renders,1);self.assertEqual(self.claude.calls,2)
        self.assertEqual(self.store.row(rid)['status'],'preview_ready')
    def test_paid_unknown_is_not_retryable(self):
        self.claude.fail=True;self.store.schedule();self.engine.run_one()
        job=self.q('SELECT * FROM jobs')[0]
        self.assertEqual(job['state'],'uncertain')
        with self.assertRaises(ValueError):resume(self.store,job['id'])
        self.assertFalse(self.engine.run_one());self.assertEqual(self.claude.calls,1)
        self.assertNotIn('DO_NOT_EXPOSE_SECRET',json.dumps(self.q('SELECT * FROM events')))
    def test_unknown_publish_is_never_replayed(self):
        rid=self.approve();self.instagram.active=True;self.instagram.fail=True;self.engine.run_one()
        j=self.q("SELECT * FROM jobs WHERE kind='publish'")[0]
        self.assertEqual(j['state'],'uncertain');self.assertEqual(self.instagram.published,1)
        with self.assertRaises(ValueError):resume(self.store,j['id'])
        self.assertIsNone(self.store.row(rid)['published_id'])
    def test_not_ready_container_resume_does_not_recreate_children(self):
        rid=self.approve();self.instagram.active=True;self.instagram.notready=True;self.engine.run_one()
        jid=self.q("SELECT id FROM jobs WHERE kind='publish'")[0]['id']
        self.assertEqual(self.instagram.created,1)
        self.instagram.notready=False;resume(self.store,jid);self.engine.run_one()
        self.assertEqual(self.instagram.created,5);self.assertEqual(self.instagram.published,1)
    def test_approval_requires_human_review_and_exact_revision(self):
        rid=self.preview()
        with self.assertRaises(ValueError):self.store.decide(rid,1,True)
        self.store.review(rid,1);self.store.revise(rid,'가상 풍자의 문장을 짧게')
        with self.assertRaises(ValueError):self.store.decide(rid,1,True)
        self.assertEqual(self.store.row(rid)['revision'],2)
        self.assertEqual(len(self.q('SELECT * FROM assets')),1)
    def test_approved_record_cannot_be_revised(self):
        rid=self.approve()
        with self.assertRaises(ValueError):self.store.revise(rid,'수정')
        self.assertEqual(self.store.row(rid)['status'],'approved')
    def test_missing_news_does_not_spend(self):
        self.engine.news=lambda:[];self.store.schedule();self.engine.run_one()
        self.assertEqual(self.claude.calls,0)
        self.assertEqual(self.q('SELECT state FROM jobs')[0]['state'],'failed')
    def test_daily_call_budget(self):
        self.engine.config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1','MAX_CLAUDE_CALLS_PER_DAY':'0'})
        self.store.schedule();self.engine.run_one();self.assertEqual(self.claude.calls,0)
        self.assertEqual(self.q('SELECT state FROM jobs')[0]['state'],'waiting')
    def test_disabled_worker_does_nothing(self):
        self.engine.config=Config(self.path,{})
        self.store.schedule();self.assertFalse(self.engine.run_one());self.assertEqual(self.claude.calls,0)
    def test_topic_image_manual_fallback(self):
        self.engine.config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1'})
        cid=self.candidates();self.store.select(cid);self.engine.run_one();self.engine.run_one()
        self.assertEqual(self.q("SELECT state FROM jobs WHERE kind='render'")[0]['state'],'waiting')
        self.assertEqual(self.media.renders,0)
    def test_daily_regeneration_limit(self):
        self.store.schedule();self.store.schedule(regenerate=True);self.store.schedule(regenerate=True)
        with self.assertRaises(ValueError):self.store.schedule(regenerate=True)
    def test_stale_day_not_generated(self):
        self.store.schedule('2000-01-01');self.engine.run_one();self.assertEqual(self.claude.calls,0)
    def test_replayed_user_request_is_idempotent(self):
        self.store.schedule()
        first=self.store.schedule(regenerate=True,request_key='update:123')
        self.assertEqual(self.store.schedule(regenerate=True,request_key='update:123'),first)
        self.engine.run_one();self.engine.run_one()
        rid=self.store.select(self.q('SELECT id FROM candidates ORDER BY id')[0]['id'])
        first=self.store.revise(rid,'짧게',request_key='revision:456')
        self.assertEqual(self.store.revise(rid,'짧게',request_key='revision:456'),first)
        self.assertEqual(self.store.row(rid)['revision'],2)
    def test_no_outbox_send_when_emergency_paused(self):
        self.preview()
        self.engine.config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1','AUTOMATION_PAUSED':'1'})
        self.assertFalse(self.engine.deliver_one())
        self.assertEqual(self.telegram.calls,0)
    def test_uncertain_write_blocks_running_recovery_resume(self):
        self.store.schedule();job=self.store.claim()
        with self.store.tx() as c:
            c.execute("INSERT INTO checkpoints(job_id,step,state,created_at) VALUES(?,'claude_candidates','running',?)",(job['id'],now()))
            c.execute("UPDATE jobs SET state='failed' WHERE id=?",(job['id'],))
        with self.assertRaises(ValueError):resume(self.store,job['id'])
    def test_source_invention_rejected(self):
        d=json.loads(json.dumps(CANDIDATES));d['candidates'][0]['source_url']='https://invented.example/'
        with self.assertRaises(ValueError):validate_candidates(d,NEWS)
    def test_path_injection_and_factual_claims_rejected(self):
        d=draft(NEWS[0]['url']);d['slides'][0]['background_image']='/secret'
        with self.assertRaises(ValueError):validate_draft(d,NEWS[0]['url'])
        d=draft(NEWS[0]['url']);d['claims']=['검증되지 않은 사실']
        with self.assertRaises(ValueError):validate_draft(d,NEWS[0]['url'])
    def test_migration_preserves_legacy_rows(self):
        with self.store.tx() as c:
            c.execute("INSERT INTO selections(candidate_number,candidate_title,status,draft_json,image_paths) VALUES(1,'기존 승인','approved','{}','[]')")
        before=self.q('SELECT * FROM selections');self.store.migrate();self.store.migrate()
        self.assertEqual(self.q('SELECT * FROM selections'),before)
    def test_actual_legacy_schema_migration(self):
        other=Path(self.tmp.name)/'legacy.db'
        with sqlite3.connect(other) as c:
            c.execute("CREATE TABLE selections(id INTEGER PRIMARY KEY AUTOINCREMENT,candidate_number INTEGER NOT NULL,candidate_title TEXT NOT NULL,selected_at TEXT DEFAULT CURRENT_TIMESTAMP,status TEXT,draft_json TEXT,image_paths TEXT)")
            c.execute("INSERT INTO selections(candidate_number,candidate_title,status,draft_json,image_paths) VALUES(2,'보존','approved','original json','original URLs')")
        Store(other).migrate()
        r=Store(other).row(1)
        self.assertEqual((r['status'],r['draft_json'],r['image_paths']),('approved','original json','original URLs'))
        self.assertIsNone(r['approved_revision'])
    def test_authorization_config_required(self):
        from bureau.telegram_app import build_app
        with self.assertRaises(ValueError):build_app(Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1'}))
    def test_rss_filters_old_duplicate_future_and_invalid(self):
        date=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=1)).strftime('%a, %d %b %Y %H:%M:%S GMT')
        item=f'<item><title>기사</title><link>https://example.org/a</link><pubDate>{date}</pubDate></item>'
        xml=f'<rss><channel>{item}{item}<item><title>old</title><link>https://example.org/b</link><pubDate>Mon, 01 Jan 2001 00:00:00 GMT</pubDate></item></channel></rss>'
        self.assertEqual(len(parse_news(xml)),1)


if __name__=='__main__':unittest.main()
