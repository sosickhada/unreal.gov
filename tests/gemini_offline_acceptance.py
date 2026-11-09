"""Real Chromium with synthetic Gemini responses. No paid or external API calls."""
import base64
import datetime as dt
import json
from pathlib import Path
import socket
import sys
from unittest.mock import Mock,patch
from PIL import Image,ImageOps
from io import BytesIO
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bureau.config import Config
from bureau.store import Store,now
from bureau.engine import Engine
from bureau.adapters import Media
from bureau.photo_review import approve
from bureau.gemini_images import pricing
from test_system import FakeClaude,FakeTelegram,FakeInstagram
from test_gemini_images import GeminiTests
from render_smoke import SAMPLE


def main():
    root=(Path('output/gemini-offline-acceptance')/now().replace(':','-')).resolve();root.mkdir(parents=True)
    cfg=Config(root/'test.db',{'ENABLE_EXTERNAL_CALLS':'1','GEMINI_IMAGE_ENABLED':'1','GEMINI_API_KEY':'OFFLINE_MOCK_ONLY',
        'AUTO_PHOTO_ACQUIRE':'1','REQUIRE_TOPIC_IMAGE':'1','IMAGE_DIR':str(root),'PUBLIC_BASE_URL':'https://offline.invalid',
        'RENDER_TIMEOUT_SECONDS':'240','RENDER_TRACE_DIR':str(root)})
    store=Store(cfg.db);store.migrate();draft=json.loads(json.dumps(SAMPLE))
    draft.update(caption='허구 기관의 풍자 창작 · OFFLINE ONLY',source_url=None,claims=[],image_queries={'content':'empty Korean office desk','resolution_extra':'empty shared kitchen kettle'})
    with store.tx() as c:
        c.execute("INSERT INTO selections(id,candidate_number,candidate_title,status,revision,draft_json) VALUES(1,1,'offline','draft_ready',1,?)",(json.dumps(draft),))
        store.enqueue(c,'render:1:1','render',{'id':1,'revision':1})
    GeminiTests.setUpClass();first=GeminiTests.image
    out=BytesIO()
    with Image.open(BytesIO(first)) as image:ImageOps.invert(image.convert('RGB')).save(out,'PNG')
    def response(content):
        payload={'candidates':[{'finishReason':'STOP','content':{'parts':[{'inlineData':{'mimeType':'image/png','data':base64.b64encode(content).decode()}}]}}],
                 'usageMetadata':{'promptTokenCount':400,'candidatesTokenCount':1680,'thoughtsTokenCount':50}}
        return Mock(status_code=200,iter_content=Mock(return_value=[json.dumps(payload).encode()]))
    def public_get(url,**kw):return Mock(content=(root/url.rsplit('/',1)[-1]).read_bytes(),headers={'Content-Type':'image/jpeg'},status_code=200)
    telegram=FakeTelegram();instagram=FakeInstagram()
    engine=Engine(cfg,FakeClaude(),Media(cfg),telegram,instagram)
    with patch('bureau.gemini_images.pricing',side_effect=lambda config,at=None:pricing(config,at or dt.datetime(2026,11,9,tzinfo=dt.timezone.utc))),patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN')),patch('bureau.images.acquire_photos',return_value={'photos':{},'attempts':[],'candidate_links':[]}),patch('bureau.gemini_images.requests.post',side_effect=[response(first),response(out.getvalue())]) as api,patch('bureau.adapters.requests.get',side_effect=public_get):
        assert engine.run_one()
        with store.tx() as c:
            rows=c.execute("SELECT rowid,result FROM checkpoints WHERE step LIKE 'gemini_image_%' AND state='succeeded'").fetchall()
            assert len(rows)==2
        for row in rows:approve(store,1,1,row[0],json.loads(row[1])['slot'],'OFFLINE SYNTHETIC FIXTURE REVIEW ONLY')
        assert engine.run_one();assert store.row(1)['status']=='preview_ready'
        with store.tx() as c:
            assets=json.loads(c.execute('SELECT payload FROM assets').fetchone()[0])
            attempts=[dict(r) for r in c.execute('SELECT state,reserved_krw FROM gemini_image_attempts')]
        assert len(assets['pngs'])==5
        photos=assets['image_provenance']['photos'];assert all(p['provider']=='gemini' for p in photos.values())
        assert photos['content']['sha256']!=photos['resolution_extra']['sha256']
        for filename in assets['pngs']:
            with Image.open(filename) as image:assert image.size==(1080,1350)
        while engine.deliver_one():pass
        store.review(1,1);store.decide(1,1,True);assert engine.run_one()
        assert store.row(1)['status']=='publish_waiting' and instagram.published==0
        assert api.call_count==2 and len(attempts)==2
        report={'result':'PASS','external_calls':0,'gemini_mock_calls':api.call_count,'telegram_mock_deliveries':telegram.calls,
                'rendered_pages':len(assets['pngs']),'status':store.row(1)['status'],'reserved_krw':sum(r['reserved_krw'] for r in attempts),
                'fixtures_only':True,'real_gemini_auth_verified':False,'real_photo_quality_or_license_verified':False}
    target=root/'report.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(target,flush=True)

if __name__=='__main__':main()
