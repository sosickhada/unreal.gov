import json
from pathlib import Path
from types import SimpleNamespace as NS
import socket
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from bureau.config import Config
from bureau.images import screen_photo,SCREEN_KEYS
from bureau.adapters import ExternalError

class PhotoScreeningTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)/'test.jpg';Image.new('RGB',(20,20)).save(self.p)
        self.c=Config(Path(self.tmp.name)/'test.db',{'ENABLE_EXTERNAL_CALLS':'1','CLAUDE_MODEL':'claude-haiku-5-5','ANTHROPIC_API_KEY':'offline-key'})
        self.guard=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN'));self.guard.start()
    def tearDown(self):self.guard.stop();self.tmp.cleanup()
    def response(self,reason,text):return NS(stop_reason=reason,usage=NS(input_tokens=10,output_tokens=20),content=[NS(type='text',text=text)])
    def test_thinking_budget_and_known_incomplete_response_are_saved_without_retry(self):
        with patch('anthropic.Anthropic') as sdk:
            call=sdk.return_value.__enter__.return_value.messages.create;call.return_value=self.response('max_tokens','{"photograph":')
            result=screen_photo(self.c,{'path':str(self.p)},'office desk')
        self.assertTrue(result['invalid_response']);self.assertEqual(result['stop_reason'],'max_tokens')
        call.assert_called_once();self.assertEqual(call.call_args.kwargs['extra_body'],{'output_config':{'effort':'low'}})
        self.assertEqual(call.call_args.kwargs['max_tokens'],1536)
        self.assertEqual(sdk.call_args.kwargs['max_retries'],0)
    def test_valid_assessment_is_returned_with_usage_not_human_flags(self):
        data={**{k:True for k in SCREEN_KEYS},'confidence':.95}
        with patch('anthropic.Anthropic') as sdk:
            sdk.return_value.__enter__.return_value.messages.create.return_value=self.response('end_turn',json.dumps(data))
            result=screen_photo(self.c,{'path':str(self.p)},'office desk')
        self.assertEqual(result['assessment'],data);self.assertNotIn('human_reviewed',result)
    def test_timeout_keeps_safe_diagnostic_and_never_retries(self):
        with patch('anthropic.Anthropic') as sdk:
            call=sdk.return_value.__enter__.return_value.messages.create;call.side_effect=TimeoutError('SECRET')
            with self.assertRaises(ExternalError) as e:screen_photo(self.c,{'path':str(self.p)},'office desk')
        call.assert_called_once();self.assertNotIn('SECRET',str(e.exception))
        self.assertEqual(json.loads(Path(str(self.p)+'.screen-error.json').read_text())['error_type'],'TimeoutError')
    def test_uncertain_photo_is_excluded_instead_of_recharged(self):
        from bureau.images import acquire_photos,LICENSE_URL
        hit={'id':'unknown','provider_type':'photo','source_url':'https://pixabay.com/photos/test-1/','license_url':LICENSE_URL,'tags':'office'}
        d={'title':'office','image_queries':{'content':'office desk','resolution_extra':'office door'},'slides':[{},{}]}
        with patch('bureau.images.search_photo_candidates',return_value=[hit]),patch('bureau.images.download_candidate') as download:
            result=acquire_photos(self.c,d,{},lambda n,f,*a:f(),4,2,['unknown'])
        self.assertFalse(result['photos']);download.assert_not_called()
    def test_known_invalid_response_stops_further_paid_assessments(self):
        from bureau.images import acquire_photos,LICENSE_URL,PhotoScreeningUnavailable
        hit={'id':1,'provider_type':'photo','source_url':'https://pixabay.com/photos/test-1/','license_url':LICENSE_URL,'tags':'office'}
        d={'title':'office','image_queries':{'content':'office desk','resolution_extra':'office door'},'slides':[{},{}]}
        with patch('bureau.images.search_photo_candidates',return_value=[hit]),patch('bureau.images.download_candidate',return_value={'sha256':'test'}),patch('bureau.images.screen_photo',return_value={'invalid_response':True}) as screen:
            with self.assertRaises(PhotoScreeningUnavailable):acquire_photos(self.c,d,{},lambda n,f,*a:f(),4,2)
        screen.assert_called_once()
    def test_operator_photo_repair_preserves_unknown_checkpoint_and_excludes_source(self):
        from bureau.cli import resume_photo_render
        from bureau.store import Store,now
        s=Store(self.c.db);s.migrate()
        with s.tx() as c:
            c.execute("INSERT INTO selections(id,candidate_number,candidate_title,status,revision) VALUES(4,1,'test','draft_ready',2)")
            jid=s.enqueue(c,'render:4:2','render',{'id':4,'revision':2})
            c.execute("UPDATE jobs SET state='uncertain' WHERE id=?",(jid,))
            for name,state,result in [('claude_photo_v2_content_1_commons-7','uncertain',None),('photo_v2_content_1_commons-7_download','succeeded',json.dumps({'id':'commons-7'}))]:
                c.execute('INSERT INTO checkpoints(job_id,step,state,result,created_at) VALUES(?,?,?,?,?)',(jid,name,state,result,now()))
        resume_photo_render(s,jid)
        with s.tx() as c:
            row=c.execute('SELECT state,payload FROM jobs WHERE id=?',(jid,)).fetchone()
            self.assertEqual(row['state'],'queued');self.assertEqual(json.loads(row['payload'])['exclude_photo_ids'],['commons-7'])
            self.assertEqual(c.execute("SELECT state FROM checkpoints WHERE step LIKE 'claude_photo%'").fetchone()[0],'uncertain')
            c.execute("UPDATE jobs SET state='uncertain' WHERE id=?",(jid,))
            c.execute("UPDATE checkpoints SET step='claude_draft' WHERE step LIKE 'claude_photo%'")
        with self.assertRaises(ValueError):resume_photo_render(s,jid)
