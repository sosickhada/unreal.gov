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
        rows=c.execute("SELECT rowid AS candidate_key,result,step FROM checkpoints WHERE job_id IN (SELECT id FROM jobs WHERE kind='render' AND json_extract(payload,'$.id')=? AND json_extract(payload,'$.revision')=?) AND state='succeeded' AND step LIKE '%_download'",(rid,revision)).fetchall()
        count=0
        for row in rows:
            photo=json.loads(row['result'])
            try:
                license_evidence(photo)
                from .images import inspect_image
                metadata=inspect_image(Path(photo['path']).read_bytes())
                if metadata['sha256']!=photo['sha256']:continue
            except (ValueError,OSError,KeyError):continue
            key=row['candidate_key'];delivery=f'photo-human:{rid}:{revision}:{key}'
            store.notify(c,delivery,{'text':f'사진 후보 {key}: 사람 검토 전','files':[photo['path']],'sha256':[photo['sha256']]})
            store.notify(c,delivery+':choice',{'after_delivery':delivery,'text':f"후보 {key}\n{photo['source_url']}\n{photo['license_url']}\n사진을 확대해 실사 여부·주제 적합성·얼굴/초상권·로고·워터마크·라이선스와 추가 권리를 확인하세요. 적합한 경우에만 슬롯을 선택하세요. 자동 검사에서 거절된 후보도 포함됩니다.", 'reply_markup':{'inline_keyboard':[[{'text':'본문 사진 검토 완료 · 선택','callback_data':f'photopick:{rid}:{revision}:{key}:content'}],[{'text':'결의 사진 검토 완료 · 선택','callback_data':f'photopick:{rid}:{revision}:{key}:resolution_extra'}]]}})
            count+=1
        return count


def approve(store,rid,revision,key,slot,reviewer):
    if slot not in SLOTS:raise ValueError('Unknown slot')
    with store.tx() as c:
        record=c.execute('SELECT status,revision FROM selections WHERE id=?',(rid,)).fetchone()
        if not record or record['revision']!=revision or record['status']!='draft_ready':raise ValueError('Stale draft')
        job=c.execute("SELECT * FROM jobs WHERE kind='render' AND json_extract(payload,'$.id')=? AND json_extract(payload,'$.revision')=?",(rid,revision)).fetchone()
        if not job or job['state']!='waiting':raise ValueError('Render must be waiting')
        row=c.execute("SELECT result FROM checkpoints WHERE rowid=? AND job_id=? AND state='succeeded' AND step LIKE '%_download'",(key,job['id'])).fetchone()
        if not row:raise ValueError('Unknown candidate')
        candidate=json.loads(row['result']);license_evidence(candidate)
        photo=manual_image(candidate['path'],candidate['source_url'],candidate['license_url'],candidate['license'],reviewer)
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
