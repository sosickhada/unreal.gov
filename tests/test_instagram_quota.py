import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from bureau.instagram import Instagram

class QuotaTests(unittest.TestCase):
    def test_quota_does_not_claim_publish_permission(self):
        ig=Instagram(SimpleNamespace(env={'IG_ACCOUNT_ID':'123'}))
        ig.request=Mock(return_value={'data':[{'quota_usage':0}]})
        result=ig.publishing_limit()
        self.assertFalse(result['publish_permission_verified'])
        self.assertEqual(result['data'][0]['quota_usage'],0)
        ig.request.assert_called_once_with('GET','123/content_publishing_limit',fields='config,quota_usage')
