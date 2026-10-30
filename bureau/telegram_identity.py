"""Read only the local official Telegram account export. No polling or network."""
import argparse
import json
from pathlib import Path


def exported_user_id(path):
    # Never print the full export (phone, contacts, messages).
    try:
        value=json.loads(Path(path).read_text())['personal_information']['user_id']
        if isinstance(value,bool) or not str(value).isdigit() or int(value)<=0:
            raise ValueError()
        return str(value)
    except Exception:
        raise ValueError('계정 정보 JSON의 personal_information.user_id를 확인하세요. 원본 내용은 출력하지 않습니다.') from None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('account_export')
    args=parser.parse_args()
    try: print(exported_user_id(args.account_export))
    except ValueError as exc: raise SystemExit(str(exc)) from None


if __name__=='__main__': main()
