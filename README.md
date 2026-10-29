# 비현실문제부 콘텐츠 자동화

뉴스를 소재로 허구 기관의 건조한 공문체 풍자 콘텐츠를 제작하는 승인 기반 시스템입니다.
**구현·오프라인 QA 단계이며 운영 전환은 아직 하지 않았습니다.** 운영 DB는 백업했고 기존 데이터는 변경하지 않았습니다. 외부 전송, 유료 호출, Instagram 게시, 서비스 재시작/활성화, GitHub 설정 변경은 별도 승인이 필요합니다.

## 흐름

```text
18:00 Asia/Seoul timer / VM 수동 실행
  → bot.py: 한국 날짜별 후보 작업 하나를 SQLite에 접수
  → worker: RSS → Claude 후보 3개 저장 → Telegram outbox
  → /candidates: 같은 DB 후보 조회 → 선택 → Claude 원고 저장
  → 주제 사진 등록·검토 (미등록이면 안전하게 대기)
  → 유일한 figma_renderer: 표지/본문/중간·최종 판정/고정 엔딩 4~5장
  → 공개 JPEG 실제 바이트 검증 → Telegram 원고·앨범·버전별 심의
  → /review ID VERSION → 게시 승인
  → 공식 Meta API 사전검사 → 캐러셀 컨테이너 → 게시
     (게시 허용/인증/권한이 없으면 publish_waiting)
```

승인, 거절, 수정은 현재 버전에만 적용됩니다. 승인·게시된 기록은 수정하지 않습니다. 예전 승인 데이터에는 새 승인을 소급 생성하지 않으며 자동 게시하지 않습니다. RSS 제목은 기사 본문의 사실 검증을 대신하지 않습니다. 사람의 출처·문장·이미지 권리·얼굴 노출 검토가 필수입니다.

## 안전한 로컬 확인

프로젝트 Python은 `.venv/bin/python`입니다. 추가 의존성은 `requirements.txt`에 정의했습니다. 설치와 브라우저 다운로드는 운영 준비 승인 단계에서 수행합니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m bureau.cli health
.venv/bin/python -m compileall -q bureau
# 실제 로컬 Chromium 테스트: 공개 디렉터리에 저장하거나 외부 HTTP를 호출하지 않음
 timeout --kill-after=5s 75s .venv/bin/python tests/render_smoke.py
```

테스트는 임시 DB와 모의 Claude/Telegram/Meta 응답을 사용하며 소켓 연결을 차단합니다. 루트의 기존 `test_claude_draft.py`, `test_render_preview.py`는 실제 API/DB를 다루는 과거 수동 실험 스크립트입니다. 일괄 실행하거나 일반 테스트 탐색에 포함하지 마세요.

## 구성

- [운영 가이드](docs/OPERATIONS.md): 설정, 백업/마이그레이션, timer 전환, 승인, 복구, 보안
- [Chromium 렌더링 검증](docs/RENDERING.md): 실제 4장/5장 PNG와 자원·성능 제한
- [QA 및 배포 검증](docs/QA.md): 검증 범위, 남은 운영 검증, 인수 조건
- `bureau/`: 설정, SQLite 저장소, 영속 큐/체크포인트/outbox, 콘텐츠 검증, 이미지 검수, Telegram, 공식 게시 어댑터
- `figma_renderer.py`, `figma_assets/`: 기존 승인 디자인·로고·폰트. 외부 Figma 파일 수정 없음
- `deploy/`: 설치 전 검토할 systemd 템플릿. 파일을 만드는 것으로 서비스가 활성화되지 않습니다
- `.github/workflows/manual_vm.yml`: 같은 VM DB를 쓰는 전용 self-hosted runner의 수동 작업

`.env.example`은 값이 없는 설정 템플릿입니다. 실제 `.env`, DB·백업, 이미지, 인증파일은 Git에서 제외합니다. DB 스키마 생성은 명시적 `migrate` 명령만 수행합니다. 프로그램 import나 상태 조회는 마이그레이션/외부 호출을 하지 않습니다.

운영 직전 전환·공개 허용·롤백 절차: [한국어 Production 전환 가이드](docs/PRODUCTION_CUTOVER_KO.md).
