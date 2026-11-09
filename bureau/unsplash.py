"""Official search only. Offline composites/rehosting await Unsplash approval."""
import json
import re
from urllib.parse import urlparse, urlencode
import requests
from .adapters import ExternalError
from .store import Store, now

POLICY_BLOCK = 'Unsplash hotlink policy: local card rendering, Telegram rehosting and Instagram reposting require clarification'


def search(config, query, http=requests):
    config.require_external()
    if not config.env.get('UNSPLASH_ACCESS_KEY'):
        raise ExternalError('Unsplash access key missing')
    if not query.strip() or len(query)>100:
        raise ValueError('Concrete query required (1..100 characters)')
    try:
        r=http.get('https://api.unsplash.com/search/photos',params={'query':query,'per_page':20,'orientation':'portrait','content_filter':'high'},headers={'Authorization':'Client-ID '+config.env['UNSPLASH_ACCESS_KEY'],'Accept-Version':'v1'},timeout=25,allow_redirects=False)
        r.raise_for_status()
        result=[]
        for p in r.json()['results']:
            w,h=p['width'],p['height']
            if min(w,h*4//5)<1080 or min(h,w*5//4)<1350: continue
            photo_id=str(p['id'])
            if not re.fullmatch(r'[A-Za-z0-9_-]+',photo_id): continue
            urls=p['urls'];url=urls.get('raw') or urls.get('full','')
            if urlparse(url).scheme!='https' or urlparse(url).hostname!='images.unsplash.com':continue
            user=p['user'];page=p['links']['html'];author=user['links']['html']
            if any(urlparse(x).scheme!='https' or urlparse(x).hostname!='unsplash.com' for x in (page,author)):continue
            tracking=urlencode({'utm_source':'unreal_bureau','utm_medium':'referral'})
            result.append({'id':photo_id,'provider':'Unsplash','original_width':w,'original_height':h,'download_url':url,'hotlink_url':url,'source_url':page+('&' if '?' in page else '?')+tracking,'photographer':user['name'],'photographer_url':author+('&' if '?' in author else '?')+tracking,'attribution':f"Photo by {user['name']} on Unsplash",'download_location':f'https://api.unsplash.com/photos/{photo_id}/download','tags':' '.join([p.get('description') or '',p.get('alt_description') or '']+[str(t.get('title','')) for t in p.get('tags',[]) if isinstance(t,dict)]), 'query':query,'review_required':True,'render_allowed':False,'policy_block':POLICY_BLOCK,'license_url':'https://unsplash.com/api-terms'})
    except Exception:
        raise ExternalError('Unsplash search failed; details withheld') from None
    store=Store(config.db)
    with store.tx() as c:
        c.execute('CREATE TABLE IF NOT EXISTS unsplash_searches(id INTEGER PRIMARY KEY,query TEXT,result TEXT,created_at TEXT)')
        c.execute('INSERT INTO unsplash_searches(query,result,created_at) VALUES(?,?,?)',(query,json.dumps(result),now()))
    return result


def track_download(config, photo, http=requests):
    """Must be called for a future approved selection/use, never mere search."""
    raise ExternalError(POLICY_BLOCK)

# Local, deterministic search translation; no billable LLM call.
GLOSSARY={
 '사무실':'Korean office','책상':'office desk','퇴근':'office evening','냉장고':'refrigerator kitchen','배달':'takeaway food containers','음식':'food kitchen','우산':'umbrella rain','비':'rain','버스':'city bus','지하철':'subway station','엘리베이터':'apartment elevator','아파트':'Korean apartment','편의점':'Korean convenience store','카페':'Korean cafe','회의':'office meeting room','수리':'household repair tools','주방':'home kitchen','공용':'shared workspace','문':'closed door','의자':'office chair','점심':'lunch food','아침':'morning','저녁':'evening','밤':'night','기다':'waiting','빈':'empty','사람':'people','직장':'office worker','짜증':'frustration','조용':'quiet','휴대폰':'smartphone','컵':'coffee cup','택배':'delivery parcel'}


def search_plan(draft,slot):
    if slot not in ('content','resolution_extra'):raise ValueError('Unknown slot')
    brief=draft.get('image_brief',{}).get(slot,{})
    if not isinstance(brief,dict):brief={}
    fields={'place':brief.get('place',''),'people':brief.get('persons',''),'action':brief.get('situation',''),'emotion':brief.get('emotion',''),'time':brief.get('time',''),'objects':brief.get('objects',''),'composition':brief.get('composition',''),'mood':brief.get('mood','')}
    source=' '.join([str(draft.get('image_queries',{}).get(slot,'')),str(draft.get('title',''))]+[str(x) for x in fields.values()])
    hints={'place':('사무실','주방','냉장고','카페','아파트','버스','지하철','편의점'),
           'people':('사람','직장','학생'), 'action':('기다','수리','배달','회의','퇴근'),
           'emotion':('짜증','억울','답답','불안'), 'time':('아침','저녁','밤','점심'),
           'objects':('우산','컵','책상','휴대폰','택배','용기','냉장고'),
           'composition':('클로즈업','전경','와이드','근접'), 'mood':('조용','쓸쓸','차분')}
    for field,keys in hints.items():
        if not fields[field]:fields[field]=' '.join(k for k in keys if k in source)
    english=re.sub(r'[^a-zA-Z0-9 -]',' ',str(draft.get('image_queries',{}).get(slot,'')))
    english=' '.join(english.split())
    mapped=list(dict.fromkeys(v for k,v in GLOSSARY.items() if k in source))
    base=english if len(english)>5 else ' '.join(mapped[:3])
    if not base:raise ValueError('구체적인 장소나 사물을 입력하세요. 예: 사무실 책상, 냉장고, 우산')
    noun=' '.join(base.split()[:5])
    queries=list(dict.fromkeys([base[:100],('Korea '+noun)[:100],(noun+' natural light')[:100],(noun+(' close up detail' if slot=='resolution_extra' else ' wide scene'))[:100],(' '.join(mapped[:2])+' everyday life')[:100]]))
    return {'slot':slot,'fields':fields,'queries':queries[:5],'method':'local bilingual glossary and approved image_queries; visual semantics require human review'}


def rank_candidates(photos,query,excluded=()):
    from .images import terms
    stop={'korea','korean','natural','light','everyday','life','wide','scene','close','detail','the','and','with'}
    wanted=terms(query)-stop;seen=set(excluded);ranked=[]
    for photo in photos:
        if photo['id'] in seen:continue
        seen.add(photo['id'])
        overlap=len(wanted & terms(photo.get('tags','')))
        relevance=overlap/max(len(wanted),1)
        w,h=photo['original_width'],photo['original_height']
        retained=min(w/h/.8,.8/(w/h))
        ranked.append(dict(photo,relevance_score=relevance,crop_retention=round(retained,3),score=round(relevance*80+retained*20,3),visual_quality_verified=False,semantic_review_required=True))
    return sorted(ranked,key=lambda p:(-p['score'],p['id']))
