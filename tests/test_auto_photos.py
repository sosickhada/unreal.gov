"""Automatic preview acquisition: fake providers, real byte checks, no sockets."""
import copy
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch,Mock
from PIL import Image
from bureau.config import Config
from bureau.images import (SCREEN_KEYS,LICENSE_URL,acquire_photos,checked_photo,inspect_image,
                           photo_queries,pixabay_search,similar_photo)
from bureau.engine import Uncertain
from bureau.cli import resume
import test_system as system

GOOD={**{key:True for key in SCREEN_KEYS},'confidence':.98,'reason':'offline fixture assessment'}

class AutoPhotosTest(unittest.TestCase):
    def setUp(self):
        self.guard=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN'));self.guard.start()
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config=Config(self.root/'test.db',{'ENABLE_EXTERNAL_CALLS':'1','PIXABAY_API_KEY':'test'})
        self.photos=[]
        for i in (1,2,3):
            p=self.root/f'{i}.png';Image.effect_noise((1200,1600),80).save(p,compress_level=0)
            self.photos.append(dict(self.hit(i),**inspect_image(p.read_bytes()),path=str(p)))
        self.draft={'title':'가상 사무실 사건','image_queries':{'content':'empty office desk','resolution_extra':'closed office door'},'slides':[{}, {'body':'가상 사건'}]}
        self.cache={};self.steps=[]
    def tearDown(self):self.guard.stop();self.tmp.cleanup()
    def hit(self,i):return {'id':i,'provider_type':'photo','source_url':f'https://pixabay.com/photos/desk-{i}/','download_url':f'https://cdn.pixabay.com/{i}.jpg','license_url':LICENSE_URL,'license':'Pixabay Content License','tags':'office desk door','review_required':True}
    def step(self,name,call,ambiguous=False,paid=False):
        if name not in self.cache:
            self.steps.append((name,ambiguous,paid));self.cache[name]=call()
        return copy.deepcopy(self.cache[name])
    def download(self,c,h,p):return copy.deepcopy(self.photos[h['id']-1])
    def screen(self,*a):return {'assessment':copy.deepcopy(GOOD),'method':'mock vision','input_tokens':3,'output_tokens':4}
    def test_two_photos_have_machine_evidence_never_fake_human_review(self):
        with patch('bureau.images.search_photo_candidates',side_effect=[[self.hit(1)],[self.hit(2)]]),patch('bureau.images.download_candidate',side_effect=self.download),patch('bureau.images.screen_photo',side_effect=self.screen) as vision:
            result=acquire_photos(self.config,self.draft,{},self.step,4,2)
            replay=acquire_photos(self.config,self.draft,{},self.step,4,2)
        self.assertEqual(len(result['photos']),2);self.assertEqual(vision.call_count,2)
        self.assertEqual(result['photos'],replay['photos'])
        for photo in result['photos'].values():
            self.assertFalse(photo['human_reviewed']);self.assertTrue(photo['review_required'])
            self.assertNotIn('reviewer',photo);checked_photo(photo)
        self.assertEqual(sum(paid for _,_,paid in self.steps),2)
    def test_three_queries_maximum_and_no_blind_retry_after_vision_timeout(self):
        with patch('bureau.images.search_photo_candidates',return_value=[]) as search:
            result=acquire_photos(self.config,self.draft,{},self.step,4,2)
        self.assertEqual(search.call_count,6);self.assertFalse(result['photos'])
        self.cache={}
        with patch('bureau.images.search_photo_candidates',return_value=[self.hit(1)]),patch('bureau.images.download_candidate',side_effect=self.download),patch('bureau.images.screen_photo',side_effect=Uncertain('unknown')) as vision:
            with self.assertRaises(Uncertain):acquire_photos(self.config,self.draft,{},self.step,4,2)
        vision.assert_called_once()
    def test_rejected_watermark_ai_people_or_uncertain_do_not_pass(self):
        for flag in SCREEN_KEYS:
            self.cache={};bad=dict(GOOD);bad[flag]=False
            with patch('bureau.images.search_photo_candidates',return_value=[self.hit(1)]),patch('bureau.images.download_candidate',side_effect=self.download),patch('bureau.images.screen_photo',return_value={'assessment':bad}):
                self.assertFalse(acquire_photos(self.config,self.draft,{},self.step,4,2)['photos'])
    def test_unlicensed_candidate_never_downloaded_and_duplicate_never_screened(self):
        bad=self.hit(1);bad['license_url']='https://unknown.invalid/license'
        with patch('bureau.images.search_photo_candidates',return_value=[bad]),patch('bureau.images.download_candidate') as download:
            self.assertFalse(acquire_photos(self.config,self.draft,{},self.step,4,2)['photos'])
        download.assert_not_called();self.cache={}
        with patch('bureau.images.search_photo_candidates',return_value=[self.hit(1)]),patch('bureau.images.download_candidate',side_effect=self.download),patch('bureau.images.screen_photo',side_effect=self.screen) as vision:
            result=acquire_photos(self.config,self.draft,{},self.step,4,2)
        self.assertEqual(len(result['photos']),1);vision.assert_called_once()
    def test_changed_bytes_and_low_native_resolution_are_rejected(self):
        photo=dict(self.photos[0],selection_policy='automated-preview-v1',human_reviewed=False,final_human_review_required=True,screening=GOOD)
        Path(photo['path']).write_bytes(Path(self.photos[1]['path']).read_bytes())
        with self.assertRaisesRegex(ValueError,'bytes changed'):checked_photo(photo)
        from io import BytesIO
        b=BytesIO();Image.new('RGB',(800,1000)).save(b,'PNG')
        with self.assertRaisesRegex(ValueError,'resolution'):inspect_image(b.getvalue())
        a={'sha256':'a','perceptual_hash':'0000000000000000'};b={'sha256':'b','perceptual_hash':'0000000000000001'}
        self.assertTrue(similar_photo(a,[b]))
    def test_pixabay_cache_metadata_filters_and_download_url_is_not_invented(self):
        hits=[]
        for i,tags in [(1,'office desk'),(2,'ai-generated office'),(3,'portrait'),(4,'watermark')]:
            hits.append({'id':i,'type':'photo','tags':tags,'pageURL':self.hit(i)['source_url'],'largeImageURL':f'https://cdn.pixabay.com/{i}.jpg'})
        http=Mock();http.get.return_value=Mock(json=lambda:{'hits':hits})
        a=pixabay_search(self.config,'office desk',http);b=pixabay_search(self.config,'office desk',http)
        self.assertEqual(a,b);self.assertEqual(http.get.call_count,1)
        self.assertEqual(a[0]['download_url'],'https://cdn.pixabay.com/1.jpg')
        self.assertFalse(any(h['id'] in (2,3) for h in a))

    def test_commons_accepts_only_explicit_cc0_and_keeps_returned_original_url(self):
        from bureau.images import commons_search,license_evidence
        meta={'LicenseShortName':{'value':'CC0'},'LicenseUrl':{'value':'https://creativecommons.org/publicdomain/zero/1.0/'}}
        good={'pageid':23,'title':'File:Food containers.jpg','imageinfo':[{'width':2400,'height':3200,'mime':'image/jpeg','url':'https://upload.wikimedia.org/food.jpg','descriptionurl':'https://commons.wikimedia.org/wiki/File:Food_containers.jpg','extmetadata':meta}]}
        bad=copy.deepcopy(good);bad['pageid']=24;bad['imageinfo'][0]['extmetadata']['LicenseShortName']['value']='CC BY-SA 4.0'
        http=Mock();http.get.return_value=Mock(json=lambda:{'query':{'pages':{'23':good,'24':bad}}})
        result=commons_search(self.config,'food containers',http)
        self.assertEqual(len(result),1);self.assertEqual(result[0]['download_url'],'https://upload.wikimedia.org/food.jpg')
        self.assertEqual(license_evidence(result[0])['provider'],'Wikimedia Commons')
    def test_basic_pixabay_key_uses_licensed_high_resolution_fallback(self):
        from bureau.images import search_photo_candidates
        with patch('bureau.images.pixabay_search',return_value=[dict(self.hit(1),high_resolution_available=False)]),patch('bureau.images.commons_search',return_value=[{'id':'commons-1'}]) as commons:
            self.assertEqual(search_photo_candidates(self.config,'food'),[{'id':'commons-1'}])
        commons.assert_called_once()

    def test_official_thumbnail_host_is_accepted_and_429_stops_downloads(self):
        from bureau.images import download_candidate,PhotoRateLimited
        hit=dict(self.hit(1),download_url='https://thumb.wikimedia.org/wikipedia/commons/thumb/file.jpg')
        http=Mock();http.get.return_value=Mock(status_code=200,content=Path(self.photos[0]['path']).read_bytes())
        result=download_candidate(self.config,hit,self.root/'download.jpg',http)
        self.assertEqual(result['width'],1200)
        http.get.return_value=Mock(status_code=429,headers={'Retry-After':'60'})
        with self.assertRaises(PhotoRateLimited):download_candidate(self.config,hit,self.root/'blocked.jpg',http)
        calls=http.get.call_count
        with self.assertRaises(PhotoRateLimited):download_candidate(self.config,hit,self.root/'blocked.jpg',http)
        self.assertEqual(http.get.call_count,calls)

class AutoPipelineTest(unittest.TestCase):
    setUp=system.SystemTest.setUp
    tearDown=system.SystemTest.tearDown
    q=system.SystemTest.q
    candidates=system.SystemTest.candidates
    def test_waiting_render_resumes_without_mutating_approved_text(self):
        cid=self.candidates();rid=self.store.select(cid);self.engine.run_one();self.store.accept_draft(rid,1)
        original=self.store.row(rid)['draft_json']
        self.engine.config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1','REQUIRE_TOPIC_IMAGE':'1'})
        self.engine.run_one();job=self.q("SELECT id,state FROM jobs WHERE kind='render'")[0]
        self.assertEqual(job['state'],'waiting')
        self.engine.config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1','REQUIRE_TOPIC_IMAGE':'1','AUTO_PHOTO_ACQUIRE':'1'})
        photos={slot:{'path':slot,'sha256':slot,'source_url':'https://pixabay.com/photos/test/','license_url':LICENSE_URL} for slot in ('content','resolution_extra')}
        with patch('bureau.images.acquire_photos',return_value={'photos':photos,'attempts':[],'candidate_links':[]}):
            resume(self.store,job['id']);self.engine.run_one()
        self.assertEqual(self.store.row(rid)['status'],'preview_ready')
        self.assertEqual(self.store.row(rid)['draft_json'],original)
        asset=json.loads(self.q('SELECT payload FROM assets')[0]['payload'])
        self.assertEqual(asset['image_provenance']['photos'],photos)
    def test_exhaustion_requests_user_photo_choice_and_image_edit_is_allowed(self):
        cid=self.candidates();rid=self.store.select(cid);self.engine.run_one();self.store.accept_draft(rid,1)
        self.engine.config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1','REQUIRE_TOPIC_IMAGE':'1','AUTO_PHOTO_ACQUIRE':'1'})
        with patch('bureau.images.acquire_photos',return_value={'photos':{},'attempts':[],'candidate_links':['https://pixabay.com/photos/test/']}):self.engine.run_one()
        self.assertEqual(self.q("SELECT state FROM jobs WHERE kind='render'")[0]['state'],'waiting')
        self.assertTrue(self.q("SELECT * FROM outbox WHERE delivery_key LIKE 'photo-choice:%'"))
        self.store.await_revision('11',rid,1,'image');self.store.apply_revision('11','office desk','new-query')
        self.assertEqual(self.store.row(rid)['revision'],2)
