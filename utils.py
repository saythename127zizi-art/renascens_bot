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
        f"{sign} *ID #{row['id']}* • {tipe}\n"
        f"   Nominal: *{rupiah(row['nominal'])}*\n"
        f"   Kategori: `{row['kategori']}`\n"
        f"   Catatan: {note}\n"
        f"   Waktu: {tanggal}"
    )


def format_transaction_one_line(row) -> str:
    sign = "➕" if row["tipe"] == "masuk" else "➖"
    note = f" — {row['catatan']}" if row["catatan"] else ""
    jam = row["created_at"][11:16]
    return f"{sign} *ID #{row['id']}* • {jam} • `{row['kategori']}` • *{rupiah(row['nominal'])}*{note}"


def format_success(row, streak: int = 0) -> str:
    sign = "➕" if row["tipe"] == "masuk" else "➖"
    tipe = "Pemasukan" if row["tipe"] == "masuk" else "Pengeluaran"
    note = row["catatan"] or "-"
    streak_line = f"\n🔥 Streak catat: *{streak} hari*" if streak else ""
    return (
        f"✅ *Berhasil dicatat!*\n\n"
        f"{sign} *{tipe}*\n"
        f"🆔 ID: *#{row['id']}*\n"
        f"💸 Nominal: *{rupiah(row['nominal'])}*\n"
        f"🏷️ Kategori: `{row['kategori']}`\n"
        f"📝 Catatan: {note}"
        f"{streak_line}\n\n"
        f"Edit: `/edit {row['id']} {row['nominal']} {row['kategori']} {note if note != '-' else ''}`\n"
        f"Delete: `/del {row['id']}`"
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
        "`/out 12000 makan seblak` → catat pengeluaran\n"
        "`/in 45000 jualan mie` → catat pemasukan\n"
        "`/today` → ringkasan hari ini\n"
        "`/month` → ringkasan bulan ini\n"
        "`/history` → transaksi terakhir\n"
        "`/stats` → statistik\n\n"
        "✏️ *Fix transaksi by ID:*\n"
        "`/edit 13 12000 makan seblak` → edit ID #13\n"
        "`/del 13` → hapus ID #13\n"
        "`/view 13` → lihat detail ID #13\n\n"
        "🛒 *Selling mode:*\n"
        "`/product indomie soto | 2200 | 4000 | 10` → tambah produk\n"
        "`/sell 1 2 pembeli tetangga` → catat penjualan\n"
        "`/stock` → lihat stok\n"
        "`/profit` → laba bulan ini\n\n"
        "Versi super cepat juga masih bisa: `/k`, `/m`, `/h`, `/b`, `/r`, `/s`. "
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
        f"#{row['id']} {row['nama']}\n"
        f"   Modal: {rupiah(row['modal'])} • Jual: {rupiah(row['harga_jual'])} • Laba/pcs: {rupiah(laba_satuan)} • Stok: {row['stok']}"
    )


def format_sale(row) -> str:
    tanggal = row["created_at"][:16].replace("T", " ")
    note = f" — {row['catatan']}" if row["catatan"] else ""
    return f"🛒 #{row['id']} {tanggal} • {row['nama_barang']} x{row['qty']} • Omzet {rupiah(row['omzet'])} • Laba {rupiah(row['laba'])}{note}"


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
