"""Semua handler Telegram command dan tombol."""
from __future__ import annotations

import tempfile
from datetime import date, datetime, time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import database as db
from models import MAIN_MENU
from utils import (
    JAKARTA_TZ,
    format_sale,
    format_sales_summary,
    format_summary,
    format_summary_detail,
    format_success,
    format_transaction,
    format_product,
    help_text,
    parse_date,
    parse_nominal,
    parse_product_args,
    parse_transaction_args,
    parse_transaction_args_with_date,
    normalize_payment_method,
    transaction_display_id,
    range_this_month,
    range_this_week,
    range_this_year,
    range_today,
    rupiah,
    today_jakarta,
)

ASK_TIPE, ASK_KATEGORI, ASK_NOMINAL, ASK_CATATAN, ASK_PAYMENT = range(5)
SELL_MENU, SELL_PRODUCT, SELL_QTY, SELL_NOTE = range(5, 9)


def menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        db.ensure_user(user.id, user.first_name)
    await update.message.reply_text(help_text(), parse_mode=ParseMode.MARKDOWN, reply_markup=menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(help_text(), parse_mode=ParseMode.MARKDOWN, reply_markup=menu_keyboard())


def ensure_user_from_update(update: Update) -> int:
    user = update.effective_user
    if not user:
        raise RuntimeError("User tidak ditemukan.")
    db.ensure_user(user.id, user.first_name)
    return user.id


def _strip_markdown(text: str) -> str:
    # Fallback kalau Telegram menolak Markdown karena ada karakter user yang aneh.
    return text.replace("*", "").replace("`", "").replace("_", "")


def _split_long_text(text: str, limit: int = 3600) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for line in text.splitlines():
        extra = len(line) + 1
        if current and length + extra > limit:
            chunks.append("\n".join(current))
            current = [line]
            length = extra
        else:
            current.append(line)
            length += extra
    if current:
        chunks.append("\n".join(current))
    return chunks or [text]


async def reply_markdown_safe(update: Update, text: str, reply_markup=None) -> None:
    message = update.effective_message
    if not message:
        return
    for chunk in _split_long_text(text):
        try:
            await message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        except Exception:
            await message.reply_text(_strip_markdown(chunk), reply_markup=reply_markup)
        reply_markup = None


async def add_transaction_command(update: Update, context: ContextTypes.DEFAULT_TYPE, tipe: str) -> None:
    user_id = ensure_user_from_update(update)
    try:
        nominal, kategori, catatan, created_at, payment_method = parse_transaction_args_with_date(context.args)
        if not db.category_exists(user_id, tipe, kategori):
            db.add_category(user_id, tipe, kategori)
        duplicate = db.find_recent_duplicate(user_id, tipe, catatan or kategori, nominal)
        transaction_id = db.add_transaction(user_id, tipe, nominal, kategori, catatan, created_at, payment_method)
        row = db.get_transaction(user_id, transaction_id)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ Cara edit", callback_data=f"edit_hint:{transaction_id}"),
                InlineKeyboardButton("🗑️ Hapus", callback_data=f"delete_yes:{transaction_id}"),
            ],
            [InlineKeyboardButton("📘 Lihat hari ini", callback_data="report_today")],
        ])
        msg = format_success(row, db.activity_streak(user_id))
        if duplicate:
            msg += "\n\n⚠️ Mirip transaksi yang baru kamu input. Kalau dobel, pakai `/undo` atau `/del ID`."
        await update.message.reply_text(
            msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
    except ValueError as exc:
        command = "/masuk" if tipe == "masuk" else "/keluar"
        await update.message.reply_text(
            f"Formatnya belum pas: {exc}\n\nContoh:\n`{command} 12000 makan seblak`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def keluar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await add_transaction_command(update, context, "keluar")


async def masuk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await add_transaction_command(update, context, "masuk")


def _parse_bulk_line(line: str, default_tipe: str | None = None) -> tuple[str, int, str, str, str | None, str]:
    """Parse satu baris bulk.

    Format campur:
    - 12000 makan seblak
    + 50000 jualan mie
    out 12000 makan seblak
    in 50000 jualan mie
    """
    raw = line.strip()
    if not raw:
        raise ValueError("baris kosong")

    tipe = default_tipe
    parts = raw.split()
    if not parts:
        raise ValueError("baris kosong")

    prefix = parts[0].lower()
    if prefix in {"-", "out", "keluar", "expense"}:
        tipe = "keluar"
        parts = parts[1:]
    elif prefix in {"+", "in", "masuk", "income"}:
        tipe = "masuk"
        parts = parts[1:]

    if tipe not in {"masuk", "keluar"}:
        raise ValueError("pakai prefix +/in atau -/out")
    if len(parts) < 2:
        raise ValueError("format kurang lengkap")

    nominal, kategori, catatan, created_at, payment_method = parse_transaction_args_with_date(parts)
    return tipe, nominal, kategori, catatan, created_at, payment_method


async def bulk_transaksi(update: Update, context: ContextTypes.DEFAULT_TYPE, default_tipe: str | None = None) -> None:
    user_id = ensure_user_from_update(update)
    text = update.message.text or ""
    lines = text.splitlines()[1:]
    lines = [line.strip() for line in lines if line.strip()]

    if not lines:
        if default_tipe == "keluar":
            contoh = "`/bulk_out\n12000 makan seblak\n5000 jajan cilok\n3000 transport parkir`"
        elif default_tipe == "masuk":
            contoh = "`/bulk_in\n50000 jualan mie\n10000 cashback spay`"
        else:
            contoh = "`/bulk\n- 12000 makan seblak\n- 5000 jajan cilok\n+ 50000 jualan mie`"
        await update.message.reply_text(
            "Bisa input banyak sekaligus. Tulis tiap transaksi di baris baru ya.\n\n"
            f"Contoh:\n{contoh}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    success_rows = []
    failed = []
    for idx, line in enumerate(lines, 1):
        try:
            tipe, nominal, kategori, catatan, created_at, payment_method = _parse_bulk_line(line, default_tipe)
            if not db.category_exists(user_id, tipe, kategori):
                db.add_category(user_id, tipe, kategori)
            tid = db.add_transaction(user_id, tipe, nominal, kategori, catatan, created_at, payment_method)
            row = db.get_transaction(user_id, tid)
            if row:
                success_rows.append(row)
        except ValueError as exc:
            failed.append((idx, line, str(exc)))

    total_in = sum(int(r["nominal"]) for r in success_rows if r["tipe"] == "masuk")
    total_out = sum(int(r["nominal"]) for r in success_rows if r["tipe"] == "keluar")
    text_lines = [
        "✅ *Bulk input selesai!*",
        f"Berhasil: *{len(success_rows)} transaksi*",
        f"➕ Masuk: *{rupiah(total_in)}*",
        f"➖ Keluar: *{rupiah(total_out)}*",
    ]
    if success_rows:
        text_lines.append("\n🧾 *ID transaksi baru:*")
        for r in success_rows[:12]:
            sign = "➕" if r["tipe"] == "masuk" else "➖"
            text_lines.append(f"{sign} ID #{transaction_display_id(r)} • `{r['kategori']}` • *{rupiah(r['nominal'])}*")
        if len(success_rows) > 12:
            text_lines.append(f"...dan {len(success_rows) - 12} transaksi lainnya.")
    if failed:
        text_lines.append("\n⚠️ *Gagal dibaca:*")
        for idx, line, err in failed[:8]:
            text_lines.append(f"Baris {idx}: `{line}` → {err}")
        if len(failed) > 8:
            text_lines.append(f"...dan {len(failed) - 8} baris gagal lainnya.")
    text_lines.append("\nCek ringkasan: `/today`")
    await update.message.reply_text("\n".join(text_lines), parse_mode=ParseMode.MARKDOWN)


async def bulk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await bulk_transaksi(update, context, None)


async def bulk_out(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await bulk_transaksi(update, context, "keluar")


async def bulk_in(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await bulk_transaksi(update, context, "masuk")


async def kategori_tambah(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) < 2 or context.args[0].lower() not in {"masuk", "keluar"}:
        await update.message.reply_text("Format: `/kategori_tambah masuk nama` atau `/kategori_tambah keluar nama`", parse_mode=ParseMode.MARKDOWN)
        return
    tipe = context.args[0].lower()
    name = " ".join(context.args[1:]).strip()
    created = db.add_category(user_id, tipe, name)
    if created:
        await update.message.reply_text(f"✅ Kategori `{name.lower()}` berhasil ditambahkan ke {tipe}.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Kategori itu sudah ada ya.")


async def kategori(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    rows = db.get_categories(user_id)
    masuk = [r["name"] for r in rows if r["tipe"] == "masuk"]
    keluar_rows = [r["name"] for r in rows if r["tipe"] == "keluar"]
    text = "🏷️ *Kategori kamu*\n\n➕ *Pemasukan:*\n" + "\n".join(f"• {x}" for x in masuk)
    text += "\n\n➖ *Pengeluaran:*\n" + "\n".join(f"• {x}" for x in keluar_rows)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE, title: str, start: date, end: date) -> None:
    user_id = ensure_user_from_update(update)
    summary = db.summarize_range(user_id, start, end)
    await reply_markdown_safe(update, format_summary(title, summary))


async def report_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, title: str, start: date, end: date) -> None:
    user_id = ensure_user_from_update(update)
    summary = db.summarize_range(user_id, start, end)
    await reply_markdown_safe(update, format_summary_detail(title, summary))


async def hariini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start, end = range_today()
    await report(update, context, f"Laporan Hari Ini ({start.isoformat()})", start, end)


async def detail_hariini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start, end = range_today()
    await report_detail(update, context, f"Hari Ini ({start.isoformat()})", start, end)


async def mingguini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start, end = range_this_week()
    await report(update, context, f"Laporan Minggu Ini ({start.isoformat()} s/d {end.isoformat()})", start, end)


async def bulanini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start, end = range_this_month()
    await report(update, context, f"Laporan Bulan Ini ({start.isoformat()} s/d {end.isoformat()})", start, end)


async def detail_bulanini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start, end = range_this_month()
    await report_detail(update, context, f"Bulan Ini ({start.isoformat()} s/d {end.isoformat()})", start, end)


async def tahunini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start, end = range_this_year()
    await report(update, context, f"Laporan Tahun Ini ({start.isoformat()} s/d {end.isoformat()})", start, end)


async def range_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.message.reply_text("Format: `/range 2026-05-01 2026-05-26`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        start, end = parse_date(context.args[0]), parse_date(context.args[1])
        if start > end:
            raise ValueError("Tanggal awal tidak boleh setelah tanggal akhir.")
        await report(update, context, f"Laporan Range ({start.isoformat()} s/d {end.isoformat()})", start, end)
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) < 2:
        await update.message.reply_text("Format: `/budget makan 500000`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        kategori = context.args[0].lower()
        nominal = parse_nominal(context.args[1])
        month = today_jakarta().strftime("%Y-%m")
        db.set_budget(user_id, kategori, nominal, month)
        status = db.get_budget_status(user_id, kategori, month)
        pct = (status["spent"] / status["budget"] * 100) if status else 0
        await update.message.reply_text(
            f"✅ Budget {kategori} bulan {month} diset ke {rupiah(nominal)}\n\n"
            f"Terpakai: {rupiah(status['spent'])}\n"
            f"Sisa: {rupiah(status['left'])}\n"
            f"Pemakaian: {pct:.1f}%"
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def riwayat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    limit = 10
    if context.args:
        try:
            limit = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Format: `/riwayat 10`", parse_mode=ParseMode.MARKDOWN)
            return
    rows = db.list_transactions(user_id, limit)
    if not rows:
        await update.message.reply_text("Belum ada transaksi.")
        return
    await update.message.reply_text("🧾 *Riwayat transaksi:*\n\n" + "\n".join(format_transaction(r) for r in rows), parse_mode=ParseMode.MARKDOWN)


async def hapus_terakhir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    last = db.get_last_transaction(user_id)
    if not last:
        await update.message.reply_text("Belum ada transaksi yang bisa dihapus.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Ya, hapus", callback_data=f"delete_yes:{transaction_display_id(last)}"), InlineKeyboardButton("Batal", callback_data="delete_no")]
    ])
    await update.message.reply_text("Yakin mau hapus transaksi terakhir ini?\n\n" + format_transaction(last), reply_markup=keyboard)


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    db.ensure_user(user_id, query.from_user.first_name)
    if query.data == "delete_no":
        await query.edit_message_text("Oke, batal dihapus.")
        return
    if query.data == "report_today":
        start, end = range_today()
        summary = db.summarize_range(user_id, start, end)
        await query.message.reply_text(format_summary(f"Laporan Hari Ini ({start.isoformat()})", summary), parse_mode=ParseMode.MARKDOWN)
        return
    if query.data.startswith("edit_hint:"):
        transaction_id = int(query.data.split(":", 1)[1])
        row = db.get_transaction(user_id, transaction_id)
        if not row:
            await query.message.reply_text("Transaksi tidak ditemukan.")
            return
        await query.message.reply_text(
            "✏️ Copy format ini lalu ubah angkanya:\n"
            f"`/edit {transaction_display_id(row)} {row['nominal']} {row['kategori']} {row['catatan'] or ''} @{row['payment_method']}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    transaction_id = int(query.data.split(":", 1)[1])
    deleted = db.delete_transaction(user_id, transaction_id)
    await query.edit_message_text("✅ Transaksi berhasil dihapus." if deleted else "Transaksi tidak ditemukan.")


async def edit_terakhir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    try:
        nominal, kategori, catatan, created_at, payment_method = parse_transaction_args_with_date(context.args)
        row = db.update_last_transaction(user_id, nominal, kategori, catatan, created_at, payment_method)
        if not row:
            await update.message.reply_text("Belum ada transaksi yang bisa diedit.")
            return
        await update.message.reply_text("✅ Transaksi terakhir sudah diedit:\n" + format_transaction(row))
    except ValueError as exc:
        await update.message.reply_text(f"Format: `/edit_terakhir 12000 makan seblak`\n\n{exc}", parse_mode=ParseMode.MARKDOWN)


async def detail_transaksi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Format: `/detail 13`", parse_mode=ParseMode.MARKDOWN)
        return
    row = db.get_transaction(user_id, int(context.args[0]))
    if not row:
        await update.message.reply_text("Transaksi dengan ID itu nggak ketemu.")
        return
    await update.message.reply_text(format_transaction(row), parse_mode=ParseMode.MARKDOWN)


async def edit_transaksi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) < 3 or not context.args[0].isdigit():
        await update.message.reply_text(
            "Format: `/edit ID nominal kategori catatan`\nContoh: `/edit 13 5105 lzd x spay deals`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    try:
        transaction_id = int(context.args[0])
        nominal, kategori, catatan, created_at, payment_method = parse_transaction_args_with_date(context.args[1:])
        if not db.category_exists(user_id, "masuk", kategori) and not db.category_exists(user_id, "keluar", kategori):
            # Kita tidak tahu tipe transaksi dari argumen, jadi nanti pakai tipe lama dari row.
            old = db.get_transaction(user_id, transaction_id)
            if old:
                db.add_category(user_id, old["tipe"], kategori)
        row = db.update_transaction(user_id, transaction_id, nominal, kategori, catatan, created_at, payment_method)
        if not row:
            await update.message.reply_text("Transaksi dengan ID itu nggak ketemu.")
            return
        await update.message.reply_text("✅ *Transaksi berhasil diedit:*\n\n" + format_transaction(row), parse_mode=ParseMode.MARKDOWN)
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def hapus_transaksi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Format: `/hapus 13`", parse_mode=ParseMode.MARKDOWN)
        return
    transaction_id = int(context.args[0])
    row = db.get_transaction(user_id, transaction_id)
    if not row:
        await update.message.reply_text("Transaksi dengan ID itu nggak ketemu.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Ya, hapus", callback_data=f"delete_yes:{transaction_id}"), InlineKeyboardButton("Batal", callback_data="delete_no")]
    ])
    await update.message.reply_text("Yakin mau hapus transaksi ini?\n\n" + format_transaction(row), parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    last = db.get_last_transaction(user_id)
    if not last:
        await update.message.reply_text("Belum ada transaksi buat di-undo.")
        return
    tid = transaction_display_id(last)
    db.delete_transaction(user_id, tid)
    await update.message.reply_text(f"↩️ Undo berhasil. Transaksi ID #{tid} dihapus. ID transaksi dirapikan lagi ya.")


async def rename_cat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    raw = " ".join(context.args).strip()
    if not raw:
        await update.message.reply_text("Format: `/rename_cat kategori lama | kategori baru`\nContoh: `/rename_cat lzd | marketplace`", parse_mode=ParseMode.MARKDOWN)
        return
    if "|" in raw:
        old, new = [x.strip() for x in raw.split("|", 1)]
    elif len(context.args) >= 2:
        old, new = context.args[0], " ".join(context.args[1:])
    else:
        await update.message.reply_text("Format: `/rename_cat lzd | marketplace`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        count = db.rename_category(user_id, old, new)
        await update.message.reply_text(f"✅ Kategori `{old.lower()}` diganti jadi `{new.lower()}`. Transaksi terdampak: {count}.", parse_mode=ParseMode.MARKDOWN)
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def search_transaksi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    keyword = " ".join(context.args).strip()
    if not keyword:
        await update.message.reply_text("Format: `/search seblak` atau `/search lzd`", parse_mode=ParseMode.MARKDOWN)
        return
    rows = db.search_transactions(user_id, keyword, 20)
    if not rows:
        await update.message.reply_text(f"Nggak nemu transaksi yang mengandung `{keyword}`.", parse_mode=ParseMode.MARKDOWN)
        return
    lines = [f"🔎 *Search:* `{keyword}`", ""]
    lines += [format_transaction(r) for r in rows[:10]]
    if len(rows) > 10:
        lines.append(f"\n...dan {len(rows)-10} hasil lain.")
    await update.message.reply_text("\n\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def category_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    kategori = " ".join(context.args).strip()
    if not kategori:
        await update.message.reply_text("Format: `/cat marketplace` atau `/cat makan`", parse_mode=ParseMode.MARKDOWN)
        return
    rows = db.filter_transactions_by_category(user_id, kategori, 20)
    if not rows:
        await update.message.reply_text(f"Belum ada transaksi di kategori `{kategori.lower()}`.", parse_mode=ParseMode.MARKDOWN)
        return
    total_in = sum(int(r["nominal"]) for r in rows if r["tipe"] == "masuk")
    total_out = sum(int(r["nominal"]) for r in rows if r["tipe"] == "keluar")
    lines = [f"🏷️ *Kategori:* `{kategori.lower()}`", f"Masuk: *{rupiah(total_in)}* • Keluar: *{rupiah(total_out)}*", ""]
    lines += [format_transaction(r) for r in rows[:10]]
    if len(rows) > 10:
        lines.append(f"\n...dan {len(rows)-10} transaksi lain.")
    await update.message.reply_text("\n\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def backup_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Versi ringan: reminder manual via chat, bukan scheduler mingguan kompleks.
    if not context.args or context.args[0].lower() not in {"on", "off"}:
        await update.message.reply_text("Untuk sekarang backup manual ya: ketik `/export_csv` sebelum update bot.\nCommand ini jadi pengingat aja: `/backup_reminder on`", parse_mode=ParseMode.MARKDOWN)
        return
    if context.args[0].lower() == "on":
        await update.message.reply_text("✅ Noted. Sebelum update/redeploy bot, jangan lupa `/export_csv` dulu ya 💾")
    else:
        await update.message.reply_text("Oke, reminder backup manual dimatikan dari chat ini.")


async def edit_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) < 2 or not context.args[0].isdigit():
        await update.message.reply_text("Format: `/pay ID metode`\nContoh: `/pay 13 qris`", parse_mode=ParseMode.MARKDOWN)
        return
    transaction_id = int(context.args[0])
    row = db.get_transaction(user_id, transaction_id)
    if not row:
        await update.message.reply_text("Transaksi dengan ID itu nggak ketemu.")
        return
    method = normalize_payment_method(" ".join(context.args[1:]))
    updated = db.update_transaction(user_id, transaction_id, int(row["nominal"]), row["kategori"], row["catatan"] or "", None, method)
    await update.message.reply_text("✅ Metode pembayaran diupdate:\n\n" + format_transaction(updated), parse_mode=ParseMode.MARKDOWN)


async def filter_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if not context.args:
        await update.message.reply_text("Format: `/method qris` atau `/method shopeepay`", parse_mode=ParseMode.MARKDOWN)
        return
    method = normalize_payment_method(" ".join(context.args))
    rows = db.filter_transactions_by_payment_method(user_id, method, 30)
    if not rows:
        await update.message.reply_text(f"Belum ada transaksi metode `{method}`.", parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(f"💳 *Transaksi metode `{method}`:*\n\n" + "\n".join(format_transaction(r) for r in rows), parse_mode=ParseMode.MARKDOWN)


async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"transaksi_{user_id}.csv"
        db.export_transactions_csv(user_id, path)
        await update.message.reply_document(document=path.open("rb"), filename="transaksi_duitku.csv", caption="Ini export CSV kamu ya 💾")


async def stat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    data = db.stats_month(user_id, today_jakarta())
    day, day_total = data["most_expensive_day"]
    cat, cat_total = data["most_expensive_cat"]
    text = (
        "📊 *Statistik bulan ini*\n\n"
        f"Rata-rata pengeluaran harian: *{rupiah(data['avg_daily'])}*\n"
        f"Hari paling boros: *{day}* — {rupiah(day_total)}\n"
        f"Kategori paling boros: *{cat}* — {rupiah(cat_total)}\n"
        f"Estimasi pengeluaran sampai akhir bulan: *{rupiah(data['projected'])}*\n\n"
        f"Total pengeluaran sejauh ini: {rupiah(data['summary']['expense'])}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def reminder_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    await context.bot.send_message(chat_id=chat_id, text="⏰ Jangan lupa catat pemasukan/pengeluaran hari ini ya. Biar duitnya kelihatan larinya ke mana 😭")


def schedule_reminder(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, hhmm: str) -> None:
    for job in context.job_queue.get_jobs_by_name(f"reminder:{user_id}"):
        job.schedule_removal()
    hour, minute = [int(x) for x in hhmm.split(":")]
    context.job_queue.run_daily(
        reminder_callback,
        time=time(hour=hour, minute=minute, tzinfo=JAKARTA_TZ),
        name=f"reminder:{user_id}",
        chat_id=chat_id,
        user_id=user_id,
    )


async def reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    chat_id = update.effective_chat.id
    if len(context.args) != 1:
        await update.message.reply_text("Format: `/reminder 21:00`", parse_mode=ParseMode.MARKDOWN)
        return
    raw = context.args[0]
    try:
        datetime.strptime(raw, "%H:%M")
        db.save_reminder(user_id, chat_id, raw)
        schedule_reminder(context, user_id, chat_id, raw)
        await update.message.reply_text(f"✅ Reminder harian aktif jam {raw} WIB.")
    except ValueError:
        await update.message.reply_text("Jam harus format HH:MM, contoh `/reminder 21:00`", parse_mode=ParseMode.MARKDOWN)


async def reminder_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    for job in context.job_queue.get_jobs_by_name(f"reminder:{user_id}"):
        job.schedule_removal()
    disabled = db.disable_reminder(user_id)
    await update.message.reply_text("✅ Reminder dimatikan." if disabled else "Reminder belum pernah diset.")


async def utang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) < 2:
        await update.message.reply_text("Format: `/utang nama nominal catatan`\nContoh: `/utang Rani 50000 pinjam makan`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        nama = context.args[0]
        nominal = parse_nominal(context.args[1])
        catatan = " ".join(context.args[2:])
        debt_id = db.add_debt(user_id, "utang", nama, nominal, catatan)
        await update.message.reply_text(f"✅ Utang dicatat #{debt_id}: {nama} — {rupiah(nominal)}")
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def piutang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) < 2:
        await update.message.reply_text("Format: `/piutang nama nominal catatan`\nContoh: `/piutang Dini 30000 titip beli`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        nama = context.args[0]
        nominal = parse_nominal(context.args[1])
        catatan = " ".join(context.args[2:])
        debt_id = db.add_debt(user_id, "piutang", nama, nominal, catatan)
        await update.message.reply_text(f"✅ Piutang dicatat #{debt_id}: {nama} — {rupiah(nominal)}")
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def daftar_utang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    rows = db.list_debts(user_id)
    if not rows:
        await update.message.reply_text("Belum ada utang/piutang.")
        return
    lines = ["🤝 *Utang & Piutang*"]
    for r in rows:
        icon = "🔴" if r["tipe"] == "utang" else "🟢"
        lines.append(f"{icon} #{r['id']} {r['tipe']} {r['nama']} — {rupiah(r['nominal'])} • {r['status']} • {r['catatan'] or '-'}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def lunas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Format: `/lunas 3`", parse_mode=ParseMode.MARKDOWN)
        return
    ok = db.mark_debt_paid(user_id, int(context.args[0]))
    await update.message.reply_text("✅ Ditandai lunas." if ok else "ID tidak ditemukan.")


async def tabungan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if not context.args:
        rows = db.list_savings(user_id)
        if not rows:
            await update.message.reply_text("Belum ada target tabungan. Buat: `/tabungan HP 3000000`", parse_mode=ParseMode.MARKDOWN)
            return
        lines = ["🎯 *Target tabungan*"]
        for r in rows:
            pct = r["terkumpul"] / r["target"] * 100
            lines.append(f"#{r['id']} {r['nama']} — {rupiah(r['terkumpul'])}/{rupiah(r['target'])} ({pct:.1f}%)")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return
    if len(context.args) < 2:
        await update.message.reply_text("Format: `/tabungan nama target`\nContoh: `/tabungan HP 3000000`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        target = parse_nominal(context.args[-1])
        nama = " ".join(context.args[:-1])
        goal_id = db.add_saving_goal(user_id, nama, target)
        await update.message.reply_text(f"✅ Target tabungan dibuat #{goal_id}: {nama} — {rupiah(target)}")
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def nabung(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) != 2 or not context.args[0].isdigit():
        await update.message.reply_text("Format: `/nabung id nominal`\nContoh: `/nabung 1 50000`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        ok = db.topup_saving(user_id, int(context.args[0]), parse_nominal(context.args[1]))
        await update.message.reply_text("✅ Tabungan ditambah." if ok else "ID tabungan tidak ditemukan.")
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def interactive_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = ensure_user_from_update(update)
    text = update.message.text
    tipe = "keluar" if "Pengeluaran" in text else "masuk"
    context.user_data["input_tipe"] = tipe
    cats = db.get_categories(user_id, tipe)
    keyboard = [[c["name"]] for c in cats[:12]] + [["Batal"]]
    await update.message.reply_text("Pilih kategori:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True))
    return ASK_KATEGORI


async def interactive_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.lower() == "batal":
        await update.message.reply_text("Batal ya.", reply_markup=menu_keyboard())
        return ConversationHandler.END
    context.user_data["input_kategori"] = update.message.text.lower()
    await update.message.reply_text("Nominalnya berapa? Contoh: 12000 atau 12k")
    return ASK_NOMINAL


async def interactive_nominal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["input_nominal"] = parse_nominal(update.message.text)
        await update.message.reply_text("Catatannya apa? Kalau nggak ada, ketik `-`.", parse_mode=ParseMode.MARKDOWN)
        return ASK_CATATAN
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return ASK_NOMINAL


async def interactive_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["input_catatan"] = "" if update.message.text.strip() == "-" else update.message.text.strip()
    keyboard = ReplyKeyboardMarkup(
        [["cash", "qris"], ["shopeepay", "dana"], ["gopay", "bank"], ["lainnya"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text("Metode pembayarannya apa? Pilih tombol atau ketik sendiri. Contoh: qris / shopeepay / dana / cash", reply_markup=keyboard)
    return ASK_PAYMENT


async def interactive_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = ensure_user_from_update(update)
    tipe = context.user_data["input_tipe"]
    kategori = context.user_data["input_kategori"]
    nominal = context.user_data["input_nominal"]
    catatan = context.user_data.get("input_catatan", "")
    payment_method = normalize_payment_method(update.message.text.strip())
    if not db.category_exists(user_id, tipe, kategori):
        db.add_category(user_id, tipe, kategori)
    transaction_id = db.add_transaction(user_id, tipe, nominal, kategori, catatan, None, payment_method)
    row = db.get_transaction(user_id, transaction_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Cara edit", callback_data=f"edit_hint:{transaction_id}"), InlineKeyboardButton("🗑️ Hapus", callback_data=f"delete_yes:{transaction_id}")],
        [InlineKeyboardButton("📘 Lihat hari ini", callback_data="report_today")],
    ])
    await update.message.reply_text(format_success(row, db.activity_streak(user_id)), parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    await update.message.reply_text("Menu utama:", reply_markup=menu_keyboard())
    return ConversationHandler.END


async def produk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    try:
        nama, modal, harga_jual, stok = parse_product_args(context.args)
        product_id = db.add_product(user_id, nama, modal, harga_jual, stok)
        laba = harga_jual - modal
        await update.message.reply_text(
            f"✅ Produk dibuat #{product_id}\n"
            f"{nama}\n"
            f"Modal: {rupiah(modal)}\n"
            f"Harga jual: {rupiah(harga_jual)}\n"
            f"Laba/pcs: {rupiah(laba)}\n"
            f"Stok: {stok}",
            reply_markup=menu_keyboard(),
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc), parse_mode=ParseMode.MARKDOWN)


async def stok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    rows = db.list_products(user_id)
    if not rows:
        await update.message.reply_text(
            "Belum ada produk. Tambah dulu:\n`/produk indomie soto | 2200 | 4000 | 10`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text("📦 *Stok barang:*\n\n" + "\n".join(format_product(r) for r in rows), parse_mode=ParseMode.MARKDOWN)


async def tambah_stok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) != 2 or not context.args[0].isdigit():
        await update.message.reply_text("Format: `/tambah_stok id_produk qty`\nContoh: `/tambah_stok 1 5`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        qty = int(context.args[1])
        if qty <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Qty harus angka lebih dari 0.")
        return
    ok = db.add_stock(user_id, int(context.args[0]), qty)
    await update.message.reply_text("✅ Stok ditambah." if ok else "Produk tidak ditemukan.")


async def jual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if len(context.args) < 2 or not context.args[0].isdigit():
        await update.message.reply_text("Format: `/jual id_produk qty catatan`\nContoh: `/jual 1 2 pembeli tetangga`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        product_id = int(context.args[0])
        qty = int(context.args[1])
        if qty <= 0:
            raise ValueError("Qty harus lebih dari 0.")
        catatan = " ".join(context.args[2:])
        sale_id = db.add_sale(user_id, product_id, qty, catatan)
        sale = db.list_sales(user_id, 1)[0]
        await update.message.reply_text("✅ Penjualan dicatat!\n" + format_sale(sale), reply_markup=menu_keyboard())
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def laporan_laba(update: Update, context: ContextTypes.DEFAULT_TYPE, title: str, start: date, end: date) -> None:
    user_id = ensure_user_from_update(update)
    summary = db.sales_summary_range(user_id, start, end)
    await reply_markdown_safe(update, format_sales_summary(title, summary))


async def laba_hariini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start, end = range_today()
    await laporan_laba(update, context, f"Laba Hari Ini ({start.isoformat()})", start, end)


async def laba_bulanini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start, end = range_this_month()
    await laporan_laba(update, context, f"Laba Bulan Ini ({start.isoformat()} s/d {end.isoformat()})", start, end)


async def jualan_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        ["➕ Tambah Produk", "🛒 Catat Penjualan"],
        ["📦 Lihat Stok", "💰 Laba Hari Ini"],
        ["📆 Laba Bulan Ini", "Batal"],
    ]
    await update.message.reply_text(
        "🛒 *Mode jualan*\nPilih yang mau kamu lakukan:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return SELL_MENU


async def jualan_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "Batal":
        await update.message.reply_text("Oke, balik ke menu utama.", reply_markup=menu_keyboard())
        return ConversationHandler.END
    if text == "📦 Lihat Stok":
        await stok(update, context)
        await update.message.reply_text("Balik ke menu utama ya.", reply_markup=menu_keyboard())
        return ConversationHandler.END
    if text == "💰 Laba Hari Ini":
        await laba_hariini(update, context)
        await update.message.reply_text("Balik ke menu utama ya.", reply_markup=menu_keyboard())
        return ConversationHandler.END
    if text == "📆 Laba Bulan Ini":
        await laba_bulanini(update, context)
        await update.message.reply_text("Balik ke menu utama ya.", reply_markup=menu_keyboard())
        return ConversationHandler.END
    if text == "➕ Tambah Produk":
        await update.message.reply_text(
            "Ketik data produk dengan format:\n`nama barang | modal | harga jual | stok`\n\nContoh:\n`indomie soto | 2200 | 4000 | 10`",
            parse_mode=ParseMode.MARKDOWN,
        )
        context.user_data["jualan_action"] = "add_product"
        return SELL_PRODUCT
    if text == "🛒 Catat Penjualan":
        user_id = ensure_user_from_update(update)
        rows = db.list_products(user_id)
        if not rows:
            await update.message.reply_text("Belum ada produk. Tambah produk dulu ya.", reply_markup=menu_keyboard())
            return ConversationHandler.END
        keyboard = [[f"#{r['id']} {r['nama']}"] for r in rows[:20]] + [["Batal"]]
        await update.message.reply_text("Pilih produk yang terjual:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True))
        return SELL_PRODUCT
    await update.message.reply_text("Pilih dari tombol ya.")
    return SELL_MENU


async def jualan_product_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.lower() == "batal":
        await update.message.reply_text("Batal ya.", reply_markup=menu_keyboard())
        return ConversationHandler.END
    user_id = ensure_user_from_update(update)
    if context.user_data.get("jualan_action") == "add_product":
        try:
            nama, modal, harga_jual, stok_qty = parse_product_args([text])
            product_id = db.add_product(user_id, nama, modal, harga_jual, stok_qty)
            await update.message.reply_text(
                f"✅ Produk dibuat #{product_id}: {nama}\nModal {rupiah(modal)} • Jual {rupiah(harga_jual)} • Stok {stok_qty}",
                reply_markup=menu_keyboard(),
            )
            context.user_data.pop("jualan_action", None)
            return ConversationHandler.END
        except ValueError as exc:
            await update.message.reply_text(str(exc), parse_mode=ParseMode.MARKDOWN)
            return SELL_PRODUCT
    if not text.startswith("#"):
        await update.message.reply_text("Pilih produk dari tombol ya.")
        return SELL_PRODUCT
    try:
        product_id = int(text.split()[0].replace("#", ""))
    except ValueError:
        await update.message.reply_text("Produk tidak valid, pilih dari tombol ya.")
        return SELL_PRODUCT
    product = db.get_product(user_id, product_id)
    if not product:
        await update.message.reply_text("Produk tidak ditemukan.")
        return SELL_PRODUCT
    context.user_data["sale_product_id"] = product_id
    await update.message.reply_text(f"Jual berapa pcs {product['nama']}? Stok saat ini: {product['stok']}")
    return SELL_QTY


async def jualan_qty_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        qty = int(update.message.text.strip())
        if qty <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Qty harus angka lebih dari 0. Contoh: 2")
        return SELL_QTY
    context.user_data["sale_qty"] = qty
    await update.message.reply_text("Catatan penjualannya apa? Kalau nggak ada, ketik `-`.", parse_mode=ParseMode.MARKDOWN)
    return SELL_NOTE


async def jualan_note_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = ensure_user_from_update(update)
    product_id = int(context.user_data["sale_product_id"])
    qty = int(context.user_data["sale_qty"])
    catatan = "" if update.message.text.strip() == "-" else update.message.text.strip()
    try:
        db.add_sale(user_id, product_id, qty, catatan)
        sale = db.list_sales(user_id, 1)[0]
        await update.message.reply_text("✅ Penjualan dicatat!\n" + format_sale(sale), reply_markup=menu_keyboard())
        return ConversationHandler.END
    except ValueError as exc:
        await update.message.reply_text(str(exc), reply_markup=menu_keyboard())
        return ConversationHandler.END


async def menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    mapping = {
        "📅 Hari Ini": hariini,
        "🔎 Detail Hari Ini": detail_hariini,
        "📆 Bulan Ini": bulanini,
        "📊 Statistik": stat,
        "🧾 Riwayat": riwayat,
        "🛒 Mode Jualan": jualan_menu,
        "💰 Laba Bulan Ini": laba_bulanini,
        "🏷️ Kategori": kategori,
        "💾 Export CSV": export_csv,
    }
    if text in mapping:
        await mapping[text](update, context)
    else:
        await update.message.reply_text("Aku belum ngerti. Coba /help ya.", reply_markup=menu_keyboard())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("ERROR:", context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Aduh ada error kecil 😭 Coba ulangi command-nya ya.")



async def theme_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if not context.args:
        current = db.get_user_theme(user_id)
        await update.message.reply_text(
            f"🎨 Theme kamu sekarang: *{current}*\n\nPilih: `/theme soft`, `/theme clean`, atau `/theme cute`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    try:
        theme = db.set_user_theme(user_id, context.args[0])
        await update.message.reply_text(f"✅ Theme diganti ke *{theme}*. Report berikutnya pakai vibe yang lebih clean/aesthetic ✨", parse_mode=ParseMode.MARKDOWN)
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def wish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    raw = " ".join(context.args).strip()
    if not raw or "|" not in raw:
        await update.message.reply_text("Format: `/wish barang | kategori | harga`\nContoh: `/wish cushion | beauty | 85000`", parse_mode=ParseMode.MARKDOWN)
        return
    parts = [x.strip() for x in raw.split("|") if x.strip()]
    if len(parts) < 3:
        await update.message.reply_text("Format: `/wish barang | kategori | harga`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        item, kategori, nominal = parts[0], parts[1], parse_nominal(parts[2])
        wish_id = db.add_wishlist(user_id, item, kategori, nominal)
        await update.message.reply_text(f"🛍️ Wishlist ditambah!\nID #{wish_id} • *{item}* • {rupiah(nominal)}", parse_mode=ParseMode.MARKDOWN)
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    rows = db.list_wishlist(user_id)
    if not rows:
        await update.message.reply_text("Wishlist masih kosong. Tambah pakai `/wish barang | kategori | harga`", parse_mode=ParseMode.MARKDOWN)
        return
    lines = ["🛍️ *Wishlist*"]
    for r in rows[:30]:
        lines.append(f"#{r['id']} • *{r['item_name']}* • {r['kategori']} • {rupiah(r['nominal'])}")
    lines.append("\nKalau sudah kebeli: `/bought ID [metode]`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def bought(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Format: `/bought ID metode`\nContoh: `/bought 3 shopeepay`", parse_mode=ParseMode.MARKDOWN)
        return
    wish_id = int(context.args[0])
    method = normalize_payment_method(" ".join(context.args[1:]) or "cash")
    tid = db.mark_wishlist_bought(user_id, wish_id, method)
    if not tid:
        await update.message.reply_text("Wishlist ID itu nggak ketemu / sudah dibeli.")
        return
    row = db.get_transaction(user_id, tid)
    await update.message.reply_text("✅ Wishlist ditandai sudah dibeli dan masuk transaksi:\n\n" + format_transaction(row), parse_mode=ParseMode.MARKDOWN)


async def close_month(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start, end = range_this_month()
    await report(update, context, f"Monthly Wrap-Up ({start.isoformat()} s/d {end.isoformat()})", start, end)


def get_handlers():
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(➖ Catat Pengeluaran|➕ Catat Pemasukan)$"), interactive_start)],
        states={
            ASK_KATEGORI: [MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_category)],
            ASK_NOMINAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_nominal)],
            ASK_CATATAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_note)],
            ASK_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_payment)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    sale_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛒 Mode Jualan$"), jualan_menu)],
        states={
            SELL_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, jualan_menu_choice)],
            SELL_PRODUCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, jualan_product_step)],
            SELL_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, jualan_qty_step)],
            SELL_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, jualan_note_step)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    return [
        CommandHandler("start", start),
        CommandHandler("help", help_command),
        CommandHandler(["keluar", "k", "out", "expense"], keluar),
        CommandHandler(["masuk", "m", "in", "income"], masuk),
        CommandHandler(["bulk", "batch"], bulk),
        CommandHandler(["bulk_out", "batch_out"], bulk_out),
        CommandHandler(["bulk_in", "batch_in"], bulk_in),
        CommandHandler(["kategori_tambah", "ktb", "add_category"], kategori_tambah),
        CommandHandler(["kategori", "kt", "category", "categories"], kategori),
        CommandHandler(["hariini", "h", "today"], hariini),
        CommandHandler(["detail_hariini", "dh", "detail_today", "daily"], detail_hariini),
        CommandHandler(["mingguini", "mg", "week"], mingguini),
        CommandHandler(["bulanini", "b", "month"], bulanini),
        CommandHandler(["detail_bulanini", "detail_month", "dm"], detail_bulanini),
        CommandHandler(["tahunini", "t", "year"], tahunini),
        CommandHandler(["range", "rg", "period"], range_report),
        CommandHandler(["budget", "bd"], budget),
        CommandHandler(["reminder", "rm"], reminder),
        CommandHandler(["reminder_off", "rmo"], reminder_off),
        CommandHandler(["hapus_terakhir", "ht"], hapus_terakhir),
        CommandHandler(["undo"], undo),
        CommandHandler(["rename_cat", "merge_cat"], rename_cat),
        CommandHandler(["search", "find"], search_transaksi),
        CommandHandler(["cat", "category_filter"], category_filter),
        CommandHandler(["pay", "payment"], edit_payment_method),
        CommandHandler(["method", "payment_method"], filter_payment_method),
        CommandHandler(["backup_reminder"], backup_reminder),
        CommandHandler(["edit_terakhir", "et"], edit_terakhir),
        CommandHandler(["detail", "d", "view"], detail_transaksi),
        CommandHandler(["edit", "e"], edit_transaksi),
        CommandHandler(["hapus", "x", "del", "delete"], hapus_transaksi),
        CommandHandler(["riwayat", "r", "history"], riwayat),
        CommandHandler(["export_csv", "csv", "export"], export_csv),
        CommandHandler(["stat", "s", "stats"], stat),
        CommandHandler(["theme"], theme_command),
        CommandHandler(["wish"], wish),
        CommandHandler(["wishlist", "wishes"], wishlist),
        CommandHandler(["bought"], bought),
        CommandHandler(["close_month", "wrapup"], close_month),
        CommandHandler(["utang", "u", "debt"], utang),
        CommandHandler(["piutang", "pu", "receivable"], piutang),
        CommandHandler(["daftar_utang", "du", "debts"], daftar_utang),
        CommandHandler(["lunas", "ln"], lunas),
        CommandHandler(["tabungan", "tb", "saving"], tabungan),
        CommandHandler(["nabung", "nb", "save"], nabung),
        CommandHandler(["produk", "p", "product"], produk),
        CommandHandler(["stok", "st", "stock"], stok),
        CommandHandler(["tambah_stok", "ts", "restock"], tambah_stok),
        CommandHandler(["jual", "j", "sell"], jual),
        CommandHandler(["laba_hariini", "lh", "profit_today"], laba_hariini),
        CommandHandler(["laba_bulanini", "lb", "profit"], laba_bulanini),
        CallbackQueryHandler(delete_callback, pattern="^(delete_|edit_hint:|report_today)"),
        conv,
        sale_conv,
        MessageHandler(filters.TEXT & ~filters.COMMAND, menu_text),
    ]
