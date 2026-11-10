import json
import unittest
from pathlib import Path
from copy import deepcopy
from bureau.release import validate_official


class OfficialReleaseTests(unittest.TestCase):
    def setUp(self):
        self.draft=json.loads((Path(__file__).resolve().parents[1]/'content/first-official-shipping.json').read_text())
        photo={'review_required':False,'source_url':'https://www.pexels.com/photo/source/','license_url':'https://www.pexels.com/license/'}
        self.media={'files':[f'page{i}.jpg' for i in range(5)],'urls':[f'https://media.example/page{i}.jpg' for i in range(5)],'sha256':[str(i) for i in range(5)],'image_provenance':{'photos':{'content':photo,'resolution_extra':dict(photo)}}}
    def test_finished_copy_has_five_slides_and_concise_relevant_caption(self):
        from figma_renderer import expand_slides
        self.assertTrue(validate_official(self.draft,self.media)['official'])
        self.assertEqual(len(expand_slides(self.draft)),5)
        caption=self.draft['caption']
        self.assertIn('1,800원',caption)
        self.assertEqual(len([word for word in caption.split() if word.startswith('#')]),6)
        self.assertLess(len('비현실문제부의 풍자 창작입니다.'),len(caption)/4)
        self.assertNotIn('출처 URL은 없습니다',caption)
    def test_test_copy_missing_official_marker_and_escaped_newlines_block(self):
        for key,value in [('title','Instagram 테스트 게시물'),('caption','임시 캡션 #풍자 창작'),('caption','풍자 창작 #비현실문제부\\n테마'),('publication_kind','test')]:
            d=deepcopy(self.draft);d[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate_official(d,self.media)
    def test_fallback_cover_incomplete_carousel_and_unreviewed_images_block(self):
        d=deepcopy(self.draft);d['slides'][0].pop('background_image')
        with self.assertRaises(ValueError):validate_official(d,self.media)
        m=deepcopy(self.media);m['files'].pop()
        with self.assertRaises(ValueError):validate_official(self.draft,m)
        m=deepcopy(self.media);m['image_provenance']['photos']['content']['review_required']=True
        with self.assertRaises(ValueError):validate_official(self.draft,m)
    def test_official_case_number_replaces_template_case_number(self):
        from figma_renderer import make_figma_cover
        from unittest.mock import patch
        # Inspect production markup without depending on server-only image/font files.
        with patch('pathlib.Path.is_file',return_value=True):
            markup=make_figma_cover(dict(self.draft['slides'][0],case_number=self.draft['case_number']),self.draft['title'],inline_assets=False)
        self.assertIn('2026-1110-001',markup)
        self.assertNotIn('2026-1024',markup)

    def test_official_render_queues_bound_approval_after_album_without_publication(self):
        import tempfile
        from unittest.mock import Mock,patch
        from bureau.config import Config
        from bureau.store import Store,now
        from bureau.engine import Engine
        with tempfile.TemporaryDirectory() as root:
            cfg=Config(Path(root)/'db',{'IG_ACCOUNT_ID':'123','REQUIRE_TOPIC_IMAGE':'1','RENDER_DIR':root,'ENABLE_PUBLIC_MEDIA':'1'})
            store=Store(cfg.db);store.migrate()
            photos=deepcopy(self.media['image_provenance']['photos'])
            photos['content']['path']='detergent.jpg';photos['resolution_extra']['path']='parcel.jpg'
            with store.tx() as c:
                c.execute("INSERT INTO selections(id,candidate_number,candidate_title,status,revision,draft_json) VALUES(1,1,'official','draft_ready',1,?)",(json.dumps(self.draft),))
                c.execute('INSERT INTO image_inputs VALUES(1,1,?,?)',(json.dumps({'photos':photos}),now()))
                jid=store.enqueue(c,'render:1:1','render',{'id':1,'revision':1})
            media=Mock();media.render.return_value=deepcopy(self.media);media.expose.return_value={'exposed':True};media.verify.return_value={'verified':True}
            engine=Engine(cfg,media=media,instagram=Mock())
            with patch('bureau.images.select_photos',return_value=photos):engine.render({'id':jid},{'id':1,'revision':1})
            with store.tx() as c:
                self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='publish'").fetchone()[0],0)
                final=json.loads(c.execute("SELECT payload FROM outbox WHERE delivery_key='instagram-final:1:1'").fetchone()[0])
                self.assertEqual(final['after_delivery'],'media:1:1')
                self.assertTrue(final['reply_markup']['inline_keyboard'][0][0]['callback_data'].startswith('igapprove:1:1:'))
                self.assertEqual(c.execute('SELECT approved FROM instagram_reviews WHERE selection_id=1').fetchone()[0],0)
            engine.instagram.publish.assert_not_called()
