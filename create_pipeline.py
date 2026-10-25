import sqlite3
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path("/opt/unreal-github")
DB_PATH = BASE_DIR / "unreal_bot.db"
PYTHON = BASE_DIR / ".venv/bin/python"


def get_status(record_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT status FROM selections WHERE id = ?",
            (record_id,),
        ).fetchone()
    return row[0] if row else None


def run_script(filename, record_id):
    print(f"[실행] {filename} / ID={record_id}", flush=True)

    subprocess.run(
        [str(PYTHON), str(BASE_DIR / filename), str(record_id)],
        cwd=str(BASE_DIR),
        check=True,
        timeout=240,
    )


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit("사용법: python create_pipeline.py 게시물ID")

    record_id = int(sys.argv[1])
    status = get_status(record_id)

    if status != "selected":
        raise RuntimeError(
            f"생성할 수 없는 게시물입니다. ID={record_id}, 상태={status}"
        )

    run_script("create_draft.py", record_id)

    if get_status(record_id) != "draft_ready":
        raise RuntimeError("Claude 원고 생성 후 상태가 올바르지 않습니다.")

    run_script("create_preview.py", record_id)

    if get_status(record_id) != "preview_ready":
        raise RuntimeError("이미지 생성 후 상태가 올바르지 않습니다.")

    print(f"게시물 {record_id} 자동 생성 완료!", flush=True)


if __name__ == "__main__":
    main()
