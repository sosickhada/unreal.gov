# Instagram Login 전환 상태

이 구현은 graph.instagram.com과 Instagram Login 토큰만 사용한다.
Facebook Page와 META_* 설정은 사용하지 않는다.

필수: IG_ACCESS_TOKEN, IG_ACCOUNT_ID, IG_GRAPH_VERSION.
추가 안전 조건: IG_TOKEN_EXPIRES_AT (발급/갱신 응답으로 확인한 만료 Unix 시각).
토큰은 /opt/unreal.gov/.env에만 저장한다.

2026-10-31 읽기 전용 실검증:
- IG_ACCESS_TOKEN 존재. /v25.0/me HTTP 200.
- username un_real_korea, account_type MEDIA_CREATOR.
- user_id 17841458850796620. 별도 id 필드와 혼동하지 않는다.
- content_publishing_limit HTTP 200, 사용량 0/100.
- me/permissions 및 user_id/permissions HTTP 400 code 100.
- graph.instagram.com/debug_token HTTP 403 code 10.
따라서 토큰 인증은 확인했으나 권한 목록과 만료 시각은 아직 검증하지 못했다.
preflight는 권한/만료를 확인하지 못하면 실제 컨테이너 생성을 차단한다.
권한 조회 호환성은 추가 해결이 필요하며 현재 상태를 게시 준비 완료로 보지 않는다.

서버 환경파일에 IG_ACCOUNT_ID=17841458850796620, IG_GRAPH_VERSION=v25.0을 설정한다.
IG_TOKEN_EXPIRES_AT은 추측하지 않고 토큰 발급 응답 또는 공식 토큰 검사 결과로 설정한다.
필요 권한은 instagram_business_basic 및 instagram_business_content_publish이다.

장기 토큰 갱신 공식 경로는 GET https://graph.instagram.com/refresh_access_token
(grant_type=ig_refresh_token). 유효한 장기 토큰은 발급 후 24시간이 지난 뒤 만료 전에
갱신한다. 새 토큰과 expires_in 응답을 비밀 저장소에 원자적으로 반영해야 한다.
현재 작업에서는 토큰 교체나 갱신 요청을 실행하지 않았다.

INSTAGRAM_PUBLISH_ENABLED=0, ENABLE_PUBLIC_MEDIA=0을 유지한다.
작업 4 v2의 승인과 게시 작업 5는 보존되어 있다.
권한/만료 검증 문제 해결 및 별도 실제 게시 승인 전에는 /retry 5를 실행하지 않는다.
컨테이너 생성도 이번 작업에서는 실행하지 않았다.

공식 자료:
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing/
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login/
공식 문서 페이지는 이번 조회에서 HTTP 429/접근 실패를 반환했다.

## 마지막 진단 보정

권한 edge 실패 원문은 `Tried accessing nonexisting field (permissions)`이다.
따라서 이 응답을 게시 권한 거부로 해석하지 않는다. 이 edge를 필수 검사에서 제거했다.
debug_token 실패는 code 10 `Application does not have permission for this action`이다.
이를 토큰 만료 또는 게시 권한 부재의 증거로 해석하지 않는다.
Facebook Login용 진단법을 Instagram Login 사용자 토큰에 그대로 적용하지 않는다.
현재 로그인 사용자 토큰만으로 앱 모드/테스터 역할/App Review 상태를 확인하지 못했다.
instagram-check는 인증/권한/만료/앱 상태를 분리하여 미검증을 명시한다.
실제 게시 preflight는 권한 증거가 없는 동안 명시적으로 차단한다.
이 차단을 해제할 자동 권한 증거 수집은 아직 구현되지 않았다.

사용자 확인 경로 (Meta UI 버전에 따라 제품/사용 사례 메뉴 위치가 다를 수 있음):
1. developers.facebook.com/apps → 해당 앱 → Instagram → API setup with Instagram login.
   새 UI에서는 Use cases → Instagram 관련 사용 사례 → Customize에서 같은 설정을 찾는다.
   Generate access tokens의 계정이 un_real_korea인지 확인한다.
2. App roles → Roles에서 본인 관리자/개발자 또는 Instagram Tester 역할을 확인한다.
   Instagram 설정 → Website permissions → Apps and websites → Tester invites에서 초대를 수락한다.
3. App Review → Permissions and Features에서 instagram_business_basic 및
   instagram_business_content_publish의 접근 수준/승인 상태를 확인한다.
   앱 Dashboard의 Development/Live 상태도 확인한다.
   계정이 앱 역할 보유자인지와 외부 사용자 대상 여부에 따라 필요한 접근 수준이 다르다.
4. Meta Tools → Access Token Debugger (https://developers.facebook.com/tools/debug/accesstoken/)
   에서 토큰을 직접 검사한다. 지원되는 경우 Scopes, Expires, App ID를 확인한다.
   토큰 자체나 토큰이 포함된 URL을 공유하지 말고 권한명/만료시각/앱 모드/역할만 전달한다.
   이 도구에서도 검사할 수 없다면 미검증 상태를 유지한다.
5. 기존 발급 응답이 있으면 실제 permissions 및 expires_in을 확인한다.
   만료시각은 응답 수신 Unix 시각 + expires_in으로 기록한다. 발급일만으로 60일을 가정하지 않는다.
   갱신은 유효한 장기 토큰의 조건을 확인한 뒤 수행하며 응답의 expires_in을 저장한다.
