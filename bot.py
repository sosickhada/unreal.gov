"""비현실문제부 - 뉴스 기반 콘텐츠 후보 생성기

현재 버전은 GitHub Actions에서 실행되는 1회성 작업입니다.
텔레그램 인라인 버튼의 선택을 실시간으로 처리하려면 별도의 상시 실행 리스너가 필요합니다.
"""
import os
import datetime as dt
import email.utils
import logging
import urllib.request
import xml.etree.ElementTree as ET

import requests
from anthropic import Anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
CLAUDE_MODEL = (os.environ.get("CLAUDE_MODEL") or "claude-haiku-5-5").strip() or "claude-haiku-5-5"
ACTION_TYPE = os.environ.get("ACTION_TYPE", "generate_trends")
CHOICE_NUMBER = os.environ.get("CHOICE_NUMBER", "1")
MAX_AGE_HOURS = int(os.environ.get("MAX_AGE_HOURS", "72"))

RSS_URL = (
    "https://news.google.com/rss/search?"
    "q=%EC%A7%81%EC%9E%A5%EC%9D%B8+OR+%EB%8C%80%ED%95%99%EC%83%9D+OR+%EC%9D%BC%EC%83%81+%EC%9D%B4%EC%8A%88"
    "&hl=ko&gl=KR&ceid=KR:ko"
)


def send_telegram_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 및 TELEGRAM_CHAT_ID 환경 변수를 설정해야 합니다.")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API 오류: {result}")


def parse_pub_date(raw_date: str):
    if not raw_date:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(raw_date)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def fetch_recent_news(max_age_hours: int = MAX_AGE_HOURS, limit: int = 20) -> list[dict]:
    """Google News RSS에서 날짜가 확인되고 지정 시간 이내인 기사만 반환."""
    request = urllib.request.Request(RSS_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; UnrealBureauBot/1.0)"})
    with urllib.request.urlopen(request, timeout=25) as response:
        xml_data = response.read()

    root = ET.fromstring(xml_data)
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=max_age_hours)
    items = []
    seen_links = set()

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_raw = (item.findtext("pubDate") or "").strip()
        pub_date = parse_pub_date(pub_date_raw)
        if not title or not link or not pub_date or pub_date < cutoff or pub_date > now + dt.timedelta(hours=1):
            continue
        if link in seen_links:
            continue
        seen_links.add(link)
        items.append({"title": title, "link": link, "published": pub_date.isoformat()})
        if len(items) >= limit:
            break
    return items


def format_news(items: list[dict]) -> str:
    if not items:
        return "조건에 맞는 최신 뉴스가 없습니다. 오래된 기사를 대신 사용하지 말고, 후보 생성 실패를 알려주세요."
    return "\n\n".join(
        f"- 제목: {item['title']}\n  링크: {item['link']}\n  게시 시각(UTC): {item['published']}"
        for item in items
    )


def make_model():
    """Anthropic Claude API client를 생성한다."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
    return Anthropic(api_key=ANTHROPIC_API_KEY, timeout=45.0, max_retries=2)


def generate_trends(client) -> str:
    news_items = fetch_recent_news()
    news_data = format_news(news_items)
    prompt = f"""
너는 인스타그램 풍자 계정 '비현실문제부'의 콘텐츠 기획자다.
아래 실제 뉴스 목록을 근거로 콘텐츠 후보를 정확히 3개 작성한다.

[계정 원칙]
- 다루는 것: 법으로 해결하기 어렵고, 참자니 분하며, 말하자니 쪼잔한 일상의 사소한 억울함.
- 문체: 웃기려 애쓰지 않는 건조하고 정중한 공문체.
- 첫 장: 기관 소개보다 즉시 공감되는 구체적 상황을 먼저 제시.
- 실존 인물·실제 정부 부처를 사칭하지 않는다. 허구 기관 '비현실문제부'임을 유지한다.
- 실제 뉴스의 사실과 창작한 풍자 상황을 구분한다. 뉴스가 직접 뒷받침하지 않는 내용을 사실처럼 쓰지 않는다.
- 기사 링크는 아래 목록에 있는 URL을 그대로 사용한다. 링크를 지어내지 않는다.

[최신 뉴스 목록: 최대 {MAX_AGE_HOURS}시간 이내]
{news_data}

각 후보를 다음 형식으로 작성:
[후보 1]
실제 기사 제목:
실제 기사 링크:
게시 시각:
이슈 요약(사실만):
일상적 공감 포인트:
사건명(풍자적 창작):
접수 유형:
판정/처분 가안:
첫 장 훅 문구:
왜 공유할 만한가:

후보 2와 후보 3도 같은 형식으로 작성한다. 서로 다른 주제를 선택한다.
조건에 맞는 뉴스가 충분하지 않으면 억지로 채우지 말고, 부족한 이유를 명시한다.
"""
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "\n".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise RuntimeError("Claude가 비어 있는 응답을 반환했습니다.")
    return text


def generate_selected_topic(client, choice_number: str) -> str:
    # 임시 안전장치: 현재 GitHub Actions 버전은 이전 후보의 본문을 저장하지 않습니다.
    # 따라서 번호만으로 정확한 후보를 복원할 수 없으며, 다음 단계에서 저장/선택 흐름을 구현합니다.
    raise RuntimeError(
        "현재 버전은 선택된 후보의 내용을 저장하지 않습니다. "
        "먼저 후보 ID와 내용을 저장하는 텔레그램 상호작용 기능을 구현해야 합니다."
    )


def main():
    logging.info("비현실문제부 콘텐츠 봇 시작 (mode=%s, model=%s)", ACTION_TYPE, CLAUDE_MODEL)

    if ACTION_TYPE in ("", "generate_trends"):
        try:
            client = make_model()
            content = generate_trends(client)
        except Exception as exc:
            logging.exception("후보 생성 실패")
            # API 키/모델/API 오류도 텔레그램으로 전달할 수 있도록 별도 처리
            content = f"⚠️ [비현실문제부] 후보 생성에 실패했습니다.\n오류: {type(exc).__name__}: {exc}"
        send_telegram_message("🏛️ [비현실문제부] 최신 이슈 기반 콘텐츠 후보 3선\n\n" + content)
    elif ACTION_TYPE == "select_choice":
        client = make_model()
        generate_selected_topic(client, CHOICE_NUMBER)
    elif ACTION_TYPE == "reject_regenerate":
        client = make_model()
        content = generate_trends(client)
        send_telegram_message("🔄 [비현실문제부] 새로운 후보 3선\n\n" + content)
    else:
        raise ValueError(f"지원하지 않는 ACTION_TYPE: {ACTION_TYPE}")

    logging.info("작업 완료")


if __name__ == "__main__":
    main()
