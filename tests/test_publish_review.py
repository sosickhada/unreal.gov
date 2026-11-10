import unittest
from bureau.publish_review import blocked_review
class PublishReviewTests(unittest.TestCase):
    def test_blocked_ui_cannot_approve(self):
        p=blocked_review(42,3,'테스트 캡션','게시 권한 미확인')
        self.assertIn('게시 차단',p['text'])
        buttons=[b for row in p['reply_markup']['inline_keyboard'] for b in row]
        self.assertTrue(all(b['callback_data'].startswith(('igblocked:','igclose:')) for b in buttons))
        self.assertTrue(all(b['callback_data'].endswith(':42:3') for b in buttons))

class BoundReviewTests(unittest.TestCase):
    def setUp(self):
        import tempfile,json,hashlib
        from pathlib import Path
        from bureau.store import Store
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root/'test.db');self.store.migrate()
        self.image=self.root/'image.jpg';self.image.write_bytes(b'image')
        self.media={'files':[str(self.image)],'sha256':[hashlib.sha256(b'image').hexdigest()],'urls':['https://example.org/image.jpg']}
        with self.store.tx() as c:
            c.execute("INSERT INTO selections(id,candidate_number,candidate_title,status,revision,draft_json) VALUES(1,1,'finished','preview_ready',1,?)",(json.dumps({'caption':'finished satire'}),))
            c.execute('INSERT INTO assets VALUES(1,1,?,?)',(json.dumps(self.media),'now'))
        from bureau.publish_review import prepare_review
        self.payload=prepare_review(self.store,1,1,'123');self.short=self.payload['reply_markup']['inline_keyboard'][0][0]['callback_data'].split(':')[3]
    def tearDown(self):self.tmp.cleanup()
    def test_no_publication_before_exact_approval_and_duplicate_click(self):
        from bureau.publish_review import assert_approved,decide_review
        with self.assertRaises(ValueError):assert_approved(self.store,1,1,'123')
        decide_review(self.store,1,1,self.short,True);assert_approved(self.store,1,1,'123')
        with self.assertRaises(ValueError):decide_review(self.store,1,1,self.short,True)
        with self.store.tx() as c:self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='publish'").fetchone()[0],1)
    def test_caption_mutation_blocks_approval(self):
        from bureau.publish_review import decide_review
        with self.store.tx() as c:c.execute("UPDATE selections SET draft_json=? WHERE id=1",('{"caption":"changed"}',))
        with self.assertRaises(ValueError):decide_review(self.store,1,1,self.short,True)
    def test_changed_image_or_account_blocks_worker(self):
        from bureau.publish_review import decide_review,assert_approved
        decide_review(self.store,1,1,self.short,True)
        with self.assertRaises(ValueError):assert_approved(self.store,1,1,'456')
        self.image.write_bytes(b'changed')
        with self.assertRaises(ValueError):assert_approved(self.store,1,1,'123')
    def test_cancel_never_queues_publication(self):
        from bureau.publish_review import decide_review
        decide_review(self.store,1,1,self.short,False)
        with self.store.tx() as c:self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='publish'").fetchone()[0],0)
