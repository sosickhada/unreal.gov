import json
import tempfile
import unittest
from pathlib import Path
from bureau.store import Store,kst_day,now
from bureau.config import Config
from bureau.engine import Engine,candidate_message
from bureau.editorial import local_pool,duplicate,assess

class EditorialTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.db');self.store.migrate()
        self.engine=Engine(Config(Path(self.store.path),{'ENABLE_EXTERNAL_CALLS':'1'}))
    def tearDown(self): self.tmp.cleanup()
    def test_pool_and_replace(self):
        self.assertGreaterEqual(len(local_pool(kst_day())),9)
        self.store.schedule();self.assertTrue(self.engine.run_one())
        with self.store.tx() as c:
            rows=[dict(r) for r in c.execute('SELECT * FROM candidates')]
            self.assertEqual(len(rows),3)
            self.assertGreaterEqual(c.execute('SELECT count(*) FROM idea_audits').fetchone()[0],9)
            self.assertIn('boring:',json.dumps(candidate_message(c,rows[0]['batch_id'])))
        self.assertTrue(self.store.reject_candidate(rows[0]['id'],'너무 뻔함'))
        self.assertFalse(self.store.reject_candidate(rows[0]['id'],'다시 클릭'))
        self.assertTrue(self.engine.run_one())
        with self.store.tx() as c:
            active=[dict(r) for r in c.execute("SELECT * FROM candidates WHERE status='available'")]
            self.assertEqual(len(active),3)
            for old in rows[1:]: self.assertIn(old,active)
            self.assertEqual(c.execute('SELECT count(*) FROM candidate_feedback').fetchone()[0],1)
            self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='candidate_replace'").fetchone()[0],1)
    def test_semantic_rejection_and_penalty(self):
        a=local_pool(kst_day())[0];b=dict(a,title='완전히 다른 제목',summary='다른 표현으로 설명한 사건')
        self.assertTrue(duplicate(a,b,29)['blocked'])
        self.assertTrue(duplicate(a,b,80,True)['blocked'])
        self.assertLess(assess(dict(a,satire_angle='서로 배려합시다'))['score'],70)
    def test_notice(self):
        import figma_renderer as r
        for fn,args in [(r.make_html,({'body':'이 사건은 허구입니다. 실제 장면','headline':'질문'},1,4,'제목')),(r.make_figma_content,({'body':'이 사건은 허구입니다. 실제 장면'},'제목')),(r.make_figma_resolution,({'body':'※ 본 사건은 허구입니다. 판정'},'제목'))]:
            markup=fn(*args)
            self.assertEqual(markup.count('※ 본 사건은 허구입니다.'),1)
            self.assertNotIn('이 사건은 허구입니다.',markup)
            self.assertIn('right:65px;bottom:34px',markup)
    def test_image_fallback_no_billable_provider(self):
        from bureau.generated_images import generate_local,scene_prompt
        result=generate_local(self.engine.config,{'image_queries':{'content':'empty kitchen'}},'content',Path(self.tmp.name)/'unused.png')
        self.assertFalse(result['available'])
        self.assertIn('natural window light',result['prompt'])
        self.assertNotIn('이 사건은',scene_prompt({},'content'))
