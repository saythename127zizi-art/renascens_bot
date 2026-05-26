"""Konstanta dan tipe data untuk DuitKu Bot."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TransactionType = Literal["masuk", "keluar"]
CategoryType = Literal["masuk", "keluar"]

EXPENSE_CATEGORIES = [
    "makan",
    "transport",
    "belanja",
    "pulsa/data",
    "jajan",
    "kesehatan",
    "rumah",
    "lainnya",
]

INCOME_CATEGORIES = [
    "gaji",
    "jualan",
    "bonus",
    "cashback",
    "hadiah",
    "lainnya",
]

MAIN_MENU = [
    ["➖ Catat Pengeluaran", "➕ Catat Pemasukan"],
    ["📅 Hari Ini", "📆 Bulan Ini"],
    ["📊 Statistik", "🧾 Riwayat"],
    ["🛒 Mode Jualan", "💰 Laba Bulan Ini"],
    ["🏷️ Kategori", "💾 Export CSV"],
]

@dataclass(frozen=True)
class TransactionInput:
    user_id: int
    tipe: TransactionType
    nominal: int
    kategori: str
    catatan: str = ""
