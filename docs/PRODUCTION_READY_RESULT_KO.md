# 운영 직전 개발·검증 결과 (2026-10-29)

**판정: 개발 및 오프라인 수용 검증 완료. 운영 환경 적용·실계정 연결·실사 검토·최소 전환 승인 전까지 운영 시작 보류.** 실제 서비스 전환이나 실계정 연결 성공을 주장하지 않습니다.

## 1. 구현·수정 기능

- Google News RSS: 최근 날짜 검증, 2MB 응답 제한, 연결/읽기/단계 시간 상한, 최대 3개 주제 검색. 중복·유사 기사 제거를 수집 한도 전에 수행해 재배포 기사가 서로 다른 기사를 밀어내지 않도록 수정했습니다. 공개 RSS 진단에서 최신 기사 20개를 확인했습니다. 기사 수가 부족하면 Claude를 호출하지 않습니다.
- 후보 3개의 출처·제목·시각·상태 저장, DB ID와 선택 버튼 연결, 긴 원문 URL은 원문 버튼으로 보존해 후보 메시지가 잘리지 않도록 수정했습니다. 날짜 실행키·선택 잠금·동일 출처 재사용으로 중복 생성을 막습니다. RSS 장애, Claude 응답 불명확, JSON 검증 실패를 구분하고 무한 재시도하지 않습니다.
- 원고 품질 검사: 반복/긴 문장, 상투적 AI 표현, 약한 훅, 허구 표시 누락, 빈약한 결의를 검토 상태로 보냅니다. `/acceptdraft ID VERSION`은 검토한 유효 원고만 진행하며 최종 승인과 별개입니다. 잘못된 JSON·출처는 우회하지 않습니다. 문체·사실성의 완전한 자동 판정 기능은 아닙니다.
- `draft_versions`와 `quality_reviews`를 포함한 추가 마이그레이션. 새 버전을 요청한 직후 과거 원고를 새 버전으로 표시하지 않습니다. `/preview ID VERSION`으로 과거 원고와 이미지를 조회할 수 있습니다. 승인된 내용은 수정·재게시하지 않습니다.
- `figma_renderer.py` 단일 경로 유지. 서로 다른 검토 사진 두 장의 해시·크롭 후 해상도·출처/라이선스 기록을 검증합니다. 미검토/저해상도/중복/변경 사진은 대기하며 임의 배경으로 우회하지 않습니다.
- Chromium: 정확한 글꼴 부분집합 캐시, 디스크 임시 프로필, SVG 디코딩/화면 반영 대기, 브라우저 종료 경로 개선. 고정 엔딩은 승인 원본 픽셀을 검증·복사합니다. 캡처 완료 manifest는 원자적으로 기록하며 부분 결과와 종료 실패를 구분합니다.
- 비공개 `RENDER_DIR` 미리보기와 공개 이미지 복사를 분리했습니다. `ENABLE_PUBLIC_MEDIA=1` 승인 없이 새 이미지를 공개하지 않습니다. 공개 복사는 완성된 바이트를 원자적으로 만들고 다른 기존 파일을 덮어쓰지 않습니다. Telegram 전송 전에도 파일 해시를 검사합니다.
- Telegram: 선택·거절·재생성·버전 미리보기·검토·승인·상태 조회 모의 검증. 동시 승인 16건이 게시 작업 한 건으로 합쳐집니다. 앨범이 성공해야 승인 메시지를 전송하며, 실패 시 기존 결과물을 재사용합니다.
- Instagram: 공식 API 어댑터와 버전별 승인/컨테이너/게시 체크포인트 유지. pending/publishing/published/failed/waiting/uncertain 상태를 기록하고 `/status`에서 확인합니다. 계정 미설정은 안전하게 대기하며 불확실한 게시를 자동 반복하지 않습니다.
- 운영 도구: 비밀값을 출력하지 않는 `doctor`, 읽기 전용 DB 원본을 이용한 0600 백업, 읽기 전용 배포 preflight. 1GB VM용 서비스 리소스·재시작·로그 제한과 선택적 journal 보관 템플릿을 준비했습니다.

## 2. 실제 테스트 결과

| 검증 | 결과 |
|---|---|
| 전체 Python 회귀 테스트 | **70개 통과**, 21.441초 |
| 운영 DB 백업·복제본 추가 마이그레이션 2회 | 통과. 기존 selections 3건과 기존 컬럼 값 보존, integrity=ok |
| 공개 Google News RSS 날짜·다양성 검사 | 통과. 최신 기사 20개. 유료 호출/운영 DB 저장 없음 |
| 후보 3개 저장·선택·Claude 모의 원고 | 통과 |
| 동적 배경 포함 실제 5장 E2E | 통과. 합성 테스트 패턴 2개 사용, 실제 외부 호출 0회 |
| 실제 Chromium 4장 / 5장 | 통과. 약 148초 / 81초, driver 정상 종료, 생존·좀비 프로세스 0 |
| 해상도·글꼴·잘림·분할·엔딩 | 모두 1080×1350, 글꼴 로딩/넘침 검사 통과, 엔딩 픽셀 일치 |
| 의도적 오버플로 | 예상 ValueError로 거절하고 정상 종료, 잔존 프로세스 없음 |
| Telegram 승인·거절·재생성·중복 클릭·전송 실패 | 모의 테스트 통과. 실제 전송 없음 |
| Instagram 캐러셀·중복 게시·불확실 응답 | 모의 테스트 통과. 실제 인증/게시 없음 |
| systemd 유닛 문법·KST 18시 표현식 | 통과. 호스트의 기존 유닛 경고/버스 권한 경고는 별도 기록 |
| 컴파일·git diff 공백 검사·알려진 비밀값의 소스 혼입 검사 | 통과. 인증값 출력 없음 |

최초 실행 중 Chromium 시작/종료 시간 초과, SVG 로고 픽셀 불일치가 발견되어 수정·재검증했습니다. 실패 기록은 `output/production-ready/render-5/*failed*report.json`, 오버플로의 동시 부하 실패는 해당 디렉터리의 별도 실패 보고서에 보존했습니다. 실패 테스트나 픽셀/글꼴/오버플로 검사를 삭제하지 않았습니다. 운영 시간 예산은 font 준비 45초, 브라우저 종료 15초, 전체 렌더링 180초입니다. 메모리 측정에서 렌더 프로세스 트리의 최대 PSS는 약 351~379MiB였습니다. 실제 systemd cgroup 적용과 재부팅은 승인 전 실행하지 않았습니다.

증거:

- `output/production-ready/unit-tests.log`
- `output/production-ready/acceptance/verification.json`
- `output/production-ready/final-migration/report.json`
- `output/production-ready/e2e-report.json`
- `output/production-ready/rss-public-check.json`
- `output/production-ready/secret-scan.json`

## 3. 실제 카드뉴스 경로

- 4장: `/opt/unreal-github/output/production-ready/render-4/case-4_01.png` ~ `case-4_04.png`
- 5장: `/opt/unreal-github/output/production-ready/render-5/case-5_01.png` ~ `case-5_05.png`
- 동적 배경 E2E: `/opt/unreal-github/output/offline-acceptance/2026-10-29T03-31-55.077071+00-00/unreal-case-1-v1_01.png` ~ `_05.png` (같은 디렉터리에 JPEG 5장·report.json·렌더 trace)

동적 배경 검증에는 **합성 패턴**을 사용했습니다. 실사 사진의 관련성·얼굴·권리 검토 완료를 뜻하지 않습니다. 새 결과는 공개 디렉터리에 복사하지 않았습니다. 기존 공개 PNG 5개의 HTTPS/해시 일치는 앞선 `output/public-check-20261029.json`에 기록되어 있습니다. 새 JPEG의 실제 공개 URL 검증은 공개 승인 이후에 남아 있습니다.

## 4. 확인된 운영 문제

- 브랜치 `feat/full-automation-cloud`, 기존 미커밋 파일 유지. Git 커밋/push 없음. 운영 DB에는 구형 스키마가 있어 추가 마이그레이션이 필요합니다. 백업: `data/backups/production-ready-2026-10-29T02-54-24.367809+00-00.sqlite3` (0600, integrity=ok).
- Telegram/이미지 서버/Caddy는 active/enabled. 새 worker와 candidates timer는 미설치·비활성입니다. 재부팅 테스트 대신 부팅 활성 설정만 확인했습니다.
- 원격 `.github/workflows/run_bot.yml`은 active입니다. 서버 timer 활성화 전에 원격 예약을 전환해야 합니다. 로컬 새 수동 workflow만으로 원격 상태가 바뀌지 않습니다.
- 현재 환경파일에는 모델명·Telegram 허용 사용자·공개 URL·이미지/비공개 렌더 경로가 없습니다. 코드와 같은 환경파일을 사용하도록 템플릿과 검사 도구를 준비했으며 실제 환경파일을 무단 변경하지 않았습니다.
- 이미지 서버 과거 journal 414건에서 포트 충돌 13건/예약 재시작 12건을 확인했습니다. 현재 서비스는 정상이며, 진단 namespace에서 소유 PID가 보이지 않아 현재 포트 소유자는 단정하지 않았습니다. 호스트에서 `sudo ss -ltnp 'sport = :8765'`를 확인하고 중복 수동 서버를 무단 종료하지 마세요.
- 서버 RAM 약 958MiB, swap 약 2GiB. NTP 동기화 yes, 서버 timezone UTC이며 timer는 Asia/Seoul 명시로 UTC 09시에 대응합니다.

## 5. 남은 계정·입력 연결

- 실제 Claude 모델명 및 최소 유료 호출 승인.
- Telegram 허용 사용자 ID와 최소 실전 전송 승인.
- 검토 완료 고해상도 실사 라이브러리, 주제 관련 태그와 얼굴/권리 확인. 로컬에 있던 예전 Pixabay JPG 5개는 최소 크롭 해상도에 미달하여 운영 입력으로 사용할 수 없습니다.
- Page 연결 Instagram Professional 계정, Meta 앱/Graph 버전, 게시용 토큰·앱 토큰·권한·만료/쿼터 확인. 예전 IG_* 값을 인증 방식 확인 없이 META_*로 복사하지 않습니다.
- VM 전용 GitHub self-hosted runner의 설치/권한/수동 실행 확인. 현재 원격에는 새 수동 workflow가 아직 반영되지 않았습니다.
- 새 공개 JPEG HTTPS 검증과 실제 게시 시험은 별도 승인 후 수행합니다. Meta 공식 문서는 이번 조회에서 접근 오류/429가 발생해 현재 계정/API 버전 호환성은 확인 완료로 표시하지 않았습니다.

## 6~8. 최소 승인·배포·롤백·판정

구체적인 명령과 순서는 [PRODUCTION_CUTOVER_KO.md](PRODUCTION_CUTOVER_KO.md)를 따릅니다. 최소 승인은 (1) 커밋/push 및 원격 예약 전환, (2) 정비 창의 환경 병합·DB 추가 마이그레이션·단일 리스너/worker 전환, (3) Claude/Telegram 실전 1회 검증, (4) KST timer 활성화입니다. 공개 이미지와 실제 Instagram 게시는 별도 승인으로 남깁니다.

롤백은 신규 실행을 중지하고 현재 DB와 외부 결과를 보존한 뒤 이전 릴리스·유닛·환경을 복구합니다. 추가 마이그레이션 DB는 가능한 한 유지하고, 과거 DB 덮어쓰기는 별도 승인·외부 결과 대조 없이 하지 않습니다. 이미지 서버와 기존 공개 파일도 삭제하지 않습니다.

`doctor-final.json`은 현재 운영 상태를 의도적으로 **ready_for_worker=false**로 판정합니다. 개발 테스트의 통과와 운영 계정·환경 적용의 완료를 구분합니다. 실제 Claude 호출, Telegram 전송, Instagram 호출/게시, 새 외부 공개, 운영 서비스 변경/재시작, timer 활성화, 원격 예약 해제, Git 커밋/push, 운영 DB 데이터 변경·삭제는 수행하지 않았습니다.
