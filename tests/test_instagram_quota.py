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

    def test_token_bound_container_evidence_and_live_quota(self):
        import tempfile,json,hashlib
        from pathlib import Path
        from bureau.config import Config
        from bureau.adapters import ExternalError
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);(root/'data').mkdir()
            cfg=Config(root/'test.db',{'IG_ACCESS_TOKEN':'current-token','IG_ACCOUNT_ID':'123'})
            ig=Instagram(cfg)
            evidence=root/'data/instagram-grant.json'
            evidence.write_text(json.dumps({'token_sha256':hashlib.sha256(b'current-token').hexdigest(),'account_id':'123','container_id':'container'}))
            def responses(*args,**kwargs):
                if args[1]=='me':return {'user_id':'123','account_type':'MEDIA_CREATOR'}
                return {'data':[{'quota_usage':0,'config':{'quota_total':100}}]}
            ig.request=Mock(side_effect=responses)
            self.assertTrue(ig.preflight()['valid'])
            self.assertFalse(any(call.args[1]=='me/permissions' for call in ig.request.call_args_list))
            ig.request=Mock(side_effect=[{'user_id':'123','account_type':'BUSINESS'},{'data':[{'quota_usage':100,'config':{'quota_total':100}}]}])
            with self.assertRaises(ExternalError):ig.preflight()
            changed=Instagram(Config(cfg.db,dict(cfg.env,IG_ACCESS_TOKEN='replacement-token')))
            changed.request=Mock(return_value={'user_id':'123','account_type':'BUSINESS'})
            with self.assertRaises(ExternalError):changed.preflight()
