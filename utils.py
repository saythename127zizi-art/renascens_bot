"""Utility formatter dan parser."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

JAKARTA_TZ = ZoneInfo("Asia/Jakarta")


def today_jakarta() -> date:
    return datetime.now(JAKARTA_TZ).date()


def rupiah(value: int | float | None) -> str:
    value = int(value or 0)
    return "Rp" + f"{value:,}".replace(",", ".")


def normalize_payment_method(name: str | None) -> str:
    raw = (name or "cash").strip().lower().replace("_", " ").replace("-", " ")
    raw = " ".join(raw.split())
    aliases = {
        "tunai": "cash", "cash": "cash",
        "qris": "qris", "qr": "qris",
        "spay": "shopeepay", "shopee pay": "shopeepay", "shopeepay": "shopeepay",
        "dana": "dana", "gopay": "gopay", "go pay": "gopay", "ovo": "ovo",
        "bank": "bank", "transfer": "bank", "tf": "bank",
        "bca": "bca", "bri": "bri", "bni": "bni", "mandiri": "mandiri", "blu": "blu", "seabank": "seabank",
        "spaylater": "spaylater", "paylater": "paylater", "kartu": "kartu", "card": "kartu",
        "lainnya": "lainnya",
    }
    return aliases.get(raw, raw or "cash")


def parse_payment_hint(raw: str) -> tuple[str, str]:
    """Ambil metode pembayaran dari teks.

    Bisa pakai:
    - @qris di akhir
    - via qris di akhir
    - | qris sebagai part terpisah
    """
    text = raw.strip()
    payment = "cash"

    # Format cepat: /out 12000 makan seblak @qris
    parts = text.split()
    if parts and parts[-1].startswith("@") and len(parts[-1]) > 1:
        payment = normalize_payment_method(parts[-1][1:])
        text = " ".join(parts[:-1]).strip()
        return text, payment

    # Format natural: /out 12000 makan seblak via qris
    if len(parts) >= 2 and parts[-2].lower() in {"via", "pakai", "pake"}:
        payment = normalize_payment_method(parts[-1])
        text = " ".join(parts[:-2]).strip()

    return text, payment


def parse_nominal(raw: str) -> int:
    cleaned = raw.lower().replace("rp", "").replace(".", "").replace(",", "").strip()
    if cleaned.endswith("k"):
        cleaned = cleaned[:-1] + "000"
    if not cleaned.isdigit():
        raise ValueError("Nominal harus angka. Contoh: 12000 atau 12k")
    nominal = int(cleaned)
    if nominal <= 0:
        raise ValueError("Nominal harus lebih dari 0.")
    return nominal


def parse_transaction_args(args: list[str]) -> tuple[int, str, str]:
    if len(args) < 2:
        raise ValueError("Format kurang lengkap.")
    nominal = parse_nominal(args[0])
    kategori = args[1].lower().strip()
    catatan = " ".join(args[2:]).strip() if len(args) > 2 else ""
    return nominal, kategori, catatan


def transaction_display_id(row) -> int:
    try:
        return int(row["display_id"] or row["id"])
    except Exception:
        return int(row["id"])


def parse_transaction_args_with_date(args: list[str]) -> tuple[int, str, str, str | None, str]:
    """Parse transaksi + optional tanggal manual + metode pembayaran.

    Format:
    /out 12000 makan seblak
    /out 12000 makan seblak @qris
    /out 12000 makan seblak | 2026-05-25 | qris
    /out 12000 makan seblak via dana
    """
    raw = " ".join(args).strip()
    created_at = None
    payment_method = "cash"

    if "|" in raw:
        parts = [p.strip() for p in raw.split("|") if p.strip()]
        raw = parts[0] if parts else raw
        for extra in parts[1:]:
            try:
                d = parse_date(extra)
                now = datetime.now(JAKARTA_TZ)
                created_at = datetime(d.year, d.month, d.day, now.hour, now.minute, now.second).isoformat(timespec="seconds")
            except ValueError:
                payment_method = normalize_payment_method(extra)

    raw, hinted_payment = parse_payment_hint(raw)
    if hinted_payment != "cash":
        payment_method = hinted_payment

    nominal, kategori, catatan = parse_transaction_args(raw.split())
    return nominal, kategori, catatan, created_at, payment_method


def parse_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("Tanggal harus format YYYY-MM-DD. Contoh: 2026-05-26") from exc


def range_today() -> tuple[date, date]:
    d = today_jakarta()
    return d, d


def range_this_week() -> tuple[date, date]:
    d = today_jakarta()
    start = d - timedelta(days=d.weekday())
    return start, d


def range_this_month() -> tuple[date, date]:
    d = today_jakarta()
    return date(d.year, d.month, 1), d


def range_this_year() -> tuple[date, date]:
    d = today_jakarta()
    return date(d.year, 1, 1), d



def progress_bar(percent: float, width: int = 10) -> str:
    percent = max(0, min(percent, 100))
    filled = round(width * percent / 100)
    return "█" * filled + "░" * (width - filled)


def money_mood(balance: int, expense: int) -> str:
    if expense == 0:
        return "🌱 Aman, belum ada pengeluaran di periode ini."
    if balance >= 0:
        return "✨ Good job, pemasukan masih nutup pengeluaran."
    if expense < 50000:
        return "🍃 Minus dikit, masih bisa dikejar."
    return "🫠 Pengeluaran lagi lebih kenceng dari pemasukan. Gapapa, yang penting kelihatan datanya."


def format_transaction(row) -> str:
    sign = "➕" if row["tipe"] == "masuk" else "➖"
    tipe = "Pemasukan" if row["tipe"] == "masuk" else "Pengeluaran"
    tanggal = row["created_at"][:16].replace("T", " ")
    note = row["catatan"] or "-"
    return (
        f"{sign} *ID #{transaction_display_id(row)}* • {tipe}\n"
        f"   Nominal: *{rupiah(row['nominal'])}*\n"
        f"   Kategori: `{row['kategori']}`\n"
        f"   Metode: `{row['payment_method']}`\n"
        f"   Catatan: {note}\n"
        f"   Waktu: {tanggal}"
    )


def format_transaction_one_line(row) -> str:
    sign = "➕" if row["tipe"] == "masuk" else "➖"
    note = f" — {row['catatan']}" if row["catatan"] else ""
    jam = row["created_at"][11:16]
    return f"{sign} *ID #{transaction_display_id(row)}* • {jam} • `{row['kategori']}` • `{row['payment_method']}` • *{rupiah(row['nominal'])}*{note}"


def format_success(row, streak: int = 0) -> str:
    sign = "➕" if row["tipe"] == "masuk" else "➖"
    tipe = "Pemasukan" if row["tipe"] == "masuk" else "Pengeluaran"
    note = row["catatan"] or "-"
    streak_line = f"\n🔥 Streak catat: *{streak} hari*" if streak else ""
    return (
        f"✅ *Berhasil dicatat!*\n\n"
        f"{sign} *{tipe}*\n"
        f"🆔 ID: *#{transaction_display_id(row)}*\n"
        f"💸 Nominal: *{rupiah(row['nominal'])}*\n"
        f"🏷️ Kategori: `{row['kategori']}`\n"
        f"💳 Metode: `{row['payment_method']}`\n"
        f"📝 Catatan: {note}"
        f"{streak_line}\n\n"
        f"Edit: `/edit {transaction_display_id(row)} {row['nominal']} {row['kategori']} {note if note != '-' else ''} @{row['payment_method']}`\n"
        f"Delete: `/del {transaction_display_id(row)}`"
    )


def format_summary(title: str, summary: dict) -> str:
    """Ringkasan pendek: enak dibaca untuk /hariini, /bulanini, dll."""
    income = int(summary["income"])
    expense = int(summary["expense"])
    balance = int(summary["balance"])
    total_flow = income + expense
    expense_pct = (expense / total_flow * 100) if total_flow else 0
    rows = summary.get("rows", [])
    expense_cats = [r for r in summary.get("per_cat", []) if r["tipe"] == "keluar"]
    income_cats = [r for r in summary.get("per_cat", []) if r["tipe"] == "masuk"]
    payment_out = [r for r in summary.get("per_payment", []) if r["tipe"] == "keluar"]

    lines = [f"📘 *{title}*", ""]
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append(f"💚 Pemasukan   : *{rupiah(income)}*")
    lines.append(f"💸 Pengeluaran : *{rupiah(expense)}*")
    lines.append(f"💰 Saldo       : *{rupiah(balance)}*")
    lines.append(f"{progress_bar(expense_pct)} {expense_pct:.0f}% arus uang keluar")
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append(money_mood(balance, expense))

    if not rows:
        lines.append("\nBelum ada transaksi di periode ini. Yuk catat 1 transaksi biar mulai kebaca ✨")
        return "\n".join(lines)

    if expense_cats:
        lines.append("\n🔥 *Top pengeluaran:*")
        for i, r in enumerate(expense_cats[:3], 1):
            lines.append(f"{i}. `{r['kategori']}` — *{rupiah(r['total'])}* ({r['jumlah']}x)")
    if income_cats:
        lines.append("\n🌱 *Top pemasukan:*")
        for i, r in enumerate(income_cats[:2], 1):
            lines.append(f"{i}. `{r['kategori']}` — *{rupiah(r['total'])}* ({r['jumlah']}x)")
    if payment_out:
        lines.append("\n💳 *Metode paling kepakai:*")
        for i, r in enumerate(payment_out[:3], 1):
            lines.append(f"{i}. `{r['payment_method']}` — *{rupiah(r['total'])}* ({r['jumlah']}x)")

    lines.append("\n🧾 *Transaksi terakhir:*")
    for r in rows[:3]:
        lines.append(format_transaction_one_line(r))

    lines.append("\nLihat lengkap: `/detail_today` atau `/history 10`")
    lines.append("Fix by ID: `/edit ID nominal kategori catatan` • `/del ID`")
    return "\n".join(lines)


def format_summary_detail(title: str, summary: dict) -> str:
    lines = [f"📒 *Detail {title}*", ""]
    lines.append(f"➕ Pemasukan: *{rupiah(summary['income'])}*")
    lines.append(f"➖ Pengeluaran: *{rupiah(summary['expense'])}*")
    lines.append(f"💰 Saldo: *{rupiah(summary['balance'])}*")

    if summary["per_cat"]:
        lines.append("\n🏷️ *Breakdown kategori lengkap:*")
        for r in summary["per_cat"]:
            icon = "➕" if r["tipe"] == "masuk" else "➖"
            lines.append(f"{icon} `{r['kategori']}`: *{rupiah(r['total'])}* ({r['jumlah']}x)")
    else:
        lines.append("\nBelum ada transaksi di periode ini.")

    if summary.get("per_payment"):
        lines.append("\n💳 *Breakdown metode pembayaran:*")
        for r in summary["per_payment"]:
            icon = "➕" if r["tipe"] == "masuk" else "➖"
            lines.append(f"{icon} `{r['payment_method']}`: *{rupiah(r['total'])}* ({r['jumlah']}x)")

    if summary["rows"]:
        lines.append("\n🧾 *Semua transaksi periode ini:*")
        for r in summary["rows"][:30]:
            lines.append(format_transaction_one_line(r))
        if len(summary["rows"]) > 30:
            lines.append(f"\n...dan {len(summary['rows']) - 30} transaksi lainnya. Pakai /export_csv buat lengkapnya.")
    return "\n".join(lines)

def help_text() -> str:
    return (
        "Hai! Aku *DuitKu Bot* 💸\n\n"
        "Biar keliatan lebih clean, kamu bisa pakai command style English. Command Indonesia lama tetap aktif kok.\n\n"
        "✨ *Daily money log:*\n"
        "`/out 12000 makan seblak @qris` → catat pengeluaran + metode bayar\n"
        "`/in 45000 jualan mie @cash` → catat pemasukan + metode terima\n"
        "`/out 12000 makan seblak | 2026-05-25 | dana` → tanggal + metode\n"
        "`/bulk` / `/bulk_out` / `/bulk_in` → input banyak sekaligus\n"
        "`/today` → ringkasan hari ini\n"
        "`/month` → ringkasan bulan ini\n"
        "`/history` → transaksi terakhir\n"
        "`/stats` → statistik\n\n"
        "✏️ *Fix transaksi by ID:*\n"
        "`/edit 13 12000 makan seblak` → edit ID #13\n"
        "`/del 13` → hapus ID #13\n"
        "`/undo` → hapus transaksi terakhir\n"
        "`/view 13` → lihat detail ID #13\n"
        "`/rename_cat lzd | marketplace` → rapihin kategori\n"
        "`/search seblak` → cari transaksi\n"
        "`/cat makan` → filter kategori\n"
        "`/pay 13 qris` → ganti metode bayar ID #13\n"
        "`/method qris` → lihat transaksi metode qris\n\n"
        "🛒 *Selling mode:*\n"
        "`/product indomie soto | 2200 | 4000 | 10` → tambah produk\n"
        "`/sell 1 2 pembeli tetangga` → catat penjualan\n"
        "`/stock` → lihat stok\n"
        "`/profit` → laba bulan ini\n\n"
        "Catatan: ID transaksi sekarang dirapikan lagi setelah delete, jadi nggak lompat-lompat ✨\n"
        "Pakai tombol menu di bawah kalau lagi males ngetik ✨"
    )

def parse_product_args(args: list[str]) -> tuple[str, int, int, int]:
    """Format: /produk nama barang | modal | harga_jual | stok"""
    raw = " ".join(args).strip()
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 4 or not parts[0]:
        raise ValueError("Format: `/produk nama barang | modal | harga_jual | stok`\nContoh: `/produk indomie soto | 2200 | 4000 | 10`")
    nama = parts[0]
    modal = parse_nominal(parts[1])
    harga_jual = parse_nominal(parts[2])
    try:
        stok = int(parts[3])
    except ValueError as exc:
        raise ValueError("Stok harus angka. Contoh: 10") from exc
    if stok < 0:
        raise ValueError("Stok tidak boleh minus.")
    return nama, modal, harga_jual, stok


def format_product(row) -> str:
    laba_satuan = int(row["harga_jual"]) - int(row["modal"])
    return (
        f"#{transaction_display_id(row)} {row['nama']}\n"
        f"   Modal: {rupiah(row['modal'])} • Jual: {rupiah(row['harga_jual'])} • Laba/pcs: {rupiah(laba_satuan)} • Stok: {row['stok']}"
    )


def format_sale(row) -> str:
    tanggal = row["created_at"][:16].replace("T", " ")
    note = f" — {row['catatan']}" if row["catatan"] else ""
    return f"🛒 #{transaction_display_id(row)} {tanggal} • {row['nama_barang']} x{row['qty']} • Omzet {rupiah(row['omzet'])} • Laba {rupiah(row['laba'])}{note}"


def format_sales_summary(title: str, summary: dict) -> str:
    lines = [f"💰 *{title}*", ""]
    lines.append(f"Barang terjual: *{summary['qty']} pcs*")
    lines.append(f"Omzet: *{rupiah(summary['omzet'])}*")
    lines.append(f"Modal: *{rupiah(summary['modal'])}*")
    lines.append(f"Laba bersih: *{rupiah(summary['laba'])}*")
    if summary["per_product"]:
        lines.append("")
        lines.append("🧾 *Per barang:*")
        for r in summary["per_product"]:
            lines.append(f"• {r['nama_barang']}: {r['qty']} pcs • omzet {rupiah(r['omzet'])} • laba {rupiah(r['laba'])}")
    if summary["rows"]:
        lines.append("")
        lines.append("Transaksi jualan terakhir:")
        for r in summary["rows"][:5]:
            lines.append(format_sale(r))
    else:
        lines.append("\nBelum ada penjualan di periode ini.")
    return "\n".join(lines)

# =========================
# v11 aesthetic input/report overrides
# =========================

CATEGORY_ICONS = {
    "food": "🍜", "makan": "🍜", "jajan": "🍭", "snack": "🍭",
    "shopping": "🛍️", "belanja": "🛍️", "marketplace": "🛒",
    "beauty": "🧴", "skincare": "🧴", "makeup": "💄",
    "home": "🏠", "rumah": "🏠", "grocery": "🥬", "dapur": "🥬",
    "transport": "🚗", "pulsa/data": "📱", "data": "📱",
    "health": "💊", "kesehatan": "💊", "cashback": "🎁", "jualan": "🛒",
    "gaji": "💼", "bonus": "✨", "hadiah": "🎁", "lainnya": "💸", "other": "💸",
}

PAYMENT_ICONS = {
    "cash": "💵", "qris": "📱", "shopeepay": "🛒", "dana": "🔵", "gopay": "🟢", "ovo": "🟣",
    "bank": "🏦", "bca": "🏦", "bri": "🏦", "bni": "🏦", "mandiri": "🏦", "blu": "🏦", "seabank": "🏦",
    "spaylater": "🧾", "paylater": "🧾", "kartu": "💳", "lainnya": "💳",
}

MONTHS_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]


def title_case_label(value: str | None) -> str:
    text = (value or "-").strip()
    if not text:
        return "-"
    special = {"qris": "QRIS", "ovo": "OVO", "dana": "DANA", "gopay": "GoPay", "shopeepay": "ShopeePay", "bca": "BCA", "bri": "BRI", "bni": "BNI", "blu": "Blu", "spaylater": "SPayLater"}
    return special.get(text.lower(), " ".join(w.capitalize() for w in text.split()))


def cat_icon(cat: str | None) -> str:
    return CATEGORY_ICONS.get((cat or "").lower(), "💸")


def pay_icon(method: str | None) -> str:
    return PAYMENT_ICONS.get((method or "cash").lower(), "💳")


def format_date_id(iso: str | None) -> str:
    if not iso:
        d = today_jakarta()
        return f"{d.day} {MONTHS_ID[d.month-1]} {d.year}"
    try:
        d = datetime.fromisoformat(iso[:10]).date()
    except Exception:
        d = today_jakarta()
    return f"{d.day} {MONTHS_ID[d.month-1]} {d.year}"


def parse_date(raw: str) -> date:  # type: ignore[override]
    text = (raw or "").strip().lower()
    today = today_jakarta()
    if text in {"today", "hari ini", "now", "sekarang"}:
        return today
    if text in {"yesterday", "kemarin", "yday"}:
        return today - timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    for fmt in ("%d/%m", "%d-%m"):
        try:
            d = datetime.strptime(text, fmt).date()
            return date(today.year, d.month, d.day)
        except ValueError:
            pass
    raise ValueError("Tanggal bisa: today, yesterday, 27/05, atau 2026-05-27")


def _date_to_iso_with_current_time(d: date) -> str:
    now = datetime.now(JAKARTA_TZ)
    return datetime(d.year, d.month, d.day, now.hour, now.minute, now.second).isoformat(timespec="seconds")


def parse_transaction_args_with_date(args: list[str]) -> tuple[int, str, str, str | None, str]:  # type: ignore[override]
    """v11 parser.

    New clean format:
    /out item | category | amount | payment
    /out today | item | category | amount | payment
    /out 27/05 | item | category | amount | payment

    Old format still works:
    /out 12000 makan seblak @qris
    """
    raw = " ".join(args).strip()
    if not raw:
        raise ValueError("Format kosong.")

    created_at = None
    payment_method = "cash"

    if "|" in raw:
        parts = [p.strip() for p in raw.split("|")]
        parts = [p for p in parts if p]
        if len(parts) < 3:
            raise ValueError("Format: `/out barang | kategori | harga | metode`")
        start_idx = 0
        # tanggal opsional di part pertama
        try:
            d = parse_date(parts[0])
            created_at = _date_to_iso_with_current_time(d)
            start_idx = 1
        except ValueError:
            start_idx = 0
        needed = parts[start_idx:]
        if len(needed) < 3:
            raise ValueError("Format: `/out barang | kategori | harga | metode`")
        item_name = needed[0].strip()
        kategori = needed[1].strip().lower()
        nominal = parse_nominal(needed[2])
        if len(needed) >= 4:
            payment_method = normalize_payment_method(needed[3])
        # tag need/want/restock boleh ditulis part ke-5, untuk saat ini disimpan di item via label ringan
        if len(needed) >= 5 and needed[4].strip():
            item_name = f"{item_name} [{needed[4].strip().lower()}]"
        return nominal, kategori, item_name, created_at, payment_method

    raw, hinted_payment = parse_payment_hint(raw)
    if hinted_payment != "cash":
        payment_method = hinted_payment
    parts = raw.split()
    if len(parts) < 2:
        raise ValueError("Format kurang lengkap.")
    nominal = parse_nominal(parts[0])
    kategori = parts[1].strip().lower()
    item_name = " ".join(parts[2:]).strip() or kategori
    return nominal, kategori, item_name, created_at, payment_method


def _row_item(row) -> str:
    try:
        return row["item_name"] or row["catatan"] or row["kategori"] or "-"
    except Exception:
        return row["catatan"] or row["kategori"] or "-"


def format_transaction(row) -> str:  # type: ignore[override]
    sign = "💚" if row["tipe"] == "masuk" else "💸"
    tipe = "Income" if row["tipe"] == "masuk" else "Expense"
    item = title_case_label(_row_item(row))
    cat = row["kategori"]
    method = row["payment_method"]
    tanggal = row["created_at"][:16].replace("T", " ") + " WIB"
    return (
        f"{sign} *ID #{transaction_display_id(row)}* • {tipe}\n"
        f"{cat_icon(cat)} *{item}*\n"
        f"   Category : {title_case_label(cat)}\n"
        f"   Amount   : *{rupiah(row['nominal'])}*\n"
        f"   Payment  : {pay_icon(method)} {title_case_label(method)}\n"
        f"   Date     : {tanggal}"
    )


def format_transaction_one_line(row) -> str:  # type: ignore[override]
    sign = "💚" if row["tipe"] == "masuk" else "💸"
    item = title_case_label(_row_item(row))
    cat = row["kategori"]
    method = row["payment_method"]
    return f"#{transaction_display_id(row):02d}  {sign} {cat_icon(cat)} *{item}* — {rupiah(row['nominal'])} • {pay_icon(method)} {title_case_label(method)}"


def format_success(row, streak: int = 0) -> str:  # type: ignore[override]
    tipe = "Income added" if row["tipe"] == "masuk" else "Expense added"
    item = title_case_label(_row_item(row))
    cat = row["kategori"]
    method = row["payment_method"]
    streak_line = f"\n🔥 Tracking day: *{streak}*" if streak else ""
    return (
        f"✅ *{tipe}!*\n\n"
        f"🆔 ID *#{transaction_display_id(row)}*\n"
        f"{cat_icon(cat)} *{item}*\n"
        f"   Category : {title_case_label(cat)}\n"
        f"   Amount   : *{rupiah(row['nominal'])}*\n"
        f"   Payment  : {pay_icon(method)} {title_case_label(method)}\n"
        f"   Date     : {format_date_id(row['created_at'])} • WIB"
        f"{streak_line}\n\n"
        f"✏️ `/edit {transaction_display_id(row)} {item.lower()} | {cat} | {row['nominal']} | {method}`\n"
        f"🗑️ `/del {transaction_display_id(row)}`"
    )


def money_mood(balance: int, expense: int) -> str:  # type: ignore[override]
    if expense == 0:
        return "🌱 Belum ada pengeluaran. Fresh start banget."
    if balance >= 0:
        return "✨ Nice, income masih nutup expense."
    if expense < 50000:
        return "🍃 Minus dikit, masih aman. Yang penting kecatat."
    return "🧘 Expense lagi kenceng, tapi gapapa. Sekarang datanya kelihatan."


def format_summary(title: str, summary: dict) -> str:  # type: ignore[override]
    income = int(summary["income"])
    expense = int(summary["expense"])
    balance = int(summary["balance"])
    rows = summary.get("rows", [])
    expense_cats = [r for r in summary.get("per_cat", []) if r["tipe"] == "keluar"]
    income_cats = [r for r in summary.get("per_cat", []) if r["tipe"] == "masuk"]
    payment_out = [r for r in summary.get("per_payment", []) if r["tipe"] == "keluar"]

    lines = [f"🌷 *{title}*", "_Asia/Jakarta • WIB_", ""]
    lines += [
        "💚 *Income*",
        f"{rupiah(income)}",
        "",
        "💸 *Expense*",
        f"{rupiah(expense)}",
        "",
        "🧾 *Balance*",
        f"{rupiah(balance)}",
        "━━━━━━━━━━━━━━",
        money_mood(balance, expense),
    ]
    if not rows:
        lines.append("\nBelum ada transaksi di periode ini. Input 1 aja dulu biar mulai kebaca ✨")
        return "\n".join(lines)

    if expense_cats:
        lines.append("\n🔥 *Biggest Categories*")
        for i, r in enumerate(expense_cats[:3], 1):
            cat = r["kategori"]
            lines.append(f"{i}. {cat_icon(cat)} {title_case_label(cat)} — *{rupiah(r['total'])}* ({r['jumlah']}x)")
    if income_cats:
        lines.append("\n🌱 *Top Income*")
        for i, r in enumerate(income_cats[:2], 1):
            cat = r["kategori"]
            lines.append(f"{i}. {cat_icon(cat)} {title_case_label(cat)} — *{rupiah(r['total'])}* ({r['jumlah']}x)")
    if payment_out:
        lines.append("\n💳 *Payment Split*")
        for r in payment_out[:3]:
            method = r["payment_method"]
            lines.append(f"{pay_icon(method)} {title_case_label(method)} — *{rupiah(r['total'])}* ({r['jumlah']}x)")

    lines.append("\n🧾 *Recent*")
    for r in rows[:5]:
        lines.append(format_transaction_one_line(r))
    lower_title = title.lower()
    if "bulan" in lower_title or "month" in lower_title:
        lines.append("\n`/detail_month` for full report ✨")
    elif "hari" in lower_title or "today" in lower_title:
        lines.append("\n`/detail_today` for full report ✨")
    else:
        lines.append("\n`/history` for transaction list ✨")
    return "\n".join(lines)


def format_summary_detail(title: str, summary: dict) -> str:  # type: ignore[override]
    lines = [f"📒 *Detail {title}*", "_Asia/Jakarta • WIB_", ""]
    lines.append(f"💚 Income  : *{rupiah(summary['income'])}*")
    lines.append(f"💸 Expense : *{rupiah(summary['expense'])}*")
    lines.append(f"🧾 Balance : *{rupiah(summary['balance'])}*")

    if summary.get("per_cat"):
        lines.append("\n🏷️ *Categories*")
        for r in summary["per_cat"]:
            icon = "💚" if r["tipe"] == "masuk" else "💸"
            cat = r["kategori"]
            lines.append(f"{icon} {cat_icon(cat)} {title_case_label(cat)}: *{rupiah(r['total'])}* ({r['jumlah']}x)")

    if summary.get("per_payment"):
        lines.append("\n💳 *Payment Methods*")
        for r in summary["per_payment"]:
            icon = "💚" if r["tipe"] == "masuk" else "💸"
            method = r["payment_method"]
            lines.append(f"{icon} {pay_icon(method)} {title_case_label(method)}: *{rupiah(r['total'])}* ({r['jumlah']}x)")

    if summary.get("rows"):
        lines.append("\n🧾 *Transactions*")
        for r in summary["rows"][:35]:
            lines.append(format_transaction_one_line(r))
        if len(summary["rows"]) > 35:
            lines.append(f"\n...dan {len(summary['rows']) - 35} transaksi lainnya. Pakai /export_csv buat lengkapnya.")
    else:
        lines.append("\nBelum ada transaksi di periode ini.")
    return "\n".join(lines)


def help_text() -> str:  # type: ignore[override]
    return (
        "🌷 *DuitKu — Money Diary Bot*\n"
        "Timezone: *Asia/Jakarta / WIB*\n\n"
        "✨ *Input rapi:*\n"
        "`/out barang | kategori | harga | metode`\n"
        "`/in sumber | kategori | nominal | metode`\n\n"
        "Contoh:\n"
        "`/out tisu basah | home | 5000 | ovo`\n"
        "`/out yesterday | joffi ramen | food | 7900 | cash`\n"
        "`/in spay deals | cashback | 5105 | shopeepay`\n\n"
        "📦 *Bulk:*\n"
        "`/bulk_out` lalu enter tiap baris:\n"
        "`joffi ramen | food | 7900 | cash`\n"
        "`sheetmask | beauty | 100 | shopeepay`\n\n"
        "📘 *Report:* `/today` `/month` `/detail_today` `/detail_month` `/history`\n"
        "✏️ *Fix:* `/edit ID barang | kategori | harga | metode` • `/del ID` • `/undo` • `/view ID`\n"
        "🔎 *Cari:* `/search nama` • `/cat kategori` • `/method cash`\n"
        "🎯 *Lainnya:* `/budget kategori nominal` • `/wish barang | kategori | harga` • `/wishlist` • `/bought ID`\n"
        "🎨 *Theme:* `/theme soft` `/theme clean` `/theme cute`\n"
        "💾 Backup: `/export_csv` sebelum update bot ya."
    )
