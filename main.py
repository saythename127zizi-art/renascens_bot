"""Entry point DuitKu Bot."""
from __future__ import annotations

import os
from datetime import time

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.ext import ApplicationBuilder

import database as db
from handlers import error_handler, get_handlers, reminder_callback
from utils import JAKARTA_TZ


async def post_init(application) -> None:
    commands = [
        BotCommand("start", "Open main menu"),
        BotCommand("out", "Add expense: /out 12000 makan seblak"),
        BotCommand("in", "Add income: /in 45000 jualan mie"),
        BotCommand("today", "Today summary"),
        BotCommand("detail", "Detailed daily report"),
        BotCommand("month", "Monthly summary"),
        BotCommand("history", "Recent transactions"),
        BotCommand("stats", "Spending stats"),
        BotCommand("edit", "Edit by ID"),
        BotCommand("del", "Delete by ID"),
        BotCommand("undo", "Undo last transaction"),
        BotCommand("view", "View transaction detail"),
        BotCommand("bulk", "Bulk input"),
        BotCommand("pay", "Edit payment method"),
        BotCommand("method", "Filter by payment method"),
        BotCommand("search", "Search transaction"),
        BotCommand("cat", "Filter category"),
        BotCommand("product", "Add product"),
        BotCommand("sell", "Record sale"),
        BotCommand("stock", "View stock"),
        BotCommand("profit", "Monthly profit"),
        BotCommand("help", "Help"),
    ]
    await application.bot.set_my_commands(commands)

    # Restore reminder dari database saat bot restart.
    for row in db.get_enabled_reminders():
        hour, minute = [int(x) for x in row["remind_time"].split(":")]
        application.job_queue.run_daily(
            reminder_callback,
            time=time(hour=hour, minute=minute, tzinfo=JAKARTA_TZ),
            name=f"reminder:{row['user_id']}",
            chat_id=row["chat_id"],
            user_id=row["user_id"],
        )


def main() -> None:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN belum diisi. Buat file .env dari .env.example lalu isi token BotFather.")

    db.init_db()
    app = ApplicationBuilder().token(token).post_init(post_init).build()

    for handler in get_handlers():
        app.add_handler(handler)
    app.add_error_handler(error_handler)

    print("DuitKu Bot jalan. Tekan Ctrl+C untuk berhenti.")
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
