# 비현실문제부 콘텐츠 봇

GitHub Actions에서 Google News RSS를 확인하고, Claude API로 인스타그램 풍자 콘텐츠 후보 3개를 생성해 텔레그램으로 전달하는 초기 버전입니다.

## GitHub 설정

Repository secrets:
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Repository variables (선택 사항):
- `CLAUDE_MODEL` — 기본값 `claude-haiku-5-5`

## 실행

Actions 탭에서 `Unreal Bureau Bot` 워크플로를 수동 실행하거나, 매일 한국 시간 18:00에 예약 실행됩니다. GitHub Actions의 예약 실행은 지연될 수 있습니다.

## 현재 한계

이 버전은 뉴스 후보를 생성해 텔레그램으로 발송하는 단계입니다. 텔레그램 인라인 버튼의 실시간 응답, 후보 상태 저장, 상세 기획 승인, 카드뉴스 렌더링은 아직 구현되어 있지 않습니다.
