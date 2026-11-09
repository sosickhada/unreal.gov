"""Fail closed: monthly allowance alone does not prove a free-only billing cap."""
import json
import os
from pathlib import Path
import subprocess
from .store import Store, now
from .gemini_images import prompt_for

class PuterBlocked(ValueError):
    pass


def inspect_account(config):
    config.require_external()
    if not config.env.get('PUTER_AUTH_TOKEN'): raise PuterBlocked('PUTER_AUTH_TOKEN required')
    try:
        r=subprocess.run(['node',str(Path(__file__).resolve().parents[1]/'scripts/puter_bridge.mjs'),'inspect'],env=dict(os.environ,PUTER_AUTH_TOKEN=config.env['PUTER_AUTH_TOKEN']),capture_output=True,text=True,timeout=60,check=True)
        data=json.loads(r.stdout)
        if data.get('authenticated') is not True or not isinstance(data.get('models'),list): raise ValueError()
        with Store(config.db).tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS puter_account_snapshots(id INTEGER PRIMARY KEY,allowance TEXT,model_count INTEGER,created_at TEXT)')
            c.execute('INSERT INTO puter_account_snapshots(allowance,model_count,created_at) VALUES(?,?,?)',(json.dumps(data.get('allowanceInfo',{})),len(data['models']),now()))
        return data
    except Exception:
        raise PuterBlocked('Puter authentication/model/usage inspection failed; details withheld') from None


def generate(config,draft,slot,*,approved_test=False):
    prompt=prompt_for(draft,slot)
    store=Store(config.db)
    with store.tx() as c:
        c.execute('CREATE TABLE IF NOT EXISTS puter_image_attempts(id INTEGER PRIMARY KEY,mode TEXT,slot TEXT,state TEXT,reason TEXT,created_at TEXT)')
        c.execute('INSERT INTO puter_image_attempts(mode,slot,state,reason,created_at) VALUES(?,?,?,?,?)',('approved_test' if approved_test else 'automatic',slot,'blocked','free_only_cost_unverified',now()))
    # Intentional: no SDK generation call, retry, payment or purchasing path.
    raise PuterBlocked('Puter 무료 전용 잔액·모델별 최대 비용을 검증할 수 없어 생성 차단 (일일 최대 2회, 자동 재시도 0회).')


def budget_message(config,store=None):
    return 'Puter 생성 비활성: 무료 전용 잔액·확정 최대 비용 검증 전 호출하지 않습니다. 하루 최대 2회, 자동 재시도 0회. /photos ID로 기존 검토 사진을 선택하세요.'
