
import json
import sqlite3
from pathlib import Path

import requests
from figma_renderer import render_carousel

ENV_PATH = Path("/opt/unreal.gov/.env")
DB_PATH = Path("/opt/unreal-github/unreal_bot.db")
IMAGE_DIR = Path("/opt/unreal.gov/public/images")
BASE_URL = "https://unreal-korea-media.duckdns.org"


def load_env():
    values = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main():
    import sys
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit("사용법: python create_preview.py 게시물ID")
    target_id = int(sys.argv[1])

    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("Telegram 인증 정보가 없습니다.")

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT id, candidate_title, draft_json
            FROM selections
            WHERE id = ?
              AND status = 'draft_ready'
              AND draft_json IS NOT NULL
        """, (target_id,)).fetchone()

    if not row:
        raise RuntimeError("렌더링할 카드뉴스 원고가 없습니다.")

    record_id, title, draft_json = row
    draft = json.loads(draft_json)

    if len(draft.get("slides", [])) != 4:
        raise ValueError("카드뉴스 원고가 4장이 아닙니다.")

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    prefix = IMAGE_DIR / f"unreal-case-{record_id}"

    print(f"선택 기록: {record_id}")
    print(f"사건명: {title}")
    print("카드뉴스 4장 렌더링 시작...", flush=True)

    image_paths = render_carousel(draft, str(prefix))

    if len(image_paths) != 4:
        raise RuntimeError("이미지 4장이 생성되지 않았습니다.")

    for path in image_paths:
        if not Path(path).is_file():
            raise RuntimeError(f"이미지 파일이 없습니다: {path}")

    print("PNG 이미지 4장 생성 완료")

    # Telegram에는 로컬 이미지 파일을 직접 전송
    # 공개 HTTPS URL은 이후 Instagram 게시에 사용
    media = []
    files = []

    try:
        for index, path in enumerate(image_paths):
            file_handle = open(path, "rb")
            files.append(file_handle)

            item = {
                "type": "photo",
                "media": f"attach://photo{index}",
            }

            if index == 0:
                item["caption"] = (
                    f"🏛️ [비현실문제부] 카드뉴스 미리보기\n\n"
                    f"사건명: {title}\n"
                    f"기록 ID: {record_id}\n\n"
                    "총 4장 · 게시 전 검토용"
                )

            media.append(item)

        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMediaGroup",
            data={
                "chat_id": chat_id,
                "media": json.dumps(media, ensure_ascii=False),
            },
            files={
                f"photo{i}": file
                for i, file in enumerate(files)
            },
            timeout=90,
        )

        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            raise RuntimeError(
                "Telegram 이미지 전송에 실패했습니다."
            )

    finally:
        for file in files:
            file.close()

    print("Telegram 이미지 4장 전송 완료")

    image_urls = [
        f"{BASE_URL}/images/{Path(path).name}"
        for path in image_paths
    ]

    # 실제 공개 URL 접근 가능 여부 확인
    for url in image_urls:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        if not response.headers.get(
            "Content-Type", ""
        ).startswith("image/"):
            raise RuntimeError("이미지 URL 응답이 올바르지 않습니다.")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            UPDATE selections
            SET image_paths = ?,
                status = 'preview_ready'
            WHERE id = ?
              AND status = 'draft_ready'
        """, (
            json.dumps(image_urls, ensure_ascii=False),
            record_id,
        ))

        if cursor.rowcount != 1:
            raise RuntimeError("DB 상태가 변경되어 저장하지 않았습니다.")

    print("HTTPS 이미지 URL 확인 완료")
    print("SQLite 상태: preview_ready")
    print("미리보기 전송 테스트 성공")


if __name__ == "__main__":
    main()
