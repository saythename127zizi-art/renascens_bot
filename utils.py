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


def format_transaction(row) -> str:
    sign = "➕" if row["tipe"] == "masuk" else "➖"
    tanggal = row["created_at"][:16].replace("T", " ")
    note = f" — {row['catatan']}" if row["catatan"] else ""
    return f"{sign} #{row['id']} {tanggal} • {row['kategori']} • {rupiah(row['nominal'])}{note}"


def format_summary(title: str, summary: dict) -> str:
    lines = [f"📒 *{title}*", ""]
    lines.append(f"➕ Pemasukan: *{rupiah(summary['income'])}*")
    lines.append(f"➖ Pengeluaran: *{rupiah(summary['expense'])}*")
    lines.append(f"💰 Saldo: *{rupiah(summary['balance'])}*")
    lines.append("")

    if summary["per_cat"]:
        lines.append("🏷️ *Breakdown kategori:*")
        for r in summary["per_cat"]:
            icon = "➕" if r["tipe"] == "masuk" else "➖"
            lines.append(f"{icon} {r['kategori']}: {rupiah(r['total'])} ({r['jumlah']}x)")
        lines.append("")
    else:
        lines.append("Belum ada transaksi di periode ini.")
        lines.append("")

    biggest = summary.get("biggest_expense")
    if biggest:
        lines.append(f"🔥 Pengeluaran terbesar: *{biggest['kategori']}* — {rupiah(biggest['total'])}")

    if summary["rows"]:
        lines.append("")
        lines.append("🧾 *Transaksi terakhir:*")
        for r in summary["rows"][:5]:
            lines.append(format_transaction(r))
    return "\n".join(lines)


def help_text() -> str:
    return (
        "Hai! Aku *DuitKu Bot* 💸\n\n"
        "Aku bisa bantu catat uang masuk/keluar, budget, utang-piutang, tabungan, laporan, dan jualan.\n\n"
        "Contoh cepat:\n"
        "`/keluar 12000 makan seblak`\n"
        "`/masuk 45000 jualan mie`\n"
        "`/budget makan 500000`\n"
        "`/hariini` / `/bulanini` / `/stat`\n\n"
        "Mode jualan:\n"
        "`/produk indomie soto | 2200 | 4000 | 10`\n"
        "`/jual 1 2 pembeli tetangga`\n"
        "`/stok` / `/laba_hariini` / `/laba_bulanini`\n\n"
        "Pakai tombol menu di bawah biar nggak perlu hafal command."
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
