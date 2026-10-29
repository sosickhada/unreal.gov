"""Image acquisition with manual relevance/face/license review as the safe fallback."""
import hashlib
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
import requests
from PIL import Image, ImageStat, ImageFilter
from .content import safe_https
from .adapters import ExternalError


def inspect_image(content):
    if len(content)>20_000_000: raise ValueError('Image too large')
    with Image.open(BytesIO(content)) as im:
        if im.format not in ('JPEG','PNG','WEBP'): raise ValueError('Unsupported raster image')
        w,h=im.size
        if w*h>40_000_000: raise ValueError('Image pixel budget exceeded')
        im.load(); im=im.convert('RGB')
        cw=min(w,h*4//5); ch=min(h,w*5//4)
        if cw<1080 or ch<1350: raise ValueError('Insufficient native resolution after 4:5 crop; no upscaling')
        sample=im.copy();sample.thumbnail((256,256))
        sharpness=ImageStat.Stat(sample.convert('L').filter(ImageFilter.FIND_EDGES)).var[0]
        if sharpness<35: raise ValueError('Insufficient detail; human photographic-quality review still required')
        return {'width':w,'height':h,'crop_width':cw,'crop_height':ch,'sharpness':sharpness,'sha256':hashlib.sha256(content).hexdigest()}


def manual_image(path,source_url,license_url,license_name,reviewer):
    path=Path(path).resolve()
    if not safe_https(source_url) or not safe_https(license_url) or not license_name.strip() or not reviewer.strip():
        raise ValueError('Source URL, license evidence and named reviewer required')
    metadata=inspect_image(path.read_bytes())
    return dict(metadata,path=str(path),source_url=source_url,license_url=license_url,license=license_name,reviewer=reviewer,relevance_reviewed=True,faces_reviewed=True,photograph_reviewed=True,review_required=False)


SLOTS = ('content', 'resolution_extra')


def terms(value):
    return set(re.findall(r'[a-z0-9가-힣]{2,}', value.lower()))


def checked_photo(photo):
    if photo.get('review_required') is not False or not all(photo.get(k) for k in
            ('reviewer','relevance_reviewed','faces_reviewed','photograph_reviewed')):
        raise ValueError('Photographic quality, no clear faces and relevance review required')
    if inspect_image(Path(photo['path']).read_bytes())['sha256'] != photo['sha256']:
        raise ValueError('Reviewed photograph bytes changed')
    return photo


def select_photos(rows, queries, existing=None):
    """Only reuse human-reviewed photos whose tags match the requested subject.

    Tag matching is a routing aid, not automatic semantic/face recognition.
    A missing/stale/duplicate input must never fall back to Figma stock imagery.
    """
    import json
    chosen=dict(existing or {}); used=set()
    for slot, photo in chosen.items():
        if slot not in SLOTS: raise ValueError('Unknown photographic slot')
        checked_photo(photo)
        if photo['sha256'] in used: raise ValueError('Two distinct photographs required')
        used.add(photo['sha256'])
    for slot in SLOTS:
        if slot in chosen: continue
        wanted=terms(queries.get(slot,''))
        ranked=sorted(rows,key=lambda r:(-len(wanted & terms(r['tags'])),r['sha256']))
        for row in ranked:
            if not wanted or not wanted <= terms(row['tags']) or row['sha256'] in used: continue
            photo=json.loads(row['payload'])
            try: checked_photo(photo)
            except (ValueError,OSError): continue
            chosen[slot]=photo;used.add(photo['sha256']);break
    return chosen


def pixabay_search(config,query,http=requests):
    config.require_external()
    if not config.env.get('PIXABAY_API_KEY'): raise ExternalError('Pixabay unavailable; supply manually reviewed licensed photograph')
    if not query.strip() or len(query)>100: raise ValueError('Concrete subject/action query required')
    try:
        response=http.get('https://pixabay.com/api/',params={'key':config.env['PIXABAY_API_KEY'],'q':query,'image_type':'photo','orientation':'vertical','min_width':1080,'min_height':1350,'per_page':20,'safesearch':'true'},timeout=25)
        response.raise_for_status();result=[]
        for hit in response.json().get('hits',[]):
            tags=str(hit.get('tags','')).lower()
            if any(term in tags for term in ('portrait','selfie','headshot','face','smiling','makeup','ai generated','ai-generated','artificial intelligence','illustration','rendering')): continue
            url=hit.get('fullHDURL') or hit.get('imageURL') or hit.get('largeImageURL','');host=urlparse(url).hostname or ''
            if not safe_https(url) or not (host=='pixabay.com' or host.endswith('.pixabay.com')): continue
            # Use exactly the returned URL. Metadata screening does not detect faces.
            result.append({'id':hit['id'],'download_url':url,'source_url':hit['pageURL'],'tags':tags,'query':query,'license_url':'https://pixabay.com/service/license-summary/','license':'Pixabay Content License; additional rights require review','review_required':True})
        return result
    except Exception:
        raise ExternalError('Pixabay search failed; use manual licensed-source fallback') from None


def download_candidate(config,candidate,destination,http=requests):
    config.require_external()
    url=candidate['download_url'];host=urlparse(url).hostname or ''
    if not safe_https(url) or not (host=='pixabay.com' or host.endswith('.pixabay.com')): raise ValueError('Untrusted image host')
    try:
        response=http.get(url,timeout=25,allow_redirects=False);response.raise_for_status()
        metadata=inspect_image(response.content)
    except Exception:
        raise ExternalError('Image failed download/native quality checks; manual fallback required') from None
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(response.content)
    return dict(candidate,**metadata,path=str(destination),review_required=True)
