"""Explicit offline acceptance: real Chromium, synthetic fixtures, mocked providers.
Run: .venv/bin/python tests/offline_acceptance.py
Fixtures are NOT photographs and must never be registered in production.
"""
import hashlib
from copy import deepcopy
import json
from pathlib import Path
import sys
import socket
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from bureau.config import Config
from bureau.store import Store, now
from bureau.engine import Engine
from bureau.adapters import Media
from bureau.images import manual_image
from render_smoke import SAMPLE
from test_system import FakeClaude, FakeTelegram, FakeInstagram, NEWS


def main():
    root=Path('output/offline-acceptance')/now().replace(':','-')
    root.mkdir(parents=True)
    config=Config(root/'test.db',{'ENABLE_EXTERNAL_CALLS':'1','CANDIDATE_GENERATION_MODE':'model','USE_NEWS_REFERENCE':'1','IMAGE_DIR':str(root.resolve()),
        'PUBLIC_BASE_URL':'https://offline.invalid','REQUIRE_TOPIC_IMAGE':'1','RENDER_TIMEOUT_SECONDS':'180','RENDER_TRACE_DIR':str(root.resolve())})
    store=Store(config.db);store.migrate()
    fixtures=[]
    for name,colors,tags in [('desk',('#102638','#a0c5ce'),'office desk'),('door',('#3b301c','#d6b77a'),'office door')]:
        path=root/(name+'.png')
        fixture=Image.new('RGB',(1200,1500),colors[0]);draw=ImageDraw.Draw(fixture)
        for y in range(0,1500,40):
            for x in range(0,1200,40):
                if (x//40+y//40)%2: draw.rectangle((x,y,x+39,y+39),fill=colors[1])
        fixture.save(path)
        photo=manual_image(path,'https://fixture.invalid/'+name,'https://fixture.invalid/license','OFFLINE SYNTHETIC FIXTURE ONLY','OFFLINE TEST ONLY')
        fixtures.append(photo)
        with store.tx() as c:c.execute('INSERT INTO image_library VALUES(?,?,?,?)',(photo['sha256'],json.dumps(photo),tags,now()))
    claude=FakeClaude();original=claude.generate
    def generate(prompt,maximum):
        result=original(prompt,maximum)
        if maximum==4000:
            d=json.loads(result['raw']);d.update(deepcopy(SAMPLE));d['image_queries']={'content':'office desk','resolution_extra':'office door'}
            result['raw']=json.dumps(d,ensure_ascii=False)
        return result
    claude.generate=generate
    media=Media(config);telegram=FakeTelegram();ig=FakeInstagram()
    engine=Engine(config,claude,media,telegram,ig,lambda:NEWS)
    def public_get(url,**kw):
        body=(root/url.rsplit('/',1)[-1]).read_bytes()
        return Mock(content=body,headers={'Content-Type':'image/jpeg'},status_code=200)
    with patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN')),patch('bureau.adapters.requests.get',side_effect=public_get):
        store.schedule();store.schedule();assert engine.run_one()
        with store.tx() as c:cid=c.execute('SELECT id FROM candidates ORDER BY position').fetchone()[0]
        rid=store.select(cid);assert store.select(cid)==rid
        assert engine.run_one();store.accept_draft(rid,store.row(rid)['revision']);assert engine.run_one()
        assert store.row(rid)['status']=='preview_ready'
        with store.tx() as c:artifact=json.loads(c.execute('SELECT payload FROM assets').fetchone()[0])
        assert len(artifact['pngs'])==5
        assert artifact['image_provenance']['photos']['content']['sha256']!=artifact['image_provenance']['photos']['resolution_extra']['sha256']
        baseline=[str(Path('output/render-smoke/acceptance')/f'case-5_{i:02}.png') for i in range(1,6)]
        assert all(Path(p).is_file() for p in baseline), 'Run tests/render_smoke.py --case 5 --output output/render-smoke/acceptance first'
        unchanged=[]
        for i in [0,3,4]:
            with Image.open(baseline[i]) as a,Image.open(artifact['pngs'][i]) as b:
                assert a.tobytes()==b.tobytes();unchanged.append(i+1)
        for i in [1,2]:
            with Image.open(baseline[i]) as a,Image.open(artifact['pngs'][i]) as b:assert a.tobytes()!=b.tobytes()
        while engine.deliver_one():pass
        sends=telegram.calls
        assert not engine.deliver_one() and telegram.calls==sends
        store.review(rid,1);store.decide(rid,1,True);assert engine.run_one()
        assert store.row(rid)['status']=='publish_waiting' and ig.published==0
        assert claude.calls==2
        details=[]
        for p in artifact['pngs']+artifact['files']:
            with Image.open(p) as im:
                assert im.size==(1080,1350)
                assert Path(p).stat().st_size<8_000_000
                details.append({'path':p,'size':list(im.size),'bytes':Path(p).stat().st_size,'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()})
        report={'result':'PASS','fixture_only':True,'real_photographs_verified':False,
            'external_calls':0,'claude_mock_calls':claude.calls,'telegram_mock_deliveries':sends,
            'public_url_check':'mocked HTTPS bytes/type/dimensions/hash only; no deployment',
            'unchanged_pages':unchanged,'changed_pages':[2,3],'status':store.row(rid)['status'],'files':details}
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(root/'report.json',flush=True)

if __name__=='__main__':main()
