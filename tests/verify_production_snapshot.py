"""Verify additive migrations against a consistent backup, never the live DB."""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bureau.store import Store


def main():
    p=argparse.ArgumentParser();p.add_argument('backup',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);copy=a.output/'migrated-copy.sqlite3'
    if copy.exists():raise ValueError('Choose a fresh output directory')
    shutil.copyfile(a.backup,copy);copy.chmod(0o600)
    with sqlite3.connect(f'file:{a.backup.resolve()}?mode=ro',uri=True) as src:
        tables=[r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        before={t:([r[1] for r in src.execute(f'PRAGMA table_info("{t}")')],src.execute(f'SELECT * FROM "{t}"').fetchall()) for t in tables}
    Store(copy).migrate();Store(copy).migrate()
    checks={}
    with sqlite3.connect(copy) as c:
        for t,(columns,rows) in before.items():
            projection=','.join('"'+name+'"' for name in columns)
            after=c.execute(f'SELECT {projection} FROM "{t}"').fetchall()
            assert all(row in after for row in rows),t
            if t!='schema_versions':assert len(rows)==len(after),t
            checks[t]={'original_rows':len(rows),'preserved':True}
        assert c.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert c.execute('SELECT MAX(version) FROM schema_versions').fetchone()[0]==3
    report={'result':'PASS','live_database_modified':False,'migration_idempotent':True,'tables':checks}
    (a.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
