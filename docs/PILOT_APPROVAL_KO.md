# 단일 시범 운영 승인안 — 2026-10-29

현재는 실제 Claude API, Telegram 인증/수신/전송, Instagram API, 서비스 변경, 예약 변경을 실행하지 않았습니다. 비밀값은 출력하지 않았으며 운영 환경파일과 DB 데이터도 변경하지 않았습니다.

## 최종 사전 점검

- `CLAUDE_MODEL`은 **누락**입니다. API 키는 존재하지만 인증/계정 사용 가능 여부는 확인하지 않았습니다. [공식 모델 목록](https://platform.claude.com/docs/en/models/overview) 및 [모델 수명주기](https://platform.claude.com/docs/en/about-claude/model-deprecations)를 2026-10-29에 대조했습니다. `bureau/claude_models.json`은 문서에 확인된 정식 ID의 오프라인 목록이며 계정의 사용 권한 증명이 아닙니다. 새 ID/별칭은 공식 문서 대조 후 목록에 추가해야 합니다. 모델을 임의 선택하거나 다른 모델로 자동 대체하지 않습니다.
- 모델 누락·미확인 ID·폐기 ID는 SDK 생성과 API 호출 전에 한국어 오류로 중단합니다. worker는 설정 오류를 출력하고 시작하지 않으며, 이미 접수된 작업도 설정 오류는 waiting으로 기록합니다. 이 경우 유료 checkpoint/토큰 예약을 만들거나 불확실한 유료 요청으로 취급하지 않습니다.
- Telegram 토큰은 존재하고 형식은 유효합니다. 환경파일 권한은 0600입니다. **허용 사용자 ID 목록은 누락**입니다. 실제 토큰 인증과 chat 접근 권한은 미확인입니다. 빈 목록·이름·와일드카드·잘못된 정수는 시작 전에 거절합니다.
- 설치된 Telegram SDK는 인증 실패 예외에 토큰을 포함할 수 있어, 시작 실패를 안전한 오류로 변환하고 로그 본문·예외 체인의 알려진 비밀값을 가리도록 보완했습니다. bootstrap 재시도는 0입니다.
- 운영 DB를 읽기 전용으로 새 백업하고 복제본에 마이그레이션을 두 번 적용했습니다. 기존 selections 3건과 기존 컬럼 값이 보존되고 integrity=ok입니다. 실제 운영 DB는 여전히 구형 스키마이므로 적용 승인이 필요합니다.
- 현재 Telegram·이미지 서버·Caddy는 active/enabled입니다. 새 worker와 서버 timer는 inactive/dead입니다. 원격 legacy GitHub workflow는 active입니다. 로컬 수동 workflow 템플릿이 원격에 적용됐다고 가정하지 않습니다.
- 기존 리스너와 새 리스너의 실행 파일은 같은 `/opt/unreal-github/telegram_listener.py`이고 설정 파일도 `/opt/unreal.gov/.env`로 일치합니다. 새 worker는 같은 VM/SQLite와 이미지 루트를 사용합니다. 유닛 문법 검사 통과이며 기존 호스트 유닛/버스 권한 경고는 별도로 기록했습니다. **현재 누락 설정과 DB 마이그레이션을 해결하기 전 새 프로세스를 시작하면 거절되는 것이 정상**입니다. 같은 토큰의 두 리스너를 동시에 시작하지 않습니다.
- 이미지 서버의 공개 루트 `/opt/unreal.gov/public`, Caddy의 `/images/* → 127.0.0.1:8765`, 새 `/images/unreal-case-ID-vREV_01.jpg` 경로 구조와 JPEG MIME이 일치합니다. 기존 공개 이미지 HTTPS HEAD는 200입니다. 새 이미지를 공개하거나 새 JPEG의 실제 바이트를 검증하지는 않았습니다. 비공개 미리보기 시범에는 이미지 서버/Caddy 변경이 필요 없습니다.

증거는 `output/pilot-preflight/`의 `settings-before.json`, `doctor.json`, `db-backup.json`, `migration/report.json`, `image-server.json`, `unit-tests.log`, `unit-verify.log`에 보관합니다.

## 필요한 승인 1 — 운영 설정·DB·리스너 전환

사용할 정식 Claude 모델 ID와 Telegram 허용 사용자 ID를 확정하고, 누락된 `PUBLIC_BASE_URL`, `IMAGE_DIR`, `RENDER_DIR` 등 운영 설정을 기존 비밀값을 유지해 병합합니다. API 키/토큰을 채팅·명령행·로그·Git에 옮기지 않습니다. 검토 완료 실사 사진도 등록해야 합니다.

정비 창에서 기존 리스너 하나를 중지하고 추가 백업 → DB 추가 마이그레이션 → `health`/`doctor` → 새 리스너 하나 시작 순서로 전환합니다. worker는 상시 서비스/timer 대신 시범용 `worker --once`로 수동 실행합니다. 기존 승인 콘텐츠는 게시 대상으로 새로 접수하지 않습니다. worker 유닛 설치/상시 시작, 부팅 활성화는 시범 이후 별도 전환 범위입니다.

## 필요한 승인 2 — 중복 방지를 위한 원격 예약 임시 중지

원격 legacy GitHub 예약 workflow를 시범 기간 임시 비활성화하고 원격 조회로 확인합니다. 서버 timer는 **계속 비활성**으로 유지합니다. Git 커밋/push, 새 수동 workflow 반영, timer 활성화는 최초 시범에 필요하지 않습니다.

## 필요한 승인 3 — 제한된 실제 Claude·Telegram 시범

아래 제한을 운영 환경 또는 승인된 단일 프로세스 환경에 명시합니다. 전역 외부 호출 허용은 승인 이후에만 1로 설정합니다.

```dotenv
MAX_CLAUDE_CALLS_PER_DAY=2
MAX_RESERVED_TOKENS_PER_DAY=60000
TOKENS_RESERVED_PER_CALL=30000
MAX_CANDIDATE_REGENERATIONS=0
MAX_CONTENT_REVISIONS=0
AUTO_IMAGE_SEARCH=0
ENABLE_PUBLIC_MEDIA=0
INSTAGRAM_PUBLISH_ENABLED=0
```

1. `health`로 이전 queued/running/uncertain/sending 작업을 확인하고 새 시범과 무관한 작업은 처리하지 않습니다. 현재 구형 DB를 초기화하거나 승인 기록을 삭제하지 않습니다.
2. KST 당일 후보 작업 하나만 접수합니다. RSS → **Claude 후보 생성 1회** → 저장된 후보 3개 → 지정 Telegram 채팅 전송. 별도의 모델 조회/더미 생성 호출은 추가하지 않습니다. 첫 실제 생성 요청으로 계정 인증·모델 사용 가능 여부도 확인합니다.
3. 새 리스너의 인증·polling과 허용 사용자 선택을 확인합니다. 해당 후보에 대해 **Claude 원고 생성 1회**만 허용합니다. 실제 Telegram 승인에는 인증/수신, callback 응답, 지정 채팅으로의 후보·원고·앨범·승인 안내 전송이 포함됩니다.
4. 원고 품질·사진이 미충족하면 안전하게 대기하고 시범을 중단합니다. 검토된 사진만 사용하여 private 렌더링 → Telegram 미리보기 → `/review` → 콘텐츠 승인까지 진행합니다. 품질 검토는 유료 재생성을 추가하지 않습니다.
5. Instagram 비활성으로 publish_waiting에서 종료합니다. 새 이미지 공개·Meta 인증/컨테이너 생성·실제 게시는 수행하지 않습니다.
6. API 오류·응답 불명확·JSON/품질 오류·전송 실패는 기존 checkpoint와 결과를 보존하고 중단합니다. 자동 재호출/재전송·모델 대체·다음 후보 재생성으로 비용을 늘리지 않습니다. 추가 호출은 새 승인을 받습니다.

유료 생성은 최대 2회지만 실제 과금은 선택 모델과 사용 토큰에 따라 달라집니다. 60,000 토큰 예약은 보수적 내부 한도이며 실제 청구 금액 보장이 아닙니다. 이전 당일 호출 기록이 있으면 남은 한도만 사용합니다.

## 종료와 복구

시범 후 결과·사용량·전송 ID·각 단계 상태를 기록하고 외부 호출을 다시 차단합니다. 설정 반영을 위한 리스너 중지/전환도 승인된 정비 범위 안에서 수행합니다. 타이머를 자동 활성화하지 않습니다. 복구 시 최신 DB/외부 결과를 보존하고 유닛·환경을 이전 보존본으로 복구하며, 과거 DB를 무조건 덮어쓰지 않습니다. 자세한 순서는 `PRODUCTION_CUTOVER_KO.md`를 따릅니다.

최종 오프라인 회귀 검증: **82개 통과 (77.741초)**. 모델 사전 차단·유료 기록 방지·Telegram 허용 목록·SDK 예외/로그 비밀값 차단을 포함합니다. 컴파일/공백 검사 및 알려진 실제 비밀값의 소스 혼입 검사도 통과했습니다.
