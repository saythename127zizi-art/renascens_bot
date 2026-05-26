"""Layer database SQLite untuk DuitKu Bot."""
from __future__ import annotations

import csv
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Iterable

from models import EXPENSE_CATEGORIES, INCOME_CATEGORIES


def _resolve_db_path() -> Path:
    """Pilih lokasi database.

    - Di Railway + Volume yang di-mount ke /data, pakai /data/finance.db supaya data tidak hilang saat redeploy.
    - Bisa dioverride dengan environment variable DB_PATH.
    - Kalau jalan lokal biasa, fallback ke finance.db di folder project.
    """
    custom_path = os.getenv("DB_PATH")
    if custom_path:
        path = Path(custom_path)
    else:
        data_dir = Path("/data")
        if data_dir.exists() and os.access(data_dir, os.W_OK):
            path = data_dir / "finance.db"
        else:
            path = Path("finance.db")

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


DB_PATH = _resolve_db_path()

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
                display_id INTEGER,
                user_id INTEGER NOT NULL,
                tipe TEXT NOT NULL CHECK(tipe IN ('masuk', 'keluar')),
                nominal INTEGER NOT NULL CHECK(nominal > 0),
                kategori TEXT NOT NULL,
                catatan TEXT,
                payment_method TEXT NOT NULL DEFAULT 'cash',
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
        _ensure_transaction_payment_method(conn)
        _ensure_transaction_display_ids(conn)



def _ensure_transaction_payment_method(conn: sqlite3.Connection) -> None:
    """Migrasi kolom metode pembayaran untuk database lama."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
    if "payment_method" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'cash'")

def normalize_payment_method(name: str | None) -> str:
    raw = (name or "cash").strip().lower()
    raw = raw.replace("_", " ").replace("-", " ")
    raw = " ".join(raw.split())
    aliases = {
        "tunai": "cash",
        "cash": "cash",
        "qris": "qris",
        "qr": "qris",
        "shopeepay": "shopeepay",
        "shopee pay": "shopeepay",
        "spay": "shopeepay",
        "dana": "dana",
        "gopay": "gopay",
        "go pay": "gopay",
        "ovo": "ovo",
        "bank": "bank",
        "transfer": "bank",
        "tf": "bank",
        "bca": "bca",
        "bri": "bri",
        "bni": "bni",
        "mandiri": "mandiri",
        "blu": "blu",
        "seabank": "seabank",
        "spaylater": "spaylater",
        "paylater": "paylater",
        "kartu": "kartu",
        "card": "kartu",
        "lainnya": "lainnya",
    }
    return aliases.get(raw, raw or "cash")

def _ensure_transaction_display_ids(conn: sqlite3.Connection) -> None:
    """Migrasi ID tampilan transaksi agar ID user rapi 1..N per user.

    Primary key internal tetap `id`, tapi user melihat `display_id`.
    Setelah transaksi dihapus, display_id dirapikan lagi supaya tidak lompat.
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
    if "display_id" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN display_id INTEGER")
    user_ids = [r[0] for r in conn.execute("SELECT DISTINCT user_id FROM transactions ORDER BY user_id").fetchall()]
    for uid in user_ids:
        _renumber_user_transactions(conn, int(uid))


def _renumber_user_transactions(conn: sqlite3.Connection, user_id: int) -> None:
    rows = conn.execute(
        "SELECT id FROM transactions WHERE user_id=? ORDER BY datetime(created_at), id",
        (user_id,),
    ).fetchall()
    for idx, row in enumerate(rows, 1):
        conn.execute("UPDATE transactions SET display_id=? WHERE id=?", (idx, row[0]))


def _next_display_id(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(display_id), 0) + 1 AS next_id FROM transactions WHERE user_id=?",
        (user_id,),
    ).fetchone()
    return int(row["next_id"] or 1)


JAKARTA_TZ = ZoneInfo("Asia/Jakarta")


def now_iso() -> str:
    """Waktu lokal Indonesia (WIB) supaya laporan /today cocok dengan tanggal Telegram user."""
    return datetime.now(JAKARTA_TZ).replace(tzinfo=None).isoformat(timespec="seconds")


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


def add_transaction(user_id: int, tipe: str, nominal: int, kategori: str, catatan: str = "", created_at: str | None = None, payment_method: str = "cash") -> int:
    kategori = normalize_category(kategori)
    with get_conn() as conn:
        display_id = _next_display_id(conn, user_id)
        cur = conn.execute(
            "INSERT INTO transactions(display_id, user_id, tipe, nominal, kategori, catatan, payment_method, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (display_id, user_id, tipe, nominal, kategori, catatan.strip(), normalize_payment_method(payment_method), created_at or now_iso()),
        )
        return display_id


def get_last_transaction(user_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM transactions WHERE user_id=? ORDER BY datetime(created_at) DESC, id DESC LIMIT 1",
            (user_id,),
        ).fetchone()


def delete_transaction(user_id: int, transaction_id: int) -> bool:
    """Hapus berdasarkan ID tampilan user, lalu rapikan lagi ID tampilannya."""
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM transactions WHERE user_id=? AND display_id=?",
            (user_id, transaction_id),
        )
        if cur.rowcount:
            _renumber_user_transactions(conn, user_id)
        return cur.rowcount > 0


def get_transaction(user_id: int, transaction_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM transactions WHERE user_id=? AND display_id=?",
            (user_id, transaction_id),
        ).fetchone()


def update_transaction(user_id: int, transaction_id: int, nominal: int, kategori: str, catatan: str, created_at: str | None = None, payment_method: str | None = None) -> sqlite3.Row | None:
    with get_conn() as conn:
        old = conn.execute(
            "SELECT id FROM transactions WHERE user_id=? AND display_id=?",
            (user_id, transaction_id),
        ).fetchone()
        if not old:
            return None
        internal_id = int(old["id"])
        if created_at:
            conn.execute(
                "UPDATE transactions SET nominal=?, kategori=?, catatan=?, payment_method=?, created_at=? WHERE user_id=? AND id=?",
                (nominal, normalize_category(kategori), catatan.strip(), normalize_payment_method(payment_method), created_at, user_id, internal_id),
            )
        else:
            conn.execute(
                "UPDATE transactions SET nominal=?, kategori=?, catatan=?, payment_method=? WHERE user_id=? AND id=?",
                (nominal, normalize_category(kategori), catatan.strip(), normalize_payment_method(payment_method), user_id, internal_id),
            )
        _renumber_user_transactions(conn, user_id)
        return conn.execute("SELECT * FROM transactions WHERE user_id=? AND id=?", (user_id, internal_id)).fetchone()

def activity_streak(user_id: int) -> int:
    """Hitung streak hari berturut-turut yang punya transaksi, mundur dari hari ini."""
    today = datetime.now(JAKARTA_TZ).date()
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

def update_last_transaction(user_id: int, nominal: int, kategori: str, catatan: str, created_at: str | None = None, payment_method: str | None = None) -> sqlite3.Row | None:
    last = get_last_transaction(user_id)
    if not last:
        return None
    with get_conn() as conn:
        if created_at:
            conn.execute(
                "UPDATE transactions SET nominal=?, kategori=?, catatan=?, payment_method=?, created_at=? WHERE user_id=? AND id=?",
                (nominal, normalize_category(kategori), catatan.strip(), normalize_payment_method(payment_method), created_at, user_id, last["id"]),
            )
            _renumber_user_transactions(conn, user_id)
        else:
            conn.execute(
                "UPDATE transactions SET nominal=?, kategori=?, catatan=?, payment_method=? WHERE user_id=? AND id=?",
                (nominal, normalize_category(kategori), catatan.strip(), normalize_payment_method(payment_method), user_id, last["id"]),
            )
    return get_last_transaction(user_id)


def rename_category(user_id: int, old_name: str, new_name: str) -> int:
    old = normalize_category(old_name)
    new = normalize_category(new_name)
    if not old or not new:
        raise ValueError("Nama kategori tidak boleh kosong.")
    with get_conn() as conn:
        conn.execute("UPDATE categories SET name=? WHERE user_id=? AND name=?", (new, user_id, old))
        cur = conn.execute("UPDATE transactions SET kategori=? WHERE user_id=? AND kategori=?", (new, user_id, old))
        return int(cur.rowcount or 0)


def search_transactions(user_id: int, keyword: str, limit: int = 20) -> list[sqlite3.Row]:
    kw = f"%{keyword.strip().lower()}%"
    limit = max(1, min(limit, 50))
    with get_conn() as conn:
        return list(conn.execute(
            """
            SELECT * FROM transactions
            WHERE user_id=? AND (lower(kategori) LIKE ? OR lower(COALESCE(catatan, '')) LIKE ?)
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (user_id, kw, kw, limit),
        ).fetchall())


def filter_transactions_by_category(user_id: int, kategori: str, limit: int = 20) -> list[sqlite3.Row]:
    kategori = normalize_category(kategori)
    limit = max(1, min(limit, 50))
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT * FROM transactions WHERE user_id=? AND kategori=? ORDER BY datetime(created_at) DESC, id DESC LIMIT ?",
            (user_id, kategori, limit),
        ).fetchall())


def filter_transactions_by_payment_method(user_id: int, payment_method: str, limit: int = 20) -> list[sqlite3.Row]:
    method = normalize_payment_method(payment_method)
    limit = max(1, min(limit, 50))
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT * FROM transactions WHERE user_id=? AND payment_method=? ORDER BY datetime(created_at) DESC, id DESC LIMIT ?",
            (user_id, method, limit),
        ).fetchall())

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
        per_payment = list(
            conn.execute(
                """
                SELECT tipe, payment_method, SUM(nominal) AS total, COUNT(*) AS jumlah
                FROM transactions
                WHERE user_id=? AND datetime(created_at) BETWEEN datetime(?) AND datetime(?)
                GROUP BY tipe, payment_method
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
        "per_payment": per_payment,
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
        writer.writerow(["id", "tanggal", "tipe", "nominal", "kategori", "payment_method", "catatan"])
        for r in reversed(rows):
            writer.writerow([r["display_id"] or r["id"], r["created_at"], r["tipe"], r["nominal"], r["kategori"], r["payment_method"], r["catatan"] or ""])


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
        display_id = _next_display_id(conn, user_id)
        conn.execute(
            "INSERT INTO transactions(display_id, user_id, tipe, nominal, kategori, catatan, payment_method, created_at) VALUES (?, ?, 'masuk', ?, 'jualan', ?, 'cash', ?)",
            (display_id, user_id, omzet, f"Penjualan {product['nama']} x{qty}. Laba {laba}", now_iso()),
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

# =========================
# v11 aesthetic extensions
# =========================

def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _init_v11_extras() -> None:
    with get_conn() as conn:
        _ensure_column(conn, "transactions", "item_name", "item_name TEXT")
        _ensure_column(conn, "transactions", "tag", "tag TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                theme TEXT NOT NULL DEFAULT 'soft',
                default_payment TEXT DEFAULT 'cash',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wishlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                kategori TEXT NOT NULL,
                nominal INTEGER NOT NULL CHECK(nominal > 0),
                status TEXT NOT NULL DEFAULT 'planned',
                created_at TEXT NOT NULL,
                bought_at TEXT
            )
            """
        )

_old_init_db_v11 = init_db

def init_db() -> None:  # type: ignore[override]
    _old_init_db_v11()
    _init_v11_extras()


def get_user_theme(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT theme FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
        return (row["theme"] if row else "soft") or "soft"


def set_user_theme(user_id: int, theme: str) -> str:
    theme = (theme or "soft").strip().lower()
    if theme not in {"soft", "clean", "cute"}:
        raise ValueError("Theme cuma bisa: soft, clean, cute")
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_settings(user_id, theme, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET theme=excluded.theme, updated_at=excluded.updated_at
            """,
            (user_id, theme, ts, ts),
        )
    return theme


def _smart_category(name: str, tipe: str = "keluar") -> str:
    raw = normalize_category(name)
    aliases = {
        "spay": "marketplace", "shopee": "marketplace", "lzd": "marketplace", "lazada": "marketplace", "tokopedia": "marketplace",
        "skincare": "beauty", "makeup": "beauty", "sheetmask": "beauty", "sunscreen": "beauty", "contour": "beauty",
        "makan": "food", "jajan": "food", "snack": "food", "ramen": "food", "mie": "food", "kopi": "food",
        "dapur": "grocery", "sembako": "grocery", "terigu": "grocery", "belanja": "shopping",
        "cashback": "cashback", "jualan": "jualan", "gaji": "gaji",
    }
    return aliases.get(raw, raw or ("income" if tipe == "masuk" else "other"))


_old_add_transaction_v11 = add_transaction

def add_transaction(user_id: int, tipe: str, nominal: int, kategori: str, catatan: str = "", created_at: str | None = None, payment_method: str = "cash", tag: str = "") -> int:  # type: ignore[override]
    kategori = _smart_category(kategori, tipe)
    item_name = (catatan or kategori).strip()
    with get_conn() as conn:
        _ensure_column(conn, "transactions", "item_name", "item_name TEXT")
        _ensure_column(conn, "transactions", "tag", "tag TEXT")
        display_id = _next_display_id(conn, user_id)
        conn.execute(
            """
            INSERT INTO transactions(display_id, user_id, tipe, nominal, kategori, catatan, item_name, payment_method, tag, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (display_id, user_id, tipe, nominal, kategori, item_name, item_name, normalize_payment_method(payment_method), (tag or "").strip().lower(), created_at or now_iso()),
        )
        return display_id


def _row_item(row: sqlite3.Row) -> str:
    try:
        return (row["item_name"] or row["catatan"] or row["kategori"] or "-").strip()
    except Exception:
        return (row["catatan"] or row["kategori"] or "-").strip()


_old_update_transaction_v11 = update_transaction

def update_transaction(user_id: int, transaction_id: int, nominal: int, kategori: str, catatan: str, created_at: str | None = None, payment_method: str | None = None) -> sqlite3.Row | None:  # type: ignore[override]
    kategori = _smart_category(kategori)
    item_name = (catatan or kategori).strip()
    with get_conn() as conn:
        _ensure_column(conn, "transactions", "item_name", "item_name TEXT")
        _ensure_column(conn, "transactions", "tag", "tag TEXT")
        old = conn.execute("SELECT id FROM transactions WHERE user_id=? AND display_id=?", (user_id, transaction_id)).fetchone()
        if not old:
            return None
        internal_id = int(old["id"])
        method = normalize_payment_method(payment_method)
        if created_at:
            conn.execute(
                "UPDATE transactions SET nominal=?, kategori=?, catatan=?, item_name=?, payment_method=?, created_at=? WHERE user_id=? AND id=?",
                (nominal, kategori, item_name, item_name, method, created_at, user_id, internal_id),
            )
        else:
            conn.execute(
                "UPDATE transactions SET nominal=?, kategori=?, catatan=?, item_name=?, payment_method=? WHERE user_id=? AND id=?",
                (nominal, kategori, item_name, item_name, method, user_id, internal_id),
            )
        _renumber_user_transactions(conn, user_id)
        return conn.execute("SELECT * FROM transactions WHERE user_id=? AND id=?", (user_id, internal_id)).fetchone()


_old_update_last_transaction_v11 = update_last_transaction

def update_last_transaction(user_id: int, nominal: int, kategori: str, catatan: str, created_at: str | None = None, payment_method: str | None = None) -> sqlite3.Row | None:  # type: ignore[override]
    last = get_last_transaction(user_id)
    if not last:
        return None
    return update_transaction(user_id, int(last["display_id"] or last["id"]), nominal, kategori, catatan, created_at, payment_method)


def find_recent_duplicate(user_id: int, tipe: str, item_name: str, nominal: int, minutes: int = 10) -> sqlite3.Row | None:
    cutoff = (datetime.now(JAKARTA_TZ).replace(tzinfo=None) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    kw = (item_name or "").strip().lower()
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT * FROM transactions
            WHERE user_id=? AND tipe=? AND nominal=? AND lower(COALESCE(item_name, catatan, ''))=? AND datetime(created_at) >= datetime(?)
            ORDER BY datetime(created_at) DESC, id DESC LIMIT 1
            """,
            (user_id, tipe, nominal, kw, cutoff),
        ).fetchone()


def add_wishlist(user_id: int, item_name: str, kategori: str, nominal: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO wishlist(user_id, item_name, kategori, nominal, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, item_name.strip(), _smart_category(kategori), nominal, now_iso()),
        )
        return int(cur.lastrowid)


def list_wishlist(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute("SELECT * FROM wishlist WHERE user_id=? AND status='planned' ORDER BY id DESC", (user_id,)).fetchall())


def mark_wishlist_bought(user_id: int, wish_id: int, payment_method: str = "cash") -> int | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM wishlist WHERE user_id=? AND id=? AND status='planned'", (user_id, wish_id)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE wishlist SET status='bought', bought_at=? WHERE user_id=? AND id=?", (now_iso(), user_id, wish_id))
    return add_transaction(user_id, "keluar", int(row["nominal"]), row["kategori"], row["item_name"], None, payment_method)


def export_transactions_csv(user_id: int, path: Path) -> None:  # type: ignore[override]
    rows = list_transactions(user_id, 10_000)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "tanggal_wib", "jenis", "nama_barang", "kategori", "harga", "metode_bayar", "tag"])
        for r in reversed(rows):
            try:
                item = r["item_name"] or r["catatan"] or ""
                tag = r["tag"] or ""
            except Exception:
                item = r["catatan"] or ""
                tag = ""
            writer.writerow([r["display_id"] or r["id"], r["created_at"], r["tipe"], item, r["kategori"], r["nominal"], r["payment_method"], tag])

def search_transactions(user_id: int, keyword: str, limit: int = 20) -> list[sqlite3.Row]:  # type: ignore[override]
    kw = f"%{keyword.strip().lower()}%"
    limit = max(1, min(limit, 50))
    with get_conn() as conn:
        return list(conn.execute(
            """
            SELECT * FROM transactions
            WHERE user_id=? AND (
                lower(kategori) LIKE ? OR lower(COALESCE(catatan, '')) LIKE ? OR lower(COALESCE(item_name, '')) LIKE ? OR lower(COALESCE(payment_method, '')) LIKE ?
            )
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (user_id, kw, kw, kw, kw, limit),
        ).fetchall())
