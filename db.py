"""
Lưu trữ: người dùng & phân quyền, dòng ngân sách theo (năm, site), trạng thái nộp/duyệt, định biên, nhật ký.

Hai loại CSDL, chọn tự động:
- PostgreSQL: khi có chuỗi kết nối ở biến môi trường ICOST_DATABASE_URL / DATABASE_URL
  hoặc trong secrets.toml mục [database] url = "postgresql://..."  (dùng khi chạy trên cloud - lưu bền)
- SQLite: file data/icost.db (mặc định khi chạy trên máy)
Toàn bộ câu SQL viết theo cú pháp chung, dấu ? được đổi sang %s khi chạy PostgreSQL.
"""
import os
import json
import time
import sqlite3
import datetime
import threading
from contextlib import contextmanager
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ICOST_DB_PATH", os.path.join(BASE_DIR, "data", "icost.db"))

# Roles
ROLE_ADMIN = "admin"        # Toàn quyền: phân quyền, duyệt, danh mục, mọi site
ROLE_VIEWER = "viewer"      # Xem & xuất báo cáo tất cả site, không sửa
ROLE_SITE_IT = "site_it"    # Lập ngân sách cho các site được phân
ROLE_DEPT = "dept"          # Lập & xem ngân sách của đúng phòng ban được phân (theo site)
ROLE_PENDING = "pending"    # Đã đăng nhập, chờ admin phân quyền
ROLE_DISABLED = "disabled"  # Bị khóa

ROLE_LABELS = {
    ROLE_ADMIN: "Quản trị (Admin)",
    ROLE_VIEWER: "Xem tổng hợp",
    ROLE_SITE_IT: "IT Site - Lập ngân sách",
    ROLE_DEPT: "Phòng ban - Lập ngân sách phòng mình",
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
# Phòng ban đã nộp / đã duyệt: khóa sửa dòng của phòng (IT site trả lại hoặc mở lại mới sửa được)
DEPT_LOCKED_STATUSES = (STATUS_SUBMITTED, STATUS_APPROVED)
DEPT_STATUS_LABELS = {
    STATUS_DRAFT: "📝 Đang lập",
    STATUS_SUBMITTED: "📨 Đã nộp - chờ IT site duyệt",
    STATUS_APPROVED: "✅ Đã duyệt",
    STATUS_RETURNED: "↩️ Trả lại - cần chỉnh sửa",
}

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
CREATE TABLE IF NOT EXISTS user_depts (
    email      TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    site_code  TEXT NOT NULL,
    dept       TEXT NOT NULL,
    PRIMARY KEY (email, site_code, dept)
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
CREATE TABLE IF NOT EXISTS dept_status (
    year        TEXT NOT NULL,
    site_code   TEXT NOT NULL,
    dept        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft',
    note        TEXT,
    updated_by  TEXT,
    updated_at  TEXT,
    PRIMARY KEY (year, site_code, dept)
);
CREATE TABLE IF NOT EXISTS dept_headcount (
    year        TEXT NOT NULL,
    site_code   TEXT NOT NULL,
    dept        TEXT NOT NULL,
    kit_code    TEXT NOT NULL,
    hc_current  REAL NOT NULL DEFAULT 0,
    hc_plan     REAL NOT NULL DEFAULT 0,
    hc_months   TEXT,
    kit_items   TEXT,
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
CREATE TABLE IF NOT EXISTS budget_exec (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    year        TEXT NOT NULL,
    site_code   TEXT NOT NULL,
    item_code   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    doc_no      TEXT,
    doc_date    TEXT,
    amount      REAL NOT NULL DEFAULT 0,
    vendor      TEXT,
    note        TEXT,
    created_by  TEXT,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_budget_exec_year_site ON budget_exec(year, site_code);
CREATE TABLE IF NOT EXISTS budget_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    year        TEXT NOT NULL,
    site_code   TEXT NOT NULL,
    version_no  INTEGER NOT NULL,
    label       TEXT,
    reason      TEXT,
    data        TEXT NOT NULL,
    total       REAL NOT NULL DEFAULT 0,
    n_lines     INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_budget_versions_year_site ON budget_versions(year, site_code);
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    email   TEXT,
    action  TEXT NOT NULL,
    detail  TEXT
);
CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT
);
"""

# Cột của từng bảng (thứ tự xóa khi khôi phục: bảng con trước) - dùng cho sao lưu / khôi phục
TABLE_COLUMNS = {
    "user_sites": ["email", "site_code"],
    "user_depts": ["email", "site_code", "dept"],
    "users": ["email", "name", "role", "provider", "created_at", "last_login"],
    "budget_lines": ["id", "year", "site_code", "seq", "data", "updated_by", "updated_at"],
    "site_status": ["year", "site_code", "status", "note", "updated_by", "updated_at"],
    "dept_status": ["year", "site_code", "dept", "status", "note", "updated_by", "updated_at"],
    "dept_headcount": ["year", "site_code", "dept", "kit_code", "hc_current", "hc_plan", "hc_months", "kit_items", "updated_by", "updated_at"],
    "dept_inventory": ["year", "site_code", "dept", "catalog_code", "current_qty", "replace_qty", "quota_override", "note",
                       "updated_by", "updated_at"],
    "budget_exec": ["id", "year", "site_code", "item_code", "kind", "doc_no", "doc_date", "amount", "vendor", "note",
                    "created_by", "created_at"],
    "budget_versions": ["id", "year", "site_code", "version_no", "label", "reason", "data", "total", "n_lines",
                        "created_by", "created_at"],
    "audit_log": ["id", "ts", "email", "action", "detail"],
    "app_settings": ["key", "value", "updated_at"],
}
SERIAL_TABLES = {"budget_lines", "audit_log", "budget_exec", "budget_versions"}  # cột id tự tăng


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _database_url() -> Optional[str]:
    url = os.environ.get("ICOST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import streamlit as st
        return (st.secrets.get("database") or {}).get("url")
    except Exception:
        return None


def using_server_db() -> bool:
    """True khi dữ liệu nằm trên PostgreSQL (lưu bền, không phụ thuộc ổ đĩa của app)."""
    return bool(_database_url())


def _pg_sql(sql: str) -> str:
    return sql.replace("?", "%s")


class _Conn:
    """Bọc kết nối để dùng chung cú pháp cho SQLite và PostgreSQL."""

    def __init__(self, raw, pg: bool):
        self.raw, self.pg = raw, pg

    def execute(self, sql: str, params=()):
        if self.pg:
            cur = self.raw.cursor()
            cur.execute(_pg_sql(sql), tuple(params))
            return cur
        return self.raw.execute(sql, tuple(params))

    def executemany(self, sql: str, seq):
        seq = [tuple(x) for x in seq]
        if not seq:
            return None
        if self.pg:
            cur = self.raw.cursor()
            cur.executemany(_pg_sql(sql), seq)
            return cur
        return self.raw.executemany(sql, seq)


_pg_lock = threading.RLock()
_pg_state: Dict[str, Any] = {"conn": None, "url": None, "last": 0.0, "ready": set()}


def _pg_connection(url: str):
    import psycopg
    from psycopg.rows import dict_row
    conn = _pg_state["conn"]
    if conn is not None and (conn.closed or conn.broken or _pg_state["url"] != url):
        try:
            conn.close()
        except Exception:
            pass
        conn = None
    if conn is not None and time.time() - _pg_state["last"] > 60:
        try:  # kết nối để lâu có thể bị máy chủ đóng (vd. Neon tạm nghỉ khi không dùng)
            conn.execute("SELECT 1")
            conn.commit()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            conn = None
    if conn is None:
        conn = psycopg.connect(url, row_factory=dict_row, autocommit=False, connect_timeout=15)
        _pg_state.update(conn=conn, url=url)
    return conn


@contextmanager
def connect():
    url = _database_url()
    if url:
        with _pg_lock:
            raw = _pg_connection(url)
            try:
                yield _Conn(raw, True)
                raw.commit()
            except Exception:
                try:
                    raw.rollback()
                except Exception:
                    pass
                raise
            finally:
                _pg_state["last"] = time.time()
        return
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    raw = sqlite3.connect(DB_PATH, timeout=30)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    try:
        yield _Conn(raw, False)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _pg_schema() -> List[str]:
    sql = (SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
           .replace(" REAL", " DOUBLE PRECISION"))
    return [x.strip() for x in sql.split(";") if x.strip()]


def init_db():
    url = _database_url()
    if url:
        if url in _pg_state["ready"]:
            return
        with connect() as conn:
            for stmt in _pg_schema():
                conn.execute(stmt)
            conn.execute("ALTER TABLE dept_headcount ADD COLUMN IF NOT EXISTS hc_months TEXT")
            conn.execute("ALTER TABLE dept_headcount ADD COLUMN IF NOT EXISTS kit_items TEXT")
        _pg_state["ready"].add(url)
        return
    with connect() as conn:
        conn.raw.execute("PRAGMA journal_mode = WAL")
        conn.raw.executescript(SCHEMA)
        cols = {r[1] for r in conn.raw.execute("PRAGMA table_info(dept_headcount)")}
        if "hc_months" not in cols:  # nâng cấp CSDL tạo trước khi có nhân sự theo tháng
            conn.raw.execute("ALTER TABLE dept_headcount ADD COLUMN hc_months TEXT")
        if "kit_items" not in cols:  # trang bị phòng ban tự chọn theo vị trí
            conn.raw.execute("ALTER TABLE dept_headcount ADD COLUMN kit_items TEXT")


def get_setting(key: str) -> Optional[str]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str):
    init_db()
    with connect() as conn:
        conn.execute("INSERT INTO app_settings(key, value, updated_at) VALUES (?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                     (key, value, _now()))


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
        user["depts"] = [(r["site_code"], r["dept"]) for r in conn.execute(
            "SELECT site_code, dept FROM user_depts WHERE email = ? ORDER BY site_code, dept", (email,))]
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
        dept_map: Dict[str, List] = {}
        for r in conn.execute("SELECT email, site_code, dept FROM user_depts ORDER BY site_code, dept"):
            dept_map.setdefault(r["email"], []).append((r["site_code"], r["dept"]))
    for u in users:
        u["sites"] = site_map.get(u["email"], [])
        u["depts"] = dept_map.get(u["email"], [])
    return users


def save_user(email: str, name: str, role: str, sites: List[str], actor: str, depts: List = None):
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
        if depts is not None:  # None = giữ nguyên phòng ban đã phân
            conn.execute("DELETE FROM user_depts WHERE email = ?", (email,))
            conn.executemany("INSERT INTO user_depts(email, site_code, dept) VALUES (?,?,?)",
                             [(email, s, d) for s, d in sorted({(s, d) for s, d in depts})])
    log(actor, "save_user", json.dumps({"email": email, "role": role, "sites": sites, "depts": depts}, ensure_ascii=False))


def delete_user(email: str, actor: str):
    with connect() as conn:
        conn.execute("DELETE FROM users WHERE email = ?", (email.strip().lower(),))
    log(actor, "delete_user", email)


def count_admins() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users WHERE role = ?", (ROLE_ADMIN,)).fetchone()["n"]


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


def get_item_seq_counters(year: str, site_code: str) -> Dict[str, int]:
    raw = get_setting(f"item_seq|{year}|{site_code}")
    try:
        return {k: int(v) for k, v in json.loads(raw).items()} if raw else {}
    except (ValueError, TypeError, AttributeError):
        return {}


def set_item_seq_counters(year: str, site_code: str, counters: Dict[str, int]):
    set_setting(f"item_seq|{year}|{site_code}", json.dumps(counters, ensure_ascii=False, sort_keys=True))


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


def _dept_key(name) -> str:
    return " ".join(str(name or "").lower().split())


def dept_statuses(year: str, site_code: str) -> Dict[str, Dict[str, Any]]:
    """Trạng thái duyệt của các phòng ban 1 site, khóa = tên phòng chuẩn hóa (không phân biệt hoa/thường)."""
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM dept_status WHERE year = ? AND site_code = ?", (year, site_code)).fetchall()
    return {_dept_key(r["dept"]): dict(r) for r in rows}


def get_dept_status(year: str, site_code: str, dept: str) -> Dict[str, Any]:
    return dept_statuses(year, site_code).get(_dept_key(dept)) or {
        "year": year, "site_code": site_code, "dept": dept, "status": STATUS_DRAFT, "note": None,
        "updated_by": None, "updated_at": None}


def set_dept_status(year: str, site_code: str, dept: str, status: str, actor: str, note: str = ""):
    init_db()
    existing = dept_statuses(year, site_code).get(_dept_key(dept))
    name = existing["dept"] if existing else str(dept).strip()  # giữ đúng tên đã lưu (khóa chính)
    with connect() as conn:
        conn.execute(
            "INSERT INTO dept_status(year, site_code, dept, status, note, updated_by, updated_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(year, site_code, dept) DO UPDATE SET status = excluded.status, note = excluded.note, "
            "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
            (year, site_code, name, status, note, actor, _now()))
    log(actor, "set_dept_status", f"{year}/{site_code}/{name} -> {status} {note}".strip())


# ---------------------------------------------------------------------
# Phiên bản ngân sách: chốt khi Admin duyệt site (bản duyệt, điều chỉnh lần N)
# ---------------------------------------------------------------------
def save_version(year: str, site_code: str, rows: List[Dict[str, Any]], actor: str, reason: str = "") -> Dict[str, Any]:
    """Chốt toàn bộ dòng ngân sách hiện tại của site thành 1 phiên bản. Trả về thông tin phiên bản."""
    init_db()
    clean = [_jsonable({k: v for k, v in r.items() if k != "site_code"}) for r in rows]
    total = float(sum(float(r.get("total_budget") or 0) for r in clean))
    with connect() as conn:
        row = conn.execute("SELECT MAX(version_no) AS n FROM budget_versions WHERE year = ? AND site_code = ?",
                           (year, site_code)).fetchone()
        no = int(row["n"] or 0) + 1
        label = "Bản duyệt" if no == 1 else f"Điều chỉnh lần {no - 1}"
        conn.execute("INSERT INTO budget_versions(year, site_code, version_no, label, reason, data, total, n_lines, created_by, created_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (year, site_code, no, label, reason, json.dumps(clean, ensure_ascii=False), total, len(clean), actor, _now()))
    log(actor, "save_version", f"{year}/{site_code}: v{no} {label} - {len(clean)} dòng, {total:,.0f}" + (f" ({reason})" if reason else ""))
    return {"version_no": no, "label": label, "total": total, "n_lines": len(clean)}


def list_versions(year: str, site_codes: List[str]) -> List[Dict[str, Any]]:
    """Danh sách phiên bản (không kèm dữ liệu dòng), mới nhất trước."""
    if not site_codes:
        return []
    init_db()
    marks = ",".join("?" * len(site_codes))
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT id, year, site_code, version_no, label, reason, total, n_lines, created_by, created_at FROM budget_versions "
            f"WHERE year = ? AND site_code IN ({marks}) ORDER BY site_code, version_no DESC", [year, *site_codes])]


def load_version(version_id: int) -> List[Dict[str, Any]]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT data FROM budget_versions WHERE id = ?", (int(version_id),)).fetchone()
    return json.loads(row["data"]) if row else []


def latest_version_lines(year: str, site_codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """Bản duyệt gần nhất của từng site: {site: {"info": {...}, "rows": [...]}}."""
    out = {}
    for v in list_versions(year, site_codes):
        if v["site_code"] not in out:
            out[v["site_code"]] = {"info": v, "rows": load_version(v["id"])}
    return out


# ---------------------------------------------------------------------
# Thực hiện ngân sách: đề nghị mua / hợp đồng / thanh toán theo Mã hạng mục
# ---------------------------------------------------------------------
EXEC_REQUEST, EXEC_CONTRACT, EXEC_PAYMENT = "request", "contract", "payment"
EXEC_LABELS = {EXEC_REQUEST: "Đề nghị mua", EXEC_CONTRACT: "Hợp đồng / PO", EXEC_PAYMENT: "Thanh toán"}


def load_exec(year: str, site_codes: List[str]) -> List[Dict[str, Any]]:
    if not site_codes:
        return []
    init_db()
    marks = ",".join("?" * len(site_codes))
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM budget_exec WHERE year = ? AND site_code IN ({marks}) ORDER BY doc_date, id", [year, *site_codes])]


def add_exec(year: str, site_code: str, item_code: str, kind: str, amount: float, actor: str,
             doc_no: str = "", doc_date: str = "", vendor: str = "", note: str = ""):
    if kind not in EXEC_LABELS:
        raise ValueError(f"Loại chứng từ không hợp lệ: {kind}")
    init_db()
    with connect() as conn:
        conn.execute("INSERT INTO budget_exec(year, site_code, item_code, kind, doc_no, doc_date, amount, vendor, note, created_by, created_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (year, site_code, item_code, kind, doc_no, doc_date, float(amount), vendor, note, actor, _now()))
    log(actor, "add_exec", f"{year}/{site_code}/{item_code}: {EXEC_LABELS[kind]} {doc_no} {float(amount):,.0f}".strip())


def delete_exec(exec_id: int, actor: str):
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM budget_exec WHERE id = ?", (int(exec_id),)).fetchone()
        if not row:
            return
        conn.execute("DELETE FROM budget_exec WHERE id = ?", (int(exec_id),))
    log(actor, "delete_exec", f"{row['year']}/{row['site_code']}/{row['item_code']}: {EXEC_LABELS.get(row['kind'], row['kind'])} "
                              f"{row['doc_no'] or ''} {row['amount']:,.0f} (id {row['id']})")


# ---------------------------------------------------------------------
# Định biên nhân sự & thiết bị hiện có theo phòng ban
# ---------------------------------------------------------------------
_DEPT_TABLES = {
    "dept_headcount": ("kit_code", "hc_current", "hc_plan", "hc_months", "kit_items"),
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
    """Sao lưu toàn bộ dữ liệu thành 1 file SQLite (dùng chung cho cả SQLite và PostgreSQL)."""
    import tempfile
    init_db()
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dst = sqlite3.connect(tmp)
        dst.executescript(SCHEMA)
        with connect() as conn:
            for table, cols in TABLE_COLUMNS.items():
                rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
                dst.executemany(f"INSERT INTO {table}({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                                [tuple(r[c] for c in cols) for r in rows])
        dst.commit()
        dst.close()
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        os.remove(tmp)


def restore_bytes(data: bytes):
    """Thay toàn bộ dữ liệu hiện tại bằng bản sao lưu (file SQLite), ghi vào CSDL đang dùng (SQLite hoặc PostgreSQL)."""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        chk = sqlite3.connect(tmp)
        chk.row_factory = sqlite3.Row
        try:
            try:
                tables = {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            except sqlite3.DatabaseError:
                tables = set()
            if not {"users", "budget_lines", "site_status"} <= tables:
                raise ValueError("File không phải bản sao lưu CSDL của hệ thống CAPEX")
            payload = {}
            for table, cols in TABLE_COLUMNS.items():
                if table not in tables:
                    continue
                have = [r[1] for r in chk.execute(f"PRAGMA table_info({table})")]
                use = [c for c in cols if c in have and not (c == "id" and table in SERIAL_TABLES)]
                order = " ORDER BY id" if table in SERIAL_TABLES else ""
                payload[table] = (use, [tuple(r[c] for c in use) for r in chk.execute(f"SELECT * FROM {table}{order}")])
        finally:
            chk.close()
        init_db()
        with connect() as conn:
            for table in TABLE_COLUMNS:  # bảng con trước
                conn.execute(f"DELETE FROM {table}")
            for table in ["users"] + [t for t in TABLE_COLUMNS if t != "users"]:  # bảng cha trước khi chèn
                if table in payload:
                    use, rows = payload[table]
                    conn.executemany(f"INSERT INTO {table}({', '.join(use)}) VALUES ({','.join('?' * len(use))})", rows)
    finally:
        os.remove(tmp)


def storage_info() -> Dict[str, Any]:
    """Thông tin CSDL đang dùng (không lộ mật khẩu) + số dòng từng bảng - để kiểm tra lưu trữ."""
    init_db()
    url = _database_url()
    if url:
        from urllib.parse import urlparse
        u = urlparse(url)
        info = {"backend": "PostgreSQL", "durable": True, "location": f"{u.hostname}/{(u.path or '/').lstrip('/')}"}
    else:
        info = {"backend": "SQLite", "durable": False, "location": DB_PATH}
    with connect() as conn:
        info["rows"] = {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in TABLE_COLUMNS}
        if url:
            info["server"] = conn.execute("SELECT version() AS v").fetchone()["v"].split(" on ")[0]
    return info
