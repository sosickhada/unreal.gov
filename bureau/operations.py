"""Read-only readiness and consistent, private SQLite backups. No network calls."""
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse
from .store import now
from .content import safe_https
from .preflight import claude_settings,telegram_settings,ConfigurationError


def backup_database(db, directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    target=directory/('preflight-'+now().replace(':','-')+'.sqlite3')
    # Create private before opening SQLite, not after copying sensitive rows.
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    try:
        with sqlite3.connect(f'file:{Path(db).resolve()}?mode=ro',uri=True) as src,sqlite3.connect(target) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise RuntimeError('Backup integrity check failed')
    except Exception:
        target.unlink(missing_ok=True)
        raise RuntimeError('Backup failed; source database was opened read-only') from None
    return target


def readiness(config):
    e=config.env;issues=[]
    configuration_errors=[];checks={}
    for name,check in (('claude',claude_settings),('telegram',telegram_settings)):
        try: checks[name]=check(e)
        except ConfigurationError as exc:
            issues.append(exc.code)
            configuration_errors.append({'code':exc.code,'message':str(exc)})
    required=('ANTHROPIC_API_KEY','CLAUDE_MODEL','TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID','TELEGRAM_ALLOWED_USER_IDS','PUBLIC_BASE_URL','RENDER_DIR','IMAGE_DIR')
    missing=[key for key in required if not e.get(key)]
    if missing: issues.append('required_settings_missing')
    if not safe_https(e.get('PUBLIC_BASE_URL','')): issues.append('public_https_invalid')
    private=Path(e.get('RENDER_DIR','data/rendered')).resolve();public=Path(e.get('IMAGE_DIR','/opt/unreal.gov/public/images')).resolve()
    if private==public or public in private.parents: issues.append('render_directory_is_public')
    if e.get('REQUIRE_TOPIC_IMAGE','1')!='1': issues.append('topic_photo_review_disabled')
    schema=0;integrity='missing';backlog={}
    if config.db.is_file():
        try:
            with sqlite3.connect(f'file:{config.db.resolve()}?mode=ro',uri=True) as c:
                integrity=c.execute('PRAGMA quick_check').fetchone()[0]
                tables={row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'schema_versions' in tables:schema=c.execute('SELECT COALESCE(MAX(version),0) FROM schema_versions').fetchone()[0]
                for table in ('jobs','outbox'):
                    if table in tables:
                        backlog[table]=dict(c.execute(f'SELECT state,count(*) FROM {table} GROUP BY state'))
        except sqlite3.Error: issues.append('database_unreadable')
    if schema<3: issues.append('migration_required')
    if integrity!='ok': issues.append('database_integrity_unverified')
    if any(backlog.get(table,{}).get(state,0) for table,states in [('jobs',('running','uncertain')),('outbox',('sending','uncertain'))] for state in states):
        issues.append('inflight_or_uncertain_work_requires_inspection')
    meta=('META_ACCESS_TOKEN','META_APP_ID','META_APP_ACCESS_TOKEN','META_PAGE_ID','INSTAGRAM_ACCOUNT_ID','META_GRAPH_VERSION')
    return {'ready_for_worker':not issues,'issues':issues,'configuration_errors':configuration_errors,'local_provider_checks':checks,'missing_settings':missing,'schema_version':schema,'integrity':integrity,'backlog':backlog,
            'external_calls_enabled':e.get('ENABLE_EXTERNAL_CALLS')=='1','public_media_enabled':e.get('ENABLE_PUBLIC_MEDIA')=='1',
            'instagram_enabled':e.get('INSTAGRAM_PUBLISH_ENABLED')=='1','missing_instagram_settings':[key for key in meta if not e.get(key)],
            'account_connections_verified':False}
