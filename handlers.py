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
    range_this_month,
    range_this_week,
    range_this_year,
    range_today,
    rupiah,
    today_jakarta,
)

ASK_TIPE, ASK_KATEGORI, ASK_NOMINAL, ASK_CATATAN = range(4)
SELL_MENU, SELL_PRODUCT, SELL_QTY, SELL_NOTE = range(4, 8)


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


async def add_transaction_command(update: Update, context: ContextTypes.DEFAULT_TYPE, tipe: str) -> None:
    user_id = ensure_user_from_update(update)
    try:
        nominal, kategori, catatan = parse_transaction_args(context.args)
        if not db.category_exists(user_id, tipe, kategori):
            db.add_category(user_id, tipe, kategori)
        transaction_id = db.add_transaction(user_id, tipe, nominal, kategori, catatan)
        row = db.get_transaction(user_id, transaction_id)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ Cara edit", callback_data=f"edit_hint:{transaction_id}"),
                InlineKeyboardButton("🗑️ Hapus", callback_data=f"delete_yes:{transaction_id}"),
            ],
            [InlineKeyboardButton("📘 Lihat hari ini", callback_data="report_today")],
        ])
        await update.message.reply_text(
            format_success(row, db.activity_streak(user_id)),
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
    await update.message.reply_text(format_summary(title, summary), parse_mode=ParseMode.MARKDOWN)


async def report_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, title: str, start: date, end: date) -> None:
    user_id = ensure_user_from_update(update)
    summary = db.summarize_range(user_id, start, end)
    await update.message.reply_text(format_summary_detail(title, summary), parse_mode=ParseMode.MARKDOWN)


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
        [InlineKeyboardButton("Ya, hapus", callback_data=f"delete_yes:{last['id']}"), InlineKeyboardButton("Batal", callback_data="delete_no")]
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
            f"`/edit {row['id']} {row['nominal']} {row['kategori']} {row['catatan'] or ''}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    transaction_id = int(query.data.split(":", 1)[1])
    deleted = db.delete_transaction(user_id, transaction_id)
    await query.edit_message_text("✅ Transaksi berhasil dihapus." if deleted else "Transaksi tidak ditemukan.")


async def edit_terakhir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = ensure_user_from_update(update)
    try:
        nominal, kategori, catatan = parse_transaction_args(context.args)
        row = db.update_last_transaction(user_id, nominal, kategori, catatan)
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
        nominal, kategori, catatan = parse_transaction_args(context.args[1:])
        if not db.category_exists(user_id, "masuk", kategori) and not db.category_exists(user_id, "keluar", kategori):
            # Kita tidak tahu tipe transaksi dari argumen, jadi nanti pakai tipe lama dari row.
            old = db.get_transaction(user_id, transaction_id)
            if old:
                db.add_category(user_id, old["tipe"], kategori)
        row = db.update_transaction(user_id, transaction_id, nominal, kategori, catatan)
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
    user_id = ensure_user_from_update(update)
    tipe = context.user_data["input_tipe"]
    kategori = context.user_data["input_kategori"]
    nominal = context.user_data["input_nominal"]
    catatan = "" if update.message.text.strip() == "-" else update.message.text.strip()
    if not db.category_exists(user_id, tipe, kategori):
        db.add_category(user_id, tipe, kategori)
    transaction_id = db.add_transaction(user_id, tipe, nominal, kategori, catatan)
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
    await update.message.reply_text(format_sales_summary(title, summary), parse_mode=ParseMode.MARKDOWN)


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


def get_handlers():
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(➖ Catat Pengeluaran|➕ Catat Pemasukan)$"), interactive_start)],
        states={
            ASK_KATEGORI: [MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_category)],
            ASK_NOMINAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_nominal)],
            ASK_CATATAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_note)],
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
        CommandHandler(["kategori_tambah", "ktb", "add_category"], kategori_tambah),
        CommandHandler(["kategori", "kt", "category", "categories"], kategori),
        CommandHandler(["hariini", "h", "today"], hariini),
        CommandHandler(["detail_hariini", "dh", "detail_today", "daily"], detail_hariini),
        CommandHandler(["mingguini", "mg", "week"], mingguini),
        CommandHandler(["bulanini", "b", "month"], bulanini),
        CommandHandler(["tahunini", "t", "year"], tahunini),
        CommandHandler(["range", "rg", "period"], range_report),
        CommandHandler(["budget", "bd"], budget),
        CommandHandler(["reminder", "rm"], reminder),
        CommandHandler(["reminder_off", "rmo"], reminder_off),
        CommandHandler(["hapus_terakhir", "ht"], hapus_terakhir),
        CommandHandler(["edit_terakhir", "et"], edit_terakhir),
        CommandHandler(["detail", "d", "view"], detail_transaksi),
        CommandHandler(["edit", "e"], edit_transaksi),
        CommandHandler(["hapus", "x", "del", "delete"], hapus_transaksi),
        CommandHandler(["riwayat", "r", "history"], riwayat),
        CommandHandler(["export_csv", "csv", "export"], export_csv),
        CommandHandler(["stat", "s", "stats"], stat),
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
