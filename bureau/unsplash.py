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
            result.append({'id':photo_id,'provider':'Unsplash','original_width':w,'original_height':h,'download_url':url,'hotlink_url':url,'source_url':page+('&' if '?' in page else '?')+tracking,'photographer':user['name'],'photographer_url':author+('&' if '?' in author else '?')+tracking,'attribution':f"Photo by {user['name']} on Unsplash",'download_location':f'https://api.unsplash.com/photos/{photo_id}/download','tags':p.get('description') or p.get('alt_description') or '', 'query':query,'review_required':True,'render_allowed':False,'policy_block':POLICY_BLOCK,'license_url':'https://unsplash.com/api-terms'})
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
