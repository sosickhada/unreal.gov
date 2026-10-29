# Chromium 렌더링 진단 및 검증 결과

## 결과

실제 가상 원고로 4장과 5장 PNG를 생성했습니다. 원본 DB·systemd·Caddy·Telegram 설정은 수정하거나 재시작하지 않았고 Claude/Telegram/API는 호출하지 않았습니다.

산출물: `/opt/unreal-github/output/render-smoke/acceptance/`

- 4장: `case-4_01.png` ~ `case-4_04.png`
- 5장: `case-5_01.png` ~ `case-5_05.png`
- `verification.json`: 9개 PNG 경로·SHA-256·1080×1350 확인·폰트·잘림·엔딩 검증
- `case-5-report.json`: 전체 smoke PASS 및 관측 프로세스 잔존/좀비 0
- `case-4-trace.json`: 4장 저장·검사 및 브라우저/driver 종료 완료
- `case-overflow-report.json`: 긴 제목의 실제 overflow 거절 및 프로세스 종료 PASS
- `lossless-comparison.json`: 고속 PNG와 기존 PNG 4개의 픽셀 완전 일치

| 검증 | 결과 |
|---|---|
| 5장 렌더 및 driver 종료 | 57.739초, 75초 watchdog 내 smoke 전체 PASS |
| 4장 렌더 및 driver 종료 | 67.945초, PNG 4개 저장 및 정상 종료 |
| 4장 전체 smoke | 후속 이미지 비교 중 75초 watchdog 도달. 전체 PASS라고 기록하지 않음 |
| 렌더링과 분리한 9장 검증 | PASS, 모든 PNG 1080×1350, 텍스트/폰트 검사 통과 |
| 고정 엔딩 | 4장/5장 모두 승인 원본과 RGB 픽셀 완전 일치 |
| 표지·본문·중간·최종 판정 | 이전 Playwright PNG와 고속 PNG의 RGBA 픽셀 완전 일치 |
| 실제 긴 제목 | 바닥 좌표 약 15148px로 overflow 감지, PNG 저장 전에 거절 |
| 호스트 진단용 Chromium 잔존 | 없음 |
| 오프라인 회귀 테스트 | 43개 PASS, 네트워크 차단·임시 DB 사용 |

따라서 실제 PNG 생성 실패는 해소됐지만, 이 1GB VM에서 **항상 75초 안에 전체 QA까지 끝난다는 성능 보장은 아직 없습니다**. 콜드 폰트 캐시·호스트 swap/I/O 상태에 따라 편차가 큽니다. 반복 timeout은 자동 무한 재시도하지 않습니다.

## 단계별 원인 구분

1. **실행 샌드박스**: 직접 Chromium 실행이 `setsockopt: Operation not permitted`, SIGTRAP(-5)로 종료됨. 이 제한은 애플리케이션의 `--no-sandbox`와 별개인 Codex 실행 환경 제한. 허용받은 샌드박스 밖 로컬 진단에서 비교.
2. **설치/Playwright**: 실행 파일과 공유 라이브러리 존재. driver 단독 시작/종료 성공. 설치된 Playwright는 `headless=True`에서 headless shell을 선택함을 로컬 패키지 코드와 실제 실행 로그로 확인. `chromium.executable_path`가 가리키는 전체 Chrome을 직접 실행한 결과만으로 렌더러의 실행 바이너리를 판단하지 않음.
3. **전체 Chrome vs headless shell**: 전체 Chrome은 `/tmp`와 `/dev/shm` 프로필 모두 디스크 대기 `D`, `folio_wait_bit_common` 관측. headless shell의 RAM 프로필 직접 about:blank 실행은 8.73초에 정상 종료.
4. **VM 자원**: RAM 약 981MB, `/dev/shm` 약 480MB. VM의 swap 사용 약 400MB, 측정 구간 I/O wait 55~89%, swap-in 2~4MB/s. OOM kill은 확인하지 않았음. 브라우저 시작과 캡처 단계의 지연이 실행마다 달라졌고, 단일 코드 지점의 영구 교착으로 단정할 수 없음.
5. **폰트**: 승인 본문 TTF가 약 22MB. 이를 매번 전체 로딩하고 Python에서 서브셋 준비와 Node/Chromium을 동시에 띄우는 것은 불필요한 자원 부담. 서브셋 후 두 폰트 합계 약 98,736바이트. 원본의 한글 윤곽·advance width·줄 간격·힌팅이 유지되는 회귀 테스트 추가.
6. **HTML·임시 파일**: 표지의 base64 포함 HTML 약 2.68MB를 IPC로 보내거나 읽는 경로를, 동일 원본 이미지·로고·폰트의 file URI를 쓰는 약 3.6KB HTML로 변경. 임시 HTML·프로필·캐시와 Chromium 공유 버퍼는 RAM 경로 사용.
7. **PNG 캡처**: 기존 캡처가 장당 약 10~13초. CDP `Page.captureScreenshot`의 `optimizeForSpeed=true`로 무손실 PNG 압축 비용을 줄여 성공 실행에서 약 4.5~7초 관측. 이미지 포맷·해상도·픽셀은 유지. 이전 PNG와 4개 페이지의 전체 픽셀 비교 PASS.
8. **종료**: timeout 뒤 EPIPE는 부모/driver 연결 종료의 2차 증상으로 관측됨. 정상과 overflow 경로 모두 context 종료를 확인. driver 종료 후 PID+생성시각으로 추적한 프로세스 잔존/좀비 검사와 별도 호스트 조회 수행.

## 구현

- `figma_renderer.py`: 기존 CSS·배치·로고·엔딩과 페이지 분할 유지. 로컬 자산 로딩, 단계 callback, 실제 font face 로딩 검사, 텍스트 경계 검사, 무손실 PNG 캡처.
- `bureau/font_subset.py`: 폰트 준비를 별도 프로세스에서 마치고 종료한 뒤 브라우저 시작. 원본 폰트 해시·문자 집합·fonttools/renderer 버전으로 캐시를 구분하고 파생 폰트 해시 검사. 원본 폰트는 수정하지 않음.
- PNG 캡처, 폰트 준비, navigation/font/close 단계의 상한을 유지하며 worker의 기존 120초 전체 렌더링 상한을 늘리지 않음.
- 단일 프로세스 Chromium은 이 작은 VM에서 프로세스 수를 줄이기 위한 선택. 기존 `--no-sandbox`와 함께 사용되므로 신뢰한 로컬 템플릿 전용. 원격 웹 콘텐츠 렌더링에 사용하지 말 것. HTTP/HTTPS page 요청은 계속 차단.
- runtime은 `/dev/shm` 쓰기와 로컬 IPC가 가능한 일반 서비스 환경이 필요. 읽기 전용/IPC 제한이 있는 Codex sandbox에서의 브라우저 실패를 timeout 확대로 우회하지 말 것.

## 재현

운영 서비스는 필요하지 않습니다. 저장소 가상환경과 기존 승인 Figma assets만 사용합니다. 제한적인 실행 sandbox라면 로컬 브라우저 실행 권한을 먼저 받습니다. 테스트 중 다른 무거운 로컬 작업을 병렬 실행하지 마세요.

```bash
timeout --kill-after=3s 75s .venv/bin/python -u tests/render_smoke.py \
  --case 5 --output output/render-smoke/acceptance

timeout --kill-after=3s 75s .venv/bin/python -u tests/render_smoke.py \
  --case 4 --output output/render-smoke/acceptance

timeout --kill-after=3s 75s .venv/bin/python -u tests/render_smoke.py \
  --case overflow --output output/render-smoke/acceptance

# 브라우저를 시작하지 않고 이미 저장된 PNG를 독립 검증
.venv/bin/python tests/verify_render_artifacts.py
.venv/bin/python -m unittest discover -s tests -v
```

`output/`은 Git에서 제외합니다. 폰트 캐시 삭제는 성능상 재준비가 필요할 뿐 원본 디자인에 영향을 주지 않습니다. 자산 변경 시 원본 해시가 바뀌어 새 캐시를 사용합니다. 테스트 helper는 DB/환경파일을 읽지 않습니다.
