"""Pure local configuration checks. Never queries provider APIs or echoes values."""
import datetime as dt
import json
from pathlib import Path
import re


class ConfigurationError(ValueError):
    def __init__(self, code, message):
        self.code=code
        super().__init__(message)


def claude_settings(env):
    model=env.get('CLAUDE_MODEL','')
    if not model:
        raise ConfigurationError('claude_model_missing','CLAUDE_MODEL이 없습니다. 공식 Claude API 모델 ID를 설정하세요. API를 호출하지 않았습니다.')
    catalog=json.loads(Path(__file__).with_name('claude_models.json').read_text())
    if model in catalog['retired']:
        raise ConfigurationError('claude_model_retired','폐기된 Claude 모델입니다. 공식 모델 목록을 확인하세요. API를 호출하지 않았습니다.')
    if model in catalog['deprecated']:
        if dt.datetime.now(dt.timezone.utc).date()>=dt.date.fromisoformat(catalog['deprecated'][model]):
            raise ConfigurationError('claude_model_retired','설정한 Claude 모델의 폐기일이 지났습니다. API를 호출하지 않았습니다.')
    elif model not in catalog['active']:
        raise ConfigurationError('claude_model_unverified','공식 문서 대조 목록에 없는 Claude 모델 ID입니다. 오타·플랫폼 ID·목록 갱신 여부를 확인하세요. API를 호출하지 않았습니다.')
    if not env.get('ANTHROPIC_API_KEY','').strip():
        raise ConfigurationError('claude_key_missing','ANTHROPIC_API_KEY가 없습니다. 비밀값을 출력하지 않고 API 호출을 중단합니다.')
    return {'catalog_verified_on':catalog['verified_on'],'model_id_documented':True,
            'deprecated':model in catalog['deprecated'],'account_access_verified':False}


def telegram_settings(env, require_users=True):
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{30,}',env.get('TELEGRAM_BOT_TOKEN','')):
        raise ConfigurationError('telegram_token_invalid','Telegram 봇 토큰이 없거나 형식이 올바르지 않습니다. 인증정보를 출력하지 않고 중단합니다.')
    if not re.fullmatch(r'-?[1-9][0-9]*',env.get('TELEGRAM_CHAT_ID','')):
        raise ConfigurationError('telegram_chat_invalid','TELEGRAM_CHAT_ID가 없거나 정수 형식이 아닙니다.')
    if require_users:
        users=env.get('TELEGRAM_ALLOWED_USER_IDS','').split(',')
        if not users or any(not re.fullmatch(r'[1-9][0-9]*',uid.strip()) for uid in users):
            raise ConfigurationError('telegram_users_invalid','TELEGRAM_ALLOWED_USER_IDS에 허용 사용자 ID를 쉼표로 구분해 설정하세요. 빈 값·이름·와일드카드는 허용하지 않습니다.')
    return {'token_format_valid':True,'chat_format_valid':True,'allowlist_valid':require_users,'authentication_verified':False}
