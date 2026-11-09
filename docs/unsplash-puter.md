# 이미지 제작 운영 (2026-11-09)

## 사용 흐름

기획 승인 → `/photos ID` → 본문/결의 참고 사진 탐색, AI 생성 또는 직접 업로드 → 후보 확대 확인 → 각 슬롯의 검토 완료/선택 → 서로 다른 두 사진이 준비되면 기존 render 작업 재개 → 카드 앨범 → 최종 승인.

- 직접 업로드: 업로드 버튼 또는 `/upload ID VERSION`, 본인 소유/허락을 확인한 사진을 캡션 `OWN`으로 전송. 원본 문서 전송 권장. JPEG/PNG/WebP, 20MB 이하, 짧은 변 512px 이상. 원본 보존, EXIF 방향 보정, 4:5 크롭 후 Lanczos 리사이즈. 실제 원본 크기와 확대 여부를 표시한다. 최종 1080×1350 파일도 품질 검사를 통과해야 한다. 업로드 자체는 슬롯 선택/최종 승인이 아니다.
- AI 생성: 본문/결의 생성 → 모델 선택 → durable worker 요청. 후보 생성 후 기존 사진 선택 버튼으로 검토, 재생성 버튼은 해당 후보/버전에 묶인다. 중복 클릭은 같은 작업으로 처리한다.
- Unsplash: 두 슬롯의 참고 검색 버튼, 다른 검색어 버튼, `/images ID 검색어`. 한국어 기획의 장소/인물/행동/감정/시간/사물/구도/분위기를 로컬 용어사전과 기존 영어 image_queries로 추출/변환하고 3~5개 전략을 제공한다. 한 번 클릭에 한 전략씩 조회한다. 번역은 범용 번역기가 아니며 사전에 없는 구체적 소재는 `/images`의 영어 검색어로 보완한다.
- 결과의 설명문 관련성 80%, 4:5 크롭 보존율 20%로 정렬. 원본 크기 조건을 통과해도 관련성이 높다고 판단하지 않는다. 실사 품질·자연스러움·감정·얼굴은 자동 검증했다고 주장하지 않으며 링크에서 사람이 검토한다. 동일 ID는 중복 제거한다.

## Puter 구현·비용 경계

공식 `@heyputer/puter.js` 2.6.5, Node 22, `init(PUTER_AUTH_TOKEN)`. JS dispatch는 한 요청에서 txt2img 정확히 한 번만 호출한다. 실패·인증 오류·usage 조회 실패 시 생성 재시도나 다른 모델 자동 호출은 없다. SDK 호출 결과의 data URI 또는 승인된 공개 호스트 URL을 수신해 포맷/픽셀/크기 검증 후 원본·카드용 파일을 별도 저장한다. URL은 HTTPS/호스트/공개 DNS 검증 및 redirect 차단, 크기 제한을 적용한다.

`puter_image_attempts`는 이전 테이블을 보존하며 request_key 유일성, 모델·프롬프트·모드·서울 날짜·요청 상태·원본/결과·비용 견적·호출 전후 usage를 추가 기록한다. SQLite IMMEDIATE 트랜잭션으로 하루 최대 2회 예약, sent/uncertain/cost_overrun 존재 시 추가 호출 차단, 실패/재시작 후 동일 요청 재호출 금지. 결과 불확실 시 새 변형도 차단된다. 자동 생성은 별도 하드 차단한다.

**운영 free_only_quote 검증기는 현재 항상 차단한다.** 공식 사용량 응답은 credits 총량만 보여주고 무료/유료 분리, 결제 수단/유료 잔액으로 넘어가지 않는 강제 제한, 해당 크기의 구속력 있는 최대 비용을 증명하지 못한다. 환경변수로 이를 우회하는 기능은 없다. SDK 실호출 Provider 코드는 구현했지만 실제 생성은 실행하지 않았다. 테스트는 별도 Mock bridge/authorizer를 주입하여 성공·한도·비용 초과·재시작 경로를 검증한다. Mock proof는 Puter의 실제 API 스키마가 아니다.

읽기 전용 재검증: 서버 인증 성공, listModels 972개는 chat 모델 목록이며 이미지 모델 카탈로그로 오인하지 않는다. 계정 응답: monthUsageAllowance=1000, remaining 약999.703, unit=credits, addons={}. 문서 microcents와 단위가 달라 USD/무료 이미지 수로 환산하지 않는다.

## 모델 선정 (문서 기반, 실제 생성 품질 비교 전)

| 용도 | 모델/옵션 | 문서상 출력 범위 | 가격 근거/한계 |
| --- | --- | --- | --- |
| 기본 | xAI `grok-imagine-image`, resolution=2k, aspect_ratio=4:5 | 1K/2K, 여러 비율; 2K는 최대 2048 수준 | 디렉터리 $0.02/image는 참고값. 해당 2K 요청 최대 소모량/무료 적용 미확정 |
| 대체 | Cloudflare `@cf/black-forest-labs/flux-2-dev`, 1080×1350, 25 steps | 256~1920/변; 직접 요청 가능 | FLUX.2 Dev 디렉터리 $0.03/image는 provider/steps별 확정 견적이 아님 |

Grok은 지시 이행/속도/2K 지원을 이유로, FLUX.2 Dev는 직접 크기·다른 provider·사물 디테일 제어를 이유로 선정했다. 실제 한국 일상 실사 품질·지연은 미검증이며 어느 모델도 무료라고 가정하지 않는다. Schnell 고정 1024²는 기본 후보에서 제외. Gemini provider는 보존하되 비활성화한다. 본문은 상황 전경, 결의는 다른 각도의 사물/결과 디테일. 한국 일상·자연광·매트 질감·저채도·HDR/광택/텍스트/로고 배제 프롬프트를 기록한다.

공식 근거: [이미지 API](https://docs.puter.com/AI/txt2img/), [모델 디렉터리](https://developer.puter.com/ai/models/), [월 사용량](https://docs.puter.com/Objects/monthlyusage/), [과금/할당량](https://docs.puter.com/rate-limits-and-quotas/).

## Unsplash 정책 판정

| 항목 | 판정 | 현재 구현 |
| --- | --- | --- |
| API 원본 이미지 표시의 핫링크 | 명시적 제한/필수 요건 | 이미지 재호스팅 없이 출처/사진가 링크로 탐색 |
| 사진가·Unsplash 출처 표시 | 명시적 필수 요건 | UTM referral 사진/사진가 URL, 이름 저장·표시 |
| 사용자 다운로드/사용 이벤트 | 명시적 추적 의무 | 검색만으로 허위 이벤트를 발생시키지 않음. 이미지 사용 경로 차단 |
| 일반 라이선스의 수정 | 명시적 허용, 추가 권리 별도 | API 계약을 대체한다고 해석하지 않음 |
| 창작 파생 이미지 핫링크 예외 | 공식 지침상 조건부 허용 | 예외 존재는 인정. 현재 카드 합성의 충족 여부는 불확실 |
| 원본 사진을 Telegram sendPhoto로 전송 | 핫링크 요건과 충돌 | 차단 |
| 현재 카드 합성 및 Instagram 재게시 | 불확실 (파생 창작 기준/추적/출처 위치) | 차단. 정책을 우회하지 않음 |
| Telegram에서 참고 출처 링크 안내 | 출처 링크 지침에 맞춘 탐색 방식 | 구현. 자동 사진 수집은 비활성 |

[API 약관](https://unsplash.com/api-terms), [핫링크 및 파생 이미지 예외](https://help.unsplash.com/en/articles/2511271-guideline-hotlinking-images), [일반 라이선스](https://unsplash.com/license). API 팀의 확인 전 원본/합성 사진 사용을 활성화하지 않는다. 카드에는 권리가 확인된 사용자 업로드 또는 생성 검증 후의 AI 이미지만 사용한다.

## 검증/운영

- 실행: `.venv/bin/python -m unittest discover -s tests -v`, `node --test tests/puter_bridge.test.mjs`.
- E2E: `.venv/bin/python scripts/image_e2e.py --send-telegram`. 격리 DB/자체 제작 Mock 이미지/Mock SDK만 사용. 실제 Chromium과 실제 Telegram 최종 테스트 앨범 전송, 격리 DB에서 최종 승인 전환을 검증한다. 실제 Puter 생성/Instagram 게시 기능은 호출하지 않는다. `--send-telegram` 없이 실행하면 외부 전송도 없다.
- E2E 전달은 durable outbox에 기록하고 결과 불확실 시 자동 재전송하지 않는다. 테스트 메시지에는 운영 승인 버튼을 넣지 않는다.
- 환경변수: UNSPLASH_ACCESS_KEY, PUTER_AUTH_TOKEN, 기존 Telegram 설정. 별도의 유료 생성 활성화 변수는 없다.
- 기존 worker의 isolated uncertain 복구 옵션과 승인/큐/단일 polling 잠금은 유지. 스케줄은 매일 18:00 KST 그대로 유지. Instagram/Gemini/자동 AI 생성은 비활성.
- 실제 생성 테스트를 열기 위한 남은 외부 조건: 공식 무료/유료 분리 응답, 유료 차감 방지 수단, 모델/옵션별 최대 비용. 확인 후 free_only_quote 구현을 갱신하고 Mock 및 별도 승인된 1회 검증을 수행해야 한다.

### 이번 검증 결과

- Python 전체 회귀 166개 통과 (485.288초). 이후 추가한 기존 Puter 원장 보존 마이그레이션 테스트를 포함해 변경 경계 10개 재검증 통과 (77.981초). Python 고유 테스트 총 167개 검증. Node SDK dispatch 4개 통과.
- SDK 내부 429/gate 자동 재시도도 `config.autoRetry=false`로 끄고, 별도 재인증/검증/업그레이드 UI 경로도 거부하도록 설정했다. 이 설정 후 실제 읽기 전용 서버 인증/usage/972 chat models 조회 성공.
- Unsplash 실제 읽기 전용 검색에서 원본 크기 적합 후보 20개와 관련성 정렬 확인. 원본 사진 다운로드/Telegram 재호스팅/Instagram 게시 없음.
- E2E 첫 병행 시도는 Chromium 시작 제한 시간으로 실패했으며 Telegram 전송 이전에 중단. 단독 재실행 성공: Mock SDK 1회 → 원본/가공본 저장 → 사용자 업로드 → 실제 Telegram callback 함수로 슬롯 선택 → 실제 Chromium 5장 렌더 → 1080×1350 PNG/JPEG 검증 → 고정 엔딩 RGB 픽셀 일치 → 격리 DB approved 전환.
- 최종 테스트 앨범 및 설명 메시지 실제 Telegram 전송 완료: 두 delivery 모두 sent. Puter/이미지 입력은 Mock·자체 제작 테스트 그림이며 실제 AI 사진 품질 검증이 아니다. 사용자 사진을 실제 Telegram에서 수신하는 네트워크 경로는 Mock callback으로 검증했다.
- 결과: `output/image-e2e-2026-11-09T10-46-24.072231+00-00/result.json`. 격리 DB와 5장 PNG/JPEG, 원본/선택/승인/전송 기록 보존. 공개 이미지 디렉터리에 게시하지 않음.
- 운영 DB 최초 백업: `backups/preflight-2026-11-09T10-28-48.844459+00-00.sqlite3`. 환경파일도 시작 시 `.env.image-project-*`로 권한0600 백업. 배포 직전 추가 DB 백업 및 기존 selection/uncertain 상태 보존 검증 후 schema 6로 마이그레이션.

운영 배포 후 worker/Telegram/images 모두 active, worker/Telegram NRestarts=0 / ExecMainStatus=0, 최근 배포 이후 journal 오류 표식 0건 확인. 매일 18:00 KST 후보 timer 일정 유지. 운영 Puter 생성 원장은 비어 있어 실제 생성 호출 0회를 확인했다. schema 6 마이그레이션 전후 기존 selection 상태/승인 버전과 uncertain 작업이 동일하며 PRAGMA quick_check=ok. 직전 정상 버전은 64daefd이며 배포 DB 백업은 `backups/preflight-2026-11-09T10-53-57.826465+00-00.sqlite3`이다.
