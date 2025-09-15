import os
import sqlite3
from contextlib import closing
from datetime import datetime
from .auth import hash_password  # NEW

DB_PATH = os.environ.get("TAKEOUT_DB_PATH", "takeout.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with closing(get_conn()) as conn, conn:
        cur = conn.cursor()

        # --- Core tables (existing) ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_code TEXT UNIQUE,
                name TEXT NOT NULL,
                discount REAL DEFAULT 0.0,
                item_cost REAL DEFAULT 0.0,
                tax_amount REAL DEFAULT 0.0,
                other_costs REAL DEFAULT 0.0,
                total_cost REAL DEFAULT 0.0,
                selling_price REAL DEFAULT 0.0,
                est_profit REAL DEFAULT 0.0,
                profit_margin REAL DEFAULT 0.0,
                all_time_sold INTEGER DEFAULT 0,
                all_time_sales REAL DEFAULT 0.0,
                status TEXT DEFAULT 'Active',
                notes TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                available_stock INTEGER DEFAULT 0,
                low_stock_alert INTEGER DEFAULT 0,
                status TEXT DEFAULT 'In Stock',
                current_inventory_value REAL DEFAULT 0.0,
                all_time_stock_in INTEGER DEFAULT 0,
                all_time_stock_out INTEGER DEFAULT 0,
                all_time_sales REAL DEFAULT 0.0,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock_in_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_in_ts TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                stocks_added INTEGER NOT NULL,
                status TEXT DEFAULT 'Stock In',
                notes TEXT DEFAULT '',
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                billing_date TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                item_price REAL NOT NULL,
                discount REAL DEFAULT 0.0,
                total_amount REAL NOT NULL,
                payment_status TEXT DEFAULT 'Unpaid',
                sales_channel TEXT DEFAULT 'Walk-in',
                customer_name TEXT DEFAULT '',
                customer_tin TEXT DEFAULT '',
                business_address TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                vat_inclusive INTEGER DEFAULT 1,
                vat_amount REAL DEFAULT 0.0,
                net_of_vat REAL DEFAULT 0.0,
                invoice_no TEXT DEFAULT NULL,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_date TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                total_cost REAL NOT NULL,
                status TEXT DEFAULT 'Posted',
                receipt_no TEXT DEFAULT '',
                vendor_name TEXT DEFAULT '',
                vendor_tin TEXT DEFAULT '',
                business_address TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS supplies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_description TEXT NOT NULL,
                supplier TEXT DEFAULT '',
                units_per_piece REAL DEFAULT 1.0,
                unit_symbol TEXT DEFAULT '',
                item_cost REAL DEFAULT 0.0,
                last_updated TEXT DEFAULT '',
                available_stocks REAL DEFAULT 0.0,
                low_stock_alert REAL DEFAULT 0.0,
                status TEXT DEFAULT 'In Stock',
                inventory_value REAL DEFAULT 0.0,
                notes TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                sales_target REAL DEFAULT 0.0,
                expense_target REAL DEFAULT 0.0,
                profit_target REAL DEFAULT 0.0,
                notes TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS shareholders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ownership_pct REAL NOT NULL CHECK(ownership_pct >= 0 AND ownership_pct <= 100),
                notes TEXT DEFAULT ''
            )
        """)

        # --- NEW: Authentication tables ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                pw_hash TEXT NOT NULL,
                pw_salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer', -- guest | viewer | user | admin
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pending_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                pw_hash TEXT NOT NULL,
                pw_salt TEXT NOT NULL,
                requested_role TEXT NOT NULL DEFAULT 'viewer',
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS password_change_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                new_pw_hash TEXT NOT NULL,
                new_pw_salt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', -- pending | approved | denied
                created_at TEXT NOT NULL,
                decided_at TEXT
            )
        """)

    ensure_admin_user()

def ensure_admin_user():
    """Create/repair built-in admin (admin / 08201977)."""
    with closing(get_conn()) as conn, conn:
        cur = conn.cursor()
        row = cur.execute("SELECT id, pw_hash, pw_salt, is_active FROM users WHERE username='admin'").fetchone()
        if row is None:
            pw_hash, pw_salt = hash_password("08201977")
            cur.execute(
                "INSERT INTO users (username, pw_hash, pw_salt, role, is_active, created_at) VALUES (?,?,?,?,?,?)",
                ("admin", pw_hash, pw_salt, "admin", 1, now_str()),
            )
        else:
            # ensure active & role
            cur.execute("UPDATE users SET role='admin', is_active=1 WHERE username='admin'")

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
