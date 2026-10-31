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
