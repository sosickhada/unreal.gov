# Telegram 콘텐츠 제작 파이프라인 점검 결과

점검일: 2026-10-30. 브랜치: `feat/full-automation-cloud`.
운영 서비스 재시작, 운영 DB migration/초기화, 환경파일 변경, 예약 작업 변경, 생성/게시 API 호출, commit/push를 수행하지 않았다. 공개 모델 문서만 조회했다. 테스트 DB와 렌더링 결과는 별도 경로를 사용한다.

## 1. 기존 시스템 구조

- `bot.py` / `bureau.cli schedule`: 한국 날짜별 후보 작업 접수.
- `bureau/store.py`: SQLite 트랜잭션, candidates/batches/selections, revision, jobs, checkpoints, outbox, publications, events, request idempotency.
- `bureau/engine.py`: 후보 → 기획 → 이미지 → 게시 작업과 Telegram outbox 전달.
- `bureau/telegram_app.py`: python-telegram-bot polling, chat ID + user ID allowlist, callback/명령 처리.
- `bureau/adapters.py`, `images.py`, `instagram.py`: Claude, 기존 Figma 기반 로컬 렌더러, 검토 사진 라이브러리, Telegram, 공식 Meta Graph API.
- `deploy/`: VM listener/worker/media 서비스와 18:00 Asia/Seoul timer 배포 후보. `.github/workflows/`에는 과거 cloud cron과 VM 수동 접수 경로가 있다.

기존 체크포인트와 unknown-write 보호를 재사용했다. 외부 쓰기 결과가 불확실하면 무조건 재호출하지 않는다. 중단 작업의 재개는 기존 recover/resume 도구를 사용한다.

## 2. 확인된 문제의 원인

### 콘텐츠

기존 `validate_candidates`는 서로 다른 실제 RSS URL 3개를 강제했고, engine은 뉴스가 3개 미만이면 실패했다. 프롬프트도 서로 다른 기사 3개를 요구했다. 따라서 일상의 공감보다 기사 수와 출처 다양성이 우선했다. 기획 품질 경고가 없으면 곧바로 render 작업을 접수해 별도 기획 승인 단계가 없었다.

### 예약 발송: 확인한 증거와 한계

읽기 전용 systemd 조회 결과:

- `unreal-telegram.service`: active/running, NRestarts=0.
- `unreal-worker.service`: inactive/dead.
- `unreal-candidates.timer`: inactive/dead. 설치된 timer/service unit을 찾지 못했다.
- 후보 timer/service journal: 조회 기간 2026-10-27 이후 기록 없음.
- `/etc/systemd/system/unreal-telegram.service`는 VM에서 `telegram_listener.py`를 실행하며 별도 timer를 포함하지 않는다.
- 운영 SQLite를 `mode=ro`로 열어 확인한 테이블은 `selections`, `sqlite_sequence`뿐이다. 새 batches/jobs/outbox/events 감사 기록은 아직 운영 DB에 없다. 선택 시각은 2026-10-24 14:50:22, 2026-10-25 01:11:22, 01:27:05이나, 과거 naive timestamp이며 후보 발송 시각의 증거가 아니다.
- 리스너 journal의 sendMessage 관련 기록 7건은 2026-10-25 00:59:05–01:27:28 UTC 범위다. 요청/응답 원문과 인증정보는 출력하지 않았다. 이 기록은 요청한 **00:56 KST 발송을 입증하지 못한다**.
- 로컬 `.github/workflows/run_bot.yml`의 cron은 `0 9 * * *`, 즉 18:00 KST다. 현재 파일은 legacy gate 및 실행 거절 코드가 있지만 원격 반영 여부를 증명하지 못한다.
- `systemd-analyze calendar '*-*-* 18:00:00 Asia/Seoul'`는 09:00 UTC로 정상 해석했다.

**00:56의 정확한 발생 경로는 미확정이다.** GitHub API 호출이 허용되지 않아 원격 실행 목록·트리거·실행 commit·로그를 새로 조회하지 않았다. 과거 운영 문서의 원격 workflow 상태를 현재 상태로 단정하지 않았다. 당시 실행 날짜와 Telegram 메시지 시각을 GitHub `event=schedule/workflow_dispatch`, `created_at/run_started_at`, 실행 SHA 및 bot 단계 로그와 대조해야 한다. 수동 실행, Actions 지연, 별도 과거 코드 실행을 현재 증거만으로 구분할 수 없다. timezone 오류로 확정하지 않는다.

## 3. 수정한 파일

- `bureau/content.py`: 뉴스 선택 사항화, 7개 필드 후보, 검토 소재 9개, 품질 rubric, 선택 출처 validation, 프롬프트.
- `bureau/store.py`: schema v4 additive migration, 기획 승인 상태, conversations, 자연어 수정 CAS/멱등성, 반환, 최종 검토 확인, 예약 감사 정보.
- `bureau/engine.py`: 후보 fallback, 기획 승인 대기, 이전 기획 문맥, 게시 URL 조회 및 재개, 발송 만료/감사 기록.
- `bureau/telegram_app.py`: 버튼, 자연어 수정, 입력 취소, `/whoami`, 민감한 인수의 예외 출력 차단.
- `bureau/telegram_identity.py`: 공식 Telegram 로컬 계정 JSON에서 본인 ID만 추출.
- `bureau/instagram.py`: 공식 permalink/timestamp 조회.
- `bureau/operations.py`: v4 schema 준비 상태 검사.
- `bureau/claude_models.json`: 공개 문서 재확인 날짜 갱신. 기존 카탈로그 전체를 새로 검증했다고 주장하지 않는다.
- `bot.py`: 예약 진입점은 KST 18:00–18:04만 접수, 접수 경로 기록. 운영자의 명시적 수동 CLI 접수는 별도다.
- `.env.example`: curated/model 모드와 뉴스 참고 opt-in.
- `tests/test_system.py`, `test_production.py`, `test_preflight.py`, `test_topic_images.py`, `offline_acceptance.py`: 명시적 기획 승인 흐름 반영.
- `tests/test_telegram_pipeline.py`: 신규 mock 통합/보호 검증.
- 이 결과 문서.

스케줄 정의 파일과 설치된 운영 unit은 변경하지 않았다. 기존 사용자 미추적 renderer 백업 파일도 수정하지 않았다.

## 4. 구현한 기능

### 후보

기본 `CANDIDATE_GENERATION_MODE=curated`는 검토된 소재 9개를 날짜별 회전해 독립된 후보 3개를 저장한다. 원래 묶음과 허용된 2회 재생성까지 하루 9개 상황이 겹치지 않는다. RSS/Claude 후보 API 없이 작동한다. 무한히 새로운 소재를 만들어내는 기능은 아니므로 소재 은행은 운영 중 확장해야 한다.

`CANDIDATE_GENERATION_MODE=model`이면 기존 Claude adapter로 3개를 작성한다. 잘못된 응답, 누락 모델/예산, 응답 불확실성에는 유료 재호출 없이 검토 소재로 대체한다. 불확실한 유료 checkpoint는 그대로 남아 일일 한도에 포함된다. 성공한 후보 작업을 다시 유료 실행하지 않는다.

`USE_NEWS_REFERENCE=1`에서만 RSS를 조회한다. 관련 일상 키워드와 위험 주제를 보수적으로 필터링한다. 모델이 뉴스를 쓸 때는 입력 URL과 직접적인 연결 근거를 요구한다. 뉴스 없이 source_url=null이 가능하며 허구/풍자 표시와 추가 factual claims 금지는 유지한다.

후보별 사건명, 실제 겪을 법한 가상 상황, 공감 포인트, 훅, 판정 방향, 공유 이유, situation_key를 저장한다. 구체적 상황/공감/행정적 웃음/공유 이유/짧은 훅의 5항목 점수는 **필드 충족 여부의 구조 검사**다. 100점이 재미·안전·실제 공감을 보장하지 않는다. 실명 공격, 취약계층 비하, 상황의 현실성, 뉴스 연결 자연스러움은 운영자의 필수 편집 검토 항목이다. 정교한 의미/유사성 판별 모델을 추가 호출하지 않는다.

편집자의 내부 품질 심의 기준은 아래와 같다. 각 항목을 0–4점으로 평가하며 **16/20 이상, 각 항목 2점 이상**을 채택 기준으로 제안한다. 자동 구조 점수와 별개이며 현재 구현은 이 의미 심의를 자동 판정하지 않는다.

| 항목 | 0점 기준 | 4점 기준 |
|---|---|---|
| 일상 구체성 | 추상적 사회 문제나 뉴스 논평 | 장소·행동·불편이 한 장면으로 보임 |
| 즉각 공감 | 배경 설명이 길어야 이해됨 | 상황 한 문장만으로 경험이 떠오름 |
| 사소한 억울함 | 중대한 범죄·재난이나 피해 조롱 | 당사자 공격 없이 작은 불편과 감정이 명확함 |
| 행정적 웃음 | 일반 훈계 또는 억지 법률 연결 | 작고 구체적인 불편에 과도하게 진지한 처분이 맞물림 |
| 훅·공유성 | 사건명 반복 또는 누구에게 보낼지 불명확 | 짧은 첫 장 훅과 특정 경험을 공유한 수신자가 떠오름 |

안전성은 점수로 상쇄할 수 없는 gate다. 실명 공격·취약계층 비하·실제 피해 왜곡이면 제외한다. 세 후보의 인물/행동/불편이 같은 사건의 말바꾸기이면 묶음을 재검토한다. 뉴스 연결을 설명하려고 사건을 억지로 변형해야 하면 출처를 제거하고 독립적인 창작으로 심의한다.

### 승인과 수정

`후보 선택 → planning_review(또는 draft_review) → 기획 승인 → draft_ready → 렌더 → preview_ready → 최종 승인 → 게시`

- 후보별 선택, 묶음별 다시 생성, 기획 승인/수정/후보 돌아가기, 이미지 수정/기획 수정/취소 버튼.
- 자연어 기획 수정은 직전 기획과 함께 기존 Claude 기획 프롬프트로 처리한다. 다시 기획 승인을 받아야 렌더링한다.
- 이미지 수정은 승인한 문구를 유지하고 새 revision에서 사진 소재 요청을 저장한다. 자연어를 사진 태그/검색 요청으로 사용하며 실제 사진의 등록·관련성·라이선스·얼굴 검토는 기존 라이브러리 절차를 따른다. 레이아웃·색상·픽셀 보정이나 임의 이미지 생성 기능은 아니다. 사진이 없으면 안전하게 waiting 상태에 머문다.
- conversations에 user ID, selection ID, revision, 수정 종류를 저장한다. 업데이트 재전달·동시 수정·이미 승인한 버전의 후속 텍스트를 차단한다.
- 최종 승인 버튼은 해당 버전의 이미지/문구/권리 검토 확인과 게시 요청을 함께 기록한다. 기존 `/review` 명령도 유지한다.
- 게시 성공 상태/ID와 UTC 확인 시각을 보낸 뒤 공식 permalink를 조회해 전달한다. URL 조회가 실패해도 published 상태를 유지하며 `/retry`는 URL 조회만 재개한다. 게시 호출은 반복하지 않는다.
- 게시 실패에는 안전한 오류 분류와 재개 가능 여부를 표시한다. uncertain은 실제 게시 여부 확인 전 재시도 불가다.

### 예약과 ID 확인

VM timer를 유일한 정기 접수 경로로 사용할 배포안을 유지했다. Asia/Seoul 지정, 지연 랜덤 없음, Persistent=false다. 날짜+generation unique key가 동일 DB의 중복 접수를 막는다. 예약 진입점의 시간창 검사와 예약 후보 outbox의 18:05 KST 만료는 밤늦은 catch-up 전송을 차단한다. manual/Telegram 재생성은 의도적 요청이므로 이 시간창과 구분한다. DB events에 `scheduled` source/day/timezone과 `delivery_sent/uncertain/expired` 시각을 기록한다.

`/whoami`는 같은 polling 리스너에서만 처리하며 설정된 private chat에서 본인 ID만 응답한다. allowlist가 없는 초기 설치에서는 listener가 시작되지 않으므로 이 명령으로 우회하지 않는다. 초기 ID는 공식 Telegram Desktop 계정 정보 JSON을 본인 컴퓨터에 내보낸 뒤 다음 로컬 추출기를 사용한다:

```bash
.venv/bin/python -m bureau.telegram_identity /path/to/account-export/result.json
```

출력은 본인 ID 숫자뿐이다. 전체 export를 서버/채팅으로 전송하지 않는다. `getUpdates`를 새로 호출하지 않는다.

## 5. 테스트 결과

- 전체 `unittest discover`: **99개 통과**, 170.057초. 네트워크 연결 금지 guard와 mock provider, 격리 SQLite 사용.
- 신규 12개 통합 검증: 후보 버튼, 기획 승인 전 렌더 금지, 자연어 기획 수정/중복 업데이트, 앱 재구성 후 대기 복구, 이미지 수정과 문구 보존, 최종 승인/중복 클릭, 취소/allowlist, 만료 버전, 후보 반환/묶음 재생성, 뉴스/모델 없는 후보 3개와 rubric, 부적절 뉴스/동일 상황 거절, KST 예약 시간창/감사 기록, 로컬 ID 추출 보호, 게시 URL 조회 실패 후 재게시 방지, 모델 timeout fallback/재과금 방지, 만료 예약 전송 금지, 3개 묶음 간 상황 다양성. 여러 항목을 한 통합 사례에서 검증한다.
- 기존 회귀 검증: 동시 예약/claim/선택/승인, 추가 migration의 기존 DB 보존, 게시 실패/불확실성, 체크포인트 재개, 일일 예산/중지, 이미지 hash/검토/출처 보호, SDK 설정 검증과 비밀값 마스킹.
- Python 컴파일과 `git diff --check` 통과.
- 실제 Chromium offline acceptance: **PASS**. 첫 샌드박스 실행과 전체 테스트 병행 중 권한 확장 실행은 첫 페이지 탐색 제한으로 실패했으나, 전체 테스트 종료 후 단독 실행은 정상 완료했다. 원인을 샌드박스만으로 단정하지 않는다. 기존 renderer는 변경하지 않았다. 고정 15초 탐색 제한의 실행 환경 부하 민감성은 운영 위험으로 남긴다.
- 렌더 결과: 1080×1350 PNG 5장 + JPEG 5장, hash·크기 검증. 기존 기준 이미지 대비 1/4/5장은 byte 동일, 검토 사진을 바꾼 2/3장은 변경 확인. Claude mock 2회, Telegram mock 4회, 실제 게시 0회, publish_waiting 확인. 합성 사진은 오프라인 검증용이며 운영 사진 라이브러리에 등록하지 않았다.
- 렌더 증거: `output/offline-acceptance/2026-10-30T13-26-33.046164+00-00/report.json`.
- 실제 유료 생성, Telegram API 호출/메시지 전송, Instagram 게시는 **0회**. 공개 문서 웹 조회와 읽기 전용 호스트/DB 조회만 수행했다.

## 6. 실제 운영 전 필요한 설정

- `CLAUDE_MODEL=claude-haiku-5-5` 추천: 공식 [모델 개요](https://platform.claude.com/docs/en/models/overview), [Haiku 5.5](https://platform.claude.com/docs/en/models/haiku-5-5/overview)에서 유효한 Claude API ID와 Active 상태를 확인했다. 100k 토큰 이하 prompt의 표준 단가는 입력 $0.10/MTok, 출력 $0.50/MTok다. 현재 서비스처럼 짧은 기획에 비용 효율적인 시범 선택이다. 한국어 풍자 품질은 mock으로 검증할 수 없어 별도 승인된 시범으로 평가해야 한다. 공식 문서 지원은 해당 API 키의 계정 접근·잔액·쿼터 검증이 아니다.
- `TELEGRAM_ALLOWED_USER_IDS`: 각 운영자의 본인 숫자 ID를 별도로 확인해 설정. chat ID를 무조건 복사하지 않는다.
- `CANDIDATE_GENERATION_MODE=curated`, `USE_NEWS_REFERENCE=0` 권장 시작값. 기획 생성 시에는 Claude 설정이 필요하다.
- 기존 `UNREAL_DB`, private `RENDER_DIR`, `IMAGE_DIR`, `PUBLIC_BASE_URL`, 권리 검토된 서로 다른 사진 2장/기획, 기존 렌더러 폰트·Chromium.
- API/전송 운영 승인 후에만 `ENABLE_EXTERNAL_CALLS=1`. 유료 모델 조회/생성 승인은 이번 작업에 포함되지 않았다.
- 실제 게시 승인과 별도로 Meta 계정/권한/토큰/Graph version, `ENABLE_PUBLIC_MEDIA=1`, `INSTAGRAM_PUBLISH_ENABLED=1` 운영 허가 필요. 준비 중에는 둘 다 0을 유지한다.
- 일일 유료 호출·토큰·재생성·수정 한도는 기존 설정을 유지한다.

## 7. 배포 절차 (미실행, 사용자 승인 필요)

1. 이 diff와 테스트 결과 검토. 명시적 승인 후 배포할 SHA를 확정하고 commit/push한다.
2. 운영 SQLite를 기존 backup 도구로 0600 백업하고 백업 복사본에 v4 migration을 검증한다. 운영자 ID·모델·private render 경로 등 doctor 조건을 준비한다. 환경값 자체는 출력하지 않는다.
3. 새 코드와 같은 배포 경로의 충돌 없는 테스트 환경에서 worker/listener 기동, mock 후보/콜백/기획 승인/복구와 timer calendar/시간창을 검증한다. 기존 listener와 같은 토큰으로 두 polling consumer를 동시에 실행하지 않는다.
4. 원격 GitHub 실행 이력과 cron을 확인한다. 기존 정기 경로를 끄기 전에 새 timer unit 정적 검증 및 같은 VM 테스트 DB를 이용한 오프라인 예약 경로 검증을 완료한다. 예약 unit 검증은 실제 후보 API 호출을 포함하지 않는다.
5. 승인된 전환 창에 기존 listener를 정상 종료하고 필요한 운영 migration·unit 설치·daemon-reload·서비스 교체를 수행한다. 실행 중인 작업/전송은 기존 recover 절차로 분류하며 불확실한 쓰기를 재큐잉하지 않는다.
6. 새 경로가 검증된 뒤 원격 legacy 정기 workflow를 비활성화하고 확인한다. 같은 DB를 쓰는 VM timer **하나만** 정기 실행으로 활성화한다. GitHub-hosted runner에서 별도 SQLite를 만드는 발송 경로는 사용하지 않는다. 수동 VM workflow는 같은 DB의 명시적 작업 접수로만 유지한다.
7. 별도 사용자 승인을 받은 제한된 실제 후보/기획/Telegram 시범을 수행한다. 실제 Instagram 게시는 이번 검증에서 제외하며 별도 승인·최종 버튼을 모두 충족할 때만 진행한다.
8. 18:00 KST에 timer 발화, worker 처리, outbox sent 시각을 events/journal과 대조한다. 18:05까지 미발송/expired면 경고 및 원인 조사. 서비스 시간 동기화와 운영 모니터링도 확인한다.

GitHub Actions 정시 cron에는 큐 지연 가능성이 있으므로 정시 전달은 VM timer를 우선한다. VM timer도 네트워크·Telegram 지연을 제거하지 않으며 정확히 18:00:00 수신을 보장하지 않는다. 현재는 예약 **접수** 18:00이고 실제 전송은 worker 처리 뒤다.

## 8. 남은 위험 요소

- 과거 00:56 발송 원인은 당시 원격 실행 증거가 없어 미확정.
- 운영에는 아직 schema v4 및 새 서비스가 반영되지 않았다. 이번 작업은 검토 가능한 코드와 오프라인 결과까지다.
- 유료 모델과 Telegram/Meta 인증·게시 URL·실제 수신 시각은 mock 통과만으로 검증되지 않는다.
- 소재 은행은 9개로 유한하며 여러 날 반복될 수 있다. 편집자가 확대하거나 승인 후 model 모드를 사용해야 한다.
- rubric과 문자열 유사도/안전 키워드는 의미 품질 및 모든 공격성을 자동 검증하지 못한다. 사람의 검토는 필수다.
- 이미지 수정은 사진 소재 요청과 재렌더링 범위다. 새 사진이 없거나 태그가 맞지 않으면 관리자 사진 등록이 필요하다.
- 이미지 공개 URL과 권리는 운영 환경에서 별도 검증 필요. 승인된 문구와 사진 byte hash 보호는 유지한다.
- Chromium 첫 페이지의 15초 탐색 제한은 이번 검증에서 부하에 민감했다. 단독 렌더 성공이 VM의 모든 부하 상황에서 성공을 보장하지 않는다. 운영 CPU/메모리와 실패율을 확인해야 한다.
- 워커 중단 시 running 상태는 DB에 남는다. 외부 쓰기를 안전/불확실로 분류하는 운영자 recover가 필요하다. 무조건 자동 복구하면 이중 과금/게시가 발생할 수 있어 자동 재호출하지 않는다.
- Telegram 전송 응답 유실은 정확히 한 번 전달을 보장할 수 없다. uncertain 상태로 보류하고 실제 채팅 확인 후에만 명시적 resend한다.
