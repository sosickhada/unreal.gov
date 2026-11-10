"""A single explicitly approved, budgeted text-only pilot. Default: prepare only."""
import argparse
from collections import Counter
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3

from .config import Config
from . import creative as c2
from .store import Store,now,kst_day
from .engine import Engine
from .adapters import Claude,Telegram,ExternalError

MODEL='claude-haiku-5-5'
STAGES={'conflict':(1,4000),'verdict':(1,4000),'draft':(3,4000),'editor':(3,2400)}
MAX_CALLS=8
MAX_INPUT=10000
COUNT_LIMIT=9500  # Counting is an estimate; keep a 500-token admission margin.
INPUT_RATE=Decimal('.10');OUTPUT_RATE=Decimal('.50')
APPROVAL_USD=Decimal('.03')
PROMPT_FILES=tuple(sorted(c2.PROMPTS.glob('*.txt')))


def write_private(path,data,exclusive=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    flags=os.O_WRONLY|os.O_CREAT|(os.O_EXCL if exclusive else os.O_TRUNC)
    fd=os.open(path,flags,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)


def prompt_hash():return c2.fingerprint({p.name:p.read_text() for p in PROMPT_FILES})


def upper_cost(stage):return (MAX_INPUT*INPUT_RATE+STAGES[stage][1]*OUTPUT_RATE)/1_000_000


def prepare(config,directory):
    root=Path(directory).resolve()
    if (root/'plan.json').exists():raise ValueError('Prepared trial already exists; inspect it instead of overwriting')
    root.mkdir(parents=True,exist_ok=True,mode=0o700);root.chmod(0o700)
    with sqlite3.connect('file:'+str(config.db)+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM selections WHERE id=7 AND status=\'published\'').fetchone()
        if not row:raise ValueError('Expected published baseline missing; select a new controlled baseline explicitly')
        baselines={str(r['revision']):json.loads(r['payload']) for r in db.execute('SELECT revision,payload FROM draft_versions WHERE selection_id=7')}
        published=json.loads(row['draft_json'])
    expected=('2,300','3,000','4,800','두 통')
    copy=' '.join(s.get('body','') for s in published['slides'])
    if not all(value in copy for value in expected):raise ValueError('Baseline changed; do not invent trial facts')
    candidate={'test_only':True,'preferred_format':'hearing','title':'무료 배송으로 늘어난 결제 금액','domain':'shopping',
        'objective':'무료 배송 기준까지 2,300원이 모자랐다. 신청인은 배송비 3,000원을 아끼려 4,800원짜리 세제를 한 통 더 담았다. 집에는 뜯지 않은 세제가 두 통 있었다.',
        'a_action':'배송비를 피하려고 세제를 한 통 더 담았다','b_action':'주문 화면은 무료 배송까지 2,300원이 모자란다고 표시했다',
        'a_claim':'배송비 대신 쓸 물건이 남는 편이 낫다','b_claim':'무료라는 표시는 배송비에 적용되며 총지출이 줄어든다는 약속은 아니다',
        'issue':'배송비를 아끼려고 더 쓴 지출을 절약으로 기록할 수 있는가','comic_anchor':'세제를 한 통 더 담았다',
        'conflict_key':'shipping_threshold:spend-vs-delivery-saving','hook':'배송비를 아꼈는데 결제 금액은 늘었다',
        'empathy':'무료 배송 조건을 맞추느라 필요 없는 물건을 담아 본 경험','share_reason':'배송비 대신 산 물건이 남아 있는 사람과 의견을 나눈다'}
    c2.validate_candidate(candidate)
    isolated_db=root/'pilot.sqlite3'
    if isolated_db==config.db.resolve():raise ValueError('Production DB cannot be a trial DB')
    store=Store(isolated_db);store.migrate();os.chmod(isolated_db,0o600)
    payload={'creative_version':2,'creative_brief':candidate,'title':candidate['title'],'source_url':None}
    with store.tx() as c:
        batch=c.execute("INSERT INTO batches(day,generation,status,created_at) VALUES(?,0,'ready',?)",(kst_day(),now())).lastrowid
        cid=c.execute('INSERT INTO candidates(batch_id,position,title,payload,created_at) VALUES(?,1,?,?,?)',(batch,candidate['title'],c2.canonical(payload),now())).lastrowid
    selection_id=store.select(cid)
    snapshot={'baseline_selection_id':7,'baseline_revision':row['revision'],'baseline_media_id':row['published_id'],'published_editorial_baseline':published,'raw_claude_baseline':baselines.get('1'),'candidate':candidate,
        'selection_reason':'단일 생활 장면에서 비용의 역전이 선명하다. 독자 반응 통계가 아닌 편집 판단이다.','provenance':'Existing fictional editorial material, not a verified real-world incident; B claim is a trial interpretation of the displayed condition.'}
    # Author/editor never receive either baseline manuscript or handwritten improved fixtures.
    write_private(root/'baseline.json',snapshot)
    ceiling=sum(upper_cost(stage)*count for stage,(count,_) in STAGES.items())
    plan={'status':'awaiting_user_approval','created_at':now(),'expires_at':(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat(),
        'model':MODEL,'prompt_version':c2.VERSION,'prompt_sha256':prompt_hash(),'baseline_sha256':c2.fingerprint(snapshot),'selection_id':selection_id,'database':str(isolated_db),
        'generation_calls_min':4,'generation_calls_max':MAX_CALLS,'max_input_per_call':MAX_INPUT,'count_tokens_admission_limit':COUNT_LIMIT,
        'max_output_tokens':27200,'max_total_input_tokens':80000,'max_total_tokens':107200,
        'input_usd_per_million':str(INPUT_RATE),'output_usd_per_million':str(OUTPUT_RATE),'model_usage_upper_usd':str(ceiling),'approval_cap_usd':str(APPROVAL_USD),
        'pricing_verified_on':datetime.now(timezone.utc).date().isoformat(),'pricing_source':'https://platform.claude.com/docs/en/models/haiku-5-5/overview',
        'retries':0,'rewrites_max':2,'tools':False,'prompt_cache':False,'service_tier':'standard_only','instagram_publish_enabled':False,'telegram_callbacks':False,'image_generation':False,
        'stages':{key:{'max_calls':v[0],'max_output_tokens':v[1],'reserved_usd_per_call':str(upper_cost(key))} for key,v in STAGES.items()}}
    write_private(root/'plan.json',plan,exclusive=True)
    return plan


class BudgetedClaude(Claude):
    def __init__(self,config,directory,approved=False,client_factory=None):
        super().__init__(config);self.root=Path(directory);self.approved=approved;self.client_factory=client_factory
        self.calls=Counter();self.reserved=Decimal(0);self.ledger=[]
    def validate(self):
        if not self.approved:raise PermissionError('Explicit paid trial approval required')
        super().validate()
    def generate_role(self,stage,system,prompt,maximum,model=None):
        self.validate()
        if stage not in STAGES or model!=MODEL or maximum!=STAGES[stage][1]:raise ValueError('Trial role/model/output cap mismatch')
        if sum(self.calls.values())>=MAX_CALLS or self.calls[stage]>=STAGES[stage][0]:raise ValueError('Trial call limit reached')
        reserve=upper_cost(stage)
        if self.reserved+reserve>APPROVAL_USD:raise ValueError('Trial dollar budget exhausted')
        from anthropic import Anthropic
        factory=self.client_factory or Anthropic
        messages=[{'role':'user','content':prompt}]
        with factory(api_key=self.config.env['ANTHROPIC_API_KEY'],base_url='https://api.anthropic.com',timeout=60,max_retries=0) as client:
            try:count=client.messages.count_tokens(model=MODEL,system=system,messages=messages).input_tokens
            except Exception:raise ExternalError('Free token preflight failed; generation not attempted') from None
            if type(count) is not int or not 0<count<=COUNT_LIMIT:raise ValueError('Trial input-token ceiling exceeded')
            self.calls[stage]+=1;self.reserved+=reserve
            entry={'stage':stage,'model':MODEL,'input_count_estimate':count,'reserved_input_tokens':MAX_INPUT,'max_output_tokens':maximum,'reserved_usd':str(reserve),'state':'sending'}
            self.ledger.append(entry);write_private(self.root/'budget.json',{'calls':self.ledger,'reserved_usd':str(self.reserved),'approval_usd':str(APPROVAL_USD)})
            try:
                response=client.messages.create(model=MODEL,max_tokens=maximum,system=system,messages=messages,service_tier='standard_only')
            except Exception:
                entry['state']='uncertain';write_private(self.root/'budget.json',{'calls':self.ledger,'reserved_usd':str(self.reserved)})
                raise ExternalError('Trial request outcome uncertain; no retry') from None
        entry.update(state='received',input_tokens=response.usage.input_tokens,output_tokens=response.usage.output_tokens,stop_reason=response.stop_reason)
        observed=(Decimal(response.usage.input_tokens)*INPUT_RATE+Decimal(response.usage.output_tokens)*OUTPUT_RATE)/1_000_000
        entry['observed_estimate_usd']=str(observed)
        write_private(self.root/'budget.json',{'calls':self.ledger,'reserved_usd':str(self.reserved),'approval_usd':str(APPROVAL_USD)})
        if response.usage.input_tokens>MAX_INPUT or response.usage.output_tokens>maximum or observed>reserve:raise ExternalError('Trial observed usage exceeded reservation; stopped')
        if response.stop_reason!='end_turn':raise ExternalError('Trial response incomplete; stopped, no paid retry')
        return {'raw':'\n'.join(b.text for b in response.content if b.type=='text'),'input_tokens':response.usage.input_tokens,'output_tokens':response.usage.output_tokens,'model_id':MODEL,'resolved_model':getattr(response,'model',MODEL)}


class NoPublication:
    def enabled(self):return False
    def __getattr__(self,name):raise PermissionError('This experiment has no image or Instagram capability')


def telegram_payloads(snapshot,draft,review,status):
    def manuscript(d):
        from figma_renderer import expand_slides
        pages=expand_slides(d)
        return '\n\n'.join(f'{i+1}장 · '+('고정 브랜드 엔딩 — 별도 후폭풍 없음' if kind=='ending' else slide.get('headline','')+'\n'+slide.get('body','')) for i,(kind,slide) in enumerate(pages))
    prefix='[실전 품질 검증 · 게시 금지 · 운영 DB와 분리]\n'
    result=[{'text':prefix+'기존 자동 원고 7번 v1\n'+manuscript(snapshot['raw_claude_baseline'])},
            {'text':prefix+'기존 실제 게시 편집본 7번 v2 — 수정하지 않음\n'+manuscript(snapshot['published_editorial_baseline'])}]
    if draft:result.append({'text':prefix+'새 엔진 실제 생성 결과 · '+status+'\n'+manuscript(draft)})
    if review:result.append({'text':prefix+c2.editor_report_text(review)})
    result.append({'text':prefix+'동일 소재 비교: 공감·양측 주장·판정 의외성·기관 논리·5장 후폭풍·한국어를 각각 평가하고, 더 낫거나 못한 문장을 인용해 주세요. 모델 점수만으로 개선 성공을 판정하지 않습니다. 게시/승인 버튼은 제공하지 않습니다.'})
    if any(len(p['text'])>3900 for p in result):raise ValueError('Comparison text too large; inspect locally before Telegram delivery')
    return result


def execute(config,directory,approved=False):
    if not approved:raise PermissionError('Stop before generation: user approval is required')
    root=Path(directory).resolve();plan=json.loads((root/'plan.json').read_text());snapshot=json.loads((root/'baseline.json').read_text())
    if datetime.now(timezone.utc)>datetime.fromisoformat(plan['expires_at']):raise ValueError('Pricing/approval plan expired; prepare again')
    if plan['model']!=MODEL or plan['prompt_sha256']!=prompt_hash() or plan['baseline_sha256']!=c2.fingerprint(snapshot):raise ValueError('Prepared plan changed; reapproval required')
    db=(root/'pilot.sqlite3').resolve()
    if db==config.db.resolve() or str(db)!=plan['database']:raise ValueError('Isolated DB required')
    if Decimal(plan['approval_cap_usd'])!=APPROVAL_USD:raise ValueError('Approval budget changed')
    # A durable single-execution intent prevents accidental reruns and uncertain paid replay.
    write_private(root/'execution.json',{'state':'started','at':now(),'approved_cap_usd':str(APPROVAL_USD)},exclusive=True)
    env={'ENABLE_EXTERNAL_CALLS':'1','CONTENT_ENGINE_VERSION':'2','PAID_AI_CALLS_ENABLED':'1','CLAUDE_MODEL':MODEL,
         'ANTHROPIC_API_KEY':config.env['ANTHROPIC_API_KEY'],'INSTAGRAM_PUBLISH_ENABLED':'0','ENABLE_PUBLIC_MEDIA':'0',
         'MAX_CLAUDE_CALLS_PER_DAY':'8','TOKENS_RESERVED_PER_CALL':'30000','MAX_RESERVED_TOKENS_PER_DAY':'240000'}
    for stage in c2.MODELS:env[c2.MODELS[stage]]=MODEL
    for stage in STAGES:
        env['CLAUDE_'+stage.upper()+'_INPUT_PER_MTOK_USD']=str(INPUT_RATE)
        env['CLAUDE_'+stage.upper()+'_OUTPUT_PER_MTOK_USD']=str(OUTPUT_RATE)
    scoped=Config(db,env);store=Store(db)
    with store.tx() as c:
        jobs=c.execute("SELECT kind,state FROM jobs WHERE state='queued'").fetchall()
        if len(jobs)!=1 or jobs[0]['kind']!='draft':raise ValueError('Exactly one isolated draft job required')
    ai=BudgetedClaude(scoped,root,approved=True)
    engine=Engine(scoped,claude=ai,media=NoPublication(),telegram=NoPublication(),instagram=NoPublication())
    engine.run_one()  # Do not run worker loop, render, publish, or sandbox callbacks.
    row=store.row(plan['selection_id'])
    with store.tx() as c:
        if c.execute("SELECT count(*) FROM jobs WHERE kind IN ('render','publish')").fetchone()[0]:raise RuntimeError('Trial isolation violated')
        draft_row=c.execute("SELECT payload FROM creative_artifacts WHERE selection_id=? AND stage='draft' ORDER BY iteration DESC LIMIT 1",(plan['selection_id'],)).fetchone()
        review_row=c.execute("SELECT payload FROM creative_artifacts WHERE selection_id=? AND stage='editor' ORDER BY iteration DESC LIMIT 1",(plan['selection_id'],)).fetchone()
    draft=json.loads(draft_row[0]) if draft_row else None;review=json.loads(review_row[0]) if review_row else None
    payloads=telegram_payloads(snapshot,draft,review,row['status'])
    if not draft:payloads.insert(0,{'text':'[실전 품질 검증 중단 · 게시 금지] 유효한 원고를 얻지 못했습니다. 자동 재호출하지 않았습니다. 저장된 단계와 예산 원장을 확인하세요.'})
    delivery=Telegram(config)
    for index,payload in enumerate(payloads):
        marker=root/f'telegram-{index}.json';write_private(marker,{'state':'sending'},exclusive=True)
        ids=delivery.send(payload);write_private(marker,{'state':'sent','message_ids':ids})
    write_private(root/'execution.json',{'state':'finished','at':now(),'status':row['status'],'paid_calls':sum(ai.calls.values()),'reserved_usd':str(ai.reserved),'instagram_publications':0})
    return {'status':row['status'],'paid_calls':sum(ai.calls.values()),'reserved_usd':str(ai.reserved),'instagram_publications':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',default='output/quality-pilot/haiku-first-20261110')
    parser.add_argument('--execute-approved',action='store_true')
    args=parser.parse_args();config=Config.load()
    result=execute(config,args.directory,approved=True) if args.execute_approved else prepare(config,args.directory)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
