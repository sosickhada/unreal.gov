import base64
import concurrent.futures
import datetime as dt
from io import BytesIO
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock,patch
from PIL import Image,ImageDraw
from bureau.config import Config
from bureau.store import Store,now
from bureau.gemini_images import GeminiImages,GeminiBlocked,pricing,clock_period,prompt_for,request_body,status,schedule

DRAFT={'title':'공용 물건의 수리 책임','image_queries':{'content':'Korean shared office repair desk','resolution_extra':'broken kettle near kitchen sink'},'slides':[{}, {'body':'공용 물건을 한 번 고친 사람이 모든 수리 문의를 받는다.'},{},{}]}

class GeminiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image=Image.new('RGB',(1200,1500),'#102638');draw=ImageDraw.Draw(image)
        for y in range(0,1500,40):
            for x in range(0,1200,40):
                if (x//40+y//40)%2: draw.rectangle((x,y,x+39,y+39),fill='#a0c5ce')
        out=BytesIO();image.save(out,'PNG');cls.image=out.getvalue()
    def setUp(self):
        self.net=patch.object(socket.socket,'connect',side_effect=AssertionError('NO NETWORK'));self.net.start()
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'test.db';self.store=Store(self.db);self.store.migrate()
        self.env={'ENABLE_EXTERNAL_CALLS':'1','GEMINI_IMAGE_ENABLED':'1','GEMINI_API_KEY':'OFFLINE_KEY_SENTINEL'}
        self.config=Config(self.db,self.env);self.at=dt.datetime(2026,11,9,tzinfo=dt.timezone.utc)
        self.prices=patch('bureau.gemini_images.pricing',side_effect=lambda cfg,at=None:pricing(cfg,at or self.at));self.prices.start()
        self.http=Mock();self.http.post.return_value=self.response()
        self.client=GeminiImages(self.config,self.http,self.at)
    def tearDown(self):self.prices.stop();self.net.stop();self.tmp.cleanup()
    def response(self,code=200,image=None,usage=None):
        payload={'candidates':[{'finishReason':'STOP','content':{'parts':[{'inlineData':{'mimeType':'image/png','data':base64.b64encode(self.image if image is None else image).decode()}}]}}],
                 'usageMetadata':usage or {'promptTokenCount':300,'candidatesTokenCount':1680,'thoughtsTokenCount':50}}
        response=Mock(status_code=code);raw=json.dumps(payload).encode();response.iter_content.return_value=[raw];return response
    def rows(self,table):
        with self.store.tx() as c:return [dict(r) for r in c.execute('SELECT * FROM '+table)]
    def test_request_auth_dimensions_prompt_and_cache(self):
        result=self.client.generate(DRAFT,'content');self.assertTrue(Path(result['path']).is_file())
        self.assertEqual(result['provider'],'gemini');self.assertTrue(result['review_required'])
        self.assertEqual(self.client.generate(DRAFT,'content')['sha256'],result['sha256']);self.assertEqual(self.http.post.call_count,1)
        args,kw=self.http.post.call_args
        self.assertNotIn('OFFLINE_KEY',args[0]);self.assertEqual(kw['headers']['x-goog-api-key'],self.env['GEMINI_API_KEY'])
        self.assertFalse(kw['allow_redirects']);self.assertEqual(kw['json']['generationConfig']['imageConfig'],{'aspectRatio':'4:5','imageSize':'2K'})
        self.assertNotEqual(prompt_for(DRAFT,'content'),prompt_for(DRAFT,'resolution_extra'))
        self.assertEqual(len(self.rows('gemini_image_attempts')),1)
        self.assertTrue(self.rows('gemini_image_attempts')[0]['usage'])
        self.assertGreater(self.rows('gemini_image_attempts')[0]['observed_estimate_krw'],0)
    def test_disabled_or_missing_key_no_reservation(self):
        for change in ({'GEMINI_IMAGE_ENABLED':'0'},{'GEMINI_API_KEY':''}):
            with self.assertRaises(GeminiBlocked):GeminiImages(Config(self.db,dict(self.env,**change)),self.http,self.at).generate(DRAFT,'content')
        self.assertFalse(self.rows('gemini_image_attempts'));self.http.post.assert_not_called()
    def test_unknown_model_expired_prices_and_bad_fx_fail_closed(self):
        for change in ({'GEMINI_IMAGE_MODEL':'unpriced-model'},{'GEMINI_IMAGE_USD_KRW':'NaN'},{'GEMINI_IMAGE_MONTHLY_BUDGET_KRW':'5001'}):
            with self.assertRaises(GeminiBlocked):pricing(Config(self.db,dict(self.env,**change)),self.at)
        with self.assertRaises(GeminiBlocked):pricing(self.config,dt.datetime(2027,1,1,tzinfo=dt.timezone.utc))
        self.http.post.assert_not_called()
    def test_insufficient_budget_before_http(self):
        cost=pricing(self.config,self.at)['ceiling_krw'];cfg=Config(self.db,dict(self.env,GEMINI_IMAGE_MONTHLY_BUDGET_KRW=str(cost-1)))
        with self.assertRaises(GeminiBlocked):GeminiImages(cfg,self.http,self.at).generate(DRAFT,'content')
        self.http.post.assert_not_called();self.assertFalse(self.rows('gemini_image_attempts'));self.assertEqual(self.rows('gemini_image_periods')[0]['halted'],1)
    def test_parallel_month_and_day_limits(self):
        q=pricing(self.config,self.at)
        def call(i):
            try:return self.client.reserve('key'+str(i),q)
            except GeminiBlocked:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(call,range(12)))
        self.assertEqual(sum(r is not None for r in results),2)
        rows=self.rows('gemini_image_attempts');self.assertLessEqual(sum(r['reserved_krw'] for r in rows),5000)
        self.assertEqual(status(self.config,self.store,self.at)['remaining_attempts_today'],0)
    def test_atomic_duplicate_claim_and_restart_uncertain(self):
        q=pricing(self.config,self.at)
        def claim(_):
            try:return self.client.reserve('same',q)
            except GeminiBlocked:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(claim,range(8)))
        self.assertEqual(sum(r is not None for r in rows),1)
        with self.assertRaises(GeminiBlocked):GeminiImages(self.config,self.http,self.at).reserve('same',q)
        self.assertEqual(len(self.rows('gemini_image_attempts')),1)
    def test_timeout_never_refunds_or_retries(self):
        self.http.post.side_effect=TimeoutError('OFFLINE_KEY_SENTINEL')
        with self.assertRaises(GeminiBlocked) as error:self.client.generate(DRAFT,'content')
        self.assertNotIn('SENTINEL',str(error.exception))
        with self.assertRaises(GeminiBlocked):GeminiImages(self.config,self.http,self.at).generate(DRAFT,'content')
        self.assertEqual(self.http.post.call_count,1)
        self.assertEqual(self.rows('gemini_image_attempts')[0]['state'],'uncertain')
        self.assertGreater(status(self.config,self.store,self.at)['reserved_krw'],0)
    def test_429_retry_is_second_billable_daily_attempt(self):
        self.http.post.side_effect=[self.response(429),self.response()]
        self.client.generate(DRAFT,'content');rows=self.rows('gemini_image_attempts')
        self.assertEqual(len(rows),2);self.assertEqual(self.http.post.call_count,2)
        self.assertEqual(rows[0]['reserved_krw'],rows[1]['reserved_krw'])
        self.assertEqual(status(self.config,self.store,self.at)['remaining_generations'],0)
    def test_zero_retries_blocks_429_replay_after_restart(self):
        cfg=Config(self.db,dict(self.env,GEMINI_IMAGE_MAX_RETRIES='0'))
        self.http.post.return_value=self.response(429)
        for _ in range(2):
            with self.assertRaises(GeminiBlocked):
                GeminiImages(cfg,self.http,self.at).generate(DRAFT,'content')
        self.assertEqual(self.http.post.call_count,1)
        rows=self.rows('gemini_image_attempts')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['error_code'],'http_429')
        self.assertGreater(rows[0]['reserved_krw'],0)
    def test_zero_retries_blocks_invalid_image_replay_after_restart(self):
        cfg=Config(self.db,dict(self.env,GEMINI_IMAGE_MAX_RETRIES='0'))
        self.http.post.return_value=self.response(image=b'not an image')
        for _ in range(2):
            with self.assertRaises(GeminiBlocked):
                GeminiImages(cfg,self.http,self.at).generate(DRAFT,'content')
        self.assertEqual(self.http.post.call_count,1)
        rows=self.rows('gemini_image_attempts')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['state'],'rejected')
        self.assertGreater(rows[0]['reserved_krw'],0)
    def test_invalid_image_retry_preserves_both_reservations(self):
        self.http.post.side_effect=[self.response(image=b'not image'),self.response()]
        self.client.generate(DRAFT,'content')
        self.assertEqual([r['state'] for r in self.rows('gemini_image_attempts')],['rejected','succeeded'])
    def test_failed_auth_no_automatic_retry_or_secret(self):
        self.http.post.return_value=self.response(403)
        with self.assertRaises(GeminiBlocked) as error:self.client.generate(DRAFT,'content')
        self.assertEqual(self.http.post.call_count,1);self.assertNotIn('SENTINEL',str(error.exception))
    def test_month_and_day_reset_at_kst_midnight(self):
        before=dt.datetime(2026,11,30,14,59,tzinfo=dt.timezone.utc);after=before+dt.timedelta(minutes=1)
        self.assertEqual(clock_period(before),('2026-11','2026-11-30'));self.assertEqual(clock_period(after),('2026-12','2026-12-01'))
        client=GeminiImages(self.config,self.http,before);q=pricing(self.config,before)
        client.reserve('a',q);client.reserve('b',q)
        self.assertEqual(status(self.config,self.store,after)['remaining_attempts_today'],2)
    def test_80_and_100_notifications_once_and_new_month(self):
        cost=pricing(self.config,self.at)['ceiling_krw'];cfg=Config(self.db,dict(self.env,GEMINI_IMAGE_MONTHLY_BUDGET_KRW=str(cost*2)))
        client=GeminiImages(cfg,self.http,self.at);q=pricing(cfg,self.at)
        client.reserve('a',q);client.reserve('b',q)
        for _ in range(2):
            with self.assertRaises(GeminiBlocked):client.reserve('c',q)
        keys=[r['delivery_key'] for r in self.rows('outbox')]
        self.assertEqual(keys.count('gemini-budget-80:2026-11'),1);self.assertEqual(keys.count('gemini-budget-stop:2026-11'),1)
        self.assertEqual(status(cfg,self.store,dt.datetime(2026,12,1,tzinfo=dt.timezone.utc))['remaining_generations'],2)
    def test_cache_bytes_changed_cannot_generate_again(self):
        result=self.client.generate(DRAFT,'content');Path(result['path']).write_bytes(b'bad')
        with self.assertRaises(GeminiBlocked):self.client.generate(DRAFT,'content')
        self.assertEqual(self.http.post.call_count,1)
    def test_month_limit_across_days_and_restart(self):
        cost=pricing(self.config,self.at)['ceiling_krw'];cfg=Config(self.db,dict(self.env,GEMINI_IMAGE_MONTHLY_BUDGET_KRW=str(cost*2)))
        for i in range(2):GeminiImages(cfg,self.http,self.at+dt.timedelta(days=i)).reserve(str(i),pricing(cfg,self.at))
        with self.assertRaises(GeminiBlocked):GeminiImages(cfg,self.http,self.at+dt.timedelta(days=2)).reserve('no',pricing(cfg,self.at))
        self.assertEqual(len(self.rows('gemini_image_attempts')),2)

class GeminiPipelineTests(unittest.TestCase):
    setUpClass=GeminiTests.__dict__['setUpClass']
    setUp=GeminiTests.setUp
    tearDown=GeminiTests.tearDown
    response=GeminiTests.response
    rows=GeminiTests.rows

    def pending(self):
        with self.store.tx() as c:
            c.execute("INSERT INTO selections(id,candidate_number,candidate_title,status,revision,draft_json) VALUES(4,1,'offline','draft_ready',1,?)",(json.dumps(DRAFT),))
            jid=self.store.enqueue(c,'render:4:1','render',{'id':4,'revision':1})
        return jid

    def test_pixabay_exhaustion_gemini_preview_selection_render(self):
        from PIL import ImageOps
        from bureau.engine import Engine
        from bureau.photo_review import approve
        import test_system as fixtures
        self.pending()
        second=BytesIO()
        with Image.open(BytesIO(self.image)) as image:ImageOps.invert(image.convert('RGB')).save(second,'PNG')
        cfg=Config(self.db,dict(self.env,REQUIRE_TOPIC_IMAGE='1'))
        engine=Engine(cfg,fixtures.FakeClaude(),fixtures.FakeMedia(),fixtures.FakeTelegram(),fixtures.FakeInstagram())
        with patch('bureau.images.acquire_photos',return_value={'photos':{},'candidate_links':[],'attempts':[]}) as stock,patch('bureau.gemini_images.requests.post',side_effect=[self.response(),self.response(image=second.getvalue())]) as api:
            self.assertTrue(engine.run_one())
            stock.assert_called_once()
            with self.store.tx() as c:
                checkpoints=c.execute("SELECT rowid,result FROM checkpoints WHERE step LIKE 'gemini_image_%'").fetchall()
                self.assertEqual(len(checkpoints),2)
                self.assertEqual(c.execute("SELECT state FROM jobs WHERE kind='render'").fetchone()[0],'waiting')
            payloads=[json.loads(row['payload']) for row in self.rows('outbox')]
            self.assertTrue(any(p.get('files') for p in payloads))
            self.assertIn('airegen:',json.dumps(payloads));self.assertIn('aigen:',json.dumps(payloads))
            first,other=checkpoints
            self.assertFalse(approve(self.store,4,1,first[0],json.loads(first[1])['slot'],'offline-reviewer'))
            self.assertTrue(approve(self.store,4,1,other[0],json.loads(other[1])['slot'],'offline-reviewer'))
            self.assertTrue(engine.run_one());self.assertEqual(engine.store.row(4)['status'],'preview_ready')
            self.assertEqual(api.call_count,2)
        with self.store.tx() as c:
            media=json.loads(c.execute('SELECT payload FROM assets').fetchone()[0])
            self.assertTrue(all(p['provider']=='gemini' for p in media['image_provenance']['photos'].values()))

    def test_budget_block_falls_back_to_photo_selection_without_post(self):
        from bureau.engine import Engine
        import test_system as fixtures
        self.pending();cfg=Config(self.db,dict(self.env,GEMINI_IMAGE_MONTHLY_BUDGET_KRW='1',AUTO_PHOTO_ACQUIRE='1'))
        engine=Engine(cfg,fixtures.FakeClaude(),fixtures.FakeMedia(),fixtures.FakeTelegram(),fixtures.FakeInstagram())
        with patch('bureau.images.acquire_photos',return_value={'photos':{},'candidate_links':[],'attempts':[]}),patch('bureau.gemini_images.requests.post') as api:
            engine.run_one();api.assert_not_called()
        self.assertEqual(self.store.row(4)['status'],'draft_ready')
        self.assertIn('photo-actions:4:1',[r['delivery_key'] for r in self.rows('outbox')])

    def test_manual_job_and_regeneration_duplicate_clicks_and_stale_revision(self):
        jid=self.pending()
        with self.store.tx() as c:c.execute("UPDATE jobs SET state='waiting' WHERE id=?",(jid,))
        one=schedule(self.store,self.config,4,1,'content');two=schedule(self.store,self.config,4,1,'content')
        self.assertEqual(one,two)
        with self.store.tx() as c:c.execute("UPDATE jobs SET state='waiting',error_code='gemini_image_blocked' WHERE id=?",(one,))
        self.assertEqual(schedule(self.store,self.config,4,1,'content'),one)
        self.assertEqual([row['state'] for row in self.rows('jobs') if row['id']==one],['queued'])
        with self.assertRaises(GeminiBlocked):schedule(self.store,self.config,4,2,'content')
        with self.assertRaises(GeminiBlocked):schedule(self.store,self.config,4,1,'content','999')
        self.assertEqual(len(self.rows('gemini_image_attempts')),0)

    def test_telegram_requests_queue_only_and_budget_button(self):
        import asyncio
        from types import SimpleNamespace as NS
        from unittest.mock import AsyncMock
        from bureau.telegram_app import build_app
        jid=self.pending()
        with self.store.tx() as c:c.execute("UPDATE jobs SET state='waiting' WHERE id=?",(jid,))
        env=dict(self.env,TELEGRAM_BOT_TOKEN='123456:OFFLINE_ONLY_012345678901234567890123456789',TELEGRAM_CHAT_ID='22',TELEGRAM_ALLOWED_USER_IDS='11')
        app=build_app(Config(self.db,env));callback=next(h.callback for h in app.handlers[0] if h.__class__.__name__=='CallbackQueryHandler')
        update=NS(effective_user=NS(id=11),effective_chat=NS(id=22),update_id=300,callback_query=NS(data='aigen:4:1:content:0',answer=AsyncMock()))
        asyncio.run(callback(update,NS()));asyncio.run(callback(update,NS()))
        self.assertEqual(len([r for r in self.rows('jobs') if r['kind']=='gemini_image']),1)
        update.update_id=301;update.callback_query.data='imagebudget:0';asyncio.run(callback(update,NS()))
        text=' '.join(json.loads(r['payload']).get('text','') for r in self.rows('outbox'))
        self.assertIn('5,000',text);self.assertNotIn('SENTINEL',text);self.http.post.assert_not_called()

    def test_observed_usage_overrun_halts_month(self):
        q=pricing(self.config,self.at);attempt=self.client.reserve('overrun',q)
        self.client.finish(attempt['id'],'failed',usage={'promptTokenCount':1000000,'candidatesTokenCount':1000000})
        self.assertEqual(self.rows('gemini_image_periods')[0]['halted'],1)
        self.assertEqual(status(self.config,self.store,self.at)['remaining_generations'],0)

    def test_completed_provider_request_recovered_from_failed_checkpoint(self):
        from bureau.engine import Engine
        import test_system as fixtures
        jid=self.pending()
        with self.store.tx() as c:c.execute("UPDATE jobs SET state='waiting' WHERE id=?",(jid,))
        gen=schedule(self.store,self.config,4,1,'content')
        # Provider result was committed, then Worker died before the engine checkpoint.
        expected=self.client.generate(DRAFT,'content')
        with self.store.tx() as c:
            c.execute("INSERT INTO checkpoints(job_id,step,state,created_at) VALUES(?,'gemini_image_content','failed',?)",(gen,now()))
        engine=Engine(self.config,fixtures.FakeClaude(),fixtures.FakeMedia(),fixtures.FakeTelegram(),fixtures.FakeInstagram())
        with patch('bureau.gemini_images.requests.post') as api:
            self.assertTrue(engine.run_one());api.assert_not_called()
        with self.store.tx() as c:
            row=c.execute("SELECT state,result FROM checkpoints WHERE job_id=? AND step='gemini_image_content'",(gen,)).fetchone()
        self.assertEqual(row['state'],'succeeded');self.assertEqual(json.loads(row['result'])['sha256'],expected['sha256'])

    def test_low_native_resolution_rejected_and_retry_cost_kept(self):
        small=BytesIO();Image.new('RGB',(512,640),'white').save(small,'PNG')
        self.http.post.side_effect=[self.response(image=small.getvalue()),self.response(image=small.getvalue())]
        with self.assertRaises(GeminiBlocked):self.client.generate(DRAFT,'content')
        self.assertEqual(len(self.rows('gemini_image_attempts')),2)
        self.assertTrue(all(r['reserved_krw']>0 for r in self.rows('gemini_image_attempts')))
