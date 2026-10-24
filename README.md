# 비현실문제부

뉴스 기반 콘텐츠 후보 생성기의 초기 버전입니다.

## GitHub Actions Secrets 설정

Repository → Settings → Secrets and variables → Actions에서 다음 Repository secrets를 추가합니다.

- `GEMINI_API_KEY`: Gemini API 키
- `TELEGRAM_BOT_TOKEN`: Telegram 봇 토큰
- `TELEGRAM_CHAT_ID`: 알림을 보낼 채팅 ID

선택 사항으로 Repository variables에 `GEMINI_MODEL`을 지정할 수 있습니다. 비워두면 `gemini-2.5-flash`를 사용합니다. 실제 계정에서 사용 가능한 모델명을 지정하세요.

## 실행 방식

- 매일 18:00 한국 시간: 최근 72시간 이내의 Google News RSS 항목을 조회해 후보 3개 생성을 시도합니다.
- Actions 탭에서 `Unreal Bureau Bot`을 수동 실행할 수 있습니다.

## 현재 범위와 한계

- 날짜가 확인되는 RSS 항목만 사용합니다. 조건에 맞는 뉴스가 부족하면 오래된 항목으로 대체하지 않습니다.
- 아직 텔레그램 버튼의 실시간 선택/승인 콜백과 후보 영속 저장은 구현되지 않았습니다.
- `select_choice`는 이전 후보 데이터를 저장하지 않으므로 현재 사용할 수 없고, 의도적으로 오류를 표시합니다.
- 카드뉴스 이미지 렌더링, Figma 연동, 인스타그램 게시 기능은 다음 단계에서 구현합니다.

## 중요

API 키와 봇 토큰을 코드에 직접 넣지 마세요. GitHub Actions Secrets를 사용하세요. 비밀값이 과거에 공개 저장소에 올라갔다면 새 값으로 교체하세요.
