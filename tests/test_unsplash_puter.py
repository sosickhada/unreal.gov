import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from bureau.config import Config
from bureau.unsplash import search
from bureau.puter_images import generate, inspect_account, PuterBlocked
from bureau.images import download_candidate
from bureau.adapters import ExternalError
from bureau.store import Store

class HybridTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.config=Config(Path(self.tmp.name)/'db',{'ENABLE_EXTERNAL_CALLS':'1','UNSPLASH_ACCESS_KEY':'secret','PUTER_AUTH_TOKEN':'secret'})
        self.http=Mock()
    def test_unsplash_original_metadata_and_header(self):
        p={'id':'abc','width':2400,'height':3000,'urls':{'raw':'https://images.unsplash.com/photo?ixid=original'},'links':{'html':'https://unsplash.com/photos/abc'},'user':{'name':'Artist','links':{'html':'https://unsplash.com/@artist'}},'alt_description':'office desk'}
        self.http.get.return_value.json.return_value={'results':[p,dict(p,width=800)]}
        photos=search(self.config,'office desk',self.http)
        self.assertEqual(len(photos),1);self.assertEqual(photos[0]['original_height'],3000)
        self.assertIn('ixid=original',photos[0]['hotlink_url']);self.assertFalse(photos[0]['render_allowed'])
        self.assertEqual(self.http.get.call_args.kwargs['headers']['Authorization'],'Client-ID secret')
        with self.assertRaises(ExternalError):download_candidate(self.config,photos[0],Path(self.tmp.name)/'image',self.http)
        self.assertEqual(self.http.get.call_count,1)
    def test_unsplash_errors_redacted(self):
        self.http.get.side_effect=RuntimeError('secret')
        with self.assertRaises(ExternalError) as e:search(self.config,'office',self.http)
        self.assertNotIn('secret',str(e.exception))
    def test_auth_mock(self):
        with patch('bureau.puter_images.subprocess.run',return_value=Mock(stdout=json.dumps({'authenticated':True,'models':[]}))) as run:
            self.assertTrue(inspect_account(self.config)['authenticated'])
            self.assertEqual(run.call_args.kwargs['env']['PUTER_AUTH_TOKEN'],'secret')
            self.assertNotIn('secret',str(run.call_args.args))
    def test_no_generation_without_free_only_cost_proof(self):
        with patch('bureau.puter_images.subprocess.run') as run:
            for approved in (False,True):
                with self.assertRaises(PuterBlocked):generate(self.config,{'image_queries':{'content':'Korean office'}},'content',approved_test=approved)
            run.assert_not_called()
        with Store(self.config.db).tx() as c:
            rows=c.execute('SELECT mode,state FROM puter_image_attempts').fetchall()
        self.assertEqual([r['mode'] for r in rows],['automatic','approved_test'])
        self.assertTrue(all(r['state']=='blocked' for r in rows))
