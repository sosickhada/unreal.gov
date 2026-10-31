import asyncio
from copy import deepcopy
import json
from pathlib import Path
import socket
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch, Mock, AsyncMock

from bureau.config import Config
from bureau.store import Store
from bureau.adapters import Media, Telegram, Claude, ExternalError
from bureau.instagram import Instagram
from bureau.images import inspect_image, manual_image, pixabay_search
from test_system import NEWS,CANDIDATES,draft


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.guard=patch.object(socket.socket,'connect',side_effect=AssertionError('Network forbidden'));self.guard.start()
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.db'
    def tearDown(self):self.guard.stop();self.tmp.cleanup()
    def config(self,**extra):
        e={'ENABLE_EXTERNAL_CALLS':'1','INSTAGRAM_PUBLISH_ENABLED':'1','IG_ACCESS_TOKEN':'test-token','IG_ACCOUNT_ID':'123','IG_GRAPH_VERSION':'v25.0','IG_TOKEN_EXPIRES_AT':'4102444800'}
        e.update(extra);return Config(self.path,e)
    def test_instagram_login_preflight(self):
        ig=Instagram(self.config())
        ig.request=Mock(side_effect=[{'user_id':'123','username':'test','account_type':'MEDIA_CREATOR'},
            {'data':[{'permission':p,'status':'granted'} for p in ('instagram_business_basic','instagram_business_content_publish')]},
            {'data':[{'quota_usage':0,'config':{'quota_total':100}}]}])
        self.assertTrue(ig.preflight()['valid'])
        ig.request=Mock(return_value={'user_id':'wrong','account_type':'BUSINESS'})
        with self.assertRaises(ExternalError):ig.preflight()

    def test_instagram_login_requires_scopes_and_verified_expiry(self):
        profile={'user_id':'123','account_type':'BUSINESS'}
        perms={'data':[{'permission':p,'status':'granted'} for p in ('instagram_business_basic','instagram_business_content_publish')]}
        for config,responses in [(self.config(),[profile,{'data':[]}]),
                                 (self.config(IG_TOKEN_EXPIRES_AT=''),[profile,perms]),
                                 (self.config(IG_TOKEN_EXPIRES_AT='1'),[profile,perms])]:
            ig=Instagram(config);ig.request=Mock(side_effect=responses)
            with self.assertRaises(ExternalError):ig.preflight()

    def test_meta_read_only_check_does_not_enable_writes(self):
        http=Mock();http.request.return_value.json.return_value={'id':'123'}
        ig=Instagram(self.config(INSTAGRAM_PUBLISH_ENABLED='0'),http)
        self.assertEqual(ig.request('GET','123',fields='id'),{'id':'123'})
        with self.assertRaises(ExternalError):ig.child('https://media.example/a.jpg')
        self.assertEqual(http.request.call_count,1)

    def test_meta_missing_settings_report_names_only(self):
        ig=Instagram(self.config(IG_ACCESS_TOKEN=''))
        self.assertEqual(ig.missing_settings(),['IG_ACCESS_TOKEN'])
        self.assertFalse(ig.enabled())

    def test_meta_carousel_payload_and_invalid_children(self):
        http=Mock();http.request.return_value.json.return_value={'id':'container'}
        ig=Instagram(self.config(),http)
        ig.carousel(['child1','child2'],'caption')
        self.assertEqual(http.request.call_args.kwargs['data'],
                         {'media_type':'CAROUSEL','children':'child1,child2','caption':'caption'})
        for children in ([],['one'],['one','one'],[str(i) for i in range(11)]):
            with self.assertRaises(ExternalError):ig.carousel(children,'caption')
        self.assertEqual(http.request.call_count,1)

    def test_meta_disallows_personal_account(self):
        ig=Instagram(self.config());ig.request=Mock(return_value={'user_id':'123','account_type':'PERSONAL'})
        with self.assertRaises(ExternalError):ig.preflight()

    def test_meta_official_host_and_bearer_token_no_query_token(self):
        http=Mock();http.request.return_value.json.return_value={'id':'7'}
        ig=Instagram(self.config(),http);ig.child('https://media.example/a.jpg')
        args,kw=http.request.call_args
        self.assertEqual(args[1],'https://graph.instagram.com/v25.0/123/media')
        self.assertNotIn('access_token',kw['data']);self.assertEqual(kw['headers']['Authorization'],'Bearer test-token')
    def test_meta_failure_redacts_token(self):
        http=Mock();http.request.side_effect=RuntimeError('SENSITIVE test-token')
        with self.assertRaises(ExternalError) as ctx:Instagram(self.config(),http).child('https://example.org/a.jpg')
        self.assertNotIn('test-token',str(ctx.exception))
    def test_external_calls_disabled_before_request(self):
        http=Mock();ig=Instagram(self.config(ENABLE_EXTERNAL_CALLS='0'),http)
        self.assertFalse(ig.enabled())
        with self.assertRaises(RuntimeError):ig.child('https://example.org/a.jpg')
        http.request.assert_not_called()
    def test_image_rejects_native_low_resolution(self):
        from PIL import Image
        from io import BytesIO
        out=BytesIO();Image.new('RGB',(600,900)).save(out,'JPEG')
        with self.assertRaisesRegex(ValueError,'native resolution'):inspect_image(out.getvalue())
    def test_image_evidence_requires_reviewer(self):
        with self.assertRaises(ValueError):manual_image('/not/read','https://example.org/a','https://example.org/license','license','')
    def test_pixabay_preserves_returned_url_and_requires_manual_review(self):
        http=Mock();url='https://cdn.pixabay.com/photo/exact-returned-image.jpg'
        http.get.return_value.json.return_value={'hits':[{'id':1,'largeImageURL':url,'pageURL':'https://pixabay.com/photos/1/','tags':'empty office'}]}
        results=pixabay_search(self.config(PIXABAY_API_KEY='test'), 'empty office',http)
        self.assertEqual(results[0]['download_url'],url);self.assertTrue(results[0]['review_required'])
        self.assertNotIn('face_detection_verified',results[0])
    def test_public_validation_rejects_redirect(self):
        response=Mock(status_code=302,content=b'html',headers={'Content-Type':'text/html'})
        config=self.config(PUBLIC_BASE_URL='https://media.example')
        with patch('bureau.adapters.requests.get',return_value=response):
            with self.assertRaises(ExternalError):Media(config).verify({'urls':['https://media.example/a.jpg'],'files':['/tmp/missing'],'sha256':['none']})
    def test_env_loader_no_shell_expansion_and_process_override(self):
        env=Path(self.tmp.name)/'env';env.write_text('CLAUDE_MODEL="model-name"\nEXAMPLE="literal $(touch /tmp/unsafe)"\n')
        with patch.dict('os.environ',{'UNREAL_ENV_FILE':str(env),'CLAUDE_MODEL':'override'},clear=True):
            c=Config.load();self.assertEqual(c.env['CLAUDE_MODEL'],'override');self.assertIn('$(',c.env['EXAMPLE'])
    def test_telegram_timeout_safe_error(self):
        config=self.config(TELEGRAM_BOT_TOKEN='private',TELEGRAM_CHAT_ID='test')
        with patch('bureau.adapters.requests.post',side_effect=TimeoutError('https://api.telegram.org/botprivate')):
            with self.assertRaises(ExternalError) as ctx:Telegram(config).send({'text':'test'})
        self.assertNotIn('private',str(ctx.exception))
    def test_telegram_handlers_use_same_saved_candidates_and_authorization(self):
        from bureau.telegram_app import build_app
        store=Store(self.path);store.migrate();store.schedule()
        with store.tx() as c:
            batch=c.execute('SELECT id FROM batches').fetchone()[0]
            c.execute("UPDATE batches SET status='ready'")
            for i,d in enumerate(CANDIDATES['candidates'],1):
                c.execute('INSERT INTO candidates(batch_id,position,title,payload,created_at) VALUES(?,?,?,?,?)',(batch,i,d['title'],json.dumps(d),'test'))
        config=self.config(TELEGRAM_BOT_TOKEN='123456:OFFLINE_ONLY_012345678901234567890123456789',TELEGRAM_CHAT_ID='22',TELEGRAM_ALLOWED_USER_IDS='11')
        app=build_app(config)
        command=next(h.callback for h in app.handlers[0] if getattr(h,'commands',None) and 'candidates' in h.commands)
        callback=next(h.callback for h in app.handlers[0] if h.__class__.__name__=='CallbackQueryHandler')
        update=NS(effective_chat=NS(id=22),effective_user=NS(id=11),update_id=100,message=NS(text='/candidates'))
        asyncio.run(command(update,NS(args=[])))
        with store.tx() as c:
            payload=json.loads(c.execute('SELECT payload FROM outbox').fetchone()[0])
            cid=c.execute('SELECT id FROM candidates ORDER BY position').fetchone()[0]
        self.assertEqual(payload['reply_markup']['inline_keyboard'][0][0]['callback_data'],f'candidate:{cid}')
        update.callback_query=NS(data=f'candidate:{cid}',answer=AsyncMock());update.update_id=101
        asyncio.run(callback(update,NS()))
        self.assertEqual(store.row(1)['candidate_id'],cid)
        update.effective_user.id=999;update.callback_query.data=f'candidate:{cid+1}'
        asyncio.run(callback(update,NS()))
        with store.tx() as c:self.assertEqual(c.execute('SELECT count(*) FROM selections').fetchone()[0],1)
    @unittest.skipUnless(Path('/opt/unreal-github/figma_assets/fonts/ROKG_R.ttf').is_file(), 'Private approved Figma assets not available')
    def test_renderer_uses_four_or_five_approved_pages(self):
        from figma_renderer import expand_slides,validate_fonts,make_figma_cover
        d=draft(NEWS[0]['url']);validate_fonts(d)
        self.assertEqual([kind for kind,_ in expand_slides(d)],['cover','content','resolution_extra','resolution_final','ending'])
        d['slides'][2]['body']='가상 처분을 통보합니다.'
        self.assertEqual(len(expand_slides(d)),4)
        cover=make_figma_cover(d['slides'][0],d['title'])
        self.assertIn('logo',cover)


if __name__=='__main__':unittest.main()
