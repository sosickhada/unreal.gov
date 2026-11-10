"""Reject rehearsal copy and stock template fallbacks at the real publish boundary."""
import json
import re
from .content import validate_draft


def validate_official(draft, media):
    if draft.get('publication_kind') != 'official':
        raise ValueError('Only explicitly prepared official content may be published')
    # Backgrounds are selected by the editor, never accepted from model text.
    source=json.loads(json.dumps(draft))
    for slide in source.get('slides',[]):
        slide.pop('background_image',None)
    validate_draft(source,source.get('source_url'))
    copy=' '.join([draft.get('title',''),draft.get('caption','')]+[
        str(s.get(k,'')) for s in draft['slides'] for k in ('eyebrow','headline','body')])
    if re.search(r'테스트|임시\s*(제목|캡션|이미지)|샘플|미리보기용|placeholder|lorem ipsum|dummy|test[-_ ]?(post|caption|content|image)',copy,re.I):
        raise ValueError('Rehearsal/placeholder copy is not publishable')
    if '\\n' in copy or not re.search(r'#[가-힣A-Za-z]',draft['caption']):
        raise ValueError('Caption hashtags and real newlines required')
    if not draft['slides'][0].get('background_image'):
        raise ValueError('Official cover requires a selected topic image')
    if not (len(media.get('files',[]))==len(media.get('urls',[]))==len(media.get('sha256',[]))==5):
        raise ValueError('Official carousel requires five completed images')
    photos=media.get('image_provenance',{}).get('photos',{})
    if set(photos)!={'content','resolution_extra'}:
        raise ValueError('Topic image provenance required for both slots')
    if any(p.get('review_required') is not False or not p.get('source_url') or not p.get('license_url') for p in photos.values()):
        raise ValueError('Unreviewed or temporary image input')
    return {'official':True,'images':5,'placeholder_copy':False}
