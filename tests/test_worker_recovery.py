import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bureau.config import Config
from bureau.store import Store
from bureau.operations import readiness, worker_start_allowed

class WorkerRecoveryTests(unittest.TestCase):
    def test_isolated_uncertain_preserved_and_other_unsafe_states_block_start(self):
        with tempfile.TemporaryDirectory() as root:
            cfg=Config(Path(root)/'test.db',{'WORKER_ALLOW_ISOLATED_UNCERTAIN':'1','ANTHROPIC_API_KEY':'offline','CLAUDE_MODEL':'offline','TELEGRAM_BOT_TOKEN':'offline','TELEGRAM_CHAT_ID':'1','TELEGRAM_ALLOWED_USER_IDS':'1','PUBLIC_BASE_URL':'https://example.com','RENDER_DIR':root+'/private','IMAGE_DIR':root+'/public','REQUIRE_TOPIC_IMAGE':'1'})
            store=Store(cfg.db);store.migrate()
            with store.tx() as c:
                jid=store.enqueue(c,'old-uncertain','candidates',{})
                c.execute("UPDATE jobs SET state='uncertain' WHERE id=?",(jid,))
            with patch('bureau.operations.claude_settings',return_value={}),patch('bureau.operations.telegram_settings',return_value={}):
                report=readiness(cfg)
                self.assertFalse(report['ready_for_worker'])
                self.assertTrue(worker_start_allowed(cfg,report))
                self.assertFalse(worker_start_allowed(Config(cfg.db,{}),report))
                self.assertIsNone(store.claim())
                with store.tx() as c:
                    self.assertEqual(c.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()[0],'uncertain')
                    c.execute("UPDATE jobs SET state='running' WHERE id=?",(jid,))
                self.assertFalse(worker_start_allowed(cfg,readiness(cfg)))
                with store.tx() as c:c.execute("UPDATE jobs SET state='uncertain' WHERE id=?",(jid,))
                bad=Config(cfg.db,dict(cfg.env,PUBLIC_BASE_URL='http://invalid'))
                self.assertFalse(worker_start_allowed(bad,readiness(bad)))
