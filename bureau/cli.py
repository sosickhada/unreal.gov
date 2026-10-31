import argparse
import json
import sqlite3
import time
from pathlib import Path
from .config import Config
from .store import Store, now


def resume(store,jid):
    with store.tx() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row or row['state'] not in ('failed','waiting'):
            raise ValueError('Only failed/waiting jobs can resume; uncertain writes need reconciliation')
        if c.execute("SELECT 1 FROM checkpoints WHERE job_id=? AND state IN ('running','uncertain')",(jid,)).fetchone():
            raise ValueError('Uncertain external checkpoint blocks replay')
        c.execute("UPDATE jobs SET state='queued',error_code=NULL WHERE id=?",(jid,))
        store.event(c,jid,'operator_resume')


def main():
    p=argparse.ArgumentParser(description='비현실문제부: all external calls disabled by default')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('instagram-check');sub.add_parser('migrate'); sub.add_parser('health'); sub.add_parser('schedule');sub.add_parser('doctor');sub.add_parser('backup')
    worker=sub.add_parser('worker'); worker.add_argument('--once',action='store_true')
    repair=sub.add_parser('resume-photo');repair.add_argument('job_id',type=int)
    r=sub.add_parser('resume');r.add_argument('job_id',type=int)
    r=sub.add_parser('recover');r.add_argument('job_id',type=int);r.add_argument('--worker-stopped',action='store_true',required=True)
    a=sub.add_parser('attach-image');a.add_argument('record_id',type=int);a.add_argument('revision',type=int);a.add_argument('--slot',choices=('content','resolution_extra'),required=True);a.add_argument('path');a.add_argument('--source-url',required=True);a.add_argument('--license-url',required=True);a.add_argument('--license',required=True);a.add_argument('--reviewer',required=True);a.add_argument('--faces-reviewed',action='store_true',required=True);a.add_argument('--relevance-reviewed',action='store_true',required=True)
    a.add_argument('--photograph-reviewed',action='store_true',required=True)
    library=sub.add_parser('register-photo');library.add_argument('path');library.add_argument('--tags',required=True);library.add_argument('--source-url',required=True);library.add_argument('--license-url',required=True);library.add_argument('--license',required=True);library.add_argument('--reviewer',required=True);library.add_argument('--faces-reviewed',action='store_true',required=True);library.add_argument('--relevance-reviewed',action='store_true',required=True);library.add_argument('--photograph-reviewed',action='store_true',required=True)
    search=sub.add_parser('image-search');search.add_argument('query')
    download=sub.add_parser('download-image');download.add_argument('query');download.add_argument('photo_id',type=int);download.add_argument('destination')
    args=p.parse_args(); config=Config.load(); store=Store(config.db)
    if args.command=='instagram-check':
        from .instagram import Instagram
        from .adapters import ExternalError
        ig=Instagram(config)
        if ig.missing_settings():
            print(json.dumps({'connected':False,'missing_settings':ig.missing_settings(),'publishing_enabled':ig.enabled()}));return
        try: print(json.dumps(ig.preflight()))
        except (ExternalError,RuntimeError) as exc: print(json.dumps({'connected':False,'error':str(exc)}));raise SystemExit(1)
    elif args.command in ('doctor','backup'):
        from .operations import readiness,backup_database
        if args.command=='backup': print(backup_database(config.db,config.db.parent/'data'/'backups'))
        else:
            report=readiness(config);print(json.dumps(report,ensure_ascii=False,indent=2))
            if not report['ready_for_worker']: raise SystemExit(1)
    elif args.command=='migrate':
        # Every migration takes a consistent backup, including first-time CLI use.
        if config.db.is_file():
            from .operations import backup_database
            backup_database(config.db,config.db.parent/'data'/'backups')
        store.migrate();print('Additive schema migration complete')
    elif args.command=='health':
        # Health never creates a DB or writes to it.
        with sqlite3.connect(f'file:{config.db}?mode=ro',uri=True) as c:
            result={'integrity':c.execute('PRAGMA quick_check').fetchone()[0]}
            for table in ('jobs','outbox'):
                if c.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():
                    column='state';result[table]=c.execute(f'SELECT {column},count(*) FROM {table} GROUP BY {column}').fetchall()
            result['schema_version']=c.execute('SELECT MAX(version) FROM schema_versions').fetchone()[0] if c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_versions'").fetchone() else 0
        print(json.dumps(result,ensure_ascii=False))
    elif args.command=='schedule':
        if config.env.get('AUTOMATION_PAUSED')=='1': raise SystemExit('Automation paused')
        print('Scheduled job',store.schedule())
    elif args.command=='resume-photo':
        resume_photo_render(store,args.job_id);print('Photo render queued; uncertain assessments preserved and excluded')
    elif args.command=='resume':
        resume(store,args.job_id);print('Job queued from saved checkpoints')
    elif args.command=='recover':
        with store.tx() as c:
            row=c.execute("SELECT id FROM jobs WHERE id=? AND state='running'",(args.job_id,)).fetchone()
            if not row: raise ValueError('Job is not running')
            # Never infer that an interrupted API request did not reach its server.
            c.execute("UPDATE checkpoints SET state=CASE WHEN step LIKE 'claude%' OR step LIKE 'ig_child_%' AND step NOT LIKE 'ig_child_ready_%' OR step IN ('ig_container','ig_publish') THEN 'uncertain' ELSE 'failed' END WHERE job_id=? AND state='running'",(args.job_id,))
            uncertain=c.execute("SELECT 1 FROM checkpoints WHERE job_id=? AND state='uncertain'",(args.job_id,)).fetchone()
            c.execute('UPDATE jobs SET state=?,error_code=? WHERE id=?',('uncertain' if uncertain else 'failed','interrupted',args.job_id))
            store.event(c,args.job_id,'operator_recovery','worker stopped asserted')
        print('Recovery recorded; uncertain writes remain blocked')
    elif args.command=='register-photo':
        from .images import manual_image,terms
        if not terms(args.tags): raise ValueError('Concrete reviewed subject tags required')
        asset=manual_image(args.path,args.source_url,args.license_url,args.license,args.reviewer)
        with store.tx() as c:
            c.execute('INSERT OR REPLACE INTO image_library VALUES(?,?,?,?)',(asset['sha256'],json.dumps(asset),args.tags,now()))
        print('Reviewed reusable photograph registered; no external request made')
    elif args.command=='attach-image':
        from .images import manual_image
        r=store.row(args.record_id)
        if r['revision']!=args.revision or r['status']!='draft_ready': raise ValueError('Only current unrendered draft can accept an image')
        with store.tx() as c:
            if c.execute('SELECT 1 FROM assets WHERE selection_id=? AND revision=?',(args.record_id,args.revision)).fetchone():
                raise ValueError('Artifacts already exist; request a new revision instead of changing reviewed inputs')
        asset=manual_image(args.path,args.source_url,args.license_url,args.license,args.reviewer)
        with store.tx() as c:
            current=c.execute('SELECT revision,status FROM selections WHERE id=?',(args.record_id,)).fetchone()
            if current['revision']!=args.revision or current['status']!='draft_ready': raise ValueError('Draft changed')
            if c.execute('SELECT 1 FROM assets WHERE selection_id=? AND revision=?',(args.record_id,args.revision)).fetchone(): raise ValueError('Artifacts already exist')
            if c.execute("SELECT 1 FROM jobs WHERE kind='render' AND state='running' AND json_extract(payload,'$.id')=?",(args.record_id,)).fetchone(): raise ValueError('Render in progress')
            old=c.execute('SELECT payload FROM image_inputs WHERE selection_id=? AND revision=?',(args.record_id,args.revision)).fetchone()
            photos=json.loads(old[0]) if old else {}
            photos=photos.get('photos',{}) if 'photos' in photos else ({'content':photos} if photos else {})
            photos[args.slot]=asset
            if len({p['sha256'] for p in photos.values()})!=len(photos): raise ValueError('Two distinct photographs required')
            c.execute('INSERT OR REPLACE INTO image_inputs VALUES(?,?,?,?)',(args.record_id,args.revision,json.dumps({'photos':photos}),now()))
        print('Reviewed image registered; resume/create render job')
    elif args.command in ('image-search','download-image'):
        from .images import pixabay_search,download_candidate
        results=pixabay_search(config,args.query)
        if args.command=='image-search': print(json.dumps(results,ensure_ascii=False,indent=2))
        else:
            matches=[r for r in results if r['id']==args.photo_id]
            if not matches: raise ValueError('Photo ID not returned by source; do not invent URLs')
            result=download_candidate(config,matches[0],args.destination)
            Path(args.destination+'.provenance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            print('Downloaded; manual photographic quality, license, relevance and face review required')
    elif args.command=='worker':
        from .engine import Engine
        from .operations import readiness
        report=readiness(config)
        if not report['ready_for_worker']:
            print(json.dumps(report,ensure_ascii=False,indent=2))
            raise SystemExit('설정·DB 사전 점검 실패: 위 오류를 해결하세요. API를 호출하지 않았습니다.')
        engine=Engine(config)
        while True:
            worked=engine.run_one()
            delivered=engine.deliver_one() if config.env.get('ENABLE_EXTERNAL_CALLS')=='1' else False
            if args.once: break
            if not worked and not delivered: time.sleep(2)




def resume_photo_render(store,jid):
    """Operator repair: skip unresolved read-only photo assessments, never replay them.

    All original uncertain checkpoints remain intact. Any other unknown operation
    blocks this narrow repair, including render, Claude draft or publication.
    """
    with store.tx() as c:
        job=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not job or job['kind']!='render' or job['state'] not in ('uncertain','waiting'):
            raise ValueError('Only an uncertain photo render can use this repair')
        payload=json.loads(job['payload'])
        current=c.execute('SELECT revision,status FROM selections WHERE id=?',(payload['id'],)).fetchone()
        if not current or current['revision']!=payload['revision'] or current['status']!='draft_ready':
            raise ValueError('Render version changed')
        uncertain=c.execute("SELECT step,state FROM checkpoints WHERE job_id=? AND state IN ('running','uncertain')",(jid,)).fetchall()
        excluded=set(payload.get('exclude_photo_ids',[]))
        if not uncertain:raise ValueError('No unresolved photo assessment')
        for row in uncertain:
            if row['state']!='uncertain' or not row['step'].startswith('claude_photo_v2_'):
                raise ValueError('Other uncertain/running operation blocks repair')
            download=c.execute("SELECT result FROM checkpoints WHERE job_id=? AND step=? AND state='succeeded'",(jid,row['step'][len('claude_'):]+'_download')).fetchone()
            if not download:raise ValueError('No saved source for unresolved photo')
            photo=json.loads(download['result']);excluded.add(str(photo['id']))
            store.event(c,jid,'unresolved_photo_skipped',json.dumps({'step':row['step'],'candidate_id':photo['id'],'charge_still_unknown':True}))
        payload['exclude_photo_ids']=sorted(excluded)
        c.execute("UPDATE jobs SET state='queued',error_code=NULL,payload=? WHERE id=?",(json.dumps(payload),jid))
        store.event(c,jid,'operator_photo_repair','Uncertain checkpoints preserved; source IDs excluded; no paid replay')


if __name__=='__main__':
    main()
