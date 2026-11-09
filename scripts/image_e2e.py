"""Isolated image-to-card acceptance. Only --send-telegram performs external writes.

Puter is ALWAYS an in-memory SDK double here. No real image generation/payment.
"""
import argparse
import asyncio
import base64
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw
from bureau.config import Config
from bureau.store import Store,now
from bureau.engine import Engine
from bureau.adapters import Media,Telegram
from bureau.puter_images import PuterImages
from bureau.image_uploads import begin,accept
from bureau.photo_review import offer
from bureau.telegram_app import build_app


def fixture(alternate=False):
    # Original, self-authored synthetic test artwork. NOT a real photograph.
    im=Image.new('RGB',(1200,1600),'#56635a' if alternate else '#68747b')
    noise=Image.effect_noise(im.size,25).convert('RGB');im=Image.blend(im,noise,.12)
    d=ImageDraw.Draw(im)
    if alternate:
        d.rectangle((80,180,1100,1450),fill='#52615c');d.rectangle((140,240,1030,1390),fill='#aeb9b0')
        for y in (400,750,1100):d.rectangle((140,y,1030,y+18),fill='#57675b')
        d.rounded_rectangle((400,820,850,1050),30,fill='#d9d0b4',outline='#6a6250',width=12)
    else:
        d.rectangle((0,900,1200,1600),fill='#9b8161');d.rectangle((80,300,650,780),fill='#c0ccd1')
        d.rectangle((110,330,620,750),fill='#6a817f');d.rectangle((330,750,380,900),fill='#303a3b')
        d.rounded_rectangle((790,780,1040,1000),30,fill='#c9c2b0',outline='#555b53',width=15)
    # Fine test detail verifies native decoding/quality checks without a provider.
    for x in range(60,1150,35):d.line((x,1280,x+10,1410),fill='#535652',width=3)
    out=BytesIO();im.save(out,'PNG');return out.getvalue()


class MockSDK:
    calls=0
    def inspect(self):return {'allowanceInfo':{'remaining':100,'unit':'test-only'}}
    def generate(self,options):
        self.calls+=1
        return {'src':'data:image/png;base64,'+base64.b64encode(fixture()).decode(),'usage_after':{'remaining':99.5}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--send-telegram',action='store_true');parser.add_argument('--root',type=Path);args=parser.parse_args()
    root=(args.root or Path('output')/('image-e2e-'+now().replace(':','-'))).resolve()
    root.mkdir(parents=True,exist_ok=False)
    live=Config.load()
    env=dict(live.env,REQUIRE_TOPIC_IMAGE='1',RENDER_DIR=str(root/'cards'),ENABLE_PUBLIC_MEDIA='0',INSTAGRAM_PUBLISH_ENABLED='0',GEMINI_IMAGE_ENABLED='0',AUTO_PHOTO_ACQUIRE='0',AUTO_IMAGE_SEARCH='0',RENDER_TIMEOUT_SECONDS='240',RENDER_TRACE_DIR=str(root/'trace'))
    cfg=Config(root/'test.sqlite3',env);store=Store(cfg.db);store.migrate()
    draft={'title':'공용 냉장고의 용기 반환 사건','caption':'[이미지 시스템 E2E 테스트] 전부 가상 사건과 자체 제작 Mock 이미지입니다. 실제 Puter 생성·Instagram 게시 없음.', 'source_url':'https://example.com/fiction','claims':[], 'image_queries':{'content':'Korean shared office desk food container','resolution_extra':'office refrigerator leftover food container'},'image_brief':{'content':{'place':'한국 사무실','situation':'반납하지 않은 공용 용기'},'resolution_extra':{'place':'공용 냉장고','situation':'이름 없는 용기의 결말'}},'slides':[{'eyebrow':'사건 접수','headline':'용기의 주인을 찾습니다','body':''},{'eyebrow':'가상 사건 경위','headline':'돌아오지 않는 도시락','body':'공용 냉장고에 둔 용기가 돌아오지 않은 가상 사건입니다.','emphasis':[]},{'eyebrow':'처분/판정안','headline':'용기 반환 명령','body':'가상 심의 경과입니다.\n\n용기는 빈 상태로 반환합니다.','emphasis':[]},{}]}
    with store.tx() as c:
        c.execute("INSERT INTO selections(id,candidate_number,candidate_title,status,revision,draft_json) VALUES(900001,1,?,'draft_ready',1,?)",(draft['title'],json.dumps(draft,ensure_ascii=False)))
        jid=store.enqueue(c,'render:900001:1','render',{'id':900001,'revision':1});c.execute("UPDATE jobs SET state='waiting' WHERE id=?",(jid,))
    app=build_app(cfg);callback=next(h.callback for h in app.handlers[0] if h.__class__.__name__=='CallbackQueryHandler')
    step=1000
    def click(data):
        nonlocal step
        step+=1
        update=NS(effective_user=NS(id=int(env['TELEGRAM_ALLOWED_USER_IDS'].split(',')[0])),effective_chat=NS(id=int(env['TELEGRAM_CHAT_ID'])),update_id=step,callback_query=NS(data=data,answer=AsyncMock()))
        asyncio.run(callback(update,NS()))
    click('aigen:900001:1:content:0');click('pmodel:900001:1:content:natural:0')
    sdk=MockSDK();provider=PuterImages(cfg,sdk,lambda a,m:{'free_only_enforced':True,'paid_balance_isolated':True,'maximum':1,'free_remaining':100})
    engine=Engine(cfg,media=Media(cfg))
    with patch('bureau.puter_images.PuterImages',return_value=provider):assert engine.run_one()
    assert sdk.calls==1
    user=env['TELEGRAM_ALLOWED_USER_IDS'].split(',')[0]
    begin(store,user,900001,1);accept(store,user,10001,fixture(True),'OWN');offer(store,900001,1)
    with store.tx() as c:
        rows=c.execute("SELECT rowid,result FROM checkpoints WHERE state='succeeded'").fetchall()
    photos={json.loads(r['result']).get('provider'):r['rowid'] for r in rows if isinstance(json.loads(r['result']),dict)}
    click(f'photopick:900001:1:{photos["puter"]}:content')
    click(f'photopick:900001:1:{photos["user-upload"]}:resolution_extra')
    assert engine.run_one();assert store.row(900001)['status']=='preview_ready'
    with store.tx() as c:media=json.loads(c.execute('SELECT payload FROM assets WHERE selection_id=900001').fetchone()[0])
    assert len(media['files'])==5
    for path in media['pngs']+media['files']:
        with Image.open(path) as im:im.load();assert im.size==(1080,1350)
    with Image.open(media['pngs'][-1]) as end,Image.open('figma_assets/ending_fixed.png') as approved:
        assert end.convert('RGB').tobytes()==approved.convert('RGB').tobytes()
    click('approve:900001:1');assert store.row(900001)['status']=='approved'
    # Suppress simulated intermediate messages; only two explicitly labeled final
    # test deliveries may go to the real configured chat. Never run publish jobs.
    with store.tx() as c:
        c.execute("UPDATE outbox SET state='suppressed' WHERE state='queued'")
        if args.send_telegram:
            store.notify(c,'e2e-final-album',{'text':'[테스트 카드뉴스] 자체 제작 Mock 이미지 2장으로 완성한 5장입니다. Puter 실제 생성 없음 · Instagram 게시 없음 · 격리 DB에서 승인 흐름 검증.', 'files':media['files'],'sha256':media['sha256']})
            store.notify(c,'e2e-final-result',{'text':'[이미지 시스템 검증] 모델 선택 → Mock SDK 1회 → 이미지 저장 → 사용자 업로드 → 본문/결의 개별 선택 → 실제 1080×1350 5장 렌더링 → 최종 승인 상태 전환 완료. 이 테스트 메시지는 운영 게시 승인 버튼이 아닙니다.','after_delivery':'e2e-final-album'})
    if args.send_telegram:
        while engine.deliver_one():pass
        with store.tx() as c:
            deliveries=[dict(r) for r in c.execute("SELECT delivery_key,state FROM outbox WHERE delivery_key LIKE 'e2e-final-%'")]
        assert len(deliveries)==2 and all(r['state']=='sent' for r in deliveries), 'Inspect uncertain Telegram delivery; NEVER resend automatically'
    else:deliveries=[]
    result={'root':str(root),'db':str(cfg.db),'sdk':'Mock only','sdk_calls':sdk.calls,'real_puter_generations':0,'real_instagram_posts':0,'status':store.row(900001)['status'],'files':media['files'],'pngs':media['pngs'],'telegram':deliveries}
    (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
