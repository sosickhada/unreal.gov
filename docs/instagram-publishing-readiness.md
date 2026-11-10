# Instagram Login 게시 차단 진단

현재 실측: graph.instagram.com/v25.0/me 프로필 인증 200, MEDIA_CREATOR,
계정 user_id 일치. content_publishing_limit 200, quota_usage 0.
me/permissions 400/code 100은 이 경로에서 권한을 확인할 수 없다는 뜻이며,
게시 권한이 없다는 판정으로 사용하지 않는다. 한도 조회도 게시 권한 증명이 아니다.

공식 확인 경로:
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login/
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing/

Meta 개발자 대시보드에서 대상 앱을 선택하고 Instagram > API setup with Instagram login
(대시보드 언어/앱 유형에 따라 명칭이 다를 수 있음)을 확인한다.
instagram_business_basic 및 instagram_business_content_publish 설정과 발급 시 동의 범위를 확인한다.
App roles에서 대상 계정의 역할 및 Instagram 테스트 초대 수락 여부를 확인한다.
개발 모드에서는 앱 역할 계정 조건을 확인하고, 일반 외부 계정 서비스에는 App Review의
Permissions and Features에서 필요한 접근 수준과 앱 Live 상태를 확인한다.
Facebook Login이나 Facebook Page 연결로 경로를 전환하지 않는다.

권한 재동의가 필요하면 해당 앱의 Instagram Login 설정에서 등록된 redirect URI와
Instagram 앱 ID로 공식 Business Login 절차를 시작한다. authorization code 교환은 서버에서
처리해야 하며, OAuth state를 세션에 결합해 검증해야 한다. 현재 저장소에는 완전한 OAuth
callback 서버가 구현되지 않았으므로 임의 재인증 링크를 운영 사용자에게 제공하지 않는다.

Telegram의 차단 UI는 진단 전용이다. 승인/상태 버튼은 게시 작업을 생성하지 않는다.
미리보기 닫기는 키보드만 제거한다. 운영 게시 취소로 해석하면 안 된다.
