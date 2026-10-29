import contextlib
import datetime as dt
import hashlib
import json
import sqlite3
from zoneinfo import ZoneInfo


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def kst_day():
    return dt.datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = str(path)

    @contextlib.contextmanager
    def tx(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=10000')
        c.execute('BEGIN IMMEDIATE')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def migrate(self):
        # Additive, transactional migration; never recreate or overwrite legacy rows.
        with self.tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS selections (id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_number INTEGER NOT NULL, candidate_title TEXT NOT NULL, selected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, status TEXT NOT NULL DEFAULT \'selected\', draft_json TEXT, image_paths TEXT)')
            columns = {r['name'] for r in c.execute('PRAGMA table_info(selections)')}
            for name, typ in {'candidate_id':'INTEGER', 'revision':'INTEGER NOT NULL DEFAULT 1', 'approved_revision':'INTEGER', 'reviewed_revision':'INTEGER', 'revision_note':'TEXT', 'published_id':'TEXT'}.items():
                if name not in columns:
                    c.execute(f'ALTER TABLE selections ADD COLUMN {name} {typ}')
            statements = [
                'CREATE TABLE IF NOT EXISTS draft_versions(selection_id INTEGER NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(selection_id,revision))',
                'CREATE TABLE IF NOT EXISTS quality_reviews(selection_id INTEGER NOT NULL, revision INTEGER NOT NULL, issues TEXT NOT NULL, accepted_at TEXT, PRIMARY KEY(selection_id,revision))',
                'CREATE TABLE IF NOT EXISTS image_library(sha256 TEXT PRIMARY KEY, payload TEXT NOT NULL, tags TEXT NOT NULL, created_at TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS image_inputs(selection_id INTEGER NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(selection_id,revision))',
                'CREATE TABLE IF NOT EXISTS requests(request_key TEXT PRIMARY KEY, result TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)',
                '''CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY, day TEXT NOT NULL, generation INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(day,generation))''',
                '''CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batches(id), position INTEGER NOT NULL, title TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'available', created_at TEXT NOT NULL, UNIQUE(batch_id,position))''',
                '''CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, job_key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', stage TEXT, error_code TEXT, attempts INTEGER NOT NULL DEFAULT 0, started_at TEXT, finished_at TEXT, created_at TEXT NOT NULL)''',
                "CREATE UNIQUE INDEX IF NOT EXISTS one_worker ON jobs((1)) WHERE state='running'",
                '''CREATE TABLE IF NOT EXISTS checkpoints(job_id INTEGER NOT NULL REFERENCES jobs(id), step TEXT NOT NULL, state TEXT NOT NULL, result TEXT, input_tokens INTEGER, output_tokens INTEGER, created_at TEXT NOT NULL, PRIMARY KEY(job_id,step))''',
                '''CREATE TABLE IF NOT EXISTS assets(selection_id INTEGER NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(selection_id,revision))''',
                '''CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, delivery_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', remote_ids TEXT, error_code TEXT, created_at TEXT NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, subject TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS publications(selection_id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL, children TEXT NOT NULL DEFAULT '[]', container_id TEXT, media_id TEXT, updated_at TEXT NOT NULL)''',
                "CREATE UNIQUE INDEX IF NOT EXISTS one_selection_per_candidate ON selections(candidate_id) WHERE candidate_id IS NOT NULL",
            ]
            for sql in statements:
                c.execute(sql)
            c.execute('INSERT OR IGNORE INTO draft_versions SELECT id,revision,draft_json,? FROM selections WHERE draft_json IS NOT NULL',(now(),))
            c.execute('INSERT OR IGNORE INTO schema_versions VALUES(1,?)', (now(),))
            c.execute('INSERT OR IGNORE INTO schema_versions VALUES(2,?)', (now(),))
            c.execute('INSERT OR IGNORE INTO schema_versions VALUES(3,?)', (now(),))

    @staticmethod
    def event(c, subject, action, detail=''):
        c.execute('INSERT INTO events(subject,action,detail,created_at) VALUES(?,?,?,?)', (str(subject), action, detail, now()))

    @staticmethod
    def enqueue(c, key, kind, payload):
        c.execute('INSERT OR IGNORE INTO jobs(job_key,kind,payload,created_at) VALUES(?,?,?,?)', (key,kind,json.dumps(payload,ensure_ascii=False),now()))
        return c.execute('SELECT id FROM jobs WHERE job_key=?',(key,)).fetchone()[0]

    @staticmethod
    def notify(c, key, payload):
        c.execute('INSERT OR IGNORE INTO outbox(delivery_key,payload,created_at) VALUES(?,?,?)',(key,json.dumps(payload,ensure_ascii=False),now()))

    def schedule(self, day=None, regenerate=False, maximum=2, request_key=None):
        day = day or kst_day()
        with self.tx() as c:
            if request_key:
                old=c.execute('SELECT result FROM requests WHERE request_key=?',(request_key,)).fetchone()
                if old: return int(old[0])
            if not regenerate:
                generation = 0
            else:
                generation = c.execute('SELECT COALESCE(MAX(generation),0)+1 FROM batches WHERE day=?',(day,)).fetchone()[0]
                if generation > maximum:
                    raise ValueError('Daily candidate regeneration limit reached')
            c.execute("INSERT OR IGNORE INTO batches(day,generation,status,created_at) VALUES(?,?,'queued',?)",(day,generation,now()))
            batch = c.execute('SELECT id FROM batches WHERE day=? AND generation=?',(day,generation)).fetchone()[0]
            result=self.enqueue(c,f'candidates:{day}:{generation}','candidates',{'batch_id':batch})
            if request_key: c.execute('INSERT INTO requests VALUES(?,?)',(request_key,str(result)))
            return result

    def claim(self):
        with self.tx() as c:
            if c.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone():
                return None
            row = c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
            if row:
                c.execute("UPDATE jobs SET state='running',attempts=attempts+1,started_at=? WHERE id=?",(now(),row['id']))
                self.event(c,row['id'],'claimed')
            return dict(row) if row else None

    def row(self, record_id):
        with self.tx() as c:
            row=c.execute('SELECT * FROM selections WHERE id=?',(record_id,)).fetchone()
            if not row:
                raise ValueError('Unknown content ID')
            return dict(row)

    def select(self, candidate_id):
        with self.tx() as c:
            old=c.execute('SELECT id FROM selections WHERE candidate_id=?',(candidate_id,)).fetchone()
            if old:
                return old[0]
            row=c.execute("SELECT x.* FROM candidates x JOIN batches b ON b.id=x.batch_id WHERE x.id=? AND x.status='available' AND b.status='ready' AND b.day=?",(candidate_id,kst_day())).fetchone()
            if not row:
                raise ValueError('Candidate unavailable or expired')
            # A fresh daily batch is not permission to regenerate the same story.
            # BEGIN IMMEDIATE serializes this check with every selection writer.
            payload=json.loads(row['payload'])
            prior=c.execute('''SELECT s.id FROM selections s JOIN candidates x ON x.id=s.candidate_id
                WHERE json_extract(x.payload,'$.source_url')=? ORDER BY s.id LIMIT 1''',
                (payload['source_url'],)).fetchone()
            if prior:
                self.event(c,prior[0],'duplicate_source_skipped',str(candidate_id))
                return prior[0]
            rid=c.execute("INSERT INTO selections(candidate_id,candidate_number,candidate_title,status) VALUES(?,?,?,'selected')",(candidate_id,row['position'],row['title'])).lastrowid
            c.execute("UPDATE candidates SET status='selected' WHERE id=?",(candidate_id,))
            self.enqueue(c,f'draft:{rid}:1','draft',{'id':rid,'revision':1})
            self.event(c,rid,'selected',str(candidate_id))
            return rid

    def revise(self, rid, note, maximum=3, request_key=None):
        if not note.strip() or len(note)>1000:
            raise ValueError('Revision request must contain 1–1000 characters')
        with self.tx() as c:
            if request_key:
                old=c.execute('SELECT result FROM requests WHERE request_key=?',(request_key,)).fetchone()
                if old: return int(old[0])
            r=c.execute('SELECT * FROM selections WHERE id=?',(rid,)).fetchone()
            if not r or r['status'] not in ('selected','preview_ready','draft_ready','revision_requested','draft_review','draft_invalid'):
                raise ValueError('Content cannot be revised in current state')
            if r['revision']>=maximum+1:
                raise ValueError('Revision limit reached')
            # Never mutate approved or published content; retain all old checkpoints/assets.
            rev=r['revision']+1
            if r['draft_json'] is not None:
                c.execute('INSERT OR IGNORE INTO draft_versions VALUES(?,?,?,?)',(rid,r['revision'],r['draft_json'],now()))
            c.execute("UPDATE selections SET revision=?,status='revision_requested',revision_note=?,approved_revision=NULL,reviewed_revision=NULL,draft_json=NULL,image_paths=NULL WHERE id=?",(rev,note,rid))
            self.enqueue(c,f'draft:{rid}:{rev}','draft',{'id':rid,'revision':rev})
            self.event(c,rid,'revision_requested',note)
            if request_key: c.execute('INSERT INTO requests VALUES(?,?)',(request_key,str(rev)))
            return rev

    def accept_draft(self, rid, revision):
        with self.tx() as c:
            r=c.execute('SELECT * FROM selections WHERE id=? AND revision=?',(rid,revision)).fetchone()
            if not r: raise ValueError('Unknown draft version')
            reviewed=c.execute('SELECT accepted_at FROM quality_reviews WHERE selection_id=? AND revision=?',(rid,revision)).fetchone()
            if reviewed and reviewed[0]: return  # Replayed acceptance is idempotent.
            if r['status']!='draft_review' or not reviewed: raise ValueError('Draft is not awaiting editorial review')
            job=c.execute('SELECT state FROM jobs WHERE job_key=?',(f'draft:{rid}:{revision}',)).fetchone()
            if job and job[0]=='running': raise ValueError('Draft worker is finishing; retry shortly')
            c.execute('UPDATE quality_reviews SET accepted_at=? WHERE selection_id=? AND revision=?',(now(),rid,revision))
            c.execute("UPDATE selections SET status='draft_ready' WHERE id=?",(rid,))
            self.enqueue(c,f'render:{rid}:{revision}','render',{'id':rid,'revision':revision})
            c.execute("UPDATE jobs SET state='succeeded',error_code=NULL WHERE job_key=? AND state='waiting' AND error_code='draft_quality_review'",(f'draft:{rid}:{revision}',))
            self.event(c,rid,'editorial_accept',str(revision))

    def review(self, rid, revision):
        with self.tx() as c:
            r=c.execute("SELECT * FROM selections WHERE id=? AND revision=? AND status='preview_ready'",(rid,revision)).fetchone()
            if not r:
                raise ValueError('Preview version changed or not ready')
            c.execute('UPDATE selections SET reviewed_revision=? WHERE id=?',(revision,rid))
            self.event(c,rid,'human_review',str(revision))

    def decide(self, rid, revision, approve):
        with self.tx() as c:
            r=c.execute('SELECT * FROM selections WHERE id=?',(rid,)).fetchone()
            if not r or r['revision']!=revision or r['status']!='preview_ready':
                raise ValueError('Already processed or stale preview')
            if approve and r['reviewed_revision']!=revision:
                raise ValueError('Source, image license, faces and text review required first: /review ID VERSION')
            c.execute('UPDATE selections SET status=?,approved_revision=? WHERE id=?',('approved' if approve else 'rejected', revision if approve else None,rid))
            if approve:
                self.enqueue(c,f'publish:{rid}:{revision}','publish',{'id':rid,'revision':revision})
            self.event(c,rid,'approved' if approve else 'rejected',str(revision))
