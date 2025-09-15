import os, hashlib, secrets
from datetime import datetime
from . import db

ROLE_LEVEL = {"guest": 0, "viewer": 1, "user": 2, "admin": 3}

def hash_password(password: str, salt: str | None = None):
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return h, salt

def verify_password(password: str, pw_hash: str, pw_salt: str) -> bool:
    calc, _ = hash_password(password, pw_salt)
    return secrets.compare_digest(calc, pw_hash)

# --- User CRUD helpers ---
def get_user(username: str):
    with db.get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

def register_request(username: str, password: str, requested_role: str = "viewer"):
    pw_hash, pw_salt = hash_password(password)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO pending_users (username, pw_hash, pw_salt, requested_role, created_at) VALUES (?,?,?,?,?)",
            (username, pw_hash, pw_salt, requested_role, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )

def list_pending_users():
    with db.get_conn() as conn:
        return conn.execute("SELECT * FROM pending_users ORDER BY created_at ASC").fetchall()

def approve_user(pending_id: int, role: str = "viewer"):
    with db.get_conn() as conn:
        p = conn.execute("SELECT * FROM pending_users WHERE id=?", (pending_id,)).fetchone()
        if not p:
            return False
        # create user
        conn.execute(
            "INSERT INTO users (username, pw_hash, pw_salt, role, is_active, created_at) VALUES (?,?,?,?,?,?)",
            (p["username"], p["pw_hash"], p["pw_salt"], role, 1, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.execute("DELETE FROM pending_users WHERE id=?", (pending_id,))
        return True

def deny_user(pending_id: int):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM pending_users WHERE id=?", (pending_id,))

def list_users():
    with db.get_conn() as conn:
        return conn.execute("SELECT id, username, role, is_active, created_at FROM users ORDER BY role DESC, username").fetchall()

def set_user_role(user_id: int, role: str):
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))

def set_user_active(user_id: int, active: bool):
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET is_active=? WHERE id=?", (1 if active else 0, user_id))

# --- Password change (requires admin approval) ---
def request_password_change(username: str, new_password: str):
    new_hash, new_salt = hash_password(new_password)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO password_change_requests (username, new_pw_hash, new_pw_salt, status, created_at) VALUES (?,?,?,?,?)",
            (username, new_hash, new_salt, "pending", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )

def list_password_requests():
    with db.get_conn() as conn:
        return conn.execute("SELECT * FROM password_change_requests WHERE status='pending' ORDER BY created_at").fetchall()

def approve_password_change(req_id: int):
    with db.get_conn() as conn:
        r = conn.execute("SELECT * FROM password_change_requests WHERE id=? AND status='pending'", (req_id,)).fetchone()
        if not r:
            return False
        # apply
        conn.execute("UPDATE users SET pw_hash=?, pw_salt=? WHERE username=?", (r["new_pw_hash"], r["new_pw_salt"], r["username"]))
        conn.execute("UPDATE password_change_requests SET status='approved', decided_at=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), req_id))
        return True

def deny_password_change(req_id: int):
    with db.get_conn() as conn:
        conn.execute("UPDATE password_change_requests SET status='denied', decided_at=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), req_id))
