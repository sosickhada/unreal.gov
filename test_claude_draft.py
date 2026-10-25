
import json
import re
import sqlite3
from pathlib import Path

from anthropic import Anthropic

ENV_PATH = Path("/opt/unreal.gov/.env")
DB_PATH = Path("/opt/unreal-github/unreal_bot.db")


def load_env():
    values = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_latest_selection():
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT id, candidate_number, candidate_title
            FROM selections
            WHERE status = 'selected'
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

    if not row:
        raise RuntimeError("선택된 후보가 없습니다.")

    return row


def validate_draft(draft):
    if not isinstance(draft, dict):
        raise ValueError("JSON 최상위 구조가 객체가 아닙니다.")

    if not isinstance(draft.get("title"), str):
        raise ValueError("title이 없습니다.")

    slides = draft.get("slides")
    if not isinstance(slides, list) or len(slides) != 4:
        raise ValueError("slides는 정확히 4개여야 합니다.")

    for i, slide in enumerate(slides, 1):
        if not isinstance(slide, dict):
            raise ValueError(f"{i}장 데이터가 객체가 아닙니다.")
        for key in ("eyebrow", "headline", "body"):
            if not isinstance(slide.get(key), str) or not slide[key].strip():
                raise ValueError(f"{i}장의 {key}가 비어 있습니다.")


def main():
    env = load_env()
    api_key = env.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY가 없습니다.")

    record_id, number, title = get_latest_selection()

    # 기존 bot.py와 동일한 기본 모델 설정
    model = env.get("CLAUDE_MODEL") or "claude-haiku-5-5"

    print(f"선택 기록 ID: {record_id}")
    print(f"후보: {number}번 / {title}")
    print(f"사용 모델: {model}")

    prompt = f"""
너는 인스타그램 풍자 계정 '비현실문제부'의 콘텐츠 작가다.

선택된 사건명: {title}

이 사건명을 소재로 1080x1350 카드뉴스 4장의 원고를 작성하라.

[계정 정체성]
- 허구의 행정기관이 일상의 사소한 억울함을 진지하게 심의한다.
- 대한민국 정부 공문서처럼 정중하고 건조한 문체.
- 웃기려고 애쓰지 않는 무표정한 풍자.
- 현실적인 상황과 공감이 가장 중요하다.
- 실제 정부기관으로 오인되지 않도록 한다.

[카드뉴스 구성]
1장: 첫 문장부터 공감되는 구체적인 상황과 강한 훅.
2장: 사건의 전개와 비현실문제부의 접수 내용.
3장: 현실적인 댓글 반응 2개와 풍자적인 심의 결과.
4장: 최종 처분, 짧은 여운, 비현실문제부 명칭.

[작성 기준]
- 제목은 짧고 명확하게.
- headline은 가급적 2줄 이내.
- body는 2~4개의 짧은 문장.
- 댓글 반응은 3장 body 안에 포함.
- 실제 뉴스나 통계, 출처를 지어내지 말 것.
- 모든 내용은 가상의 풍자 사례로 작성할 것.
- 이미지 생성은 하지 말고 텍스트 원고만 작성.

[반환 형식]
JSON 객체 하나만 반환한다.
마크다운 코드블록이나 JSON 외 설명은 넣지 않는다.

{{
  "title": "사건명",
  "slides": [
    {{
      "eyebrow": "사건 접수",
      "headline": "첫 장 제목",
      "body": "첫 장 본문"
    }},
    {{
      "eyebrow": "사실 관계",
      "headline": "두 번째 장 제목",
      "body": "두 번째 장 본문"
    }},
    {{
      "eyebrow": "국민 의견 및 심의",
      "headline": "세 번째 장 제목",
      "body": "세 번째 장 본문"
    }},
    {{
      "eyebrow": "최종 처분",
      "headline": "네 번째 장 제목",
      "body": "네 번째 장 본문"
    }}
  ]
}}
"""

    print("Claude 원고 생성 요청 중...", flush=True)

    client = Anthropic(
        api_key=api_key,
        timeout=60.0,
        max_retries=0,
    )

    response = client.messages.create(
        model=model,
        max_tokens=1800,
        messages=[
            {"role": "user", "content": prompt}
        ],
    )

    if response.stop_reason == "max_tokens":
        raise RuntimeError("응답이 잘렸습니다. 토큰 한도를 조정해야 합니다.")

    raw = "\n".join(
        block.text
        for block in response.content
        if block.type == "text"
    ).strip()

    # 모델이 코드블록을 반환한 경우를 대비
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    draft = json.loads(raw)
    validate_draft(draft)

    # 선택 기록이 그대로인지 확인하고 저장
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            UPDATE selections
            SET draft_json = ?,
                status = 'draft_ready'
            WHERE id = ? AND status = 'selected'
        """, (
            json.dumps(draft, ensure_ascii=False),
            record_id,
        ))
        if cursor.rowcount != 1:
            raise RuntimeError("선택 기록 상태가 변경되어 저장하지 않았습니다.")

    print("\nClaude 카드뉴스 원고 생성 성공")
    print("SQLite 저장 완료 / 상태: draft_ready")

    for i, slide in enumerate(draft["slides"], 1):
        print(f"\n[{i}장] {slide['headline']}")
        print(slide["body"])

    print("\n토큰 사용량:")
    print("입력:", response.usage.input_tokens)
    print("출력:", response.usage.output_tokens)


if __name__ == "__main__":
    main()
