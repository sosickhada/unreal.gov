# 2026-10-30 실제 운영 전환 결과

사용자의 실제 Telegram 송수신·Claude 소액 호출·서비스 전환 승인에 따라 적용했다. Instagram 게시 및 공개 이미지는 비활성이다.

- 기존 Telegram PID 473338을 정상 종료한 뒤 새 리스너 PID 912488을 시작했다. 호스트 조회에서 리스너 하나만 확인했다. 다른 호스트의 동일 토큰 사용은 로컬 조회로 증명할 수 없다.
- Telegram 유닛과 Worker/Candidates service/timer를 설치하고 daemon-reload했다. Telegram·Worker는 active/running 및 부팅 enabled, Timer는 active/waiting 및 enabled이다.
- 다음 Timer 실행: 2026-10-31 09:00 UTC = 18:00 KST. 과거 예약을 따라잡지 않는다. timer는 날짜별 접수만 하고 Worker가 처리한다.
- /opt/unreal.gov/.env를 원자적으로 갱신했다. ENABLE_EXTERNAL_CALLS=1, AUTOMATION_PAUSED=0, ENABLE_PUBLIC_MEDIA=0, INSTAGRAM_PUBLISH_ENABLED=0. 비밀값은 출력하지 않았다.
- 실제 Telegram getMe 성공, webhook 없음. 별도 getUpdates 소비자는 실행하지 않았다.
- Claude 최소 실제 생성 1회 성공: 입력 16·출력 4토큰. SDK 자동 재시도는 0이다.
- 오늘(2026-10-30 KST) 후보 작업 1회, 후보 3개, 후보 메시지 하나 Telegram API 성공 응답 및 outbox sent/remote message 1개 확인. 후보 재발송은 하지 않았다. curated 모드는 유지했다.
- 사용자가 Telegram 후보 선택을 완료했고 Worker가 기획안 생성 요청을 실제 처리했다. 최초 응답은 검색어 102자(최대 100자) 및 비어 있어야 하는 엔딩 슬롯에 본문이 들어가 검증 실패했다. 원래 응답·실패 작업은 보존했다.
- 프롬프트에 검색어 80자 제한과 마지막 빈 객체 조건을 보강했다. 전체 오프라인 테스트 99개 통과(39.561초), compileall 및 diff --check 통과.
- 유휴 Worker를 재시작하고 선택 기록 4의 revision 2 수정 생성 작업을 한 번만 접수했다. 기존 작업의 체크포인트를 덮어쓰거나 무한 재시도하지 않는다. 결과는 아래 최종 확인에 기록한다.
- 운영 사진 라이브러리는 비어 있다. 기획 승인 후 이미지 작업은 서로 다른 실사 2장의 출처·권리·관련성·얼굴 검토가 충족되어야 진행한다. 이를 우회하거나 합성 테스트 이미지를 운영 사진으로 등록하지 않았다. 최종 승인·실제 이미지 앨범 전달은 아직 운영 검증 전이다.
- 최초 전환 후 Telegram과 Worker의 자동 NRestarts는 0이었다. 반복 실패 작업은 자동 재큐잉하지 않으며 불확실한 응답은 사람의 확인 전 재호출하지 않는다.

## 보존 자료와 복구

- 전환 직전 SQLite 백업: data/backups/preflight-2026-10-30T14-14-50.882152+00-00.sqlite3.
- 이전 운영 환경파일·Telegram 유닛: data/backups/live-cutover-20261030T141450Z/ (디렉터리 0700, 파일 0600).
- 근거: output/live-cutover-20261030/의 connection.json, cutover.json, service-state.json, pipeline-state.json, journal-redacted.log, unittest-after-prompt-fix.log.
- 실패 복구는 Timer·Worker·Telegram을 정지해 신규 외부 요청을 차단하고 현 DB 추가 백업 후 이전 환경·유닛을 복원한다. 기존 DB는 덮어쓰지 않는다. 이전 환경은 외부 호출 비활성이므로 새 코드 리스너를 무조건 재시작하지 않는다. 호환 릴리스·통신 설정을 확인한다.
- 기존 Git 변경을 보존했고 commit/push/reset하지 않았다. 원격 legacy GitHub 예약의 비활성 상태는 확인하지 않았으므로 별도 운영 확인 항목이다. 로컬 legacy workflow에는 실행 차단 게이트가 있다.

## 최종 확인 (2026-10-30 14:19 UTC)

- Telegram PID 912488, Worker PID 913142: active/running, enabled, NRestarts=0. 리스너는 1개.
- Timer active/waiting, enabled, 다음 2026-10-31 18:00 KST.
- 선택 기록 4 v2는 planning_review. 수정 생성 작업 3 succeeded, 기획안 outbox draft:4:2 sent. 원래 실패 작업 2는 waiting 상태로 보존했고 재실행하지 않는다.
- Claude 원고 생성 사용량: 최초 입력 1334/출력 3615, 수정 입력 1622/출력 3317토큰. 별도 연결 검증 입력 16/출력 4토큰 포함 실제 호출은 총 3회.
- 운영 DB integrity=ok. 후보 3개가 든 메시지는 정확히 1회 sent. Instagram 비활성.
- 다음 사용자 동작: 기획안 4 v2의 기획 승인(또는 기획 수정). 사진 등록 전 이미지 단계는 안전하게 대기하며 실제 이미지 생성·최종 승인 완료를 보고한 것은 아니다.
- 최종 근거: output/live-cutover-20261030/final-state.json.
