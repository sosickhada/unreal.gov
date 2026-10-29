# 운영 가이드

최신 운영 전환 기준은 [PRODUCTION_CUTOVER_KO.md](PRODUCTION_CUTOVER_KO.md)를 우선합니다. 1GB 서버 기준 렌더 상한은 180초, 종료 예산은 15초, 프로필은 `/tmp`, 기본 미리보기는 비공개 `RENDER_DIR`입니다. 이전 실행 기록의 기본값과 구분하세요.

## 현재 배포 경계와 기존 구성

개발 기준 브랜치는 `feat/full-automation-cloud`입니다. 시작 시 미커밋 파일은 `figma_renderer_before_fix.py`, `figma_renderer_before_fonts.py`, `renderer_original.py` 세 개였으며 보존했습니다. 운영 DB의 SQLite backup API 백업은 `data/backups/unreal_bot-20261029T003822Z.sqlite3`이고 무결성은 `ok`입니다. 백업은 권한 0600이며 Git에 포함하지 않습니다.

기존 서비스 설정은 다음과 같습니다. 실제 활성 상태는 샌드박스에서 systemd bus에 접근할 수 없어 미확인입니다.

- `unreal-telegram.service`: 프로젝트 가상환경으로 리스너 실행, `Restart=on-failure`.
- `unreal-images.service`: `/opt/unreal.gov/public`을 `127.0.0.1:8765`에 제공.
- Caddy: 공개 미디어 도메인을 위 이미지 서버로 프록시.
- 기존 Actions: UTC 09시 예약, 후보 생성·텍스트 전송만 수행. 뉴스 후보는 저장되지 않았고 리스너에는 고정 테스트 후보가 있었음.

이미지 서버·Caddy 설정은 수정하지 않았습니다. 서비스 설치/재시작도 하지 않았습니다. 기존 checkout을 직접 참조하는 서비스는 다음 실행/자식 프로세스 시작 때 수정된 파일을 읽을 수 있으므로, 승인된 전환 창에서 마이그레이션과 worker/리스너 전환을 함께 진행해야 합니다. 기존 리스너와 새 리스너를 같은 봇 토큰으로 동시에 polling하지 마세요.

## 데이터와 상태

마이그레이션은 `BEGIN IMMEDIATE` 트랜잭션에서 새 테이블과 컬럼만 추가합니다. 기존 `selections` ID, 원고, 이미지 URL, 승인 상태를 삭제/초기화하지 않습니다. 버전은 `schema_versions`에 기록합니다. `migrate`는 실행 직전에도 백업합니다.

```bash
# 운영 전환 승인 후: 외부 호출 없이 백업+스키마 추가
.venv/bin/python -m bureau.cli migrate
.venv/bin/python -m bureau.cli health
```

운영 DB에는 이번 개발 중 마이그레이션을 실행하지 않았습니다. 운영 DB 복제본에 적용한 보존 검증과 임시 DB 테스트를 사용합니다. 백업의 복원은 서비스를 중지한 정비 창에서만 수행하고, 자동으로 과거 DB를 덮어쓰지 마세요. 백업은 VM 밖의 접근 제한 저장소에도 복제하는 운영 정책이 필요합니다.

| 저장소 | 역할 |
|---|---|
| batches / candidates | 한국 날짜, 후보 재생성 회차, 기사 출처·생성일·내용·선택/거절 |
| selections | 기존 기록 및 현재 원고·버전·검토/승인 버전·게시 ID |
| jobs | idempotency key, queued/running/succeeded/failed/waiting/uncertain, 단계·오류 유형 |
| checkpoints | 단계별 원시 Claude 응답·토큰 사용량·렌더링 결과·Meta 컨테이너 ID |
| assets / image_inputs | 버전별 결과 이미지와 검토된 원본 사진의 출처·라이선스·해시 |
| outbox | 원고/앨범/심의/오류 메시지, 전송 상태와 Telegram message ID |
| publications | 캐러셀 자식·부모 컨테이너 및 실제 게시 ID |
| requests / events | 명령 중복 방지와 처리 이력 |

콘텐츠 흐름: `selected → draft_ready → preview_ready → approved → published`.
수정은 새 revision과 `revision_requested`를 만들고 기존 버전의 체크포인트/이미지를 유지합니다. 미설정 게시 단계는 `publish_waiting`, 거절은 `rejected`입니다. 작업 실패는 jobs에 따로 남기므로 콘텐츠 상태를 일괄 `failed`로 덮어쓰지 않습니다.

예전 승인 기록은 `approved_revision`과 `reviewed_revision`이 비어 있으므로 자동 게시 대상으로 간주하지 않습니다. 예전 제목만 있는 기록의 자동 원고 재생성은 출처가 없으면 `waiting`입니다. 새 후보 흐름을 사용하거나 관리자가 별도 출처 이관 절차를 설계해야 합니다.

## 환경 설정

`.env.example`을 기준으로 `/opt/unreal.gov/.env`에 필요한 키를 병합하세요. 기존 값을 출력하거나 덮어쓰지 마세요. 파일 소유자는 서비스 사용자, 권한은 0600을 권장합니다. systemd와 앱 양쪽에서 읽을 수 있도록 단순 `KEY=value` 또는 따옴표 문자열만 사용하며 셸 치환은 지원하지 않습니다. 실제 프로세스 환경변수가 파일보다 우선합니다.

- `ENABLE_EXTERNAL_CALLS=0`: 기본 외부 차단. worker는 작업을 선점하지 않으며 outbox도 전송하지 않습니다. 운영 승인 후에만 1.
- `AUTOMATION_PAUSED=1`: 예약 접수와 새 외부 작업/전송 중단. 이미 진행 중인 HTTP 요청을 취소하는 기능은 아님.
- Claude API 키와 실제 계정에서 사용 가능한 `CLAUDE_MODEL`을 명시. 기본 모델명을 추측하지 않습니다.
- Telegram 봇 토큰, 대상 chat ID, `TELEGRAM_ALLOWED_USER_IDS`(쉼표 구분). 그룹 chat과 사용자 ID는 별도로 검사.
- `PUBLIC_BASE_URL`, `IMAGE_DIR`: 기존 Caddy/이미지 경로와 일치.
- `REQUIRE_TOPIC_IMAGE=1`: 주제 사진 검토 등록 전 대기. 기존 승인 배경만 쓰는 운영 정책을 명시적으로 선택한 경우에만 0. 최종 판정·고정 엔딩·로고는 기존 디자인 유지.
- `MAX_CLAUDE_CALLS_PER_DAY=12`, `MAX_RESERVED_TOKENS_PER_DAY=360000`, `TOKENS_RESERVED_PER_CALL=30000`: 한국 날짜별 보수적 토큰 예약. 입력 UTF-8 바이트+최대 출력이 예약 한도를 넘으면 호출하지 않음. 실제 청구액 계산은 아님. 현재 가격·모델별 한도는 계정에서 별도 확인.
- 후보 재생성 기본 하루 2회, 게시물 수정 기본 3회. SDK 유료 호출 재시도 0. 실패/불명확 요청도 예산 기록에 남음.
- `UNREAL_BROWSER_PROFILE_DIR`: 기존 방식인 `/dev/shm`을 기본값으로 유지. 메모리 용량과 쓰기 권한 확인. 필요 시 검증한 다른 임시 경로 지정.
- `RENDER_TIMEOUT_SECONDS`: 기본 120초. 렌더링 자식 프로세스 그룹의 강제 종료 상한.

환경변수를 바꾸면 서비스에 반영하려면 승인된 재시작이 필요합니다. 장시간 실행 중 파일만 바꾸어 즉시 pause된다고 가정하지 마세요.

## 잠금·중복·재시도

SQLite는 로컬 영속 디스크를 사용합니다. 네트워크 공유 DB를 여러 VM에서 동시에 사용하지 않습니다. `BEGIN IMMEDIATE`, UNIQUE 실행키와 하나의 running 작업만 허용하는 부분 인덱스로 API 전에 작업을 선점합니다. 외부 호출 동안 DB 트랜잭션을 잡고 있지 않습니다. 하루 기본 후보 작업은 `candidates:한국날짜:0`, 원고/렌더/게시 작업은 게시물 ID와 revision을 실행키로 사용합니다. Telegram 명령 재전달도 후보 재생성·수정의 같은 update ID라면 작업을 늘리지 않습니다.

| 상황 | 정책 |
|---|---|
| RSS/공개 URL/컨테이너 준비 확인 실패 | failed, 관리자 `/retry JOB_ID`로 해당 단계부터 재개 |
| 사진 미등록, 일일 예산 초과, 게시 조건 미충족 | waiting, 조건 해결 후 명시적 재개 |
| Claude 응답 후 JSON 검증 실패 | 응답은 이미 저장됨. 재개가 같은 응답을 검증하며 추가 과금하지 않음. 새 유료 요청은 새 후보/원고 revision으로 명시 |
| Claude·Meta 쓰기 요청 타임아웃/프로세스 중단 | uncertain. 자동 재호출 금지 |
| Telegram 요청 실패/타임아웃 | uncertain. 실제 채팅 확인 후 `/resend DELIVERY_ID CONFIRM` |
| 프로세스가 running 상태로 중단 | 자동 잠금 만료 없음. 관리자가 worker가 멈췄음을 확인한 뒤 recover |

이 정책은 정확히 한 번의 외부 전달을 보장한다고 주장하지 않습니다. 응답이 유실된 쓰기는 서비스를 확인한 뒤 수동 조정해야 합니다. 결과를 모른 채 새 작업을 만드는 것은 중복 비용/게시 위험이 있습니다.

```bash
.venv/bin/python -m bureau.cli resume JOB_ID
# worker 중지 승인을 받아 실제 중지를 확인한 경우에만:
.venv/bin/python -m bureau.cli recover JOB_ID --worker-stopped
```

recover는 미완료 외부 쓰기를 uncertain, 안전한 로컬/읽기 단계를 failed로 남깁니다. paid uncertain에 대한 강제 reset 명령은 제공하지 않습니다. Instagram publish 결과가 불확실하면 공식 API/프로페셔널 대시보드에서 컨테이너·실제 게시물을 확인하고 게시 ID를 검증한 별도 DB 정비를 계획해야 합니다. 이 수동 조정은 운영 변경 승인을 받아 수행하며, 새 `/retry`로 우회하지 마세요.

## 뉴스·원고 검토

RSS는 최근 72시간, 최대 20개, 날짜·HTTPS URL·중복 링크를 검사합니다. 뉴스가 3개 미만이면 Claude를 호출하지 않습니다. 모델이 만든 출처 URL은 입력 목록에 실제 존재해야 하고 세 후보는 서로 다른 출처·사건명을 사용합니다. RSS 제목 이상의 사실관계는 자동 검증할 수 없으므로 원문 확인은 사람이 수행합니다.

원고 JSON 스키마, 문장 길이, 강조 문구, 출처 보존, 풍자/창작 표기를 검증합니다. 자동 모드에서 추가 사실 주장 `claims`는 빈 배열만 허용합니다. 이는 거짓 사실이나 비문을 완벽히 검출한다는 의미가 아닙니다. 승인 전 원문·문장·톤을 확인해야 합니다. 모델이 이미지 경로나 템플릿 코드를 지정할 수 없습니다.

## 이미지 수집과 렌더링

`/images ID empty Korean office desk`로 Pixabay 후보를 검색할 수 있습니다. 검색어는 편집자가 구체적인 사물/행동으로 지정합니다. 태그 기반 얼굴 관련어 제외는 **시각적 얼굴 검출이 아닙니다**. 검색 결과는 자동 승인되지 않습니다.

```bash
# 외부 호출 승인 및 ENABLE_EXTERNAL_CALLS=1 이후에만
.venv/bin/python -m bureau.cli image-search 'empty office desk'
.venv/bin/python -m bureau.cli download-image 'empty office desk' PHOTO_ID /tmp/selected.jpg
# 다른 합법적인 원본 소스도 수동 다운로드·권리 확인 후 동일하게 등록 가능
.venv/bin/python -m bureau.cli attach-image ID VERSION /tmp/selected.jpg \
  --source-url https://source.example/photo \
  --license-url https://source.example/license \
  --license '검토한 실제 이용허락 이름과 범위' --reviewer '담당자' \
  --faces-reviewed --relevance-reviewed
# /status에서 해당 render 작업 ID를 찾고 /retry JOB_ID
```

위 URL은 설명용이며 실제 출처/허락 문서로 대체해야 합니다. Pixabay 검색 결과에 반환된 다운로드 URL만 그대로 사용하고 CDN 주소를 추측해 변경하지 않습니다. 다운로드 원본의 4:5 크롭 후 해상도가 1080x1350 미만이면 거절합니다. 선명도 휴리스틱과 실제 이미지 포맷을 검사하되, 실사성·주제 관련성·라이선스의 적용 범위·얼굴/초상권은 편집자가 최종 검토합니다. 원본 파일은 정리 대상 `/tmp` 대신 영속적인 관리 디렉터리로 이동해서 등록하는 것이 운영 기본입니다. 파일 SHA-256이 변경되면 렌더링을 거절합니다.

모든 최초/재생성은 `figma_renderer.py` 하나를 사용합니다. 표지, 본문, 중간 판정, 기존 최종 판정 배경, 고정 엔딩·로고는 재사용합니다. 원본 4장 중 판정문을 분할해 결과 4~5장을 만듭니다. 더 긴 본문은 글꼴 축소로 숨기지 않고 오버플로 오류를 내며 수정 요청을 요구합니다. 한글 glyph cmap 및 브라우저 font load, 이미지 로드와 텍스트 프레임 검사를 수행합니다. Chromium의 HTTP/HTTPS 요청은 차단하며 로컬 asset만 로드합니다. 최종 해상도는 1080x1350입니다.

PNG는 원래 렌더링 결과로 보존하고 Instagram용 JPEG를 파생 생성합니다. 공개 HTTPS GET에서 상태/타입/크기/해상도/파일 해시/로컬 일치를 검사합니다. 리다이렉트는 거절합니다. 공개 URL 검증 실패가 Telegram 재전송이나 Claude 재호출을 유발하지 않습니다.

## Telegram 운영

- `/candidates`: 당일 최신 저장 후보. 선택 버튼은 DB 후보 ID 참조. 후보 묶음 거절 후 필요하면 `/newcandidates`.
- `/preview ID`: 저장된 원고와 이미지 재조회. 새 원고 생성 없음.
- `/images ID 검색어`: 사진 후보 검색.
- `/revise ID 수정내용`: 새 버전 원고 요청. 게시 승인된 내용은 수정하지 않음.
- `/review ID VERSION`: 출처·사실과 창작 구분·문장·주제 관련성·이미지 라이선스·얼굴 노출 검토 확인.
- 게시 승인/거절/재생성 버튼: 해당 revision에만 적용. 승인은 Instagram 서버 허용 설정과 별개.
- `/status`: 작업 ID, 단계, 오류 코드, 콘텐츠 버전, 확인이 필요한 전송 ID.
- `/retry JOB_ID`, `/resend DELIVERY_ID CONFIRM`: 저장 결과 기반 복구. 유료 불명확 요청은 재시도 불가.

리스너는 수신과 DB 기록만 담당하며 느린 Claude/Chromium/사진 HTTP는 worker에서 실행합니다. 아웃박스에서 원고·앨범·심의 메시지를 각각 기록합니다. polling 시작 시 pending updates를 버리지 않습니다. 사용자 ID allowlist와 대상 chat을 모두 검사합니다.

## Instagram 공식 API

지원 범위는 **Facebook Login으로 연결된 Page + Instagram Professional 계정**입니다. Instagram Login 방식의 다른 권한 이름과 혼용하지 않습니다. 공식 안내는 [Meta 콘텐츠 게시 문서](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/content-publishing/), [Meta 제공 API 컬렉션](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)을 참고하세요. 개발 중 Meta 개발자 문서 본문은 접근 제한이 있어 실제 계정과 현재 지원 버전에서의 호환성 검증이 남아 있습니다.

기본 `INSTAGRAM_PUBLISH_ENABLED=0`입니다. 다음 모두를 준비한 뒤 별도 게시 승인을 받아야 합니다.

1. Meta 앱, 현재 지원 Graph 버전, 앱 모드/검수·계정 역할, 필요한 비즈니스 설정.
2. Page와 Professional 계정 연결, Page/IG 계정 ID.
3. 게시용 access token, token debug용 app access token, 앱 ID. 유효기간과 회전 정책.
4. `instagram_basic`, `instagram_content_publish`, `pages_read_engagement` 등 해당 계정/앱 구성에 필요한 권한. 계정 구성에 추가 권한이 필요할 수 있음.
5. Meta가 실제로 내려받을 수 있는 공개 HTTPS JPEG 이미지.

모듈은 토큰 유효성/앱 ID/권한·만료, Page 연결, Professional 계정, 게시 쿼터를 API로 확인합니다. 계정의 실제 게시 가능 여부는 최종 공식 API 응답이 결정합니다. 이 확인은 임의의 모든 앱 심사 조건을 자동 증명하지 않습니다.

게시물의 검토·승인 버전과 현재 버전이 모두 같아야 게시합니다. 자식 컨테이너·캐러셀 부모를 저장하고 `FINISHED` 상태를 확인한 뒤 `media_publish`를 호출합니다. 아직 준비되지 않았으면 관리자 재개 시 저장된 컨테이너를 재사용합니다. 게시 응답을 저장한 경우 같은 작업 재실행은 게시하지 않습니다. 쓰기 응답이 불명확하면 자동 게시를 중단합니다.

## systemd 및 Actions 전환

**아래 단계의 서비스 변경·실전 API 검증·GitHub 예약 해제는 아직 실행하지 않았고 별도 승인이 필요합니다.** 템플릿 사용자와 디렉터리 권한을 실제 VM에 맞게 검토하세요.

1. 백업·의존성·현재 서비스 상태와 시간 동기화 확인. 외부 키를 출력하지 않음.
2. 운영 정비 창에서 DB migrate, 안전한 환경 설정 병합. 최초에는 외부 호출과 Instagram 게시 모두 비활성.
3. 기존 GitHub Actions 예약 workflow를 GitHub에서 비활성화하거나 승인된 커밋에서 schedule 제거. 저장소 파일만 바꿔도 원격 예약이 즉시 바뀌는 것은 아님.
4. `deploy/`의 worker·리스너 서비스와 candidates service/timer를 설치. 기존 이미지 서버·Caddy 유지. 승인받은 daemon-reload/서비스 전환 수행.
5. 승인된 최소 뉴스·Claude·Telegram 실전 검증. Instagram은 계속 비활성.
6. 중복 예약 제거와 상태 점검 확인 후 timer 활성화. 공식 게시 설정 검증과 별도 게시 승인 후 Instagram 허용.

`OnCalendar=*-*-* 18:00:00 Asia/Seoul`, `AccuracySec=1s`, `RandomizedDelaySec=0`, `Persistent=false`입니다. 서버 timezone이 UTC여도 명시한 한국 시간으로 동작합니다. NTP/chrony 동기화는 `timedatectl` 또는 `chronyc tracking`으로 운영자가 확인합니다. 설정 해석은 `systemd-analyze calendar '*-*-* 18:00:00 Asia/Seoul'`로 확인했습니다. VM 다운으로 놓친 날짜는 건너뛰며, 큐에 남은 과거 날짜 후보 작업도 유료 호출 전에 waiting 처리합니다. 기동/부하/네트워크 때문에 정확히 18:00:00에 전송 완료된다는 보장은 없습니다.

기존 `run_bot.yml`에는 원격 반영 후 실행을 차단하는 gate와 실패 경로를 준비했지만 schedule 항목은 승인 전 제거하지 않았습니다. 수동 작업은 `manual_vm.yml`의 전용 VM self-hosted runner에서 같은 DB에 접수합니다. runner 설치·등록·권한 설정은 별도 작업입니다. 공용/비신뢰 PR을 이 runner에서 실행하지 마세요. 일반 GitHub-hosted runner의 별도 SQLite로 API를 호출하는 경로는 지원하지 않습니다.

## 보안·자원·모니터링

worker는 한 번에 작업 1개, 기본 2GB 메모리 한도·태스크 128개 템플릿을 제공합니다. Chromium은 필요할 때 자식 프로세스로 시작하고 120초 상한을 적용합니다. VM RAM과 실제 폰트/Chromium 렌더 시간은 실측 후 조정하세요. DB 트랜잭션은 짧게 유지하며 busy timeout 10초를 사용합니다.

서비스 사용자를 root로 실행하지 않습니다. 파일은 기본 umask 0077, 읽기 전용 시스템·제한된 쓰기 경로를 사용합니다. Chromium의 기존 `--no-sandbox` 옵션이 남아 있으므로 비신뢰 원격 HTML을 로드하지 않고 로컬 템플릿만 사용합니다. 별도 OS sandbox 정책 강화는 실제 VM에서 검증이 필요합니다. Caddy 공개 루트에는 이미지 외 민감 파일·DB를 넣지 않습니다.

API 예외 문자열·HTTP 요청 객체·인증 URL은 로그/Telegram에 내보내지 않습니다. DB에는 오류 유형과 단계만 남깁니다. 내부 이벤트·뉴스·원고·출처는 업무 데이터이므로 백업도 접근 제한합니다. 인증 값은 로그·Git·이슈에 붙이지 마세요.

`health`는 읽기 전용 DB 무결성/스키마/작업·전송 상태 집계를 출력합니다. 운영 모니터링은 마지막 당일 후보 생성, 오래된 running/sending, uncertain 증가, outbox 적체, 디스크/메모리·백업 성공, 인증 만료를 대상으로 구성하세요. 현재 별도 외부 모니터링 서비스는 연결하지 않았습니다. Telegram 자체가 불통이면 Telegram 실패 알림도 도착하지 않으므로 독립 모니터링이 필요합니다.

## 동적 사진 입력 전환 (2026-10-29 추가)

기존의 단일 `image_inputs` 사진은 본문과 중간 결의에 같은 파일을 넣었습니다. 이제 payload는 `photos.content`, `photos.resolution_extra` 두 슬롯을 저장합니다. 예전 단일 입력은 본문 슬롯으로만 해석하며, 두 번째 검토 사진이 없으면 기다립니다. 표지와 최종 결의는 렌더러에서 기존 배경을 사용하고 고정 엔딩도 유지합니다. 4장 원고에는 중간 결의가 없지만 운영 사진 입력은 두 장을 요구해 재구성 때도 같은 정책을 유지합니다.

스키마 추가 대상은 `image_library` 하나입니다. 운영 DB에 직접 적용하지 않았습니다. 전환 승인 후 기존 `migrate` 명령으로 백업과 추가 마이그레이션을 수행합니다.

검토 완료 사진을 주제 태그와 함께 등록하면 worker가 원고의 `image_queries`와 일치하는 서로 다른 두 사진을 선택합니다. 각 검색어의 모든 단어가 태그에 포함되어야 하며 파일 해시·원본 크롭 해상도·검토 이력을 다시 검사합니다. 태그 매칭은 의미·얼굴·AI 탐지 기능이 아닙니다. 실사성, 뚜렷한 얼굴이 없음, 이용 권리와 주제 적합성은 담당자가 확인하고 최종 미리보기에서도 재검토합니다. 단지 사진 파일이라는 이유로 검토 플래그를 체크하지 마세요.

```bash
# 아래 source/license URL은 설명용. 실제 확인한 출처로 대체.
.venv/bin/python -m bureau.cli register-photo /영속경로/desk.jpg \
  --tags 'empty office desk' --source-url https://source.example/photo \
  --license-url https://source.example/license --license '확인한 이용허락' \
  --reviewer '담당자' --faces-reviewed --relevance-reviewed --photograph-reviewed

# 개별 원고에 지정하는 경우 두 슬롯 각각 등록. 동일 사진 재사용은 거절.
.venv/bin/python -m bureau.cli attach-image ID VERSION /영속경로/desk.jpg \
  --slot content --source-url https://source.example/photo \
  --license-url https://source.example/license --license '확인한 이용허락' \
  --reviewer '담당자' --faces-reviewed --relevance-reviewed --photograph-reviewed
# 다른 사진을 --slot resolution_extra 로 등록한 뒤 해당 render 작업 /retry.
```

위쪽의 과거 attach-image 예시에도 이제 `--slot`과 `--photograph-reviewed`가 필요합니다. 기존 원고에 `image_queries`가 없다면 직접 두 슬롯을 등록하세요. 사진 등록은 유료 원고 재생성을 요구하지 않습니다. 결과 이미지가 이미 있는 버전과 실행 중인 render 입력은 수정할 수 없습니다.

`AUTO_IMAGE_SEARCH=1`을 운영 승인 후 설정하면 사진이 부족할 때 슬롯별 Pixabay 검색 작업을 중복 없이 접수합니다. 기본값은 0입니다. 검색은 후보 링크를 검토용으로 제시하며 자동 승인을 하지 않습니다. 반환된 원본/Full HD URL을 우선하고 없으면 반환된 large URL만 사용합니다. 다운로드 후 최소 해상도에 못 미치면 거절하며 URL을 추측하거나 확대하지 않습니다. 검색/다운로드 실패·후보 없음·사진 부족은 수동 검토로 남깁니다. 사진 실패를 Claude 재호출이나 기본 Figma 배경으로 우회하지 않습니다 (`REQUIRE_TOPIC_IMAGE=1` 유지).

동일 기사 URL이 다른 날짜/재생성 후보에 다시 등장해도 기존 selection을 반환하여 새 원고 작업을 만들지 않습니다. 서로 다른 URL로 재배포된 동일 기사까지 의미적으로 탐지하는 기능은 없으므로 편집 단계 확인이 필요합니다.

### 전환 전 확인 및 순서

- `/etc/systemd/system/unreal-images.service`는 `/opt/unreal.gov/public`의 정적 HTTP 서버이며 Caddy가 `/images/*`를 프록시합니다. 새 렌더링 파일도 같은 이미지 루트에 저장하므로 이미지 서버/Caddy 재시작이 필요하지 않습니다. 서비스 설정은 변경하지 않았습니다.
- 리스너와 worker는 운영 DB 백업·마이그레이션·환경 병합 후 승인된 정비 창에서 전환합니다. 먼저 기존 polling 프로세스를 중지하고 하나의 새 리스너만 시작해야 합니다. 실행 중인 유료 요청과 outbox `sending`/`uncertain`을 먼저 확인하고 자동 초기화하지 않습니다.
- 타이머를 켜기 전에 원격 GitHub의 기존 예약 비활성화를 확인합니다. 로컬 파일만으로 원격 상태를 증명할 수 없습니다. GitHub-hosted workflow는 API 실행 대신 실패하도록 준비되어 있고 수동 workflow는 VM의 같은 SQLite에 접수합니다. 원격 변경·push·timer 활성화는 별도 승인 대상입니다.
- `systemd-analyze calendar`는 18:00 Asia/Seoul을 UTC 09:00으로 해석했습니다. `systemd-analyze verify`는 템플릿 오류 없이 종료했지만 system bus 접근 제한 및 기존 시스템 유닛 경고가 있으므로 실제 시작 검증은 미완료입니다.
- Instagram 코드 구현 점검만 수행했습니다. 환경에는 키 이름의 존재 여부만 확인하며 값을 출력하지 않습니다. 공식 계정의 실제 Graph 버전/권한/토큰/페이지 연결/쿼터 검증과 컨테이너 생성·게시 테스트는 승인 후 수행합니다. 현재 구현 설명은 계정 연결 성공을 뜻하지 않습니다.

로컬 재현: `.venv/bin/python -m unittest discover -s tests -v` 및 `timeout --kill-after=5s 240s .venv/bin/python tests/offline_acceptance.py`. 후자는 기존 `output/render-smoke/acceptance/case-5_*.png` 기준 이미지가 필요하며, 실제 Chromium과 **합성 테스트 패턴**을 사용합니다. 합성 패턴은 운영용 실사 사진 검증을 대체하지 않습니다. 외부 소켓은 차단하고 Claude/Telegram/Meta와 공개 JPEG GET을 모의 처리합니다. 새 테스트 출력은 공개 디렉터리에 복사하지 않습니다.

Chromium은 검증된 마지막 PNG 저장 직후 완료 manifest를 원자적으로 기록합니다. 모든 페이지가 완료된 manifest가 있을 때만 종료 실패/시간 초과 뒤 프로세스 정리 후 해당 출력을 재사용합니다. 완료 기록이 없는 부분 결과는 실패로 남습니다. PNG 포맷/해상도 및 파생 JPEG의 8MB 상한도 검사합니다. 이 변경은 종료 오류를 무시하고 임의의 이전 파일을 채택하는 기능이 아닙니다. manifest는 작업마다 새 임시 디렉터리에 생성합니다.
