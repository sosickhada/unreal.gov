# Gemini 이미지 생성 운영 및 비용 관리

## 모델과 공식 근거 (2026-11-09 확인)

기본 표시명은 **Gemini Nano Banana 2.1**, 실제 API ID는 `gemini-nano-banana-2.1`이다. 4:5 / 2K / 이미지 1장 / minimal thinking / 최대 출력 4,096 토큰을 요청한다. REST `v1beta/models/{model}:generateContent`를 사용하며 검색 grounding, 참조 이미지, 유료 도구는 요청하지 않는다. 별도 SDK나 로컬 모델 다운로드는 필요 없다.

- [공식 이미지 생성 문서](https://ai.google.dev/gemini-api/docs/image-generation): 신규 프로젝트의 효율형 주력 모델로 권장, 1K/2K/4K 지원.
- [공식 모델 문서](https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1).
- [공식 Standard 가격표](https://ai.google.dev/gemini-api/docs/pricing#gemini-nano-banana-2.1): 입력 $1.50/백만 토큰, 텍스트·thinking 출력 $7.50/백만 토큰, 이미지 출력 $30/백만 토큰. 2K 이미지 출력은 $0.0504/장이다. 이미지 API 무료 티어는 없다. Batch 할인은 대화형 Telegram 흐름에 적용하지 않는다.
- 더 싼 Flash Lite Image는 1K만 지원하여 기존 카드의 원본 1080×1350 검사 기준에 부족하다. 기본 경로에서는 확대해 통과시키지 않는다.
- 대체 허용 ID `gemini-3.1-flash-image`는 2K 출력 $0.101, 입력 $0.50/백만, 텍스트·thinking $3/백만, 이미지 $60/백만 토큰이다. 다른 모델·해상도는 공식 가격 확인 및 가격 파일 갱신 전까지 차단한다.
- [공식 약관](https://ai.google.dev/gemini-api/terms#use-generated): Google은 생성 콘텐츠의 소유권을 주장하지 않지만 법 준수·제3자 권리·출력 사용 책임은 사용자에게 있다. 상업적 콘텐츠에 활용할 때도 실존 인물·상표·저작권 검토가 필요하다. API 연결을 라이선스 검증 완료로 기록하지 않는다. 원본 생성 바이트를 저장하고 SynthID 제거 처리를 하지 않는다.

## 설정과 승인

설정 파일은 `/opt/unreal.gov/.env`이며 기존 Claude·Telegram·Instagram 값은 변경하지 않는다.

```dotenv
GEMINI_API_KEY=
GEMINI_IMAGE_MODEL=gemini-nano-banana-2.1
GEMINI_IMAGE_ENABLED=0
GEMINI_IMAGE_MONTHLY_BUDGET_KRW=5000
GEMINI_IMAGE_MAX_GENERATIONS_PER_DAY=2
GEMINI_IMAGE_MAX_RETRIES=1
GEMINI_IMAGE_USD_KRW=1800
GEMINI_IMAGE_COST_MARGIN=1.25
```

현재 키가 없어 실제 인증·생성은 미검증이며, 운영 생성 스위치는 0으로 유지한다. 키 자체를 채팅·Git·Telegram에 보내지 않는다. [Google AI Studio 키 발급 안내](https://ai.google.dev/gemini-api/docs/api-key)를 따라 프로젝트에서 키를 생성하고 서버 환경 파일에 직접 등록한다. 해당 모델 이용에는 결제 설정이 필요하다. 다른 애플리케이션의 지출이 섞이지 않도록 전용 프로젝트·키 사용을 권장한다.

실제 테스트 전 사용자가 **“Gemini 본문 이미지 1장 유료 테스트 승인”**처럼 대상·수량을 승인해야 한다. 승인 후에도 먼저 Worker의 자동 생성 스위치 0을 유지하고, 별도의 단발 프로세스에서만 활성화하고 재시도는 0으로 내려 요청 1회·최대 404원 예약 범위에서 생성·검증·Telegram 미리보기로 전달한다. 일반 활성화는 테스트 결과 검토 후 별도로 결정한다. 이 문서의 작성이나 버튼 배포 자체를 유료 호출 승인으로 취급하지 않는다.

## 비용 계산과 보장 범위

`config/gemini_image_pricing.json`에서 USD 가격, 확인일, 유효기한을 관리한다. 기본 가격 정보는 2026-12-09까지 유효하며, 기간 만료·알 수 없는 모델·가격 누락·잘못된 환율이면 API 호출 전에 차단한다. 가격과 환율은 운영자가 공식 문서로 재검증해 갱신해야 한다. 환율은 시장 실시간 환율이 아닌 보수적인 설정값이다.

기본 환율 1,800원/USD, 여유 계수 1.25. 이미지 출력분만 약 91원이며 입력·thinking은 추가다. 여유를 반영한 출력분은 약 114원이다. 청구 금액이나 고정된 총 장당 단가를 의미하지 않는다.

매 호출 전 다음 상한을 예약한다.

```
USD 예약 = (입력 4,096 UTF-8 bytes + 여유 64 tokens) × 입력 단가
         + 출력 상한 4,096 tokens × 가장 비싼 출력 모달리티 단가
         + 공식 2K 이미지 1장 단가
KRW 예약 = ceil(USD 예약 × 보수 환율 × 여유 계수)
```

출력 상한과 이미지 1장 비용을 함께 더하여 의도적으로 중복 여유를 잡는다. 기본 모델의 1회 예약액은 **404원**, 기존 모델 대체 시 **785원**이다. 기본 5,000원에서 최대 **12회(4,848원)** 예약 가능하며 재시도도 포함한다. 하루 상한은 2회다. 성공 시에도 예약액을 자동 환급하지 않으므로 실제 사용량보다 일찍 중단될 수 있다. 캐시 재사용은 추가 비용 예약이 없다.

앱이 관리하는 것은 이 시스템을 통해 발생한 Gemini 이미지 요청의 **보수적 추정 비용**이다. Google의 실제 청구액, 세금·환율·요금 변경, 다른 앱의 같은 키 사용까지 보장하는 절대적 청구 상한이 아니다. 기존 Claude 기획·Pixabay 시각 검사 비용은 이 Gemini 원장과 별개이며, Gemini 후보에는 별도의 유료 Claude 시각 검사를 추가하지 않는다.

## 원장과 복구

- `gemini_image_requests`: 모델·프롬프트·슬롯·재생성 계보의 해시, 상태, 캐시 결과.
- `gemini_image_attempts`: 시도별 KST 월/일, KRW 예약, USD/환율/가격 스냅샷, provider usageMetadata, 관측 토큰 기반 비용 추정, 오류·상태. 관측 비용도 실제 청구서가 아니다.
- `gemini_image_periods`: 월별 중단 상태. 새 월은 KST 매월 1일 00:00부터 별도 집계한다.
- SQLite `BEGIN IMMEDIATE` 안에서 중복·월 예산·일 한도를 확인하고 예약을 생성하므로 다중 Worker도 과예약하지 않는다.
- 예약·전송 중 상태가 남으면 불확실 호출로 간주하고 자동 재호출하지 않는다. 실패·타임아웃·검증 거절도 예약액을 유지한다.
- 명확한 HTTP 429 또는 알려진 이미지 검증 실패에 한하여 최대 1회 재시도하며 새 예약·일일 호출을 소비한다. 네트워크/응답 불확실은 재시도하지 않는다.
- 80% 예약 시 Telegram에 한 번 알린다. 100% 또는 다음 1회를 예약할 잔액이 없으면 해당 월 생성을 차단하고 기존/수동 사진으로 안내한다. 관측 토큰 비용이 예약 가정을 초과하면 월 생성을 중단하고 알린다.
- Worker 장애 복구는 기존 `recover JOB_ID --worker-stopped` 및 `resume JOB_ID` 절차를 따른다. 이미 저장한 provider 결과는 캐시로 복구하고, 불확실 원장은 차단을 유지한다. 이력·예약을 지워 재시도하지 않는다.

가능하면 [Google Cloud Billing 예산 알림](https://docs.cloud.google.com/billing/docs/how-to/budgets)을 5,000원 및 80%/100%에 맞춰 별도로 설정한다. 일반 예산 알림은 사용·청구를 자동 차단하는 수단이 아니다. 서비스와 계정에서 지원하는 추가 할당량·지출 제어가 있는지도 별도로 확인한다.

## Telegram 및 이미지 처리

기획 승인 → 기존 Pixabay 검색/시각 평가 → 적합한 사진 사용 → 부족한 슬롯만 Gemini → 기술 검사 → Telegram 후보 → 사용자 선택 → 렌더 순서다. 키/스위치/가격/예산 문제는 사진 선택 대기로 전환한다. 기존 `/images`, `/photos`, 이미지 수정 흐름을 보존한다.

- `/photos ID`: 검색 사진·AI 후보 미리보기와 슬롯 선택. AI 여부 및 출처를 명시한다.
- 본문/결의 AI 생성 버튼: 작업만 큐에 넣는다. Telegram 핸들러에서 직접 API를 호출하지 않는다.
- AI 이미지 재생성: 해당 후보의 계보에 새 요청 하나만 만든다. 반복 클릭은 같은 작업 ID를 반환한다.
- `/imagebudget` 또는 남은 횟수 버튼: 월 예약/잔액, 일 한도, 추가 예약 가능 횟수. 키는 표시하지 않는다.
- 사건의 시각 브리프·공간·감정·오브젝트를 사용한다. 본문 카드 문구는 프롬프트에 복사하지 않는다. 한국 일상 공간·환경광·자연 질감·절제된 색·실사 다큐 스타일을 지시한다. 본문은 상황의 중경, 결의는 다른 각도·핵심 사물의 디테일로 구분한다.
- 형식·MIME·네이티브 해상도·선명도·크기와 해시를 검사한다. 이 검사가 해부학·실사 품질·권리를 검증했다고 표시하지 않는다. 손·얼굴·텍스트·로고·관련성은 Telegram에서 사람이 확인한다.
- 두 슬롯에 같은 바이트 이미지는 사용할 수 없다. 선택 결과에 `provider=gemini`와 모델/요청키를 보존한다. 허구 고지와 최종 승인 보호는 유지한다.

## 검증

기본 테스트는 네트워크를 차단한 Mock API·격리 DB로 수행한다. 실제 Google 인증이나 유료 생성에 성공했다고 해석하지 않는다.

- 전체 기존+새 테스트 초기 실행: 141개 PASS.
- 확장 Gemini 전용: 예산/일일·월 경계/동시 예약/재시도·불확실/캐시/복구/Telegram/선택 후 렌더 연결 21개 PASS.
- `tests/gemini_offline_acceptance.py`: Google 응답은 합성 이미지 Mock, 카드 렌더는 실제 Chromium으로 수행한다. 실제 사진/라이선스 검증 결과가 아니다.

## 최종 운영 검증 (2026-11-09 UTC)

- 최종 전체 unittest **148개 PASS**, 이후 작은 복구/테스트 시간 고정 보완은 Gemini 전용 **21개 재검증 PASS**. 별도 사진 선택 테스트와 기존 렌더 경계 검사도 전체 실행에 포함했다.
- Gemini Mock 응답 → 사진 미리보기 → 두 슬롯 사용자 선택 → **실제 Chromium 5장 렌더** → Telegram 모의 전송 → 최종 승인 후 `publish_waiting`까지 **PASS / exit 0**.
- 결과: `output/gemini-offline-acceptance/2026-11-09T07-09-23.063192+00-00/report.json`. 외부 API 0회, Gemini 모의 2회, Telegram 모의 12회, 격리 테스트 원장 예약 808원. 합성 fixture를 실제 Gemini 품질·라이선스 검증으로 취급하지 않는다.
- 운영 백업: `backups/gemini-20261109T064204Z.db` 및 서비스 정지 후 생성한 `backups/gemini-cutover-*.db`. 선택 7건·후보 30건·게시 상태 레코드 1건을 전후 비교해 완전히 보존했다. 스키마 버전 5 추가, 무결성 검사 OK.
- 기존 비-Gemini 환경 설정은 문자열 그대로 보존했다. 운영은 Gemini 키 없음 / `GEMINI_IMAGE_ENABLED=0` / Gemini 비용 예약 0원이다. 실제 인증·생성 요청은 수행하지 않았다.
- Worker/Telegram active/running, NRestarts=0, 후보 timer active/waiting. 기존 서비스만 정지 후 시작하여 두 번째 polling을 실행하지 않았다. 실제 Gemini 이미지의 Telegram 미리보기는 유료 테스트 승인 후 수행한다.
- 한도 때문에 대기한 생성 작업은 날짜/월 변경 후 같은 버튼으로 다시 요청할 수 있다. 같은 작업 ID를 재사용하며 provider 원장이 중복·불확실 호출을 계속 차단한다.
