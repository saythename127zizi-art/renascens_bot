"""Layer database SQLite untuk DuitKu Bot."""
from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

from models import EXPENSE_CATEGORIES, INCOME_CATEGORIES

DB_PATH = Path("finance.db")

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tipe TEXT NOT NULL CHECK(tipe IN ('masuk', 'keluar')),
                name TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, tipe, name)
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tipe TEXT NOT NULL CHECK(tipe IN ('masuk', 'keluar')),
                nominal INTEGER NOT NULL CHECK(nominal > 0),
                kategori TEXT NOT NULL,
                catatan TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kategori TEXT NOT NULL,
                nominal INTEGER NOT NULL CHECK(nominal > 0),
                month TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, kategori, month)
            );

            CREATE TABLE IF NOT EXISTS reminders (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                remind_time TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS debts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tipe TEXT NOT NULL CHECK(tipe IN ('utang', 'piutang')),
                nama TEXT NOT NULL,
                nominal INTEGER NOT NULL CHECK(nominal > 0),
                catatan TEXT,
                status TEXT NOT NULL DEFAULT 'belum_lunas',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS savings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                nama TEXT NOT NULL,
                target INTEGER NOT NULL CHECK(target > 0),
                terkumpul INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                nama TEXT NOT NULL,
                modal INTEGER NOT NULL CHECK(modal >= 0),
                harga_jual INTEGER NOT NULL CHECK(harga_jual > 0),
                stok INTEGER NOT NULL DEFAULT 0 CHECK(stok >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                nama_barang TEXT NOT NULL,
                qty INTEGER NOT NULL CHECK(qty > 0),
                modal_satuan INTEGER NOT NULL CHECK(modal_satuan >= 0),
                harga_satuan INTEGER NOT NULL CHECK(harga_satuan > 0),
                omzet INTEGER NOT NULL,
                modal_total INTEGER NOT NULL,
                laba INTEGER NOT NULL,
                catatan TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(product_id) REFERENCES products(id)
            );
            """
        )


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_user(user_id: int, first_name: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(user_id, first_name, created_at) VALUES (?, ?, ?)",
            (user_id, first_name or "", now_iso()),
        )
        ensure_default_categories(conn, user_id)


def ensure_default_categories(conn: sqlite3.Connection, user_id: int) -> None:
    created_at = now_iso()
    for name in EXPENSE_CATEGORIES:
        conn.execute(
            "INSERT OR IGNORE INTO categories(user_id, tipe, name, is_default, created_at) VALUES (?, 'keluar', ?, 1, ?)",
            (user_id, name, created_at),
        )
    for name in INCOME_CATEGORIES:
        conn.execute(
            "INSERT OR IGNORE INTO categories(user_id, tipe, name, is_default, created_at) VALUES (?, 'masuk', ?, 1, ?)",
            (user_id, name, created_at),
        )


def add_category(user_id: int, tipe: str, name: str) -> bool:
    name = normalize_category(name)
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO categories(user_id, tipe, name, is_default, created_at) VALUES (?, ?, ?, 0, ?)",
                (user_id, tipe, name, now_iso()),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def get_categories(user_id: int, tipe: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT tipe, name, is_default FROM categories WHERE user_id=?"
    params: list[Any] = [user_id]
    if tipe:
        sql += " AND tipe=?"
        params.append(tipe)
    sql += " ORDER BY tipe, is_default DESC, name"
    with get_conn() as conn:
        return list(conn.execute(sql, params).fetchall())


def category_exists(user_id: int, tipe: str, name: str) -> bool:
    name = normalize_category(name)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM categories WHERE user_id=? AND tipe=? AND name=?",
            (user_id, tipe, name),
        ).fetchone()
        return row is not None


def normalize_category(name: str) -> str:
    return " ".join(name.strip().lower().split())


def add_transaction(user_id: int, tipe: str, nominal: int, kategori: str, catatan: str = "") -> int:
    kategori = normalize_category(kategori)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO transactions(user_id, tipe, nominal, kategori, catatan, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, tipe, nominal, kategori, catatan.strip(), now_iso()),
        )
        return int(cur.lastrowid)


def get_last_transaction(user_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM transactions WHERE user_id=? ORDER BY datetime(created_at) DESC, id DESC LIMIT 1",
            (user_id,),
        ).fetchone()


def delete_transaction(user_id: int, transaction_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM transactions WHERE user_id=? AND id=?",
            (user_id, transaction_id),
        )
        return cur.rowcount > 0



def get_transaction(user_id: int, transaction_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM transactions WHERE user_id=? AND id=?",
            (user_id, transaction_id),
        ).fetchone()


def update_transaction(user_id: int, transaction_id: int, nominal: int, kategori: str, catatan: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE transactions SET nominal=?, kategori=?, catatan=? WHERE user_id=? AND id=?",
            (nominal, normalize_category(kategori), catatan.strip(), user_id, transaction_id),
        )
        if cur.rowcount == 0:
            return None
    return get_transaction(user_id, transaction_id)


def activity_streak(user_id: int) -> int:
    """Hitung streak hari berturut-turut yang punya transaksi, mundur dari hari ini."""
    today = date.today()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT substr(created_at, 1, 10) AS tanggal
            FROM transactions
            WHERE user_id=?
            ORDER BY tanggal DESC
            """,
            (user_id,),
        ).fetchall()
    dates = {date.fromisoformat(r["tanggal"]) for r in rows if r["tanggal"]}
    streak = 0
    cur = today
    while cur in dates:
        streak += 1
        cur = cur.replace() - timedelta(days=1)
    return streak

def update_last_transaction(user_id: int, nominal: int, kategori: str, catatan: str) -> sqlite3.Row | None:
    last = get_last_transaction(user_id)
    if not last:
        return None
    with get_conn() as conn:
        conn.execute(
            "UPDATE transactions SET nominal=?, kategori=?, catatan=? WHERE user_id=? AND id=?",
            (nominal, normalize_category(kategori), catatan.strip(), user_id, last["id"]),
        )
    return get_last_transaction(user_id)


def list_transactions(user_id: int, limit: int = 10) -> list[sqlite3.Row]:
    limit = max(1, min(limit, 50))
    with get_conn() as conn:
        return list(
            conn.execute(
                "SELECT * FROM transactions WHERE user_id=? ORDER BY datetime(created_at) DESC, id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        )


def summarize_range(user_id: int, start_date: date, end_date: date) -> dict[str, Any]:
    start = datetime.combine(start_date, time.min).isoformat()
    end = datetime.combine(end_date, time.max).isoformat()
    with get_conn() as conn:
        rows = list(
            conn.execute(
                "SELECT * FROM transactions WHERE user_id=? AND datetime(created_at) BETWEEN datetime(?) AND datetime(?) ORDER BY datetime(created_at) DESC, id DESC",
                (user_id, start, end),
            ).fetchall()
        )
        per_cat = list(
            conn.execute(
                """
                SELECT tipe, kategori, SUM(nominal) AS total, COUNT(*) AS jumlah
                FROM transactions
                WHERE user_id=? AND datetime(created_at) BETWEEN datetime(?) AND datetime(?)
                GROUP BY tipe, kategori
                ORDER BY tipe, total DESC
                """,
                (user_id, start, end),
            ).fetchall()
        )
    income = sum(int(r["nominal"]) for r in rows if r["tipe"] == "masuk")
    expense = sum(int(r["nominal"]) for r in rows if r["tipe"] == "keluar")
    biggest = None
    expense_cats = [r for r in per_cat if r["tipe"] == "keluar"]
    if expense_cats:
        biggest = expense_cats[0]
    return {
        "rows": rows,
        "income": income,
        "expense": expense,
        "balance": income - expense,
        "per_cat": per_cat,
        "biggest_expense": biggest,
    }


def set_budget(user_id: int, kategori: str, nominal: int, month: str) -> None:
    kategori = normalize_category(kategori)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO budgets(user_id, kategori, nominal, month, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, kategori, month)
            DO UPDATE SET nominal=excluded.nominal, created_at=excluded.created_at
            """,
            (user_id, kategori, nominal, month, now_iso()),
        )


def get_budget_status(user_id: int, kategori: str, month: str) -> dict[str, int] | None:
    kategori = normalize_category(kategori)
    start_date = date.fromisoformat(f"{month}-01")
    if start_date.month == 12:
        next_month = date(start_date.year + 1, 1, 1)
    else:
        next_month = date(start_date.year, start_date.month + 1, 1)
    start = datetime.combine(start_date, time.min).isoformat()
    end = datetime.combine(next_month, time.min).isoformat()
    with get_conn() as conn:
        budget = conn.execute(
            "SELECT nominal FROM budgets WHERE user_id=? AND kategori=? AND month=?",
            (user_id, kategori, month),
        ).fetchone()
        if not budget:
            return None
        spent = conn.execute(
            """
            SELECT COALESCE(SUM(nominal), 0) AS total FROM transactions
            WHERE user_id=? AND tipe='keluar' AND kategori=?
            AND datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)
            """,
            (user_id, kategori, start, end),
        ).fetchone()["total"]
    nominal = int(budget["nominal"])
    spent = int(spent or 0)
    return {"budget": nominal, "spent": spent, "left": nominal - spent}


def save_reminder(user_id: int, chat_id: int, remind_time: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO reminders(user_id, chat_id, remind_time, enabled, updated_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET chat_id=excluded.chat_id, remind_time=excluded.remind_time, enabled=1, updated_at=excluded.updated_at
            """,
            (user_id, chat_id, remind_time, now_iso()),
        )


def disable_reminder(user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE reminders SET enabled=0, updated_at=? WHERE user_id=?",
            (now_iso(), user_id),
        )
        return cur.rowcount > 0


def get_enabled_reminders() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM reminders WHERE enabled=1").fetchall())


def export_transactions_csv(user_id: int, path: Path) -> None:
    rows = list_transactions(user_id, 10_000)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "tanggal", "tipe", "nominal", "kategori", "catatan"])
        for r in reversed(rows):
            writer.writerow([r["id"], r["created_at"], r["tipe"], r["nominal"], r["kategori"], r["catatan"] or ""])


def stats_month(user_id: int, today: date) -> dict[str, Any]:
    start = date(today.year, today.month, 1)
    summary = summarize_range(user_id, start, today)
    rows = summary["rows"]
    expenses = [r for r in rows if r["tipe"] == "keluar"]
    days_passed = today.day
    avg_daily = round(summary["expense"] / days_passed) if days_passed else 0

    per_day: dict[str, int] = {}
    per_cat: dict[str, int] = {}
    for r in expenses:
        d = r["created_at"][:10]
        per_day[d] = per_day.get(d, 0) + int(r["nominal"])
        per_cat[r["kategori"]] = per_cat.get(r["kategori"], 0) + int(r["nominal"])

    most_expensive_day = max(per_day.items(), key=lambda x: x[1], default=("-", 0))
    most_expensive_cat = max(per_cat.items(), key=lambda x: x[1], default=("-", 0))

    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    days_in_month = (next_month - start).days
    projected = avg_daily * days_in_month
    return {
        "summary": summary,
        "avg_daily": avg_daily,
        "most_expensive_day": most_expensive_day,
        "most_expensive_cat": most_expensive_cat,
        "projected": projected,
    }


def add_debt(user_id: int, tipe: str, nama: str, nominal: int, catatan: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO debts(user_id, tipe, nama, nominal, catatan, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, tipe, nama.strip(), nominal, catatan.strip(), now_iso()),
        )
        return int(cur.lastrowid)


def list_debts(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM debts WHERE user_id=? ORDER BY status, datetime(created_at) DESC", (user_id,)).fetchall())


def mark_debt_paid(user_id: int, debt_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("UPDATE debts SET status='lunas' WHERE user_id=? AND id=?", (user_id, debt_id))
        return cur.rowcount > 0


def add_saving_goal(user_id: int, nama: str, target: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO savings(user_id, nama, target, created_at) VALUES (?, ?, ?, ?)",
            (user_id, nama.strip(), target, now_iso()),
        )
        return int(cur.lastrowid)


def topup_saving(user_id: int, goal_id: int, amount: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("UPDATE savings SET terkumpul=terkumpul+? WHERE user_id=? AND id=?", (amount, user_id, goal_id))
        return cur.rowcount > 0


def list_savings(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM savings WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall())


def add_product(user_id: int, nama: str, modal: int, harga_jual: int, stok: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO products(user_id, nama, modal, harga_jual, stok, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, nama.strip(), modal, harga_jual, stok, now_iso(), now_iso()),
        )
        return int(cur.lastrowid)


def list_products(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT * FROM products WHERE user_id=? ORDER BY id DESC",
            (user_id,),
        ).fetchall())


def get_product(user_id: int, product_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM products WHERE user_id=? AND id=?",
            (user_id, product_id),
        ).fetchone()


def add_stock(user_id: int, product_id: int, qty: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE products SET stok=stok+?, updated_at=? WHERE user_id=? AND id=?",
            (qty, now_iso(), user_id, product_id),
        )
        return cur.rowcount > 0


def add_sale(user_id: int, product_id: int, qty: int, catatan: str = "") -> int:
    with get_conn() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE user_id=? AND id=?",
            (user_id, product_id),
        ).fetchone()
        if not product:
            raise ValueError("Produk tidak ditemukan.")
        if int(product["stok"]) < qty:
            raise ValueError(f"Stok {product['nama']} cuma {product['stok']}, belum cukup buat jual {qty}.")
        modal_satuan = int(product["modal"])
        harga_satuan = int(product["harga_jual"])
        omzet = harga_satuan * qty
        modal_total = modal_satuan * qty
        laba = omzet - modal_total
        cur = conn.execute(
            """
            INSERT INTO sales(user_id, product_id, nama_barang, qty, modal_satuan, harga_satuan,
                              omzet, modal_total, laba, catatan, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, product_id, product["nama"], qty, modal_satuan, harga_satuan, omzet, modal_total, laba, catatan.strip(), now_iso()),
        )
        conn.execute(
            "UPDATE products SET stok=stok-?, updated_at=? WHERE user_id=? AND id=?",
            (qty, now_iso(), user_id, product_id),
        )
        # Otomatis catat sebagai pemasukan kategori jualan agar laporan finansial tetap nyambung.
        conn.execute(
            "INSERT INTO transactions(user_id, tipe, nominal, kategori, catatan, created_at) VALUES (?, 'masuk', ?, 'jualan', ?, ?)",
            (user_id, omzet, f"Penjualan {product['nama']} x{qty}. Laba {laba}", now_iso()),
        )
        return int(cur.lastrowid)


def list_sales(user_id: int, limit: int = 10) -> list[sqlite3.Row]:
    limit = max(1, min(limit, 50))
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT * FROM sales WHERE user_id=? ORDER BY datetime(created_at) DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall())


def sales_summary_range(user_id: int, start_date: date, end_date: date) -> dict[str, Any]:
    start = datetime.combine(start_date, time.min).isoformat()
    end = datetime.combine(end_date, time.max).isoformat()
    with get_conn() as conn:
        rows = list(conn.execute(
            """
            SELECT * FROM sales
            WHERE user_id=? AND datetime(created_at) BETWEEN datetime(?) AND datetime(?)
            ORDER BY datetime(created_at) DESC, id DESC
            """,
            (user_id, start, end),
        ).fetchall())
        per_product = list(conn.execute(
            """
            SELECT nama_barang, SUM(qty) AS qty, SUM(omzet) AS omzet, SUM(modal_total) AS modal, SUM(laba) AS laba
            FROM sales
            WHERE user_id=? AND datetime(created_at) BETWEEN datetime(?) AND datetime(?)
            GROUP BY nama_barang
            ORDER BY laba DESC
            """,
            (user_id, start, end),
        ).fetchall())
    return {
        "rows": rows,
        "per_product": per_product,
        "qty": sum(int(r["qty"]) for r in rows),
        "omzet": sum(int(r["omzet"]) for r in rows),
        "modal": sum(int(r["modal_total"]) for r in rows),
        "laba": sum(int(r["laba"]) for r in rows),
    }
