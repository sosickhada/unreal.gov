"""Local editorial screening. Scores assist an editor; they do not certify comedy."""
import datetime as dt
import json
import re
import random
from difflib import SequenceMatcher
from .store import now

FIELDS=('title','summary','conflict','cause','verdict_structure')
WEIGHTS={'empathy':25,'specificity':20,'parody':20,'humor':20,'novelty':15}

def structure(p):
    return {k:str(p.get(k) or p.get({'conflict':'situation_key','cause':'empathy','verdict_structure':'satire_angle'}.get(k,k),'')).strip() for k in FIELDS}

def grams(s):
    s=re.sub(r'[^가-힣a-z0-9]','',s.lower())
    return {s[i:i+3] for i in range(max(0,len(s)-2))}

def similarity(a,b):
    x,y=grams(a),grams(b)
    return max(len(x&y)/max(1,len(x|y)),SequenceMatcher(None,a,b).ratio())

def duplicate(p, old, age=0, published=False):
    a,b=structure(p),structure(old)
    lexical=similarity(a['title']+a['summary'],b['title']+b['summary'])
    semantic=sum(similarity(a[k],b[k]) for k in ('conflict','cause','verdict_structure'))/3
    concepts=[('퇴근','마감','업무 접수'),('정산','영수증','결제','채권'),('수리','고장','고친','고객센터'),('답장','응답','단톡'),('예약','자리','양보'),('배송비','무료 배송','추가 구매'),('교체','물통','정수기')]
    def semantic_tags(d):
        text=' '.join(d.values())
        return {i for i,group in enumerate(concepts) if any(t in text for t in group)}
    tags_a,tags_b=semantic_tags(a),semantic_tags(b)
    if tags_a and tags_a==tags_b: semantic=max(semantic,.65)
    same=bool(a['conflict'] and a['conflict']==b['conflict'])
    blocked=(same and age<=30) or lexical>=.70 or semantic>=(.62 if published else .78)
    if age<=90 and semantic>=.60 and not p.get('new_perspective'): blocked=True
    return {'blocked':blocked,'lexical':round(lexical,3),'semantic':round(semantic,3),'reason':'core conflict / event overlap' if blocked else 'distinct local structure; human review required'}

def assess(p):
    reasons={};scores={}
    for k,maximum in WEIGHTS.items():
        evidence=p.get({'empathy':'empathy','specificity':'summary','parody':'satire_angle','humor':'hook','novelty':'cause'}[k],p.get('empathy',''))
        scores[k]=round(maximum*(.8 if len(evidence)>=12 else .3));reasons[k]=evidence
    if any(x in p.get('satire_angle','') for x in ('함께 노력','서로 배려','시사하는','말장난')): scores['humor']=0
    evaluation=p.get('evaluation',{})
    model_scores=evaluation.get('scores',{}) if isinstance(evaluation,dict) else {}
    if all(type(model_scores.get(k)) in (int,float) and 0<=model_scores[k]<=v for k,v in WEIGHTS.items()) and evaluation.get('reasons') and evaluation.get('laugh_point'):
        for k in scores: scores[k]=min(scores[k],model_scores[k])
        reasons['model_review']=evaluation['reasons']
    return {'scores':scores,'score':sum(scores.values()),'reasons':reasons,'laugh_point':p.get('satire_angle'),'human_review_required':True}

def local_pool(day, generation=0, count=18):
    # Composed events, never the old rotating fallback bank. Model generation is preferred.
    places=['공유 주방','동호회 회식','공동 구매방','여행 숙소','스터디룸','아파트 택배실','팀 간식함','가족 모임','중고 거래','공용 냉장고','카풀','헬스장']
    events=[('비용 절약을 제안한 사람','정산 담당자','절약액보다 큰 정산 노동을 맡는다','benefit_labor','절약 이익은 공동 소유지만 계산 노동은 제안자 사유 재산이 된다'),('먼저 자리를 예약한 사람','늦게 합류한 친구','예약 덕에 온 친구에게 좋은 자리를 양보하라는 말을 듣는다','priority_sacrifice','준비한 공로가 양보 의무로 전환된다'),('공용 물건을 고친 사람','함께 쓰는 사람','이후 모든 고장 문의를 혼자 받는다','competence_tax','한 번의 무상 수리가 평생 고객센터 계약으로 해석된다'),('불참 의사를 먼저 밝힌 사람','모임 총무','인원 부족을 이유로 참석자보다 오래 설득 전화를 받는다','refusal_labor','참석하지 않기 위해 참석 시간만큼 설명한다'),('영수증을 보관한 사람','함께 결제한 친구','돈을 돌려받으려 증빙을 하다가 쪼잔하다는 평가를 받는다','proof_blame','기억하지 못한 채무보다 기억한 채권이 심사 대상이 된다'),('마지막 물건을 남긴 사람','다음 이용자','양보해 둔 한 개 때문에 빈 상자를 치울 책임까지 맡는다','courtesy_cleanup','마지막 몫을 포기했는데 마지막 이용자로 분류된다')]
    rng=random.Random(str(day)+':'+str(generation)); combos=[(a,b) for a in places for b in events];rng.shuffle(combos)
    pool=[]
    for place,(actor,other,event,key,cause) in combos[:count]:
        p={'title':f'{place} {actor} 책임 전환 사건','summary':f'{place}에서 {actor}이 {other} 때문에 {event}.','empathy':cause,'hook':f'{actor}에게 왜 추가 의무가 생깁니까?','satire_angle':f'{cause}. 수혜자가 해당 업무를 한 차례 직접 수행한 뒤 책임 귀속을 재심하도록 판정한다.','share_reason':'같은 역할을 떠맡은 사람과 책임 전환의 모순을 나눈다.','situation_key':place+':'+key,'conflict':key,'cause':cause,'verdict_structure':key+':수혜자 직접 수행','source_url':None,'origin':'everyday'}
        p['quality']=assess(p);pool.append(p)
    return pool

def screen(c, pool, subject, exclude=()):
    history=[]
    for r in c.execute('SELECT x.*,s.published_id FROM candidates x LEFT JOIN selections s ON s.candidate_id=x.id'):
        history.append((r['id'],json.loads(r['payload']), max(0,(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(r['created_at']).replace(tzinfo=dt.timezone.utc)).days),bool(r['published_id'])))
    for r in c.execute('SELECT id,candidate_title,draft_json,selected_at,published_id FROM selections WHERE candidate_id IS NULL'):
        try: draft=json.loads(r['draft_json'] or '{}')
        except ValueError: draft={}
        old={'title':r['candidate_title'],'summary':' '.join(x.get('body','') for x in draft.get('slides',[]))}
        history.append((-r['id'],old,0,bool(r['published_id'])))
    chosen=list(exclude);accepted=[]
    for p in sorted(pool,key=lambda x:assess(x)['score'],reverse=True):
        p['quality']=assess(p);checks=[]
        for cid,old,age,pub in history:
            if age<=90 or pub:
                result=duplicate(p,old,age,pub)
                if result['blocked']: checks.append(dict(result,candidate_id=cid))
        if any(duplicate(p,x)['blocked'] for x in chosen): checks.append({'blocked':True,'reason':'same batch conflict'})
        ok=p['quality']['score']>=70 and not checks
        c.execute('INSERT INTO idea_audits(subject,payload,accepted,checks,created_at) VALUES(?,?,?,?,?)',(str(subject),json.dumps(p,ensure_ascii=False),int(ok),json.dumps(checks,ensure_ascii=False),now()))
        if ok: accepted.append(p);chosen.append(p)
    return accepted
