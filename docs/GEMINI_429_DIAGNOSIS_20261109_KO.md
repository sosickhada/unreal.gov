# Gemini HTTP 429 원인 조사 (2026-11-09 UTC)

## 결론

**정확한 근본 원인은 기존 증거만으로 확정할 수 없다.** Google이 실제 이미지 생성 요청에 HTTP 429를 반환한 사실과 요청 모델은 확인했다. 하지만 당시 구현이 오류 응답 본문·헤더를 읽거나 저장하지 않고 닫았기 때문에 결제 미연결, 할당량 0, 사용량 초과, 일시적인 속도 제한을 구분할 공급자 상세 정보가 없다. 본문이 없다는 것은 quota 정보가 원래 응답에 없었다는 뜻이 아니다.

이번 조사에서 이미지 생성·countTokens·배치 생성 요청은 **0회**다. 설정·결제·IAM·OAuth 범위를 변경하지 않았고, API 키·토큰·계정 정보를 출력하지 않았다.

## 기존 요청과 오류 증거

운영 DB를 읽기 전용으로 조회했다.

| 항목 | 확인 결과 |
| --- | --- |
| 요청 시각 | 2026-11-09 07:37:31.197904 UTC 원장 기록 |
| 요청 모델 ID | `gemini-nano-banana-2.1` |
| API | Gemini Developer API v1beta `generateContent` |
| 운영 원장 | 요청 1개, attempt 0, `failed`, `http_429` |
| 비용 | 보수적 예약 404원, usageMetadata 없음, 실제 청구액 미확인 |
| HTTP 상태 | 429 |
| JSON `error.message` | 미보존·복원 불가 |
| JSON `error.status` | 미보존·복원 불가. `RESOURCE_EXHAUSTED`라고 관측한 것으로 보고하지 않음 |
| quota metric | 미보존·복원 불가 |
| quota ID | 미보존·복원 불가 |
| `retryDelay` / `Retry-After` | 미보존·복원 불가. 0초로 해석하지 않음 |

기존 단발 실행 보고서는 `GeminiBlocked`와 HTTP 호출 수 1만 남겼다. `bureau/gemini_images.py`는 비정상 HTTP 상태에서 `finish(..., 'http_429')`만 저장하고 응답 본문을 읽기 전에 예외 처리한다. 따라서 이번 예외 문구 개선만으로 과거 응답을 복구하거나 향후 상세 오류를 수집할 수 있는 것은 아니다.

기존 단발 실행 산출물과 Worker/Telegram journal의 07:35–07:40 UTC 구간도 확인했다. 해당 journal 구간의 항목은 0건으로 별도의 공급자 상세 로그가 없었다. 단발 호출은 서비스 밖의 프로세스였으므로 서비스 journal에 공급자 응답이 남는다고 가정하지 않았다.

## 실제 모델 목록과 공식 문서 대조

등록된 키로 읽기 전용 `GET /v1beta/models?pageSize=1000`을 한 번 호출했고 HTTP 200을 받았다. 다음 ID가 모두 목록에 있고 `generateContent` 지원을 표시했다. 다음 페이지는 없었다.

| ID | 확인 범위 |
| --- | --- |
| `gemini-nano-banana-2.1` | 기존 요청 모델. 공식 문서의 Stable ID 및 저장된 가격표와 일치 |
| `gemini-3.1-flash-image` | 저장된 가격표의 대체 모델. 현재 키의 모델 목록에 존재 |
| `gemini-3-pro-image` | 모델 목록에 존재. 이번 시스템에서 가격 승인·모델 전환은 하지 않음 |
| `gemini-2.5-flash-image` | 모델 목록에 존재. 이번 시스템에서 가격 승인·모델 전환은 하지 않음 |

목록 조회는 모델 카탈로그 접근·존재 확인이며, 실제 생성 성공·유료 티어·할당량 보장을 뜻하지 않는다. 현재 모델이 잘못된 ID라서 발생했다는 근거는 발견하지 못했다.

공식 문서와 가격표를 다시 HTTPS 200으로 확인했다. 현재 모델은 1K/2K/4K 이미지 출력을 지원하고, API 무료 티어는 **Not available**이다. Standard 유료 가격은 입력 $1.50/백만 토큰, 텍스트·thinking 출력 $7.50/백만 토큰, 이미지 출력 $30/백만 토큰, 2K 이미지 $0.0504다. 무료 AI Studio 이용이나 소비자용 Gemini 구독을 이 API의 무료 이미지 생성 권한으로 해석하면 안 된다.

- [현재 모델 공식 문서](https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1)
- [공식 모델별 가격표](https://ai.google.dev/gemini-api/docs/pricing#gemini-nano-banana-2.1)

## 프로젝트 결제·할당량 조회 가능 여부

기존 gcloud에 활성 인증과 기본 프로젝트 설정이 있는지 값 출력 없이 확인했다. 기본 프로젝트가 Gemini 키의 프로젝트와 같다고 추정하지 않았다.

기존 OAuth 토큰을 메모리에서만 사용해 API Keys API의 읽기 전용 `keys:lookupKey`를 호출했으나 **HTTP 403 / `PERMISSION_DENIED` / `ACCESS_TOKEN_SCOPE_INSUFFICIENT`**였다. 따라서 Gemini 키의 프로젝트를 신뢰할 수 있게 식별하지 못했고, 그 프로젝트에 대한 billingInfo 및 이미지 생성 quota 조회는 실행하지 않았다. 이 403은 조사용 OAuth 범위 부족이며 원래 Gemini 생성 요청의 429와 별개다. 결제가 꺼져 있다는 증거가 아니다.

공식적으로는 프로젝트 `getBillingInfo`와 Service Usage `consumerQuotaMetrics.list` 조회가 가능하지만 각각 적절한 OAuth 범위와 IAM 읽기 권한이 필요하다. BillingInfo가 정상이어도 AI Studio의 Prepay 잔액·모델별 실제 한도까지 모두 확인되는 것은 아니다. 인증 범위 확대, IAM 변경, API 활성화, 로그인 재설정은 수행하지 않았다.

- [프로젝트 결제 정보 조회와 권한](https://docs.cloud.google.com/billing/docs/reference/rest/v1/projects/getBillingInfo)
- [할당량 조회와 권한](https://docs.cloud.google.com/service-usage/docs/reference/rest/v1beta1/services.consumerQuotaMetrics/list)

## 원인별 구분과 사용자가 확인할 항목

| 가능 원인 | 이번 판정 | 확인 및 해결 방법 |
| --- | --- | --- |
| 시스템 월 예산 5,000원 부족 | 이번 HTTP 429의 원인이 아님 | 요청이 공급자까지 전송되었고 사전 예약 404원이 성공함. 앱 예산은 Google 할당량과 별개 |
| 모델 ID 오기 | 근거 없음 | 원장의 ID가 공식 Stable ID 및 현재 키의 모델 목록과 일치 |
| 결제 미연결 / Free tier | 미확정 | AI Studio에서 해당 키에 연결된 프로젝트를 선택. Billing Tier와 `Set up billing` 상태 확인. 현재 모델은 무료 API 티어가 없음 |
| Prepay 미설정·잔액 소진 / 지출 상한 | 미확정 | Billing/Projects의 `Set up Prepay`, `No credits`, 잔액 및 프로젝트·계정 지출 상한 확인. 계정별 Postpay 여부도 확인 |
| 해당 모델 할당량 0 | 미확정 | 같은 프로젝트의 Rate limits에서 현재 모델의 RPM·TPM·RPD·이미지 한도를 확인. 한도가 0이면 단순 대기로 해결된다고 가정하지 않음 |
| 분당·일일 사용량 초과 / 일시적인 속도 제한 | 미확정 | 양수 한도와 요청 시각의 사용량을 비교. 다른 키·다른 앱이 같은 프로젝트를 사용했는지도 확인 |

Google의 한도는 API 키별이 아니라 프로젝트별로 적용되며, 일일 한도는 미국 태평양 시간 자정에 초기화된다. 이 앱에서 1회만 호출했다는 사실만으로 프로젝트 전체의 속도 제한을 배제할 수 없다. 계정·프로젝트 지출 한도나 Prepay 상태도 함께 확인해야 한다.

사용자는 [AI Studio Projects](https://aistudio.google.com/projects)에서 키와 연결된 프로젝트를 확인하고, [Billing](https://aistudio.google.com/billing), [Rate limits](https://aistudio.google.com/rate-limit?timeRange=last-28-days)를 같은 프로젝트로 조회하면 된다. 현재 프로젝트의 티어·상태와 해당 모델 한도/사용량을 확인해야 세 원인을 구분할 수 있다. 결제 활성화·충전·한도 변경은 사용자가 결정하고 실행할 사항이며 이번 작업에서는 실행하지 않았다.

공식 결제 안내에 따르면 유료 전환에는 활성 결제 계정 연결이 필요하며, Prepay 적용 계정은 선결제 설정과 사용 가능한 잔액도 필요하다. 안내에 표시되는 최소 선결제 금액은 $5 또는 현지 통화 상당액이다. 선결제액은 이미지 1장 가격 및 시스템의 월 5,000원 예산과 서로 다른 항목이다. 적용되는 결제 방식은 AI Studio의 해당 계정 상태에서 확인해야 한다.

- [공식 결제·Prepay 및 상태 확인 안내](https://ai.google.dev/gemini-api/docs/billing)
- [공식 프로젝트별 한도 안내](https://ai.google.dev/gemini-api/docs/rate-limits)

과거 원인 확인을 위해 새 이미지 요청을 실행하지 않았다. 향후 별도 승인된 생성 시험이 있을 때에는 원본 응답을 무작정 출력하는 대신 비밀값을 제거한 제한된 진단 필드를 보존해야 한다. `retryDelay`가 있더라도 결제나 0 할당량 문제가 해결되었다는 보장은 아니다.

## 코드 변경과 검증

HTTP 429의 최종 실패 안내를 다음 내용으로 바꿨다.

> Gemini 이미지 생성이 제한되었습니다 (HTTP 429). 할당량 또는 결제 상태 확인 필요: Google AI Studio에서 해당 API 키 프로젝트의 유료 티어·이미지 생성 할당량·사용량을 확인하세요. 429만으로 결제 미연결과 일시적인 속도 제한을 구분할 수 없습니다. 비용 예약은 유지합니다.

수동 Gemini 작업 및 렌더 중 Gemini 실패 알림은 기존 공통 예외 메시지를 사용하므로 해당 안내가 Telegram outbox로 전달된다. 공급자 오류 본문·키·프로젝트 식별자는 사용자 메시지에 삽입하지 않는다. 기존 예약·캐시·재시도 정책은 변경하지 않았다. 이번 조사에서는 생성 요청을 하지 않았고, 운영의 자동 생성 스위치는 계속 0이다.

관련 오프라인 테스트: `PYTHONPATH=tests:. .venv/bin/python -m unittest test_gemini_images -v` — **25개 PASS / 5.291초**. 소켓 연결을 차단하고 모의 응답만 사용했다. 429 안내 문구·원인 단정 방지, 실제 수동 작업의 Telegram outbox 전달, 대기 상태 보존, 0회 재시도 설정에서 재시작 후 재전송 차단, 비밀값 비노출, 기존 예산/캐시/이미지 선택 흐름을 확인했다.

진단 요약·공식 문서 사본·테스트 로그는 Git 제외 경로 `output/gemini-429-diagnosis-20261109/`에 보관했다. 운영 설정·스키마 변경 및 서비스 재시작은 하지 않았다.
