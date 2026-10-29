"""Plan by default; one approved Models GET, never a Messages/generation request."""
import argparse
import json
from pathlib import Path
import re
from .config import Config


def plan(model):
    if not isinstance(model,str) or not re.fullmatch(r'claude-[a-z0-9][a-z0-9._-]{0,110}',model):
        raise ValueError('정식 Claude 모델 ID/별칭 형식이 아닙니다. 입력값은 출력하지 않습니다.')
    catalog=json.loads(Path(__file__).with_name('claude_models.json').read_text())
    return {'model':model,'method':'GET','endpoint':'https://api.anthropic.com/v1/models/'+model,
            'documented_in_local_snapshot':model in catalog['active'] or model in catalog['deprecated'],
            'executed':False,'metadata_requests':0,'generation_requests':0,
            'account_support_verified':False}


def probe_once(config,model,*,approved=False,client_factory=None):
    result=plan(model)
    if not approved or config.env.get('ENABLE_MODEL_METADATA_LOOKUP')!='1':
        raise PermissionError('모델 조회는 미실행 상태입니다. 별도 승인과 일회성 ENABLE_MODEL_METADATA_LOOKUP=1 설정이 필요합니다.')
    key=config.env.get('ANTHROPIC_API_KEY','')
    if not key.strip():raise ValueError('ANTHROPIC_API_KEY가 없습니다. 비밀값을 출력하지 않습니다.')
    from .safe_logging import configure_logging
    configure_logging(config.env)
    requests=0
    try:
        if client_factory is None:
            from anthropic import Anthropic
            client_factory=Anthropic
        with client_factory(api_key=key,base_url='https://api.anthropic.com',timeout=15,max_retries=0) as client:
            requests=1
            response=client.models.retrieve(model)
            canonical=response.id
            if not isinstance(canonical,str) or not re.fullmatch(r'claude-[a-z0-9][a-z0-9._-]{0,110}',canonical):
                raise ValueError('Unexpected model metadata')
        return dict(result,executed=True,metadata_requests=1,account_support_verified=True,resolved_model=canonical)
    except Exception as exc:
        status=getattr(exc,'status_code',None)
        kind={401:'authentication_failed',403:'access_denied',404:'model_unavailable_or_not_accessible'}.get(status,'metadata_check_failed')
        return dict(result,executed=bool(requests),metadata_requests=requests,error=kind)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',required=True)
    parser.add_argument('--execute-approved',action='store_true',help='별도 승인 이후에만 사용; 일회성 환경 플래그도 필요')
    args=parser.parse_args()
    try:
        result=probe_once(Config.load(),args.model,approved=True) if args.execute_approved else plan(args.model)
    except (ValueError,PermissionError) as exc:raise SystemExit(str(exc)) from None
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result.get('error'):raise SystemExit(1)

if __name__=='__main__':main()
