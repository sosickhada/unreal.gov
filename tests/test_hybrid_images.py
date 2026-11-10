import base64
import concurrent.futures
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from PIL import Image
from bureau.config import Config
from bureau.store import Store
from bureau.puter_images import PuterImages,PuterBlocked,MODELS,schedule
from bureau.image_uploads import begin,accept
from bureau.photo_review import offer,approve
from bureau.unsplash import search_plan,rank_candidates

class HybridProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        buf=BytesIO();Image.effect_noise((1100,1400),65).convert('RGB').save(buf,'PNG');cls.content=buf.getvalue()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.config=Config(Path(self.tmp.name)/'test.db',{'ENABLE_EXTERNAL_CALLS':'1'})
        self.store=Store(self.config.db);self.store.migrate()
        self.draft={'title':'공용 사무실 냉장고','image_queries':{'content':'Korean shared office refrigerator','resolution_extra':'leftover food container close up'}}
        self.bridge=Mock();self.bridge.inspect.return_value={'allowanceInfo':{'remaining':100,'unit':'test-only'}}
        self.bridge.generate.return_value={'src':'data:image/png;base64,'+base64.b64encode(self.content).decode(),'usage_after':{'remaining':99.5}}
        self.authorize=lambda a,m:{'free_only_enforced':True,'paid_balance_isolated':True,'maximum':1,'free_remaining':100}
        self.client=PuterImages(self.config,self.bridge,self.authorize)
    def test_full_mock_generation_cache_dimensions_and_audit(self):
        a=self.client.generate(self.draft,'content','once')
        self.assertEqual(a['provider'],'puter');self.assertEqual((a['width'],a['height']),(1080,1350))
        self.assertTrue(Path(a['original_path']).is_file());self.assertTrue(a['prompt'])
        self.assertEqual(self.client.generate(self.draft,'content','once'),a);self.bridge.generate.assert_called_once()
        self.assertEqual(self.bridge.generate.call_args.args[0]['model'],MODELS['natural']['model'])
        with self.store.tx() as c:
            r=c.execute('SELECT * FROM puter_image_attempts').fetchone()
            self.assertEqual(r['state'],'succeeded');self.assertIn('remaining',r['usage_after']);self.assertIn('Korean',r['prompt'])
    def test_free_paid_unknown_and_automatic_never_generate(self):
        for key,client,mode in [('unknown',PuterImages(self.config,self.bridge),'manual'),('auto',self.client,'automatic'),('paid',PuterImages(self.config,self.bridge,lambda a,m:{'free_only_enforced':True,'paid_balance_isolated':False}),'manual')]:
            with self.assertRaises(PuterBlocked):client.generate(self.draft,'content',key,mode=mode)
        self.bridge.generate.assert_not_called()
    def test_two_daily_attempts_and_atomic_duplicate(self):
        def call(_):
            try:return self.client.generate(self.draft,'content','same')
            except PuterBlocked:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(call,range(4)))
        self.assertEqual(self.bridge.generate.call_count,1)
        self.client.generate(self.draft,'resolution_extra','second','detail')
        with self.assertRaises(PuterBlocked):self.client.generate(self.draft,'content','third')
        self.assertEqual(self.bridge.generate.call_count,2)
    def test_timeout_restart_and_bad_output_never_retry(self):
        self.bridge.generate.side_effect=TimeoutError('secret')
        with self.assertRaises(PuterBlocked) as exc:self.client.generate(self.draft,'content','unknown')
        self.assertNotIn('secret',str(exc.exception))
        with self.assertRaises(PuterBlocked):PuterImages(self.config,self.bridge,self.authorize).generate(self.draft,'content','unknown')
        with self.assertRaises(PuterBlocked):self.client.generate(self.draft,'content','new')
        self.assertEqual(self.bridge.generate.call_count,1)
    def test_usage_overrun_halts_new_requests(self):
        self.bridge.generate.return_value['usage_after']={'remaining':90}
        with self.assertRaises(PuterBlocked):self.client.generate(self.draft,'content','over')
        with self.assertRaises(PuterBlocked):self.client.generate(self.draft,'content','after')
        self.assertEqual(self.bridge.generate.call_count,1)
    def pending(self):
        with self.store.tx() as c:
            c.execute("INSERT INTO selections(id,candidate_number,candidate_title,status,revision,draft_json) VALUES(7,1,'sample','draft_ready',1,?)",(json.dumps(self.draft),))
            jid=self.store.enqueue(c,'render:7:1','render',{'id':7,'revision':1})
            c.execute("UPDATE jobs SET state='waiting' WHERE id=?",(jid,))
        return jid
    def test_upload_rights_stale_duplicate_choice_and_resume(self):
        self.pending();begin(self.store,'11',7,1)
        with self.assertRaises(ValueError):accept(self.store,'11',1,self.content,'')
        accept(self.store,'11',1,self.content,'OWN');accept(self.store,'11',1,self.content,'OWN')
        self.assertEqual(offer(self.store,7,1),1)
        with self.store.tx() as c:key=c.execute("SELECT rowid FROM checkpoints WHERE step='upload_1_download'").fetchone()[0]
        self.assertFalse(approve(self.store,7,1,key,'content','11'))
        with self.assertRaises(ValueError):approve(self.store,7,1,key,'resolution_extra','11')
        with self.assertRaises(ValueError):begin(self.store,'11',7,2)
        with self.store.tx() as c:c.execute('UPDATE selections SET revision=2 WHERE id=7')
        with self.assertRaises(ValueError):accept(self.store,'11',2,self.content,'OWN')
    def test_schedule_model_and_regeneration_scope(self):
        self.pending()
        a=schedule(self.store,self.config,7,1,'content');self.assertEqual(a,schedule(self.store,self.config,7,1,'content'))
        with self.assertRaises(ValueError):schedule(self.store,self.config,7,2,'content')
        with self.assertRaises(ValueError):schedule(self.store,self.config,7,1,'content','999')
        with self.assertRaises(ValueError):schedule(self.store,self.config,7,1,'content',model_key='unknown')
    def test_bilingual_queries_and_relevance_over_resolution(self):
        plan=search_plan({'title':'사무실 냉장고','image_brief':{'content':{'place':'사무실','situation':'냉장고 음식'}}},'content')
        self.assertGreaterEqual(len(plan['queries']),3);self.assertLessEqual(len(plan['queries']),5)
        self.assertIn('office',plan['queries'][0]);self.assertIn('place',plan['fields'])
        photos=[{'id':'huge','tags':'mountain sunset','original_width':4000,'original_height':5000},{'id':'relevant','tags':'office refrigerator food','original_width':1200,'original_height':1500}]
        result=rank_candidates(photos,'office refrigerator')
        self.assertEqual(result[0]['id'],'relevant');self.assertFalse(result[0]['visual_quality_verified'])
        self.assertEqual(len(rank_candidates(photos+photos,'office refrigerator')),2)

    def test_telegram_upload_and_model_callbacks_are_version_bound(self):
        import asyncio
        from types import SimpleNamespace as NS
        from unittest.mock import AsyncMock
        from bureau.telegram_app import build_app
        self.pending()
        cfg=Config(self.config.db,dict(self.config.env,TELEGRAM_BOT_TOKEN='123456:OFFLINE_ONLY_012345678901234567890123456789',TELEGRAM_CHAT_ID='22',TELEGRAM_ALLOWED_USER_IDS='11'))
        app=build_app(cfg)
        callback=next(h.callback for h in app.handlers[0] if h.__class__.__name__=='CallbackQueryHandler')
        upload=next(h.callback for h in app.handlers[0] if h.callback.__name__=='upload_message')
        update=NS(effective_user=NS(id=11),effective_chat=NS(id=22),update_id=400,callback_query=NS(data='upstart:7:1',answer=AsyncMock()))
        asyncio.run(callback(update,NS()))
        blob=NS(file_size=len(self.content),download_as_bytearray=AsyncMock(return_value=bytearray(self.content)))
        bot=NS(get_file=AsyncMock(return_value=blob))
        update.message=NS(document=NS(file_size=len(self.content),file_id='offline'),photo=None,caption='OWN')
        asyncio.run(upload(update,NS(bot=bot)));asyncio.run(upload(update,NS(bot=bot)))
        self.assertEqual(bot.get_file.await_count,1)
        with self.store.tx() as c:
            photo=json.loads(c.execute("SELECT result FROM checkpoints WHERE step='upload_400_download'").fetchone()[0])
            self.assertTrue(photo['rights_confirmed'])
        update.callback_query.data='aigen:7:1:content:0';update.update_id=401
        asyncio.run(callback(update,NS()))
        with self.store.tx() as c:payloads=[json.loads(r[0]) for r in c.execute('SELECT payload FROM outbox')]
        self.assertTrue(any('pmodel:7:1:content:natural:0' in json.dumps(p) for p in payloads))
        update.callback_query.data='pmodel:7:1:content:natural:0';update.update_id=402
        asyncio.run(callback(update,NS()));asyncio.run(callback(update,NS()))
        with self.store.tx() as c:self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='puter_image'").fetchone()[0],1)
        update.callback_query.data='pmodel:7:2:content:natural:0';update.update_id=403
        asyncio.run(callback(update,NS()))
        self.assertTrue(update.callback_query.answer.call_args.kwargs.get('show_alert'))

    def test_legacy_puter_ledger_migration_preserves_rows(self):
        import sqlite3
        path=Path(self.tmp.name)/'legacy.db'
        with sqlite3.connect(path) as c:
            c.execute('CREATE TABLE puter_image_attempts(id INTEGER PRIMARY KEY,mode TEXT,slot TEXT,state TEXT,reason TEXT,created_at TEXT)')
            c.execute("INSERT INTO puter_image_attempts VALUES(41,'automatic','content','blocked','old reason','2026-11-01')")
        legacy=Store(path);legacy.migrate();legacy.migrate()
        with legacy.tx() as c:
            row=c.execute('SELECT * FROM puter_image_attempts WHERE id=41').fetchone()
            self.assertEqual((row['state'],row['reason'],row['created_at']),('blocked','old reason','2026-11-01'))
            self.assertIsNone(row['request_key'])
            self.assertEqual(c.execute('SELECT MAX(version) FROM schema_versions').fetchone()[0],7)
