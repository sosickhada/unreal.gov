# Instagram Login 게시 준비 및 운영 절차

후속 상태: 기존 4번 v2는 사용자 지시에 따라 테스트 게시물로 철회했다.
첫 공식 콘텐츠는 7번 v2이며 [제작 기록](first-official-content.md)을 참조한다.
아래 4번 전송 기록은 당시 연동 확인 이력이다.

2026-11-10 운영 실측 (비밀값은 기록하지 않음):

- `graph.instagram.com/v25.0/me`: HTTP 200, `un_real_korea`,
  `user_id=17841458850796620`, `MEDIA_CREATOR`.
- `/{account}/content_publishing_limit`: HTTP 200,
  `quota_usage=0`, `quota_total=100`, `quota_duration=86400`.
- `me/permissions`: HTTP 400 / code 100. 이 edge 오류는 게시 권한 부족의 증거가 아니다.
- 완성 카드뉴스 4번 v2의 실제 이미지로 `POST /{account}/media`
  (`is_carousel_item=true`) 성공, 컨테이너 `17976542729961694` 상태 `FINISHED`.
  **미게시 컨테이너이며 `media_publish`를 호출하지 않았다.**
- 5장 모두 공개 HTTPS HTTP 200 / RGB JPEG 1080×1350 / 8 MB 미만,
  로컬 승인 자산과 공개 응답의 SHA-256 및 바이트 일치 확인.
- Telegram 앨범 메시지 127–131 및 실제 게시 승인 메시지 132 전송 성공.
  사람의 승인/취소 클릭과 공개 게시 성공 여부는 별도 운영 기록으로 확인해야 한다.

이전 UNKNOWN의 원인은 `preflight()`의 무조건 예외 발생, 운영 환경파일의
`IG_USER_ID`와 코드가 요구하는 `IG_ACCOUNT_ID` 차이, `IG_GRAPH_VERSION` 누락,
게시/공개 이미지 비활성 설정이었다. 기존 이미지 URL도 실제 파일이 없어 404였다.
운영 환경에는 명시적인 계정 ID와 API 버전을 추가하고 공개 이미지 제공을 활성화했다.

## 승인 및 게시

```bash
.venv/bin/python -m bureau.cli instagram-check
.venv/bin/python -m bureau.cli instagram-review RECORD_ID REVISION
```

두 번째 명령은 완성 이미지 5장과 현재 캡션을 검증하고 Telegram 전송 대기열에 넣는다.
Worker가 앨범 전송 성공 후 승인 UI를 전송한다. 승인 버튼은 계정·전체 원고·이미지
목록/URL/해시의 fingerprint에 결합된다. 이전 승인 기록은 새 요청을 승인하지 않는다.
사용자/채팅 허용 목록을 통과한 `igapprove` 콜백만 정확한 콘텐츠의 승인과 게시 작업을
하나의 DB 트랜잭션으로 저장한다. `igcancel`은 게시 작업을 만들지 않는다.
일반 미리보기의 기존 `approve` 콜백만으로는 새 Instagram 승인 검증을 통과하지 못한다.

Worker는 시작 시점과 `media_publish` 직전에 현재 계정, 원고, 자산 메타데이터 및 로컬
이미지 바이트를 승인 기록과 비교한다. 달라지면 새 승인 요청이 필요하다. 수정 콘텐츠는
새 revision과 새 파일명으로 렌더링한다. 기존 공개 파일의 다른 바이트 덮어쓰기는 금지한다.

## 권한 증거 및 복구

`data/instagram-grant.json`은 접근 제한된 운영 전용 파일이며 Git에 포함하지 않는다.
실제 미게시 컨테이너 생성 성공과 토큰 SHA-256 및 계정 ID를 결합한다. 토큰 자체는 저장하지
않는다. 매 게시 사전 점검은 프로필 인증과 계정 일치, professional 유형, 현재 토큰에 대한
컨테이너 생성 증거, 실시간 게시 한도를 확인한다. 토큰을 교체하면 새 토큰의 미게시 컨테이너
생성으로 증거를 다시 검증해야 한다. 이 파일은 재사용 가능한 컨테이너 캐시가 아니다.
게시 권한 준비 확인과 실제 공개 게시 성공은 구분한다.

각 자식/캐러셀 생성 및 공개 게시 쓰기는 호출 전 durable checkpoint에 기록된다.
타임아웃/프로세스 종료로 외부 결과가 불명확하면 `uncertain`으로 두며 자동 재시도하지 않는다.
확정 실패/대기는 `/retry JOB_ID`로 저장된 단계부터 재개한다. 성공한 컨테이너는 재생성하지 않는다.
게시 ID는 `publications.media_id`, `selections.published_id`에 저장한다. URL은
`ig_permalink` 체크포인트, `events`의 `instagram_permalink`, Telegram outbox에 저장한다.
URL 조회 실패로 공개 게시를 반복하지 않는다. 컨테이너 만료/외부 쓰기 결과 불명확은
운영자가 실제 계정 상태를 조사한 뒤 처리한다.

기존 후보 생성 job 19의 유료 요청 결과 불명확 상태는 유지한다. 기존의 명시적
`WORKER_ALLOW_ISOLATED_UNCERTAIN=1` 설정은 해당 작업을 재실행하지 않고 다른 안전한
작업을 처리하도록 허용한다.

운영 DB 백업은 `data/backups/preflight-2026-11-10T01-19-09.491119+00-00.sqlite3`에 생성했고,
추가 스키마 마이그레이션도 별도 백업 후 수행했다. 백업은 SQLite backup API와 integrity
검증을 사용하며 권한은 0600이다.

공식 참고:
- https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing/
- https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login/
- https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-fc851f39-7194-4522-a475-2cea8de46d16

Meta 개발자 문서는 이번 브라우징에서 429/접근 오류를 반환했다. Meta 공식 Postman 문서의
Instagram Login 권한 안내와 운영 API 실측을 함께 확인했다. Facebook Login 경로로 전환하지 않는다.

## 배포 검증

- Python 전체 unittest: 178개 통과.
- Node Puter bridge: 4개 통과.
- 최신 Worker 코드의 게시 1회 실행 및 불확실한 게시 복구 추가 검증: 2개 통과.
- 토큰 바인딩/한도, 콘텐츠 변경, 계정 변경, 이미지 바이트 변경, 취소,
  미승인 차단, 승인 콜백 허용 목록 및 중복 클릭 테스트 포함.
- 운영 `INSTAGRAM_PUBLISH_ENABLED=1`, `ENABLE_PUBLIC_MEDIA=1` 설정 적용.
  운영 서비스는 승인된 정확한 콘텐츠만 게시한다.
- Telegram 리스너와 Worker를 새 코드/환경으로 재시작한다. 이미지 서버는
  기존 실행을 유지하며 실제 HTTPS 이미지 응답으로 정상 동작을 확인한다.
- Git 변경 내용에 운영 비밀값이 포함되지 않았음을 검사했다.
