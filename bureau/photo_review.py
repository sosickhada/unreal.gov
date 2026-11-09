"""Human selection of downloaded candidates; never infer approval from delivery."""
import json
from pathlib import Path
from .images import checked_photo, manual_image, license_evidence, SLOTS
from .store import now


def offer(store, rid, revision):
    with store.tx() as c:
        record=c.execute('SELECT status,revision FROM selections WHERE id=?',(rid,)).fetchone()
        if not record or record['revision']!=revision or record['status']!='draft_ready':
            raise ValueError('Stale draft')
        rows=c.execute("SELECT rowid AS candidate_key,result,step FROM checkpoints WHERE job_id IN (SELECT id FROM jobs WHERE kind IN ('render','gemini_image','puter_image') AND json_extract(payload,'$.id')=? AND json_extract(payload,'$.revision')=?) AND state='succeeded' AND (step LIKE '%_download' OR step LIKE 'local_image_%' OR step LIKE 'gemini_image_%' OR step LIKE 'puter_image_%')",(rid,revision)).fetchall()
        count=0
        for row in rows:
            photo=json.loads(row['result'])
            try:
                review_license(photo)
                from .images import inspect_image
                metadata=inspect_image(Path(photo['path']).read_bytes())
                if metadata['sha256']!=photo['sha256']:continue
            except (ValueError,OSError,KeyError):continue
            kind='AI 이미지' if photo.get('ai_generated') else '사진'
            key=row['candidate_key'];delivery=f'photo-human:{rid}:{revision}:{key}'
            source={'puter':'Puter AI 생성','gemini':'Gemini AI 생성','user-upload':'사용자 업로드'}.get(photo.get('provider'),'로컬 AI 생성' if photo.get('ai_generated') else '검색 사진')
            store.notify(c,delivery,{'text':f'{source} 후보 {key}: 사람 검토 전 · 원본 {photo.get("original_width",photo.get("width"))}×{photo.get("original_height",photo.get("height"))} · 확대 {bool(photo.get("upscaled"))}','files':[photo['path']],'sha256':[photo['sha256']]})
            store.notify(c,delivery+':choice',{'after_delivery':delivery,'text':f"후보 {key}\n{photo['source_url']}\n{photo['license_url']}\nAI 생성 여부를 확인하고 사진을 확대해 실사 스타일·주제 적합성·얼굴/초상권·로고·워터마크·라이선스와 추가 권리를 확인하세요. 적합한 경우에만 슬롯을 선택하세요. 자동 검사에서 거절된 후보도 포함됩니다.", 'reply_markup':{'inline_keyboard':[[{'text':f'본문 {kind} 검토 완료 · 선택','callback_data':f'photopick:{rid}:{revision}:{key}:content'}],[{'text':f'결의 {kind} 검토 완료 · 선택','callback_data':f'photopick:{rid}:{revision}:{key}:resolution_extra'}]]}})
            if photo.get('provider') in ('gemini','puter'):
                slot=photo['slot']
                store.notify(c,delivery+':regenerate',{'after_delivery':delivery,'text':'이 AI 이미지를 다시 생성하면 새 호출·비용이 예약됩니다. 중복 클릭은 한 작업으로 처리합니다.', 'reply_markup':{'inline_keyboard':[[{'text':'AI 이미지 재생성','callback_data':f'airegen:{rid}:{revision}:{slot}:{key}'}]]}})
            count+=1
        store.notify(c,f'photo-actions:{rid}:{revision}',{'text':'Unsplash는 참고 링크로 탐색합니다. 직접 만든 사진은 업로드 후 두 슬롯에 각각 선택하세요. Puter는 무료 전용 비용 검증 후에만 호출합니다.', 'reply_markup':{'inline_keyboard':[
            [{'text':'본문 사진 참고','callback_data':f'imgsearch:{rid}:{revision}:0:content'},{'text':'결의 사진 참고','callback_data':f'imgsearch:{rid}:{revision}:0:resolution_extra'}],
            [{'text':'직접 이미지 업로드','callback_data':f'upstart:{rid}:{revision}'}],
            [{'text':'본문 AI 생성','callback_data':f'aigen:{rid}:{revision}:content:0'},{'text':'결의 AI 생성','callback_data':f'aigen:{rid}:{revision}:resolution_extra:0'}],
            [{'text':'남은 AI 생성 횟수','callback_data':'imagebudget:0'}]]}})
        return count


def approve(store,rid,revision,key,slot,reviewer):
    if slot not in SLOTS:raise ValueError('Unknown slot')
    with store.tx() as c:
        record=c.execute('SELECT status,revision FROM selections WHERE id=?',(rid,)).fetchone()
        if not record or record['revision']!=revision or record['status']!='draft_ready':raise ValueError('Stale draft')
        job=c.execute("SELECT * FROM jobs WHERE kind='render' AND json_extract(payload,'$.id')=? AND json_extract(payload,'$.revision')=?",(rid,revision)).fetchone()
        if not job or job['state']!='waiting':raise ValueError('Render must be waiting')
        row=c.execute("SELECT result FROM checkpoints WHERE rowid=? AND job_id IN (SELECT id FROM jobs WHERE kind IN ('render','gemini_image','puter_image') AND json_extract(payload,'$.id')=? AND json_extract(payload,'$.revision')=?) AND state='succeeded' AND (step LIKE '%_download' OR step LIKE 'local_image_%' OR step LIKE 'gemini_image_%' OR step LIKE 'puter_image_%')",(key,rid,revision)).fetchone()
        if not row:raise ValueError('Unknown candidate')
        candidate=json.loads(row['result']);review_license(candidate)
        photo=manual_image(candidate['path'],candidate['source_url'],candidate['license_url'],candidate['license'],reviewer)
        if not candidate.get('ai_generated'):
            from urllib.parse import urlparse
            host=urlparse(candidate.get('source_url','')).hostname
            photo['provider']='pixabay' if host in ('pixabay.com','www.pixabay.com') else ('commons' if host=='commons.wikimedia.org' else 'manual')
        for field in ('original_path','original_sha256','original_width','original_height','upscaled','transform','prompt'):
            if field in candidate:photo[field]=candidate[field]
        if candidate.get('uploaded'): photo.update(provider='user-upload',uploaded=True,rights_confirmed=True,uploader=candidate.get('uploader'))
        if candidate.get('ai_generated'): photo.update(ai_generated=True,provider=candidate.get('provider','local-diffusers'),model=candidate.get('model'),request_key=candidate.get('request_key'),model_path=candidate.get('model_path'),license_verified=False)
        if photo['sha256']!=candidate['sha256']:raise ValueError('Candidate changed')
        old=c.execute('SELECT payload FROM image_inputs WHERE selection_id=? AND revision=?',(rid,revision)).fetchone()
        photos=json.loads(old[0]).get('photos',{}) if old else {}
        if any(p['sha256']==photo['sha256'] for s,p in photos.items() if s!=slot):raise ValueError('Distinct photos required')
        photos[slot]=photo
        c.execute('INSERT OR REPLACE INTO image_inputs VALUES(?,?,?,?)',(rid,revision,json.dumps({'photos':photos}),now()))
        store.event(c,rid,'human_photo_approval',json.dumps({'revision':revision,'slot':slot,'candidate':key,'reviewer':reviewer,'sha256':photo['sha256']}))
        if set(photos)==set(SLOTS):
            for p in photos.values():checked_photo(p)
            # Both inputs now exist, so the acquisition branch and its old uncertain
            # vision checkpoint are not entered. Preserve every checkpoint.
            c.execute("UPDATE jobs SET state='queued',error_code=NULL WHERE id=?",(job['id'],))
            return True
        return False


def review_license(photo):
    if photo.get('uploaded'):
        if photo.get('rights_confirmed') is not True or not photo.get('uploader'):raise ValueError('User rights declaration required')
        return {'basis':'user ownership/permission declaration; final human review required','verified':False}
    if photo.get('ai_generated'):
        from .content import safe_https
        if not photo.get('available') or not safe_https(photo.get('source_url','')) or not safe_https(photo.get('license_url','')) or not photo.get('license'): raise ValueError('Missing local model license evidence')
        return {'basis':'Google API terms' if photo.get('provider')=='gemini' else 'operator supplied model license; human verification required','verified':False}
    return license_evidence(photo)
