# 중단 시점 인계 (2026-10-30)

사용자의 긴급 종료 요청으로 현재 상태를 GitHub에 백업한다. 아래 미완료 사항을 성공으로 간주하지 않는다.

## 운영 상태

- 프로젝트 `/opt/unreal-github`, 운영 환경 `/opt/unreal.gov/.env`, DB `/opt/unreal-github/unreal_bot.db` (schema v4).
- Telegram/Worker/매일 18:00 KST Timer 설치·활성화 완료. 단일 Telegram 리스너로 전환했고 실제 후보 3개를 담은 메시지 1회 발송 성공.
- 실제 Claude 기획안 생성·수정·Telegram 전달 성공. 선택 기록 4의 revision 2를 사용자가 기획 승인했다.
- 외부 호출 허용, 자동 사진 모드 허용. 공개 이미지와 Instagram 게시는 비활성. 비밀값은 이 문서에 기록하지 않는다.
- 운영 DB와 백업·환경파일·다운로드 사진·렌더 결과는 GitHub에 업로드하지 않는다. 기존 서버 경로에 보존한다.

## 이미지 파이프라인 구현

- 기존 Pixabay 검색·다운로드 재사용. 기본 키는 1280px만 제공하므로 원본 해상도 부족 시 Commons의 명시적 CC0 사진으로 대체한다.
- 슬롯별 최초 검색+대체 검색 최대 2회, 캐시 24시간, 후보별 다운로드/해상도/형식/SHA-256/지각 해시 검사, Claude 시각 검사, 출처·라이선스·검사 근거 저장.
- 자동 선정은 사람 검토 완료로 표시하지 않는다. 모든 시각 검사 항목 true 및 confidence>=0.9 조건이다. 실제 검사에서 confidence=0.8인 사진은 거부됐으며 이 조건을 낮추지 않았다.
- 검색 소진 시 Telegram에 출처와 이미지 수정/검색어 변경 버튼을 보낸다. draft_ready에서도 이미지 수정이 가능하다.
- 공식 `thumb.wikimedia.org` 반환 URL 지원 및 HTTP 429 다운로드 중단/대기 파일을 구현했다.
- Claude 검사 응답 한도를 1536, effort low로 설정했다. 알려진 불완전 응답은 결과를 저장하고 중단한다. 네트워크 불확실성은 자동 재호출하지 않는다.

## 현재 미완료 및 안전한 재개

- render 작업 **4는 waiting / requirements_missing**이다. 마지막 단계 `claude_photo_v2_resolution_extra_2_commons-135605646`.
- **완성 카드뉴스의 Telegram 이미지 전달은 아직 성공하지 않았다.** 적합한 사진 2개를 모두 확보하지 못했다.
- 최초 고해상도 사진 1개 다운로드 후 시각 검사 `claude_photo_v2_content_1_commons-140349589`가 uncertain으로 남았다. 응답/비용 확정 불가이며 이 사진은 제외 목록에 넣었다. 해당 체크포인트를 삭제·성공으로 변경하거나 같은 사진을 유료 재호출하지 않았다.
- `bureau.cli.resume_photo_render`는 다른 유형의 불확실한 요청을 거부하고, 사진 검사 불확실성을 보존하면서 해당 source ID를 제외하는 제한된 운영 복구 함수다. 이미 한 번 사용했다. 현재 waiting 상태에서 일반 `/retry 4`는 잔존 uncertain 체크포인트 때문에 차단될 수 있다. 이를 무조건 초기화하지 않는다.
- 나머지 실제 시각 검사들은 정상 수신됐지만 상점 간판·인물 가능성·주제 불일치 또는 확신도 부족으로 제외됐다. 검색 결과 상위 후보에 상점 외관/박물관 사진이 치우쳐 선정 순위 개선이 필요하다. 기존 검색 캐시와 검사 결과를 재사용하고 검색 횟수·일일 호출 예산을 지켜야 한다.
- 다음에는 먼저 현재 jobs/checkpoints/image_inputs/outbox 및 Worker 상태를 읽기 전용으로 확인한다. 기획안/승인/버전은 보존한다. 사람 검토 완료를 허위 기록하거나 검증 기준을 몰래 우회하지 않는다.
- 작업이 waiting이므로 Worker는 작업 4를 자동 반복 실행하지 않는다. Timer는 다음 예약 시각의 후보 생성 접수용이다.

## 테스트 및 근거

- 전체 오프라인 테스트 109개 통과(171.512초, 호스트 수정 전).
- 공식 호스트·429 보강 후 사진 파이프라인 회귀 11개 통과(84.023초).
- 최종 시각 검사/불확실 사진 제외 복구 테스트 6개 통과(9.994초).
- 마지막 변경 전체를 합친 통합 테스트 116개 일괄 실행은 아직 하지 않았다. 다음 작업에서 필요 시 실행한다.
- 테스트 로그: `/tmp/unreal-auto-photo-all-tests.log`, `/tmp/unreal-auto-photo-final-regression.log`, `/tmp/unreal-photo-screening-final-tests.log`.
- 마지막 복구 직전 DB 백업: `data/backups/preflight-2026-10-30T14-49-18.585656+00-00.sqlite3`.
- 상세 문서: `AUTOMATIC_PHOTOS_KO.md`, `LIVE_CUTOVER_RESULT_20261030_KO.md`, `TELEGRAM_CUTOVER_PLAN_20261030_KO.md`.
