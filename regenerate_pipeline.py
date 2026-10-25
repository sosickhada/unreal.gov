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


def run_script(script_name, record_id):
    print(f"[시작] {script_name}", flush=True)

    subprocess.run(
        [
            str(PYTHON),
            str(BASE_DIR / script_name),
            str(record_id),
        ],
        cwd=str(BASE_DIR),
        check=True,
        timeout=240,
    )

    print(f"[완료] {script_name}", flush=True)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(
            "사용법: python regenerate_pipeline.py <게시물ID>"
        )

    record_id = int(sys.argv[1])

    if record_id <= 0:
        raise ValueError("게시물 ID는 양수여야 합니다.")

    status = get_status(record_id)

    if status != "regenerate_requested":
        raise RuntimeError(
            f"게시물 {record_id}의 상태가 "
            f"regenerate_requested가 아닙니다: {status}"
        )

    print(f"게시물 {record_id} 재생성 시작", flush=True)

    run_script("regenerate_draft.py", record_id)

    if get_status(record_id) != "draft_ready":
        raise RuntimeError("Claude 원고 저장 상태가 올바르지 않습니다.")

    run_script("regenerate_preview.py", record_id)

    if get_status(record_id) != "preview_ready":
        raise RuntimeError("이미지 미리보기 상태가 올바르지 않습니다.")

    print("재생성 파이프라인 완료", flush=True)


if __name__ == "__main__":
    main()
