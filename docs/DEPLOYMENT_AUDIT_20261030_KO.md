# 2026-10-30 운영 배포 점검

## 완료한 작업

- `feat/full-automation-cloud`의 기존 수정 14개 및 미추적 파일을 확인하고 보존했다. 커밋, push, checkout, 서비스 변경은 실행하지 않았다.
- 운영 환경파일 `/opt/unreal.gov/.env`를 실행하거나 비밀값을 출력하지 않고 읽었다. 권한은 0600이며 운영 DB 경로가 요청과 일치한다.
- SQLite backup API로 운영 DB를 일관된 읽기 전용 원본에서 추가 백업했다: `data/backups/preflight-2026-10-30T13-55-13.767630+00-00.sqlite3` (0600).
- 백업 SHA-256: `cbd8adf9fef504a2366538d705a629cc0f37187db5ec536b3a64c4c864a767b1`.
- 기존 선택 기록의 원래 컬럼 전체를 백업과 대조하며 운영 DB에 트랜잭션 기반 추가 스키마 v4를 적용했다. 기존 3건의 모든 원래 값이 동일하다. 승인·게시 작업을 추가하지 않았다.
- systemd 배포 템플릿 5개를 검증했다. Telegram은 active/running, enabled, NRestarts=0, MainPID=473338이다. Worker 및 Candidates service/timer는 설치되지 않았고 비활성이다.
- 호스트 프로세스 조회에서 `/opt/unreal-github/telegram_listener.py` 리스너 1개를 확인했다. 샌드박스 내부 프로세스 조회는 운영 프로세스를 볼 수 없으므로 호스트 조회를 기준으로 한다.
- 현재 환경의 외부 호출·공개 이미지·Instagram 게시 플래그는 모두 비활성이다. 후보 모드는 curated, 뉴스 참조는 비활성이다.
- 비공개 렌더 디렉터리 `/opt/unreal-github/data/rendered`를 0700으로 생성했다. 공개 이미지 디렉터리는 호스트에서 서비스 사용자 소유·0755·쓰기 가능임을 확인했으며 변경하지 않았다. 샌드박스의 쓰기 불가 판정은 호스트 권한과 구분한다.

## 테스트 결과

- 운영 DB와 추가 백업의 `PRAGMA integrity_check`: ok. 운영 DB `foreign_key_check`: 위반 없음. schema_version=4.
- 마이그레이션 후 doctor: ready_for_worker=true, issues=[], 필수 설정 누락 없음. jobs/outbox 모두 비어 있다. 이는 로컬 준비 판정이며 계정 인증·외부 통신 성공을 뜻하지 않는다.
- 최초 오프라인 unittest 99개 통과(51.298초). 마이그레이션 후 전체 재실행도 99개 통과(156.525초).
- 실제 Chromium 인수 테스트 최초 실행은 브라우저 시작 단계에서 렌더 작업이 ExternalError로 실패하고 preview_ready 단언 실패를 출력했으며, 전체 명령은 제한 시간 초과(exit 124)로 종료됐다. 이 실패를 보존했다. 외부 소켓 차단·모의 공급자를 유지한 호스트 재검증 결과는 최종 검증 기록에 명시한다.
- compileall 및 git diff --check 통과.
- systemd-analyze verify 종료 코드 0. 호스트의 무관한 netplan 접근 권한 및 snapd RestartMode 경고가 있으며 검토 대상 배포 유닛 오류는 보고되지 않았다.
- calendar는 매일 18:00 Asia/Seoul=09:00 UTC, 다음 실행 2026-10-31 09:00 UTC로 해석된다. timer는 Persistent=false, 무작위 지연 없음. bot.py는 18:00~18:04 KST만 접수하며 날짜별 실행키를 공유한다. 실제 운영 DB에는 테스트 후보 작업을 접수하지 않았다.
- 후보 3개, 중복 선택 방지, 기획안 수정, 원고 승인 후 이미지 작업 1개, 이미지 수정 시 원고 보존, 이전 버전 승인 거부, 최종 승인 중복 방지, 모의 게시 결과 링크 및 재게시 방지를 격리 DB/모의 어댑터 테스트로 확인했다. 운영 메시지·유료 생성·게시 검증은 수행하지 않았다.

## 남은 문제

- 기존 설치 Telegram 유닛은 새 템플릿과 다르다. EnvironmentFile 지시자가 없고 inline Environment 지시자가 1개 있다. 실행 중 프로세스는 재시작 전 코드·환경을 계속 사용할 수 있다. 현재 파일의 비활성 플래그가 실행 중 프로세스에도 적용됐다고 단정할 수 없다.
- 애플리케이션 수준 polling singleton 잠금이 없다. 현재 로컬 리스너는 1개이지만 수동 추가 실행 및 다른 호스트의 동일 토큰 polling은 별도로 통제해야 한다. 원격 상태는 외부 API 호출 금지 원칙에 따라 조회하지 않았다.
- 로컬 legacy workflow는 비활성화 게이트 및 명시적 실패 처리로 실행을 막지만, 원격 GitHub에 반영됐는지와 예약 비활성 상태는 미확인이다. Timer 활성화 전에 원격 확인이 필요하다.
- 현재 외부 호출 비활성 상태에서는 Worker가 curated 모드 작업도 실행하지 않는다. Timer 설치만으로 후보 3개 생성·전달이 완성되는 것은 아니며 단일 리스너·Worker 및 승인된 외부 호출 설정 전환이 필요하다.
- Instagram 미설정: META_ACCESS_TOKEN, META_APP_ID, META_APP_ACCESS_TOKEN, META_PAGE_ID, INSTAGRAM_ACCOUNT_ID, META_GRAPH_VERSION. 기존 IG_* 값을 임의 변환하지 않았다.
- Meta 계정/토큰의 유효성·만료·앱 일치, Facebook Page와 professional account 연결, instagram_basic/instagram_content_publish/pages_read_engagement 권한, 게시 할당량 및 공개 JPEG HTTPS 바이트 검사는 실제 연동 승인 후 확인해야 한다. 이 목록은 저장소 어댑터의 검사 항목이며 최신 Meta 정책을 외부 조회한 결과가 아니다.
- 운영 사진 라이브러리는 0건이다. 운영용 주제 실사 사진의 라이선스·관련성·얼굴·실사성 검토와 라이브러리 등록이 필요하다. 합성 인수 테스트 이미지는 운영에 등록하지 않는다.
- 이전 PRODUCTION_CUTOVER_KO.md에는 schema=3 및 운영 DB 미변경이라는 과거 상태가 남아 있다. 이번 DB 적용 상태는 본 보고서와 migration.json을 기준으로 한다.

## 사용자 승인이 필요한 작업

1. 정비 창에서 기존 Telegram 리스너 정지, 유닛 설치·daemon-reload, 단일 리스너와 Worker 전환 및 시작/부팅 활성화. 새 리스너를 기존 리스너와 동시에 시작하지 않는다.
2. 배포 변경 커밋·push 및 원격 legacy 예약 해제/확인 후 Candidates Timer 설치·활성화.
3. 검토 완료 사진 등록, 외부 호출 플래그 활성화와 Claude/Telegram 실전 검증. curated 모드를 유지할지 모델 기반 후보로 변경할지도 전환 설정에 명시한다.
4. Meta 설정 병합·계정 검증·공개 이미지 허용과 실제 Instagram 게시는 각각 별도 승인한다.

로컬 근거 파일은 `output/deployment-audit-20261030/`에 보관한다. 환경파일과 운영 서비스는 변경하지 않았으며 외부 API 호출·Telegram 발송·Instagram 게시를 실행하지 않았다. 롤백 시 이후 기록을 잃는 과거 DB 덮어쓰기는 수행하지 말고, 현 DB를 추가 보존한 뒤 별도 복구 승인을 받는다.

## 최종 검증 기록

- 호스트에서 동일 실제 Chromium 인수 테스트 재실행: PASS, exit 0. 보고서: `output/offline-acceptance/2026-10-30T14-01-25.673292+00-00/report.json`.
- 실제 PNG/JPEG 5장, 각 1080×1350 및 8MB 미만, 고정 페이지 1·4·5 픽셀 동일, 사진 교체 페이지 2·3 변경을 확인했다. 합성 테스트 입력이며 운영 실사 검토를 대신하지 않는다.
- 외부 호출 0, Claude 모의 호출 2회. Telegram 전달은 모의 처리이고 Instagram 실게시 없이 publish_waiting으로 종료했다.
- 최초 샌드박스 실패 로그와 성공한 호스트 로그·보고서는 `output/deployment-audit-20261030/`에 함께 보존했다.
- 마지막 운영 health: schema=4, integrity=ok, jobs/outbox 비어 있음. 운영 선택 기록 3건·사진 라이브러리 0건.
- 실제 서비스 전환은 미실행이며, DB 준비와 로컬 검증이 완료된 승인 대기 상태다.
