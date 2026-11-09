# Unsplash / Puter 운영 기록 (2026-11-09)

## 구현 및 안전 경계

- 기존 Pixabay 구현·테스트와 Gemini provider는 보존. 운영 기본 경로는 Unsplash 검색이며 legacy Gemini는 `IMAGE_PROVIDER=gemini-legacy`를 명시하지 않으면 worker에서 실행하지 않는다.
- `/images ID 검색어`는 Unsplash 공식 REST 검색을 호출하고 사진가·출처 링크를 Telegram 텍스트로 제공한다. 원본 raw URL의 ixid를 유지하고 API width/height로 1080×1350 4:5 crop 가능 여부를 검사한다. 실제 이미지 바이트는 내려받지 않는다. API 해상도와 실제 디코딩 해상도의 일치는 현재 확인하지 않았으며 합성 허용 시 기존 inspect_image로 확인해야 한다.
- 검색 응답과 사진가·원본 URL·추적 URL은 운영 DB `unsplash_searches`에 저장된다. 본문/결의 자동 추천·이미지 평가·자동 다운로드는 활성화하지 않았다. 기존 사진 선택의 해시·중복·원본 해상도·사람 검토 조건과 렌더러의 허구 고지는 유지한다.
- `/photos ID`의 기존 로컬 후보 미리보기·선택은 유지. AI 요청 버튼은 Puter 무료 비용 검증 미완료를 안내하며 `puter_image_attempts`에 `automatic` / `approved_test` 모드와 차단 사유를 기록한다. 실제 Puter 생성 결과·사용량 기록과 미리보기·재생성은 아직 구현/검증 완료 상태가 아니다.
- Node 22 / 공식 `@heyputer/puter.js` 2.6.5, `init(PUTER_AUTH_TOKEN)` 사용. 원본 모델/잔액 조회 응답은 git 제외 `data/puter-inspection.json`에 권한 0600으로 저장했다. SDK가 stdout을 flush하기 전에 종료하여 긴 JSON이 잘리는 문제를 수정했다.
- 실제 txt2img 호출 코드와 결제·구매 경로는 없다. 무료 전용 비용 검증이 해결되기 전에는 환경변수 변경이나 버튼 클릭으로 생성할 수 없다. 목표 일일 상한 2회·자동 재시도 0회보다 강하게 0회로 제한한다. 임의 가격표나 잔액을 넣어 우회하지 않는다.

## 정책 적합성

공식 근거:

- https://unsplash.com/api-terms
- https://unsplash.com/documentation
- https://help.unsplash.com/en/articles/2511271-guideline-hotlinking-images
- https://help.unsplash.com/en/collections/1451694-api-guidelines

검색과 링크 안내는 구현했다. Unsplash는 모든 이미지 표시에서 API의 urls 핫링크를 요구하며 사진가 및 Unsplash 링크 출처 표시, 선택/사용에 해당하는 다운로드 이벤트 보고가 필요하다. 로컬 합성 파일을 Telegram 및 Instagram에 업로드하면 API 핫링크 표시가 유지되지 않는다. 자동화의 적합성과 합성·재게시/대체 뷰 추적 허용 여부를 Unsplash API 팀에 확인하기 전 자동 활성화하지 않는다. 연락은 수행하지 않았다. 검색만으로 다운로드 이벤트를 허위 발생시키지 않는다. `track_download`도 사용 승인 전 차단한다. 일반 Unsplash 사진 라이선스만으로 API 계약 준수를 추정하지 않는다.

## Puter 인증·비용

- https://docs.puter.com/getting-started/
- https://developer.puter.com/tutorials/puter-auth-token/
- https://docs.puter.com/Auth/getMonthlyUsage/
- https://docs.puter.com/Objects/monthlyusage/
- https://docs.puter.com/rate-limits-and-quotas/
- https://docs.puter.com/AI/txt2img/
- https://developer.puter.com/ai/models/

서버 인증, getMonthlyUsage, listModels 조회 성공. listModels SDK 소스는 `/puterai/chat/models/details`를 호출하므로 받은 972개를 이미지 생성 지원 모델 목록이라고 간주할 수 없다. 문서의 이미지 모델 디렉터리를 별도 비교했다.

실제 allowanceInfo는 `unit: credits`, `monthUsageAllowance: 1000`, `remaining: 약 999.724`, `addons: {}`였다. 문서의 microcents 설명과 다르므로 USD로 환산하지 않았다. 무료 잔액이라는 보장, 특정 크기/모델의 최대 비용, 무료 한도 소진 후 유료 크레딧 차감 차단을 확인하지 못했다. 무인 생성은 차단한다. 사용자 테스트 승인도 자동 생성 승인이 되지 않는다.

문서상 비교 후보 (품질은 직접 생성 비교하지 않았음; 가격은 게시된 기초 단위이며 요청 견적이 아님):

| 후보 | 검토 이유 | 디렉터리 참고 가격 |
| --- | --- | --- |
| FLUX.2 Pro / Dev | 사물·공간 실사 후보, 단일 FLUX 종속 회피 | $0.03/image |
| FLUX.2 Klein 9B | 속도·비용 비교 | $0.015/image |
| GPT Image 2.5 Flare / Sunburst | 장면 지시·편집 비교 후보 | $0.0059/image (1024² low 기준) |
| Leonardo Lucid Origin | 재질·사진 스타일 비교; 과채도 주의 | 확정 단가 미표시 |

1080×1350용 고해상도 출력은 위 기초 가격과 달라질 수 있다. Schnell의 고정 1024² 출력은 기존 원본 해상도 검사에 부적합하다. 한국 일상 공간·자연광·매트 질감·저채도·텍스트/로고/HDR 배제 프롬프트와 본문 establishing view / 결의 detail view 구분은 기존 prompt_for를 재사용한다.

## 환경변수

`/opt/unreal.gov/.env`: `UNSPLASH_ACCESS_KEY`, `PUTER_AUTH_TOKEN`. 기존 외부 호출/일시정지 설정은 그대로 적용한다. 토큰은 argv나 로그에 출력하지 않는다. 실제 생성 활성화 환경변수는 제공하지 않는다.

## 실제 이미지 1장 테스트 절차 (현재 실행 불가)

1. Puter 공식 지원으로 credits 단위·무료 allowance 구분·모델별 해당 크기의 최대 차감액·유료 차감 방지 방법을 확인한다.
2. 확인된 응답 스키마에 대해 검증기와 원자적 DB 비용 예약/하루 2회 제한/0회 재시도, 결과 불확실 시 재호출 금지를 구현하고 Mock 테스트한다.
3. 모델을 하나 지정하고 본문 1장에 대한 사용자 승인을 별도로 받는다. 현재 요청은 실제 생성 금지이므로 승인이 아니다.
4. 승인된 테스트에만 한 번 txt2img를 호출하여 bytes 검사, 원본 해상도·품질·출처/사용량/모델/프롬프트 기록 후 기존 Telegram 검토 경로에 연결한다. 결의 자동 추가 생성·Instagram 게시는 하지 않는다.

현재 실행 가능한 무과금 검증: `.venv/bin/python -m unittest discover -s tests -p test_unsplash_puter.py -v`. 실제 생성 명령을 제공하거나 사용 가능하다고 주장하지 않는다.

## 검증 및 운영 반영

- 전체 unittest: 156개 통과 (397.759초). Unsplash Mock 2건, Puter 인증/차단 Mock 2건 포함. 기존 Telegram 승인·사진 선택·렌더링 경계·고정 허구 고지 회귀 테스트 포함.
- 허용된 실제 Unsplash 검색은 정확히 1회: 원본 메타데이터 기준 해상도 적합 후보 20개. 사진 다운로드/선택 이벤트는 실행하지 않음.
- Puter는 실제 서버 인증·모델/사용량 조회만 실행. 이미지 생성·구매·결제·Instagram 실제 게시 0회.
- npm audit: 취약점 0건. SDK의 postal-mime 의존성을 수정된 4.0.8로 override 고정.
- 실제 Chromium 5장 모두 저장, 폰트/누락 이미지/레이아웃 넘침 검사 통과. 다만 최초 75초 제한과 단독 실행의 180초 제한 모두 초과: 마지막 실행은 163.7초에 5장 저장 후 browser_close_start에서 종료 제한에 걸림. smoke 전체 성공으로 간주하지 않는다. 렌더러 코드는 변경하지 않았다.
- 운영 DB는 `backups/pre-unsplash-puter-20261109T095933Z.db`에 SQLite online backup, 권한 0600으로 백업. 환경파일은 `/opt/unreal.gov/.env.pre-unsplash-puter-20261109T101706Z`에 0600 백업.
- 운영 설정: `IMAGE_PROVIDER=unsplash`, `GEMINI_IMAGE_ENABLED=0`, `AUTO_PHOTO_ACQUIRE=0`, `AUTO_IMAGE_SEARCH=0`, `INSTAGRAM_PUBLISH_ENABLED=0`. Telegram/worker를 재시작하여 검색 및 차단 경로를 반영한다. 기존 대기 작업·승인 기록을 강제 재시도/변경하지 않는다.
- 남은 작업: Unsplash 합성/자동화 정책 확인, Puter 무료 전용 비용 검증 및 실제 생성·usage ledger/Telegram 생성 미리보기·재생성 구현, Chromium 종료 지연 원인 확인. 현재 결과를 완성된 자동 하이브리드 이미지 시스템으로 간주하지 않는다.

재시작 시 기존 uncertain 후보 작업 1건 때문에 기존 startup preflight가 worker 시작을 차단했다. 작업/체크포인트를 재분류하거나 재시도하지 않고, 점검한 운영 환경에만 `WORKER_ALLOW_ISOLATED_UNCERTAIN=1`을 설정했다. 이 명시적 복구 옵션은 유일한 readiness 오류가 isolated uncertain jobs이고 running jobs / sending 또는 uncertain outbox가 없을 때에만 시작을 허용한다. 설정/DB 오류는 계속 차단하며 claim은 기존대로 queued만 선택한다. 기본값은 꺼짐이다. 별도 DB 회귀 테스트에서 uncertain 상태 보존·자동 재실행 없음·running/설정 오류 차단을 검증했다.

저장된 5장 파일에 대한 별도 검증: 모두 실제 1080×1350 PNG, 마지막 장은 승인된 ending_fixed.png와 RGB 픽셀이 정확히 일치했다. smoke 전체의 종료시간 초과 문제는 여전히 미해결이다.

추가 복구 변경 검증: worker recovery 테스트 1개 통과, 영향받는 preflight 테스트 12개 재실행 통과. 서비스 재시작 후 worker/Telegram/images active, worker/Telegram NRestarts=0 확인. 전체 156개 테스트 실행 후 추가된 복구 변경은 이 두 테스트 묶음으로 검증했으며, 그 후 전체 묶음을 다시 실행한 것은 아니다.
