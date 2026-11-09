"""Version-bound Telegram upload intents and immutable review candidates."""
import json
from pathlib import Path
from .image_assets import ingest
from .store import now


def migrate(c):
    c.execute('CREATE TABLE IF NOT EXISTS image_upload_intents(user_key TEXT PRIMARY KEY,selection_id INTEGER,revision INTEGER,created_at TEXT)')


def begin(store,user_key,rid,revision):
    with store.tx() as c:
        migrate(c)
        row=c.execute('SELECT status,revision FROM selections WHERE id=?',(rid,)).fetchone()
        if not row or row['status']!='draft_ready' or row['revision']!=revision:raise ValueError('Stale upload request')
        c.execute('INSERT OR REPLACE INTO image_upload_intents VALUES(?,?,?,?)',(str(user_key),rid,revision,now()))


def accept(store,user_key,update_id,data,caption):
    if caption.strip().upper()!='OWN':raise ValueError('본인 소유 또는 이용 허락을 확인했다면 캡션 OWN으로 보내세요.')
    with store.tx() as c:
        migrate(c)
        intent=c.execute('SELECT * FROM image_upload_intents WHERE user_key=?',(str(user_key),)).fetchone()
        if not intent:raise ValueError('먼저 /upload ID VERSION 또는 업로드 버튼을 선택하세요.')
        rid,revision=intent['selection_id'],intent['revision']
        row=c.execute('SELECT status,revision FROM selections WHERE id=?',(rid,)).fetchone()
        if not row or row['status']!='draft_ready' or row['revision']!=revision:raise ValueError('Upload version expired')
        job=c.execute("SELECT id FROM jobs WHERE kind='render' AND json_extract(payload,'$.id')=? AND json_extract(payload,'$.revision')=? AND state='waiting'",(rid,revision)).fetchone()
        if not job:raise ValueError('Waiting render required')
    photo=dict(ingest(data,Path(store.path).parent/'data/user-images'/f'{rid}-{revision}-{int(update_id)}.png'),provider='user-upload',uploaded=True,rights_confirmed=True,uploader=str(user_key),review_required=True,source_url='https://telegram.org/',license_url='https://telegram.org/tos',license='User declares ownership or permission; human verification required')
    with store.tx() as c:
        row=c.execute('SELECT status,revision FROM selections WHERE id=?',(rid,)).fetchone()
        if not row or row['status']!='draft_ready' or row['revision']!=revision:raise ValueError('Upload version expired')
        step='upload_'+str(int(update_id))+'_download'
        c.execute("INSERT OR IGNORE INTO checkpoints(job_id,step,state,result,created_at) VALUES(?,?,'succeeded',?,?)",(job['id'],step,json.dumps(photo),now()))
        store.event(c,rid,'image_upload',json.dumps({'revision':revision,'sha256':photo['sha256'],'uploader':str(user_key)}))
    return rid,revision
