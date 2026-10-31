# Instagram 운영 준비

현재 Facebook Login 기반 Graph API 구현을 사용한다. 실제 게시 테스트는 별도 승인이 필요하다.

필수 환경변수: META_ACCESS_TOKEN, META_APP_ID, META_APP_ACCESS_TOKEN,
INSTAGRAM_ACCOUNT_ID, META_PAGE_ID, META_GRAPH_VERSION. 비밀값은 채팅이나 로그에 붙이지 않는다.

Meta 앱에서 Facebook Login과 Instagram API를 구성하고 Facebook Page에 연결된
Business 또는 Creator Instagram 계정을 준비한다. 토큰에는 instagram_basic,
instagram_content_publish, pages_read_engagement 권한이 필요하다. 계정 탐색을 한다면
pages_show_list도 필요하다. 앱 모드·앱 역할과 계정 접근 권한을 확인하고 외부 고객 계정을
지원할 경우 해당 권한의 Advanced Access/App Review 요건을 확인한다.
공식 참고: https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api

설정 후 `.venv/bin/python -m bureau.cli instagram-check`로 읽기 전용 검증한다.
게시 비활성 상태에서도 토큰 앱/유효기간/권한, Page 연결, 계정 유형, 게시 할당량을 검사한다.
필수 설정이 없으면 네트워크 요청 없이 변수명만 안내한다.

현재 작업 4 v2는 최종 승인되어 있고 게시 작업 5가 대기 중이다.
운영 게시를 승인받은 뒤에만 INSTAGRAM_PUBLISH_ENABLED=1 및 ENABLE_PUBLIC_MEDIA=1을
설정하고 서비스를 재시작한다. 기존 승인 작업은 Telegram `/retry 5`로 재개한다.
새 작업이나 승인을 생성하지 않는다. 이 명령은 설정이 활성화되면 실제 게시로 이어진다.
RENDER_DIR의 이미지는 게시 단계에서 공개 경로로 복사되며 HTTPS URL 바이트·형식·크기를 검증한다.

자식 컨테이너 → 준비 상태 조회 → 캐러셀 → 준비 조회 → 게시 → permalink 순서로 처리한다.
각 외부 쓰기는 영속 체크포인트를 남긴다. 결과 불명확 시 자동 재시도하지 않는다.
단순 처리 지연도 자동 반복하지 않고 원인 확인 후 기존 작업을 명시적으로 재개한다.
permalink 조회 실패는 게시 자체를 반복하지 않는다.

서비스 중단으로 running 작업이 남으면 worker가 추가 작업을 가져가지 않는다.
worker를 정지한 상태에서 `recover JOB --worker-stopped`로 확인·복구한다.
Claude/Meta 외부 쓰기의 uncertain 기록은 실제 결과 대조 전 재실행하지 않는다.
Telegram sending/uncertain도 전달 여부 확인 후에만 명시적으로 복구한다.
매일 18:00 Asia/Seoul 타이머를 사용하며 지난 날짜 후보를 몰아서 보내지 않는다.
