import unittest
from bureau.publish_review import blocked_review
class PublishReviewTests(unittest.TestCase):
    def test_blocked_ui_cannot_approve(self):
        p=blocked_review(42,3,'테스트 캡션','게시 권한 미확인')
        self.assertIn('게시 차단',p['text'])
        buttons=[b for row in p['reply_markup']['inline_keyboard'] for b in row]
        self.assertTrue(all(b['callback_data'].startswith(('igblocked:','igclose:')) for b in buttons))
        self.assertTrue(all(b['callback_data'].endswith(':42:3') for b in buttons))
