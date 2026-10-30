# Telegram 운영 전환 승인안

## 현재 확인 결과

- 브랜치: `feat/full-automation-cloud`. 기존 추적 파일 변경 14개 및 미추적 파일 보존. commit/push/checkout 미실행.
- Telegram active/running, NRestarts=0. 호스트에서 리스너 PID 473338 하나를 확인했다. 다른 호스트의 동일 토큰 polling은 외부 호출 없이 확인할 수 없다. 애플리케이션 singleton 잠금은 없다.
- Worker와 Candidates Timer는 비활성이며 이전 점검에서 유닛 미설치 상태를 확인했다. 실행 직전 재확인한다.
- 운영 DB schema=4, integrity=ok, doctor issues=[], jobs/outbox 비어 있음. 기존 DB 및 백업 보존.
- 기존 유닛과 새 유닛의 User/WorkingDirectory/ExecStart/Restart는 동일하다. 새 유닛은 EnvironmentFile=/opt/unreal.gov/.env, UMask=0077, TimeoutStopSec=30, NoNewPrivileges, PrivateTmp, ProtectSystem=strict 및 쓰기 경로 제한을 추가한다. 기존 유닛은 EnvironmentFile 없이 inline Environment 1개를 사용한다. 비밀값은 출력하지 않았다.
- 실행 중 프로세스의 상속 환경에는 세 가지 안전 플래그가 없었다. 프로그램이 이후 파일에서 읽었을 값이나 현재 프로세스 메모리 상태는 이 조회로 단정할 수 없다.
- 현재 파일 설정: 외부 호출/공개 이미지/Instagram 게시 비활성. 후보 curated, 뉴스 참조 비활성. 새 Telegram은 외부 호출 비활성 상태로 시작하면 실패하므로 지금 재시작하지 않는다.
- 18:00 Asia/Seoul=09:00 UTC. 다음 실행은 2026-10-31 09:00 UTC. Persistent=false, 지연 실행 없음. 날짜별 중복 접수 방지 및 18:00~18:04 실행 창 적용.

## 준비한 복구 자료

- 이전 Telegram 유닛과 운영 환경파일 사본: `data/backups/telegram-cutover-20261030T140645Z/`. 디렉터리 0700, 각 파일 0600. 비밀 환경파일은 Git 추적 대상이 아니다.
- 설치 후보 유닛 4개: `output/telegram-cutover-20261030/units/`. 원본 SHA-256은 같은 디렉터리 상위의 preparation.json에 기록했다. 설치 직전 원본 변경 여부를 대조한다.
- 운영 DB 백업은 앞선 점검의 SQLite 일관된 백업을 보존했다. 실제 전환 직전에 `bureau.cli backup`을 추가 실행한다.
- 현재 디스크의 코드는 이미 개발 변경을 포함한다. 실행 중 프로세스가 과거에 읽은 소스 전체를 복구 자료로 재구성할 수는 없다. 이전 동작 그대로의 복구를 보장하려면 알려진 이전 릴리스가 별도로 필요하다. 현 프로세스를 중지하기 전에 이 한계를 승인 범위에 포함한다.

## 승인 A: 설치만 수행

예상 영향: 유닛 파일 4개 설치와 systemd 설정 재로딩. 기존 Telegram 프로세스·환경은 유지되고 Worker/Timer 시작 및 부팅 활성화는 하지 않는다. 설치는 향후 수동 시작 및 서비스 재시작 시 사용할 설정을 바꾸므로 승인 후 실행한다.

```bash
cd /opt/unreal-github
.venv/bin/python -m bureau.cli backup
sudo install -m 0644 deploy/unreal-telegram.service deploy/unreal-worker.service deploy/unreal-candidates.service deploy/unreal-candidates.timer /etc/systemd/system/
sudo systemctl daemon-reload
systemctl show unreal-telegram.service unreal-worker.service unreal-candidates.timer -p Id -p ActiveState -p SubState -p MainPID -p NRestarts
```

기존 Telegram은 enabled이므로 유닛 교체 후 다음 부팅/비정상 종료 때 새 설정으로 재시작될 수 있다. 외부 비활성 상태에서는 시작 실패 가능성이 있어 설치 A도 승인된 정비 창에서 수행하고 B와의 간격을 최소화한다.

## 승인 B: 단일 Telegram 전환과 통신 허용

승인 범위: 기존 Telegram 중지 및 새 리스너 시작, Telegram 인증/polling/응답·실제 메시지 발송. Worker는 계속 중지 상태이므로 큐 기반 생성은 실행하지 않는다. `/whoami`와 callback 응답 등은 리스너에서 직접 전송될 수 있다. 일반 응답은 outbox에 대기할 수 있다.

```bash
sudo systemctl stop unreal-telegram.service
# 호스트에서 기존 MainPID 종료와 추가 리스너 없음 확인; 남아 있으면 진행 중단
sudoedit /opt/unreal.gov/.env
# 승인된 편집: ENABLE_EXTERNAL_CALLS=1
# 유지: ENABLE_PUBLIC_MEDIA=0, INSTAGRAM_PUBLISH_ENABLED=0
# 환경파일을 source 하거나 값 전체를 출력하지 않는다
cd /opt/unreal-github
.venv/bin/python -m bureau.cli doctor
sudo systemctl start unreal-telegram.service
systemctl show unreal-telegram.service -p ActiveState -p SubState -p MainPID -p NRestarts
```

이전 업데이트를 버리지 않는 drop_pending_updates=false 설정이다. 대기 중 업데이트가 DB 작업을 접수할 수 있으므로 Worker 승인 전 큐를 다시 검토한다. 앱 실행 명령을 별도로 수동 실행하지 않는다. 동일 토큰을 쓰는 다른 호스트가 없음을 전환 전에 확인해야 한다.

## 승인 C: Worker 및 매일 예약 실행

Worker를 외부 허용 상태에서 시작하면 후보 선택 후 Claude 유료 생성과 Telegram outbox 발송이 가능하다. curated 후보 모드 자체는 모델을 사용하지 않아도 기획안 생성은 유료 호출이다. 유료 사용 승인 없이 이 단계를 실행하지 않는다. Instagram과 공개 미디어는 계속 비활성으로 유지한다.

원격 legacy GitHub 예약 비활성 확인, 배포 변경의 리뷰/릴리스 고정, 라이브러리 실사 사진 검토·등록, 운영 큐 검토 후 아래를 실행한다. Git commit/push와 원격 조회·변경도 이번 준비 작업에서는 하지 않았다.

```bash
sudo systemctl enable --now unreal-worker.service
sudo systemctl enable --now unreal-candidates.timer
systemctl list-timers unreal-candidates.timer
systemctl show unreal-telegram.service unreal-worker.service unreal-candidates.timer -p Id -p ActiveState -p SubState -p NRestarts
```

Timer는 네트워크 호출 없이 날짜별 접수만 수행하며 Worker가 처리한다. 사진 라이브러리는 현재 비어 있어 실사 입력이 필요한 단계는 대기한다. 실전 메시지 및 유료 호출 검증은 승인된 사용자와 한 건으로 시작한다.

## 실패 시 복구

1. 승인된 전환 작업의 복구 범위로 Timer·Worker를 정지/비활성화하고 Telegram을 정지하여 신규 실행을 차단한다. 진행된 API 결과가 취소됐다고 가정하지 않는다.
2. `bureau.cli backup`으로 현재 DB를 다시 보존한다. running/uncertain/sending 작업과 외부 결과를 대조한다. 예전 DB로 덮어쓰거나 상태를 초기화하지 않는다.
3. 보존한 Telegram 유닛과 환경파일을 원래 경로에 복원한다. 환경파일은 0600으로 유지한다. 새 Worker/Timer는 중지·비활성 상태로 남긴다. daemon-reload를 실행한다.

```bash
sudo systemctl disable --now unreal-candidates.timer unreal-worker.service
sudo systemctl stop unreal-telegram.service
cd /opt/unreal-github
.venv/bin/python -m bureau.cli backup
sudo install -m 0644 data/backups/telegram-cutover-20261030T140645Z/unreal-telegram.service /etc/systemd/system/unreal-telegram.service
sudo install -m 0600 data/backups/telegram-cutover-20261030T140645Z/production.env /opt/unreal.gov/.env
sudo systemctl daemon-reload
```

복원 환경은 외부 호출 비활성이므로 현재 새 리스너 코드를 자동 시작하지 않는다. 알려진 호환 릴리스 및 외부 호출 승인 상태를 확인한 후 하나만 시작한다. Git reset, DB 복원, 불확실한 작업 재실행은 하지 않는다.

## 로컬 검증

- doctor/health, compileall, git diff --check 통과.
- systemd-analyze verify 종료 코드 0. 배포 대상과 무관한 호스트 netplan 권한 및 snapd RestartMode 경고가 있었다.
- 기존 전체 오프라인 테스트 99개 및 호스트 실제 Chromium 인수 테스트 통과 기록을 보존했다. 이번 변경은 운영 준비 문서와 로컬 스테이징뿐이며 전체 오프라인 테스트 재실행도 99개 모두 통과했다(89.981초). 로그: output/telegram-cutover-20261030/unittest.log.
- 이번 작업 중 서비스 중지·재시작·활성화, 환경 변경, API 호출, 실제 Telegram 발송, Instagram 게시를 실행하지 않았다.
