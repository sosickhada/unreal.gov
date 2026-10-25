
import os
import logging
import sqlite3
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

ENV_PATH = Path("/opt/unreal.gov/.env")


def load_env():
    values = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


env = load_env()
TOKEN = env.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = env.get("TELEGRAM_CHAT_ID")

CANDIDATES = {
    "1": "퇴근 8분 전 질문",
    "2": "읽씹의 행정적 기준",
    "3": "점심 메뉴 결정 책임",
}


DB_PATH = Path("/opt/unreal-github/unreal_bot.db")


def save_selection(number, title):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT INTO selections (
                candidate_number,
                candidate_title,
                status
            )
            VALUES (?, ?, ?)
            """,
            (int(number), title, "selected"),
        )
        conn.commit()
        return cursor.lastrowid


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or str(update.effective_chat.id) != CHAT_ID:
        return

    await update.message.reply_text(
        "🏛️ 비현실문제부\n\n"
        "Telegram 승인 시스템이 연결되었습니다.\n\n"
        "후보를 확인하려면 /candidates 를 입력하세요."
    )


async def candidates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or str(update.effective_chat.id) != CHAT_ID:
        return

    message = (
        "🏛️ [비현실문제부] 오늘의 심의 안건\n\n"
        "01. 퇴근 8분 전 질문\n"
        "02. 읽씹의 행정적 기준\n"
        "03. 점심 메뉴 결정 책임\n\n"
        "심의할 안건을 선택해 주세요."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                f"{number}번 선택",
                callback_data=f"select:{number}",
            )
        ]
        for number in CANDIDATES
    ]

    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )



async def run_creation_pipeline(record_id, bot, chat_id):
    import asyncio
    import sys

    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "/opt/unreal-github/create_pipeline.py",
            str(record_id),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=540,
        )

        if process.returncode != 0:
            raise RuntimeError(
                (stderr or stdout).decode(errors="replace")[-3000:]
            )

        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ 게시물 {record_id} 카드뉴스 자동 생성 완료!\\n/preview 로 심의할 수 있습니다.",
        )

    except Exception:
        logging.exception("자동 생성 실패: ID=%s", record_id)
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ 게시물 {record_id} 자동 생성에 실패했습니다. 서버 로그를 확인해 주세요.",
        )


async def handle_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query or not query.message:
        return

    if str(query.message.chat.id) != CHAT_ID:
        await query.answer("접근 권한이 없습니다.", show_alert=True)
        return

    number = query.data.split(":")[-1]
    title = CANDIDATES.get(number)

    if not title:
        await query.answer("유효하지 않은 후보입니다.", show_alert=True)
        return

    selection_id = save_selection(number, title)

    await query.answer("안건이 선택되었습니다.")

    await query.edit_message_text(
        "🏛️ [비현실문제부] 심의 안건 선택 완료\n\n"
        f"선택 번호: {number}번\n"
        f"사건명: {title}\n\n"
        "다음 단계: 카드뉴스 초안 생성\n"
        "현재는 버튼 작동 테스트 단계입니다."
    )

    logging.info("후보 선택 저장 완료: ID=%s, 후보=%s번", selection_id, number)

    import asyncio
    asyncio.create_task(
        run_creation_pipeline(
            selection_id,
            context.bot,
            query.message.chat.id,
        )
    )



async def preview_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or str(update.effective_chat.id) != CHAT_ID:
        return

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT id, candidate_title
            FROM selections
            WHERE status = 'preview_ready'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    if not row:
        await update.message.reply_text(
            "현재 승인 대기 중인 카드뉴스가 없습니다."
        )
        return

    record_id, title = row

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "게시 승인",
                callback_data=f"approve:{record_id}"
            ),
            InlineKeyboardButton(
                "재생성",
                callback_data=f"regenerate:{record_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                "반려",
                callback_data=f"reject:{record_id}"
            )
        ],
    ])

    await update.message.reply_text(
        "🏛️ [비현실문제부] 게시 심의\n\n"
        f"사건명: {title}\n"
        f"기록 ID: {record_id}\n\n"
        "카드뉴스 4장을 확인한 뒤 선택해 주세요.",
        reply_markup=keyboard,
    )


async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not query:
        return

    if (
        not update.effective_chat
        or str(update.effective_chat.id) != CHAT_ID
        or not update.effective_user
        or str(update.effective_user.id) != CHAT_ID
    ):
        await query.answer("접근 권한이 없습니다.", show_alert=True)
        return

    try:
        action, raw_id = query.data.split(":", 1)
        record_id = int(raw_id)
    except (ValueError, AttributeError):
        await query.answer("잘못된 요청입니다.", show_alert=True)
        return

    transitions = {
        "approve": ("approved", "게시 승인 완료"),
        "regenerate": ("regenerate_requested", "재생성 요청 접수"),
        "reject": ("rejected", "반려 완료"),
    }

    if action not in transitions:
        await query.answer("지원하지 않는 동작입니다.", show_alert=True)
        return

    new_status, label = transitions[action]

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE selections
            SET status = ?
            WHERE id = ?
              AND status = 'preview_ready'
            """,
            (new_status, record_id),
        )

        changed = cursor.rowcount

        row = conn.execute(
            "SELECT candidate_title FROM selections WHERE id = ?",
            (record_id,),
        ).fetchone()

    if changed != 1:
        await query.answer(
            "이미 처리되었거나 승인 대기 상태가 아닙니다.",
            show_alert=True,
        )
        return

    title = row[0] if row else "알 수 없는 사건"

    await query.answer(label)

    if action == "regenerate":
        await query.edit_message_text(
            "🏛️ [비현실문제부] 재생성 접수\\n\\n"
            f"사건명: {title}\\n"
            f"기록 ID: {record_id}\\n\\n"
            "Claude 원고 및 카드뉴스를 재생성합니다."
        )

        import asyncio
        import sys

        async def run_regeneration():
            try:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "/opt/unreal-github/regenerate_pipeline.py",
                    str(record_id),
                    cwd="/opt/unreal-github",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )

                _, stderr = await process.communicate()

                if process.returncode != 0:
                    logging.error(
                        "재생성 실패 ID=%s: %s",
                        record_id,
                        stderr.decode(errors="replace")[-2000:],
                    )
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=(
                            f"⚠️ 게시물 {record_id}번 재생성에 실패했습니다. "
                            "서버 로그를 확인해 주세요."
                        ),
                    )
                    return

                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=(
                        f"✅ 게시물 {record_id}번 재생성 완료!\\n"
                        "새 이미지 4장을 확인한 뒤 /preview 를 입력하세요."
                    ),
                )

            except Exception:
                logging.exception(
                    "재생성 실행 오류: ID=%s",
                    record_id,
                )

        asyncio.create_task(run_regeneration())
        return

    await query.edit_message_text(
        "🏛️ [비현실문제부] 심의 처리 결과\n\n"
        f"사건명: {title}\n"
        f"기록 ID: {record_id}\n"
        f"처리 결과: {label}\n"
        f"DB 상태: {new_status}\n\n"
        "현재는 테스트 단계로 실제 게시나 재생성은 실행되지 않습니다."
    )

    logging.info(
        "심의 처리: ID=%s, status=%s",
        record_id,
        new_status,
    )


def main():
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("Telegram 토큰 또는 Chat ID가 없습니다.")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("candidates", candidates))
    app.add_handler(
        CallbackQueryHandler(handle_selection, pattern=r"^select:[123]$")
    )

    print("비현실문제부 Telegram 승인 봇 실행 중", flush=True)
    print("Telegram에서 /candidates 를 입력하세요.", flush=True)

    app.add_handler(CommandHandler("preview", preview_approval))
    app.add_handler(
        CallbackQueryHandler(
            handle_approval,
            pattern=r"^(approve|regenerate|reject):[0-9]+$",
        )
    )

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
