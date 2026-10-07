"""
SQLite storage: users & permissions, budget lines per (year, site), site submission status
"""
import os
import json
import sqlite3
import datetime
from contextlib import contextmanager
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ICOST_DB_PATH", os.path.join(BASE_DIR, "data", "icost.db"))

# Roles
ROLE_ADMIN = "admin"        # Toàn quyền: phân quyền, duyệt, danh mục, mọi site
ROLE_VIEWER = "viewer"      # Xem & xuất báo cáo tất cả site, không sửa
ROLE_SITE_IT = "site_it"    # Lập ngân sách cho các site được phân
ROLE_PENDING = "pending"    # Đã đăng nhập, chờ admin phân quyền
ROLE_DISABLED = "disabled"  # Bị khóa

ROLE_LABELS = {
    ROLE_ADMIN: "Quản trị (Admin)",
    ROLE_VIEWER: "Xem tổng hợp",
    ROLE_SITE_IT: "IT Site - Lập ngân sách",
    ROLE_PENDING: "Chờ phân quyền",
    ROLE_DISABLED: "Khóa",
}

# Site budget status
STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_APPROVED = "approved"
STATUS_RETURNED = "returned"

STATUS_LABELS = {
    STATUS_DRAFT: "📝 Đang lập",
    STATUS_SUBMITTED: "📨 Đã nộp - chờ duyệt",
    STATUS_APPROVED: "✅ Đã duyệt",
    STATUS_RETURNED: "↩️ Trả lại - cần chỉnh sửa",
}
EDITABLE_STATUSES = (STATUS_DRAFT, STATUS_RETURNED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    email       TEXT PRIMARY KEY,
    name        TEXT,
    role        TEXT NOT NULL DEFAULT 'pending',
    provider    TEXT,
    created_at  TEXT,
    last_login  TEXT
);
CREATE TABLE IF NOT EXISTS user_sites (
    email      TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    site_code  TEXT NOT NULL,
    PRIMARY KEY (email, site_code)
);
CREATE TABLE IF NOT EXISTS budget_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    year        TEXT NOT NULL,
    site_code   TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    data        TEXT NOT NULL,
    updated_by  TEXT,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_budget_lines_year_site ON budget_lines(year, site_code);
CREATE TABLE IF NOT EXISTS site_status (
    year        TEXT NOT NULL,
    site_code   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft',
    note        TEXT,
    updated_by  TEXT,
    updated_at  TEXT,
    PRIMARY KEY (year, site_code)
);
CREATE TABLE IF NOT EXISTS dept_headcount (
    year        TEXT NOT NULL,
    site_code   TEXT NOT NULL,
    dept        TEXT NOT NULL,
    kit_code    TEXT NOT NULL,
    hc_current  REAL NOT NULL DEFAULT 0,
    hc_plan     REAL NOT NULL DEFAULT 0,
    hc_months   TEXT,
    updated_by  TEXT,
    updated_at  TEXT,
    PRIMARY KEY (year, site_code, dept, kit_code)
);
CREATE TABLE IF NOT EXISTS dept_inventory (
    year            TEXT NOT NULL,
    site_code       TEXT NOT NULL,
    dept            TEXT NOT NULL,
    catalog_code    TEXT NOT NULL,
    current_qty     REAL NOT NULL DEFAULT 0,
    replace_qty     REAL NOT NULL DEFAULT 0,
    quota_override  REAL,
    note            TEXT,
    updated_by      TEXT,
    updated_at      TEXT,
    PRIMARY KEY (year, site_code, dept, catalog_code)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    email   TEXT,
    action  TEXT NOT NULL,
    detail  TEXT
);
"""


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


@contextmanager
def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(dept_headcount)")}
        if "hc_months" not in cols:  # nâng cấp CSDL tạo trước khi có nhân sự theo tháng
            conn.execute("ALTER TABLE dept_headcount ADD COLUMN hc_months TEXT")


def log(email: Optional[str], action: str, detail: str = ""):
    with connect() as conn:
        conn.execute("INSERT INTO audit_log(ts, email, action, detail) VALUES (?,?,?,?)",
                     (_now(), email, action, detail))


# ---------------------------------------------------------------------
# Users & permissions
# ---------------------------------------------------------------------
def get_user(email: str) -> Optional[Dict[str, Any]]:
    email = email.strip().lower()
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            return None
        user = dict(row)
        user["sites"] = [r["site_code"] for r in conn.execute(
            "SELECT site_code FROM user_sites WHERE email = ? ORDER BY site_code", (email,))]
        return user


def upsert_login(email: str, name: str, provider: str, default_role: str = ROLE_PENDING) -> Dict[str, Any]:
    """Record a login; creates the user with default_role if unknown. Returns the user."""
    email = email.strip().lower()
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        if exists:
            conn.execute("UPDATE users SET name = COALESCE(NULLIF(?, ''), name), provider = ?, last_login = ? WHERE email = ?",
                         (name, provider, _now(), email))
        else:
            conn.execute("INSERT INTO users(email, name, role, provider, created_at, last_login) VALUES (?,?,?,?,?,?)",
                         (email, name, default_role, provider, _now(), _now()))
    return get_user(email)


def list_users() -> List[Dict[str, Any]]:
    with connect() as conn:
        users = [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY role, email")]
        site_map: Dict[str, List[str]] = {}
        for r in conn.execute("SELECT email, site_code FROM user_sites ORDER BY site_code"):
            site_map.setdefault(r["email"], []).append(r["site_code"])
    for u in users:
        u["sites"] = site_map.get(u["email"], [])
    return users


def save_user(email: str, name: str, role: str, sites: List[str], actor: str):
    email = email.strip().lower()
    if role not in ROLE_LABELS:
        raise ValueError(f"Vai trò không hợp lệ: {role}")
    with connect() as conn:
        conn.execute(
            "INSERT INTO users(email, name, role, created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(email) DO UPDATE SET name = excluded.name, role = excluded.role",
            (email, name, role, _now()))
        conn.execute("DELETE FROM user_sites WHERE email = ?", (email,))
        conn.executemany("INSERT INTO user_sites(email, site_code) VALUES (?,?)",
                         [(email, s) for s in sorted(set(sites))])
    log(actor, "save_user", json.dumps({"email": email, "role": role, "sites": sites}, ensure_ascii=False))


def delete_user(email: str, actor: str):
    with connect() as conn:
        conn.execute("DELETE FROM users WHERE email = ?", (email.strip().lower(),))
    log(actor, "delete_user", email)


def count_admins() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users WHERE role = ?", (ROLE_ADMIN,)).fetchone()[0]


# ---------------------------------------------------------------------
# Budget lines
# ---------------------------------------------------------------------
def load_lines(year: str, site_codes: List[str]) -> List[Dict[str, Any]]:
    if not site_codes:
        return []
    marks = ",".join("?" * len(site_codes))
    with connect() as conn:
        rows = conn.execute(
            f"SELECT site_code, data FROM budget_lines WHERE year = ? AND site_code IN ({marks}) "
            f"ORDER BY site_code, seq, id", [year, *site_codes]).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        d["site_code"] = r["site_code"]
        out.append(d)
    return out


def replace_lines(year: str, site_code: str, rows: List[Dict[str, Any]], actor: str):
    """Overwrite all budget lines of one site for one year."""
    now = _now()
    with connect() as conn:
        conn.execute("DELETE FROM budget_lines WHERE year = ? AND site_code = ?", (year, site_code))
        conn.executemany(
            "INSERT INTO budget_lines(year, site_code, seq, data, updated_by, updated_at) VALUES (?,?,?,?,?,?)",
            [(year, site_code, i, json.dumps(_jsonable(r), ensure_ascii=False), actor, now)
             for i, r in enumerate(rows)])
        conn.execute(
            "INSERT INTO site_status(year, site_code, status, updated_by, updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(year, site_code) DO NOTHING", (year, site_code, STATUS_DRAFT, actor, now))
    log(actor, "save_lines", f"{year}/{site_code}: {len(rows)} dòng")


def site_summary(year: str) -> Dict[str, Dict[str, Any]]:
    """Per site: line count, last update (budget totals are computed from the rows by the caller)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT site_code, COUNT(*) AS n, MAX(updated_at) AS last_at FROM budget_lines "
            "WHERE year = ? GROUP BY site_code", (year,)).fetchall()
    return {r["site_code"]: dict(r) for r in rows}


# ---------------------------------------------------------------------
# Site submission workflow
# ---------------------------------------------------------------------
def get_status(year: str, site_code: str) -> Dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM site_status WHERE year = ? AND site_code = ?",
                           (year, site_code)).fetchone()
    return dict(row) if row else {"year": year, "site_code": site_code, "status": STATUS_DRAFT, "note": None,
                                  "updated_by": None, "updated_at": None}


def all_statuses(year: str) -> Dict[str, Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM site_status WHERE year = ?", (year,)).fetchall()
    return {r["site_code"]: dict(r) for r in rows}


def set_status(year: str, site_code: str, status: str, actor: str, note: str = ""):
    with connect() as conn:
        conn.execute(
            "INSERT INTO site_status(year, site_code, status, note, updated_by, updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(year, site_code) DO UPDATE SET status = excluded.status, note = excluded.note, "
            "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
            (year, site_code, status, note, actor, _now()))
    log(actor, "set_status", f"{year}/{site_code} -> {status} {note}".strip())


# ---------------------------------------------------------------------
# Định biên nhân sự & thiết bị hiện có theo phòng ban
# ---------------------------------------------------------------------
_DEPT_TABLES = {
    "dept_headcount": ("kit_code", "hc_current", "hc_plan", "hc_months"),
    "dept_inventory": ("catalog_code", "current_qty", "replace_qty", "quota_override", "note"),
}


def load_dept_rows(table: str, year: str, site_codes: List[str], dept: Optional[str] = None) -> List[Dict[str, Any]]:
    if table not in _DEPT_TABLES or not site_codes:
        return []
    marks = ",".join("?" * len(site_codes))
    sql = f"SELECT * FROM {table} WHERE year = ? AND site_code IN ({marks})"
    params: List[Any] = [year, *site_codes]
    if dept is not None:
        sql += " AND dept = ?"
        params.append(dept)
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def replace_dept_rows(table: str, year: str, site_code: str, dept: str, rows: List[Dict[str, Any]], actor: str):
    cols = _DEPT_TABLES[table]
    now = _now()
    with connect() as conn:
        conn.execute(f"DELETE FROM {table} WHERE year = ? AND site_code = ? AND dept = ?", (year, site_code, dept))
        conn.executemany(
            f"INSERT INTO {table}(year, site_code, dept, {', '.join(cols)}, updated_by, updated_at) "
            f"VALUES (?,?,?,{','.join('?' * len(cols))},?,?)",
            [(year, site_code, dept, *[r.get(c) for c in cols], actor, now) for r in rows])
    log(actor, f"save_{table}", f"{year}/{site_code}/{dept}: {len(rows)} dòng")


def recent_audit(limit: int = 200) -> List[Dict[str, Any]]:
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]


def _jsonable(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in row.items():
        if k == "site_code":
            continue
        if hasattr(v, "item"):  # numpy scalar
            v = v.item()
        if isinstance(v, float) and v != v:  # NaN
            v = None
        if isinstance(v, (datetime.date, datetime.datetime)):
            v = v.isoformat()
        out[k] = v
    return out


# ---------------------------------------------------------------------
# Sao lưu / khôi phục (dùng khi chạy trên dịch vụ không có ổ đĩa lưu bền)
# ---------------------------------------------------------------------
def backup_bytes() -> bytes:
    """Bản sao nhất quán của CSDL (sqlite backup API) dưới dạng bytes."""
    import tempfile
    init_db()
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(tmp)
        src.backup(dst)
        dst.close()
        src.close()
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        os.remove(tmp)


def restore_bytes(data: bytes):
    """Thay CSDL hiện tại bằng bản sao lưu (kiểm tra đúng là CSDL của hệ thống trước khi ghi)."""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        chk = sqlite3.connect(tmp)
        try:
            try:
                tables = {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            except sqlite3.DatabaseError:
                tables = set()
            if not {"users", "budget_lines", "site_status"} <= tables:
                raise ValueError("File không phải bản sao lưu CSDL của hệ thống CAPEX")
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            dst = sqlite3.connect(DB_PATH)
            chk.backup(dst)
            dst.close()
        finally:
            chk.close()
    finally:
        os.remove(tmp)
    init_db()
