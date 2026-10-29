# 모델·Telegram 사용자 설정 복구 조사

## 조사 결과

- 현재 `bot.py`는 DB 작업 접수만 하며 모델 기본값이 없습니다. Git HEAD의 기존 `bot.py`, `create_draft.py`, `test_claude_draft.py`에는 **claude-haiku-5-5** 기본값이 있습니다. 현재 과거 수동 원고 테스트 파일에도 같은 값이 남아 있습니다. 이 파일은 실행하지 않았습니다.
- `.env.example`은 `CLAUDE_MODEL`이 빈 값입니다. 운영 환경과 조사한 환경 백업에서도 명시적인 모델/허용 사용자 설정을 복원하지 못했습니다. 운영 문서는 모델 자동 추측 대신 명시적인 설정을 요구합니다.
- [Anthropic 공식 모델 수명주기](https://platform.claude.com/docs/en/about-claude/model-deprecations)에서 claude-haiku-5-5가 Active임을 확인했습니다. 이는 공개 지원 여부이며 현재 API 키/계정의 실제 접근 권한까지 확인한 것은 아닙니다.
- 기존 리스너는 대부분 `effective_chat.id == CHAT_ID`로 제한했습니다. 일부 callback에서 `effective_user.id == CHAT_ID`도 비교했지만, 별도 허용 사용자 설정이나 실제 발신자 관측 증거가 아니므로 그 값을 사용자 ID로 복사하지 않았습니다.
- 새 리스너는 chat ID 일치와 `effective_user.id`의 명시적 allowlist 포함 여부를 각각 검사합니다. 전화번호·@사용자명·채팅 ID는 허용 사용자 ID의 대체 값이 아닙니다.
- 운영 DB는 selections와 sqlite_sequence만 있으며 사용자·업데이트 기록 컬럼이 없습니다. 로컬 파일과 과거 리스너 백업을 조사했고, 기존 Telegram journal 최근 1000건에서도 신뢰할 수 있는 구조화된 실제 발신자 ID를 찾지 못했습니다. 원문 로그·채팅 ID·비밀값을 출력하지 않았습니다. 테스트 데이터의 가짜 사용자 ID는 복구 근거에서 제외했습니다.
- `getUpdates`, `getMe` 등 Telegram API를 호출하지 않았습니다. 실행 중인 리스너의 polling과 충돌하거나 업데이트 확인 상태에 영향을 줄 수 있는 조회도 하지 않았습니다.

## 준비한 안전한 모델 확인 방법

`bureau/model_probe.py`는 기본적으로 **계획만 출력**합니다. 운영 모델을 설정하거나 DB를 열지 않습니다.

```bash
.venv/bin/python -m bureau.model_probe --model claude-haiku-5-5
```

현재 실행한 것은 위 계획 출력뿐입니다. 추후 실제 조회 승인을 받으면 `--execute-approved`와 일회성 `ENABLE_MODEL_METADATA_LOOKUP=1`을 모두 지정한 경우에만 공식 [GET /v1/models/{model_id}](https://platform.claude.com/docs/en/api/http/models/retrieve)를 1회 호출합니다. API 키는 기존 환경에서 내부 로드하며 명령행·출력에 넣지 않습니다. 공식 Anthropic 주소로 고정하고 timeout=15, 재시도=0입니다. 응답은 모델 ID·성공/실패 분류만 출력하며 모델 생성(Messages) 요청은 없습니다. 별칭은 공식 응답의 정식 ID로 확인할 수 있습니다. 404는 잘못된 ID 또는 계정에서 접근할 수 없는 모델로 구분해 기록하며 원문 응답·인증값은 출력하지 않습니다.

**Models 조회도 실제 Anthropic API 요청 1회입니다.** 현재 승인되지 않았으므로 실행하지 않았습니다. 시범의 총 API 호출 상한을 계산할 때 이 조회도 포함해야 합니다. 조회 1회와 후보 생성 1회로 총 2회를 사용하면 원고 생성은 추가 승인 전 진행하지 않습니다. 공개 문서 확인만으로 계정 접근 검증이 완료됐다고 표시하지 않습니다.

## 본인 사용자 ID 확인: 공식 Telegram Desktop만 사용

1. 본인 Telegram 계정으로 공식 Telegram Desktop에 로그인합니다.
2. **설정 → 고급 → Telegram 데이터 내보내기**를 엽니다.
3. **계정 정보만** 선택하고 형식을 **JSON**으로 지정해 내보냅니다. 대화·연락처·사진은 필요 없습니다.
4. 본인 컴퓨터에서 `result.json`을 열고 **personal_information.user_id**의 숫자를 확인합니다. 해당 필드는 Telegram의 [공식 내보내기 스키마](https://core.telegram.org/import-export#personalinformation)에서 본인 사용자 식별자로 정의되어 있습니다.
5. 그 숫자만 알려주세요. 전체 JSON, 전화번호, 봇 토큰/API 키는 전송하지 마세요. 여러 운영자를 허용하려면 각자가 확인한 숫자 ID를 쉼표로 구분합니다.

이는 봇에 메시지를 보내거나 서버 polling/서비스를 변경하지 않는 방법입니다. 개별 채팅의 `id`, 연락처의 `id`, 임의 메시지의 `from_id`를 본인 ID로 대신하지 마세요. `personal_information`이 없다면 계정 정보 선택과 JSON 형식을 확인하고 다시 내보내세요. Telegram이 보안 대기를 요구하면 앱 안내를 따릅니다.

## 준비한 복구 후보와 필요한 입력

`output/settings-recovery/candidate.env`에 명시적으로 **미적용 후보**를 보관했습니다(0600). 운영 환경파일은 수정하지 않았으며 누락된 사용자 ID는 비워 두었습니다.

필요한 입력은 두 가지입니다.

- `CLAUDE_MODEL`: 기존 기본값 **claude-haiku-5-5**를 사용할지 확인하거나 사용할 다른 공식 모델 ID를 지정.
- `TELEGRAM_ALLOWED_USER_IDS`: 본인이 확인한 숫자 사용자 ID(여러 명이면 쉼표 구분).

실제 모델 지원의 계정 확인에는 별도 API 조회 승인이 필요합니다. 이 조사에서는 모델 조회·생성 API 0회, Telegram API/메시지 전송 0회, 운영 DB·서비스·환경 변경 0건입니다. 로컬 코드·문서·미적용 후보 파일만 추가했습니다.

검증 결과: 전체 오프라인 테스트 **87개 통과 (108.258초)**, 컴파일 및 공백 검사 통과. Models 조회 성공은 해당 모델 메타데이터 조회를 확인하는 것이며 생성 요청의 잔액·쿼터·성공을 보장하지 않습니다.
