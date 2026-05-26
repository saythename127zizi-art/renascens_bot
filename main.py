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
        BotCommand("start", "Mulai bot"),
        BotCommand("keluar", "Catat pengeluaran"),
        BotCommand("masuk", "Catat pemasukan"),
        BotCommand("hariini", "Laporan hari ini"),
        BotCommand("bulanini", "Laporan bulan ini"),
        BotCommand("stat", "Statistik sederhana"),
        BotCommand("riwayat", "Lihat transaksi terakhir"),
        BotCommand("export_csv", "Export transaksi CSV"),
        BotCommand("produk", "Tambah produk jualan"),
        BotCommand("jual", "Catat penjualan"),
        BotCommand("stok", "Lihat stok jualan"),
        BotCommand("laba_bulanini", "Laporan laba bulan ini"),
        BotCommand("help", "Bantuan"),
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
