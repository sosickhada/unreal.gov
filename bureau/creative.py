"""Creative engine v2 contracts. Local validation is not a claim that a story is funny."""
import hashlib
import json
import re
from pathlib import Path

VERSION='creative-2.0.0'
DOMAINS=('friends','relationships','work','university','food','public_space','shopping','home','digital','appointments')
VERDICT_TYPES={
 'A':'발언의 문자 그대로 집행','B':'책임 소재의 역전','C':'감정·시간·눈치 계량화',
 'D':'사소한 행동의 제도화','E':'갈등에 맞는 대칭 의무','F':'해결하며 새 문제 발생',
 'G':'예외 조항이 규칙을 무력화','H':'제3의 사물·상황에 책임 부여',
 'I':'지나치게 엄격한 증거 제출','J':'관행의 금지·의무화'}
FORMATS={
 'hearing':('cover','scene','claims','decision','aftermath'),
 'emergency':('incident','order','scope','exception','side_effect'),
 'reply':('petition','background','response','implementation','aftermath'),
 'reversal':('initial_decision','recorded_evidence','counterclaim','revised_decision','consequence'),
 'decree':('practice','definition','rule','loophole','side_effect'),
 'appeal':('original_ruling','objection','reconsideration','revised_ruling','consequence')}
FORMAT_LABELS={'hearing':'정식 사건 심의','emergency':'긴급 행정명령','reply':'국민 민원 회신','reversal':'판정 번복','decree':'시행령 발표','appeal':'행정심판 재심'}
FACT_KEYS=('objective','a_action','b_action','a_claim','b_claim','issue','comic_anchor')
CRITERIA=('action_link','responsibility_reversal','literal_meaning','specific_rule','usable_rule','side_effect','one_line')
SCORES=('hook','empathy','concrete_conflict','two_sides','verdict_logic','surprise','institutional_humor','payoff','natural_korean','novelty')
BANNED=('다각적이고 심도 있는','성숙한 시민 의식','현대 사회에서 상호 배려','이는 단순한 문제가 아닌','시사하는 바가 큽니다')
MODELS={'ideas':'CLAUDE_IDEA_MODEL','conflict':'CLAUDE_CONFLICT_MODEL','verdict':'CLAUDE_VERDICT_MODEL','draft':'CLAUDE_DRAFT_MODEL','editor':'CLAUDE_EDITOR_MODEL','image_brief':'CLAUDE_IMAGE_MODEL'}
PROMPTS=Path(__file__).parent/'prompts/v2'


def enabled(config):return config.env.get('CONTENT_ENGINE_VERSION','1')=='2'

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

def model_for(config,stage):
    model=config.env.get(MODELS[stage]) or config.env.get('CLAUDE_MODEL') or 'claude-haiku-5-5'
    if stage not in ('draft','editor') and 'haiku' not in model:
        raise ValueError('Upper-tier models are restricted to draft/editor stages')
    return model

def request(stage,data):
    return {'system':(PROMPTS/'brand.txt').read_text()+'\n'+(PROMPTS/(stage+'.txt')).read_text(),
            'user':canonical(data),'prompt_version':VERSION+':'+stage}

def migrate(c):
    c.execute('''CREATE TABLE IF NOT EXISTS creative_calls(job_id INTEGER NOT NULL,step TEXT NOT NULL,
        stage TEXT NOT NULL,model_id TEXT NOT NULL,prompt_version TEXT NOT NULL,request_sha256 TEXT NOT NULL,
        request_json TEXT NOT NULL,state TEXT NOT NULL,input_tokens INTEGER,output_tokens INTEGER,
        estimated_usd REAL,created_at TEXT NOT NULL,PRIMARY KEY(job_id,step))''')
    c.execute('''CREATE TABLE IF NOT EXISTS creative_artifacts(selection_id INTEGER NOT NULL,revision INTEGER NOT NULL,
        stage TEXT NOT NULL,iteration INTEGER NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,
        PRIMARY KEY(selection_id,revision,stage,iteration))''')
    c.execute('''CREATE TABLE IF NOT EXISTS creative_appeals(id INTEGER PRIMARY KEY,parent_selection_id INTEGER NOT NULL,parent_revision INTEGER NOT NULL,feedback TEXT NOT NULL,source_ref TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS creative_history(selection_id INTEGER NOT NULL,revision INTEGER NOT NULL,
        domain TEXT NOT NULL,conflict_key TEXT NOT NULL,format TEXT NOT NULL,verdict_type TEXT NOT NULL,
        anchor TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(selection_id,revision))''')


def text(value,minimum=1,maximum=600):
    if not isinstance(value,str) or not minimum<=len(value.strip())<=maximum:
        raise ValueError('Missing or oversized creative field')
    if any(ord(c)<32 and c not in '\n\t' for c in value):raise ValueError('Invalid control character')
    return value


def facts(candidate):return {k:candidate[k] for k in FACT_KEYS}


def validate_candidate(p):
    for k in FACT_KEYS:text(p.get(k),6,400)
    for k in ('title','hook','empathy','share_reason','conflict_key'):text(p.get(k),4,100)
    if p.get('domain') not in DOMAINS:raise ValueError('Unknown topic domain')
    if any(k in p for k in ('verdict','verdict_type','satire_angle','order','verdict_structure')):
        raise ValueError('Ideas must not decide the verdict')
    if p['a_claim']==p['b_claim'] or p['a_action']==p['b_action']:raise ValueError('Two distinct positions required')
    if p['comic_anchor'] not in p['a_action']+' '+p['b_action']+' '+p['objective']:
        raise ValueError('Comic anchor must quote the actual scene')
    copy=' '.join(p[k] for k in FACT_KEYS)
    forbidden=(('한 입','케이크'),('택시','반반'),('단체 사진','잘 나온'),('통화','40분'),('아무거나','거절'),('다 왔다','집'))
    if any(all(term in copy for term in pair) for pair in forbidden):raise ValueError('Illustrative examples cannot become candidates')
    if re.search(r'https?://|@[A-Za-z0-9_]+|01[016789][- ]?\d{3,4}[- ]?\d{4}|[가-힣]{2,4}\s?씨\b',copy):raise ValueError('Use fictional roles, not identifying details')
    if any(term in copy for term in ('실명 저격','성폭력','실제 판결','법적 효력')):raise ValueError('Unsafe/real-authority framing')
    return p


def choose_candidates(items,history,needed=3):
    from .editorial import similarity
    accepted=[];seen=[]
    for p in items:
        validate_candidate(p)
        body=p['objective']+' '+p['a_action']+' '+p['b_action']
        overlap=False
        for old in history+seen:
            old_body=old.get('objective',old.get('summary',''))+' '+old.get('a_action','')+' '+old.get('b_action','')
            if p['conflict_key']==old.get('conflict_key',old.get('situation_key')) or similarity(body,old_body)>=.68:overlap=True;break
        if not overlap:accepted.append(p);seen.append(p)
    counts={domain:sum(x.get('domain')==domain for x in history) for domain in DOMAINS}
    accepted.sort(key=lambda p:counts[p['domain']])
    chosen=[]
    for p in accepted:
        if p['domain'] not in {x['domain'] for x in chosen}:chosen.append(p)
        if len(chosen)==needed:return chosen
    raise ValueError('Not enough distinct grounded domains; do not recycle examples')


def validate_conflict(plan,candidate,trusted_feedback=()):
    if plan.get('facts')!=facts(candidate):raise ValueError('Conflict stage changed frozen facts')
    for k in ('a_reason','b_reason','tension','format_reason'):text(plan.get(k),6)
    if plan.get('format') not in FORMATS:raise ValueError('Unknown format')
    if candidate.get('preferred_format') and plan['format']!=candidate['preferred_format']:raise ValueError('Requested format must be preserved')
    if plan['format']=='appeal':
        refs={x['reference'] for x in trusted_feedback}
        if not candidate.get('appeal_reference') or plan.get('appeal_reference')!=candidate['appeal_reference'] or plan['appeal_reference'] not in refs:
            raise ValueError('Appeal requires matching actual supplied user feedback')
    return plan


def validate_verdicts(data,plan):
    options=data.get('options',[])
    if not 3<=len(options)<=5:raise ValueError('Three to five verdicts required')
    if len({v.get('type') for v in options})!=len(options) or len({v.get('id') for v in options})!=len(options):
        raise ValueError('Verdict directions and IDs must be distinct')
    for v in options:
        if v.get('type') not in VERDICT_TYPES or v.get('anchor')!=plan['facts']['comic_anchor']:raise ValueError('Verdict is not grounded')
        for key in ('id','order','logic','side_effect'):text(v.get(key),2,180)
        if len(set(v.get('criteria',[])))<2 or not set(v['criteria'])<=set(CRITERIA):raise ValueError('Two verdict criteria required')
        if any(type(v.get(k)) not in (int,float) or not 0<=v[k]<=5 for k in ('fit','surprise','humor')):raise ValueError('Invalid design scores')
        if any(x in v['order'] for x in ('사과를 권고','주의를 권고','서로 양보','양측 모두 책임')):
            raise ValueError('Generic conciliatory verdict')
    return options


def select_verdict(options,history,format_id):
    # Diversity only breaks a quality tie; it never promotes a weaker design.
    qualified=[v for v in options if v['fit']>=4 and v['surprise']>=3 and v['humor']>=3]
    if not qualified:raise ValueError('No sufficiently fitting verdict; editorial hold required')
    rank=lambda v:(v['fit'],v['surprise']+v['humor'])
    best=max(rank(v) for v in qualified)
    finalists=[v for v in qualified if rank(v)==best]
    fresh=[v for v in finalists if not any(h['format']==format_id and h['verdict_type']==v['type'] for h in history[:2])]
    if not fresh:raise ValueError('Best fitting verdict repeats recent pattern; redesign rather than choose a weaker type')
    return fresh[0]


def validate_draft(d,source_url=None):
    if d.get('schema_version')!=2 or d.get('format') not in FORMATS:raise ValueError('Invalid v2 manuscript')
    text(d.get('title'),1,40);text(d.get('caption'),1,500)
    if d.get('claims')!=[] or d.get('source_url') is not None:raise ValueError('Fiction cannot claim external evidence')
    if not all(x in d['caption'] for x in ('풍자','창작')) or not 3<=len(re.findall(r'#[가-힣A-Za-z0-9_]+',d['caption']))<=6:
        raise ValueError('Relevant caption, brief fiction notice and 3–6 hashtags required')
    slides=d.get('slides',[])
    if len(slides)!=5 or tuple(s.get('role') for s in slides)!=FORMATS[d['format']]:raise ValueError('Five format-specific story beats required')
    text(d.get('facts_hash'),64,64);text(d.get('verdict_id'),1,30)
    for i,s in enumerate(slides):
        if set(s)-{'role','eyebrow','headline','body','fact_refs','emphasis','background_image'}:raise ValueError('Unexpected slide field')
        text(s.get('eyebrow'),1,22);text(s.get('headline'),1,32)
        text(s.get('body',''),0 if i==0 else 1,150)
        if i==0 and s.get('body'):raise ValueError('Cover content must be visible in its headline')
        if not isinstance(s.get('fact_refs'),list) or not s['fact_refs'] or not set(s['fact_refs'])<=set(FACT_KEYS):raise ValueError('Scene references required')
        em=s.get('emphasis',[])
        if not isinstance(em,list) or len(em)>1 or any(not t or t not in s.get('body','') for t in em):raise ValueError('Invalid emphasis')
    copy=' '.join(s['headline']+' '+s.get('body','') for s in slides)
    if any(term in copy for term in BANNED) or any(term in slides[-1]['body'] for term in ('이 사건은 가상','본 사건은 허구','요약하면','배려합시다')):
        raise ValueError('Explanatory/moralizing or disclaimer ending')
    if '\\n' in copy:raise ValueError('Literal escaped newlines in manuscript')
    if d['slides'][-1]['body']==d['slides'][-2]['body']:raise ValueError('Aftermath cannot merely repeat the ruling')
    return d


def ground_draft(d,plan,options):
    if set(d)-{'schema_version','title','format','facts_hash','verdict_id','caption','claims','source_url','slides','test_only'}:
        raise ValueError('Writer cannot set publishing, review or image-preparation metadata')
    validate_draft(d)
    if d['facts_hash']!=fingerprint(plan['facts']) or d['format']!=plan['format']:
        raise ValueError('Writer changed the frozen conflict or format')
    if d['verdict_id'] not in {v['id'] for v in options}:raise ValueError('Writer invented an unreviewed verdict direction')
    if any('background_image' in s for s in d['slides']):raise ValueError('Writer cannot inject image paths')
    return d


def review_accepted(review,draft):
    copy='\n'.join(s['headline']+'\n'+s['body'] for s in draft['slides'])
    for k in ('boring_sentence','explanatory_sentence'):
        text(review.get(k),2)
        if review[k] not in copy:raise ValueError('Editor must cite the actual manuscript')
    for k in ('stronger_conflict','predictable_verdict_reason','ending_improvement'):text(review.get(k),6)
    dropout=review.get('dropout_scene',{})
    if type(dropout.get('slide')) is not int or not 1<=dropout['slide']<=5:raise ValueError('Editor must locate the dropout scene')
    text(dropout.get('reason'),6)
    scores=review.get('scores',{})
    if set(scores)!=set(SCORES) or any(type(x) not in (int,float) or not 0<=x<=5 for x in scores.values()):raise ValueError('Invalid editorial rubric')
    checks=('factual_consistency','no_identifying_people','verdict_linked')
    if type(review.get('approved')) is not bool or any(type(review.get(k)) is not bool for k in checks):raise ValueError('Editorial checks required')
    return review['approved'] and all(review[k] for k in checks) and min(scores.values())>=3 and sum(scores.values())>=38


def migrate_legacy(candidate):
    """Old ideas are input evidence, never silently invented conflict facts."""
    if candidate.get('creative_version')==2:return candidate
    raise ValueError('Legacy idea needs an editor-supplied grounded v2 brief')


def editorial_text(draft):
    keys=('schema_version','title','format','facts_hash','verdict_id','caption','claims','source_url')
    data={k:draft[k] for k in keys}
    data['slides']=[{k:v for k,v in s.items() if k!='background_image'} for s in draft['slides']]
    return data


def assert_editorial_evidence(store,rid,revision,draft):
    mark=draft.get('editorial_checkpoint',{})
    if not mark or type(mark.get('revision')) is not int or mark['revision']>revision:raise ValueError('Editorial checkpoint required')
    with store.tx() as c:
        reviewed=c.execute("SELECT payload FROM creative_artifacts WHERE selection_id=? AND revision=? AND stage='draft' AND iteration=?",(rid,mark['revision'],mark.get('iteration'))).fetchone()
        review=c.execute("SELECT payload FROM creative_artifacts WHERE selection_id=? AND revision=? AND stage='editor' AND iteration=?",(rid,mark['revision'],mark.get('iteration'))).fetchone()
    if not reviewed or not review:raise ValueError('Editorial evidence unavailable')
    source=json.loads(reviewed[0])
    if fingerprint(editorial_text(source))!=mark.get('draft_hash') or editorial_text(source)!=editorial_text(draft):raise ValueError('Text changed after editorial review')
    if not review_accepted(json.loads(review[0]),source):raise ValueError('Independent editorial review did not pass')


def editor_report_text(report):
    labels={'hook':'표지','empathy':'공감','concrete_conflict':'구체적 갈등','two_sides':'양측 주장','verdict_logic':'판정 논리','surprise':'의외성','institutional_humor':'기관 유머','payoff':'마지막 장 보상','natural_korean':'한국어','novelty':'차별성'}
    scores=report.get('scores',{})
    lines=['편집장 평가 · 실제 독자 반응을 보장하지 않습니다.']
    if scores:lines.append(' / '.join(labels[k]+' '+str(scores[k])+'/5' for k in SCORES if k in scores))
    for key,label in [('boring_sentence','가장 약한 문장'),('explanatory_sentence','가장 설명적인 문장'),('stronger_conflict','갈등 개선'),('predictable_verdict_reason','판정 검토'),('ending_improvement','결말 개선'),('validation_error','검증 미통과'),('reason','보류 사유')]:
        if report.get(key):lines.append(label+': '+str(report[key]))
    if report.get('dropout_scene'):lines.append('이탈 장면: '+str(report['dropout_scene'].get('slide'))+'장 · '+str(report['dropout_scene'].get('reason','')))
    return '\n'.join(lines)
