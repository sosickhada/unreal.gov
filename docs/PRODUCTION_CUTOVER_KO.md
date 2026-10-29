# 운영 전환과 롤백 (실행 전 사용자 승인 필요)

이 문서는 실제 전환 창의 실행 절차입니다. 이번 개발에서는 아래 운영 변경을 실행하지 않았습니다. 운영 DB 백업·읽기 전용 진단·복제 DB 마이그레이션·오프라인 테스트만 수행했습니다.

## 변경 내용과 사전 조건

현재 체크아웃은 `feat/full-automation-cloud`이며 기존 미커밋 변경을 유지합니다. 운영 서비스가 이 디렉터리를 직접 참조하므로 운영 중 git checkout/reset으로 되돌리지 않습니다. 커밋·push는 사용자 승인 후에만 수행합니다. 개발 중 기존 프로세스를 재시작하지 않습니다.

현재 운영 DB의 스키마는 구형입니다. 새 코드는 기존 행을 보존하는 스키마 버전 3 추가 마이그레이션이 필요합니다. 새 `quality_reviews`는 원고의 품질 검토를 버전별로 기록합니다. 기존 승인 3건은 삭제·재승인·자동 재게시하지 않습니다.

운영 환경에는 예전 `IG_ACCESS_TOKEN`, `IG_USER_ID`, `IG_USERNAME`이 있습니다. 새 Page/Facebook Login 방식의 `META_*` 설정으로 인증 방식을 확인하지 않고 임의 변환하지 않습니다. 기존 비밀값을 유지하면서 `.env.example`의 신규 설정을 안전한 편집기로 병합하세요. 파일 소유자는 서비스 사용자, 권한 0600, 환경파일을 셸 `source`로 실행하지 않습니다. 서비스와 CLI가 같은 `/opt/unreal.gov/.env`를 사용합니다.

필수 신규 설정:

- `CLAUDE_MODEL`: 실제 계정에서 사용 가능한 모델명. 모델을 추측하거나 실전 호출하지 않았습니다.
- `TELEGRAM_ALLOWED_USER_IDS`: 허용 사용자 ID 목록. chat ID와 별개입니다.
- `PUBLIC_BASE_URL=https://unreal-korea-media.duckdns.org`
- `IMAGE_DIR=/opt/unreal.gov/public/images`
- `RENDER_DIR=/opt/unreal-github/data/rendered`: 공개 루트 밖. 미리보기 파일은 이 디렉터리에 저장하고 Telegram에 첨부합니다.
- `UNREAL_BROWSER_PROFILE_DIR=/tmp`: PrivateTmp 내 디스크 프로필. 1GB 서버에서 큰 임시 파일을 /dev/shm에 유지하지 않습니다.
- `REQUIRE_TOPIC_IMAGE=1`: 운영에서는 항상 유지합니다.
- 최초 `ENABLE_EXTERNAL_CALLS=0`, `ENABLE_PUBLIC_MEDIA=0`, `INSTAGRAM_PUBLISH_ENABLED=0`.

사진 라이브러리에 검토 완료 고해상도 실사 2장 이상을 영속 경로로 등록해야 합니다. 주제 검색어의 모든 단어가 검토 태그에 포함되는 사진을 자동 선택합니다. 얼굴/실사성/라이선스는 휴리스틱으로 확정할 수 없으므로 담당자의 검토가 필요합니다. 사진이 없으면 안전하게 대기합니다. 운영 DB에 사진을 등록하는 작업도 전환 승인을 받은 뒤 수행합니다. 미검토 사진을 자동 확정하거나 합성 테스트 패턴을 운영 라이브러리에 넣지 마세요.

## 최소 승인 작업

1. 배포할 변경의 Git 커밋·push, 원격 legacy 예약 workflow 비활성화. 현재 원격 workflow는 active입니다. 수동 실행 기능은 새 VM 전용 `manual_vm.yml`로 유지합니다. self-hosted runner는 같은 VM/DB를 사용하고 비신뢰 PR을 실행하지 않도록 별도 권한을 제한해야 합니다.
2. 정비 창에서 기존 리스너 정지·안전한 환경 병합·운영 DB 백업/마이그레이션·새 worker와 단일 리스너 전환. 이미지 서버/Caddy는 동일 경로/포트이므로 변경하지 않아도 됩니다.
3. Claude/Telegram 최소 실전 검증을 위한 외부 호출 허용. 사진 라이브러리 등록 및 후보 생성 1회, 선택과 미리보기·승인을 확인합니다. Instagram은 계속 비활성.
4. 원격 예약 해제와 동일 날짜 실행키 확인 후 KST 18시 timer 활성화 및 부팅 활성화.
5. 별도 공개 이미지 승인 후 `ENABLE_PUBLIC_MEDIA=1`, 공식 Meta 계정/토큰/권한 검증 및 **별도 게시 승인**. Telegram에서의 콘텐츠 승인과 서버의 외부 공개·실제 게시 허용을 구분합니다.

## 승인된 정비 창에서의 실행 순서

아래는 실행할 명령을 검토하기 위한 예시이며 자동 실행 스크립트가 아닙니다.

```bash
cd /opt/unreal-github
# 외부 호출 없이 새 백업 생성 (파일명만 출력)
.venv/bin/python -m bureau.cli backup
# 운영 서비스 정지/변경에 대한 승인을 받은 뒤
sudo systemctl stop unreal-telegram.service
# 기존 설정/유닛/체크아웃을 접근 제한된 릴리스 백업에 보존
# 승인된 신규 환경 병합: 인증정보를 명령행/로그/저장소에 넣지 않음
.venv/bin/python -m bureau.cli migrate
.venv/bin/python -m bureau.cli health
.venv/bin/python -m bureau.cli doctor
# 세부 설정과 계정 누락 항목을 해결한 후에만 다음 단계 진행
sudo install -m 0644 deploy/unreal-worker.service /etc/systemd/system/
sudo install -m 0644 deploy/unreal-telegram.service /etc/systemd/system/
sudo install -m 0644 deploy/unreal-candidates.service /etc/systemd/system/
sudo install -m 0644 deploy/unreal-candidates.timer /etc/systemd/system/
sudo systemctl daemon-reload
# 허용된 Claude/Telegram 실전 검증을 위해 ENABLE_EXTERNAL_CALLS=1 병합 후
sudo systemctl enable --now unreal-worker.service unreal-telegram.service
```

`doctor`는 네트워크 호출 없이 필수 키의 존재, schema/integrity, 공개/비공개 경로, 미확인 작업을 검사합니다. 키 값은 출력하지 않습니다. 미완료 running/uncertain/sending이 있으면 먼저 조사하고, 단순 DB 초기화로 제거하지 마세요. 필요 시 worker 중지 확인 후 `recover JOB --worker-stopped`, 불확실한 유료 요청·게시는 자동 재호출하지 않습니다.

이미지 서버는 현재 active/enabled이며 변경이 필요 없습니다. `deploy/unreal-images.service`는 나중에 root 실행을 서비스 사용자로 바꾸고 리소스를 제한할 때 사용할 **선택적 템플릿**입니다. 이를 설치하는 변경은 별도 승인 대상입니다. 이미지 공개 파일은 0644로 원자적으로 생성하고 기존 다른 바이트를 덮어쓰지 않습니다.

원격 legacy workflow를 먼저 비활성화하고, 그 사실을 원격 조회로 확인한 뒤 다음을 실행합니다.

```bash
sudo systemctl enable --now unreal-candidates.timer
systemctl list-timers unreal-candidates.timer
systemctl is-enabled unreal-telegram.service unreal-images.service caddy.service unreal-worker.service unreal-candidates.timer
```

timer는 `18:00 Asia/Seoul`, `Persistent=false`이며 과거 날짜를 유료로 따라잡지 않습니다. 수동 workflow도 같은 SQLite의 날짜 실행키를 사용해야 합니다. GitHub-hosted VM과 별도 SQLite로 생성 작업을 실행하면 중복 방지를 공유할 수 없으므로 사용하지 않습니다.

## 전환 후 확인

- `doctor`, `health`: integrity=ok, schema=3, 미확인 running/uncertain/sending 조사.
- `/candidates` 후보 3개와 버튼의 DB ID 일치, 중복 클릭 시 원고 작업 1개.
- 원고 품질 대기 시 `/preview`, `/revise`, 또는 직접 문장 검토 후 `/acceptdraft ID VERSION`. 이는 최종 이미지 승인과 별개이며 잘못된 JSON/출처를 우회하지 않습니다.
- 본문/중간 결의의 서로 다른 실사·권리·얼굴·가독성 확인 후 `/review ID VERSION`, 승인 버튼. 4장 원고에서는 중간 결의 페이지가 없습니다.
- 공개 비활성 상태에서도 private 렌더링과 Telegram 미리보기는 가능. Instagram 단계는 안전하게 대기합니다.
- 공개 활성화 승인 후 공개 JPEG의 HTTPS 상태·포맷·해상도·해시 일치, Meta preflight, 게시 허용을 별도로 확인합니다.
- 서비스 `ActiveState`, `UnitFileState`, `NRestarts`, journal 오류, RSS 최종 성공 시간, 큐 적체, 디스크, 메모리·스왑을 점검합니다. 재부팅 자체는 이번에 실행하지 않았습니다.

## 리소스·로그

worker는 작업 1개, MemoryHigh=450M/MemoryMax=600M/MemorySwapMax=256M, CPUQuota=100%, TasksMax=128입니다. 서버 전체 RAM 약 958MiB이며 기존 서비스도 사용하므로 실제 운영 부하에서 재측정합니다. OOM/중단 시 자동 유료 재시도 대신 running/uncertain 상태를 조사합니다. Chromium 작업은 부모에서 시간 상한과 자식 프로세스 정리를 수행합니다. 고정 엔딩은 기존 원본 픽셀을 직접 검증·복사해 불필요한 CDP 전송을 줄이고 글꼴 캐시는 원본 폰트/부분집합 알고리즘/글자 집합으로 무결성을 검증합니다.

유닛에는 journal 출력, 30초당 100행 제한, 5분당 재시작 3회 제한을 둡니다. `deploy/journald-unreal.conf`는 100MB/14일 보관의 **호스트 전체 선택적 정책**이며 적용 시 다른 서비스에도 영향을 주므로 별도 승인 후 적용합니다. 현재 오류는 DB events와 Telegram outbox에 남습니다. Telegram 자체 장애를 감지하는 독립 외부 모니터링은 연결하지 않았습니다.

## 롤백

1. 사용자 승인 후 timer와 worker/리스너를 중지해 신규 외부 요청을 차단합니다. 이미 진행된 외부 요청을 취소했다고 가정하지 않습니다.
2. 현재 DB를 추가 백업하고 jobs/checkpoints/outbox/publications의 마지막 상태를 보존합니다. 불확실한 Claude/Telegram/Meta 요청의 외부 결과를 확인합니다.
3. 이전 릴리스 파일·유닛·환경파일을 별도 보존본에서 복구합니다. 개발 체크아웃을 `git reset --hard`로 정리하지 않습니다.
4. 추가 마이그레이션 DB는 기존 컬럼/행을 보존하므로 가능한 한 현재 DB를 유지합니다. 과거 DB 덮어쓰기는 이후 승인·전송 이력을 잃어 중복 게시를 유발할 수 있습니다. DB 복원은 별도 승인과 외부 결과 대조 후에만 수행합니다.
5. 승인된 이전 리스너 하나만 시작하고 상태를 확인합니다. 원격 예약과 timer를 동시에 복구하지 않습니다. 이미지 서버와 기존 공개 파일은 롤백 중 삭제하지 않습니다.
