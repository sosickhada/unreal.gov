"""Official Puter image provider; durable at-most-once reservations, no retries.

Live free-only authorization is intentionally unavailable until Puter exposes
verifiable free/paid separation and a binding maximum quote. Test doubles may
exercise the complete provider without authorizing a real SDK call.
"""
import base64
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo
from .store import Store, now, digest
from .gemini_images import prompt_for
from .image_assets import ingest

MODELS={
 'natural':{'model':'grok-imagine-image','provider':'xai','resolution':'2k','aspect_ratio':'4:5'},
 'detail':{'model':'@cf/black-forest-labs/flux-2-dev','provider':'cloudflare','width':1080,'height':1350,'steps':25},
}
BLOCK='Puter 무료 전용 잔액·유료 차감 방지·모델별 최대 비용이 검증되지 않아 생성 차단. 수동 업로드는 사용할 수 있습니다.'

class PuterBlocked(ValueError): pass


def migrate(c):
    c.execute('CREATE TABLE IF NOT EXISTS puter_image_attempts(id INTEGER PRIMARY KEY,mode TEXT,slot TEXT,state TEXT,reason TEXT,created_at TEXT)')
    columns={r[1] for r in c.execute('PRAGMA table_info(puter_image_attempts)')}
    for name in ('request_key','model','prompt','result','usage_before','usage_after','day','cost_quote'):
        if name not in columns:c.execute('ALTER TABLE puter_image_attempts ADD COLUMN '+name+' TEXT')
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS puter_request_once ON puter_image_attempts(request_key)')
    c.execute('CREATE TABLE IF NOT EXISTS puter_account_snapshots(id INTEGER PRIMARY KEY,allowance TEXT,model_count INTEGER,created_at TEXT)')


class SDKBridge:
    def __init__(self,config): self.config=config
    def call(self,action,payload=None):
        self.config.require_external()
        if not self.config.env.get('PUTER_AUTH_TOKEN'):raise PuterBlocked('PUTER_AUTH_TOKEN required')
        env=dict(os.environ,PUTER_AUTH_TOKEN=self.config.env['PUTER_AUTH_TOKEN'])
        if action=='generate':env['UNREAL_PUTER_RESERVED_CALL']='1'
        try:
            r=subprocess.run(['node',str(Path(__file__).resolve().parents[1]/'scripts/puter_bridge.mjs'),action],input=json.dumps(payload or {}),env=env,capture_output=True,text=True,timeout=180 if action=='generate' else 60,check=True)
            return json.loads(r.stdout)
        except Exception:raise PuterBlocked('Puter request failed or uncertain; no automatic retry; details withheld') from None
    def inspect(self): return self.call('inspect')
    def generate(self,options):return self.call('generate',options)


def inspect_account(config):
    data=SDKBridge(config).inspect()
    if data.get('authenticated') is not True or not isinstance(data.get('models'),list):raise PuterBlocked('Invalid Puter inspection response')
    with Store(config.db).tx() as c:
        migrate(c)
        c.execute('INSERT INTO puter_account_snapshots(allowance,model_count,created_at) VALUES(?,?,?)',(json.dumps(data.get('allowanceInfo',{})),len(data['models']),now()))
    return data


def free_only_quote(account,model):
    # Official allowanceInfo currently has no enforceable no-paid-spend cap,
    # free/paid separation or per-request maximum quote. No operator env bypass.
    raise PuterBlocked(BLOCK)


class PuterImages:
    def __init__(self,config,bridge=None,authorize=None):
        self.config=config;self.store=Store(config.db)
        self.bridge=bridge or SDKBridge(config);self.authorize=authorize or free_only_quote
    def generate(self,draft,slot,request_key,model_key='natural',mode='manual'):
        if model_key not in MODELS or mode not in ('manual','approved_test','automatic'):raise PuterBlocked('Invalid model or request mode')
        prompt=prompt_for(draft,slot)
        day=dt.datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
        with self.store.tx() as c:
            migrate(c)
            old=c.execute('SELECT * FROM puter_image_attempts WHERE request_key=?',(request_key,)).fetchone()
            if old:
                if old['state']=='succeeded':return json.loads(old['result'])
                raise PuterBlocked('기존 요청은 재호출하지 않습니다. 상태 확인 후 새 요청을 선택하세요.')
            aid=c.execute('INSERT INTO puter_image_attempts(mode,slot,state,created_at,request_key,model,prompt,day) VALUES(?,?,?,?,?,?,?,?)',(mode,slot,'checking',now(),request_key,MODELS[model_key]['model'],prompt,day)).lastrowid
        try:
            if mode=='automatic':raise PuterBlocked('무인 AI 생성 비활성: 사람의 명시적 요청이 필요합니다.')
            if self.authorize is free_only_quote:raise PuterBlocked(BLOCK)
            account=self.bridge.inspect()
            quote=self.authorize(account,MODELS[model_key])
            if not isinstance(quote,dict) or quote.get('free_only_enforced') is not True or quote.get('paid_balance_isolated') is not True:raise PuterBlocked(BLOCK)
            import math
            maximum=quote.get('maximum');remaining=quote.get('free_remaining')
            if type(maximum) not in (float,int) or type(remaining) not in (float,int) or not math.isfinite(maximum) or not math.isfinite(remaining) or not 0<maximum<=remaining:raise PuterBlocked(BLOCK)
            with self.store.tx() as c:
                if c.execute("SELECT 1 FROM puter_image_attempts WHERE state IN ('sent','uncertain','cost_overrun')").fetchone():raise PuterBlocked('이전 생성 결과/비용 불확실: 새 생성 차단')
                if c.execute("SELECT count(*) FROM puter_image_attempts WHERE day=? AND state IN ('sent','uncertain','succeeded','failed')",(day,)).fetchone()[0]>=2:raise PuterBlocked('오늘 생성 한도 2회 도달')
                c.execute("UPDATE puter_image_attempts SET state='sent',usage_before=?,cost_quote=? WHERE id=?",(json.dumps(account.get('allowanceInfo',{})),json.dumps(quote),aid))
        except Exception as exc:
            with self.store.tx() as c:c.execute("UPDATE puter_image_attempts SET state='blocked',reason=? WHERE id=?",('free_only_cost_unverified' if isinstance(exc,PuterBlocked) else 'inspection_failed',aid))
            if isinstance(exc,PuterBlocked):raise
            raise PuterBlocked('Puter account inspection failed; details withheld') from None
        try:
            response=self.bridge.generate(dict(MODELS[model_key],prompt=prompt))
            src=response['src']
            if not isinstance(src,str) or len(src)>28_000_000:raise ValueError('Invalid image response')
            if src.startswith('data:image/'):
                header,raw=src.split(',',1)
                if header not in ('data:image/png;base64','data:image/jpeg;base64','data:image/webp;base64'):raise ValueError('Unsupported image data')
                content=base64.b64decode(raw,validate=True)
            else:
                from .image_assets import fetch_generated
                content=fetch_generated(src)
            path=Path(self.config.db).parent/'data/puter-images'/f'{aid}-{digest(request_key)[:12]}.png'
            photo=dict(ingest(content,path),provider='puter',ai_generated=True,available=True,model=MODELS[model_key]['model'],slot=slot,prompt=prompt,request_key=request_key,review_required=True,license_verified=False,source_url='https://puter.com/',license_url='https://puter.com/terms',license='Puter and underlying model terms; human rights review required')
            after=response.get('usage_after')
            state='succeeded'
            try:
                delta=float(account['allowanceInfo']['remaining'])-float(after['remaining'])
                if not math.isfinite(delta) or delta<0 or delta>maximum:state='cost_overrun'
            except (TypeError,KeyError,ValueError):state='cost_overrun'
            with self.store.tx() as c:c.execute("UPDATE puter_image_attempts SET state=?,result=?,usage_after=? WHERE id=?",(state,json.dumps(photo),json.dumps(after),aid))
            if state!='succeeded':raise PuterBlocked('Usage verification failed')
            return photo
        except Exception:
            with self.store.tx() as c:c.execute("UPDATE puter_image_attempts SET state='uncertain',reason='generation_or_output_unverified' WHERE id=? AND state!='cost_overrun'",(aid,))
            raise PuterBlocked('Puter 생성 결과 또는 비용 불확실: 자동 재호출 금지. /imagebudget 확인') from None


def generate(config,draft,slot,*,approved_test=False):
    return PuterImages(config).generate(draft,slot,digest([draft,slot,'test' if approved_test else 'automatic']),mode='approved_test' if approved_test else 'automatic')


def schedule(store,config,rid,revision,slot,variant='0',model_key='natural'):
    if slot not in ('content','resolution_extra') or model_key not in MODELS:raise ValueError('Invalid slot/model')
    with store.tx() as c:
        r=c.execute('SELECT * FROM selections WHERE id=?',(rid,)).fetchone()
        if not r or r['revision']!=revision or r['status']!='draft_ready':raise ValueError('Stale draft')
        if variant!='0':
            old=c.execute("SELECT result FROM checkpoints WHERE rowid=? AND state='succeeded' AND job_id IN (SELECT id FROM jobs WHERE kind='puter_image' AND json_extract(payload,'$.id')=? AND json_extract(payload,'$.revision')=?)",(int(variant),rid,revision)).fetchone()
            if not old or json.loads(old[0]).get('slot')!=slot:raise ValueError('Unknown regeneration source')
        return store.enqueue(c,f'puter:{rid}:{revision}:{slot}:{model_key}:{variant}','puter_image',{'id':rid,'revision':revision,'slot':slot,'variant':variant,'model_key':model_key})


def budget_message(config,store=None):
    count=0
    with (store or Store(config.db)).tx() as c:
        migrate(c)
        count=c.execute("SELECT count(*) FROM puter_image_attempts WHERE day=? AND state IN ('sent','uncertain','succeeded','failed')",(dt.datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat(),)).fetchone()[0]
    return BLOCK+f'\n오늘 호출 예약 {count}/2 · 자동 재시도 0회 · 무인 생성 비활성'
