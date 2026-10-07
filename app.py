"""
HỆ THỐNG QUẢN LÝ & TÍNH TOÁN NGÂN SÁCH ĐẦU TƯ CAPEX
CÔNG TY CỔ PHẦN CƠ KHÍ XÂY DỰNG THƯƠNG MẠI ĐẠI DŨNG
"""
import os
import html as _html
import datetime
import io
import pandas as pd
import numpy as np
import openpyxl
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

import auth
import db
from master_data import (
    load_master_data,
    save_master_data,
    generate_project_code,
    generate_item_code,
    generate_budget_code,
    fiscal_months,
    it_groups,
    it_kinds,
    apply_it_catalog,
    classify_item,
    item_scope,
    item_owner,
    SCOPE_SHARED,
    SCOPE_USER,
    SCOPE_LABELS,
    accounting_class,
    default_invest_type,
    INVEST_TYPES,
    KIND_HARDWARE,
    DEFAULT_MONTHS
)
import quota as qt
import headcount_import as hi
import unicodedata
from capex_engine import (
    load_capex_from_excel,
    export_capex_to_excel,
    calculate_row,
    calculate_depreciation_schedule,
    calculate_project_financials,
    clean_number,
    USEFUL_LIFE_DEFAULTS
)

# Page configuration
st.set_page_config(
    page_title="Hệ thống ngân sách",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for executive corporate look
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .main-header {
        background: linear-gradient(135deg, #0F2C59 0%, #1E4E8C 100%);
        padding: 24px 30px;
        border-radius: 12px;
        color: white;
        margin-bottom: 24px;
        box-shadow: 0 4px 15px rgba(15, 44, 89, 0.15);
    }

    .main-header h1 {
        color: #FFFFFF !important;
        font-size: 26px;
        font-weight: 700;
        margin: 0;
        padding: 0;
    }

    .main-header p {
        color: #D0E1FD;
        font-size: 14px;
        margin-top: 6px;
        margin-bottom: 0;
    }

    .kpi-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 18px 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }

    .kpi-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 14px rgba(0,0,0,0.08);
    }

    .kpi-title {
        color: #64748B;
        font-size: 13px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 8px;
    }

    .kpi-value {
        color: #0F2C59;
        font-size: 26px;
        font-weight: 700;
        margin-bottom: 4px;
    }

    .kpi-sub {
        color: #10B981;
        font-size: 12px;
        font-weight: 500;
    }

    .badge-code {
        background: #EFF6FF;
        color: #1D4ED8;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
        font-family: monospace;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }

    .stTabs [data-baseweb="tab"] {
        height: 48px;
        padding: 0 20px;
        font-weight: 600;
        border-radius: 8px 8px 0 0;
    }
</style>
""", unsafe_allow_html=True)

# Format currency helper
def format_vnd(amount: float) -> str:
    """Format money into VND with billions notation"""
    if pd.isna(amount) or amount is None:
        return "0 VNĐ"
    amount = float(amount)
    if abs(amount) >= 1_000_000_000:
        return f"{amount:,.0f} VNĐ ({amount/1e9:,.2f} tỷ)"
    elif abs(amount) >= 1_000_000:
        return f"{amount:,.0f} VNĐ ({amount/1e6:,.2f} tr)"
    return f"{amount:,.0f} VNĐ"

def format_vnd_short(amount: float) -> str:
    """Short format for charts"""
    if pd.isna(amount) or amount is None:
        return "0"
    amount = float(amount)
    if abs(amount) >= 1_000_000_000:
        return f"{amount/1e9:,.2f} tỷ"
    elif abs(amount) >= 1_000_000:
        return f"{amount/1e6:,.1f} tr"
    return f"{amount:,.0f}"

# =====================================================================
# ĐĂNG NHẬP & PHÂN QUYỀN
# =====================================================================
current_user = auth.require_login()

master = load_master_data()
SITES = master.get("sites", [])
SITE_NAME = {s["code"]: s["name"] for s in SITES}
SITE_BY_NAME = {s["name"]: s["code"] for s in SITES}
ALL_SITES = "__ALL__"
SAMPLE_EXCEL_PATH = os.path.join(os.path.dirname(__file__), "2. Form file nhập liệu CAPEX 2026.xlsx")


def site_label(code: str) -> str:
    if code == ALL_SITES:
        return "🌐 Tất cả site được xem"
    return f"{SITE_NAME.get(code, code)} ({code})"


def rows_for_site(df: pd.DataFrame, site_code: str, months, year_code: str):
    """Recalculate rows, renumber STT and pin location to the site."""
    rows = []
    for i, (_, r) in enumerate(df.iterrows()):
        d = {k: v for k, v in r.to_dict().items()
             if k != "site_code" and not k.startswith("_") and not (v is None or (isinstance(v, float) and np.isnan(v)))}
        d["stt"] = i + 1
        d["location"] = SITE_NAME.get(site_code, site_code)
        rows.append(calculate_row(d, months=months, year_code=year_code, master=master))
    return rows


def save_site(df: pd.DataFrame, site_code: str):
    if current_user.is_dept_user:
        allowed = {dept_key(d) for d in current_user.allowed_depts(site_code)}
        mine = df[df["dept_proposing"].map(dept_key).isin(allowed)] if "dept_proposing" in df.columns else df.iloc[0:0]
        stored = pd.DataFrame(db.load_lines(budget_year, [site_code]))
        if not stored.empty:
            stored = stored.drop(columns=["site_code"], errors="ignore")
            stored = stored[~stored["dept_proposing"].map(dept_key).isin(allowed)] if "dept_proposing" in stored.columns else stored
        df = pd.concat([stored, mine], ignore_index=True)
    db.replace_lines(budget_year, site_code, rows_for_site(df, site_code, months, year_code), actor=current_user.email)
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1


ALL_DEPTS = "(Tất cả phòng ban)"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@st.cache_data(max_entries=8, show_spinner="Đang tạo file Excel...")
def _cached_export(df: pd.DataFrame, meta_items: tuple, months_t: tuple) -> bytes:
    return export_capex_to_excel(df, dict(meta_items), months=list(months_t))


def lazy_excel_download(df: pd.DataFrame, meta: dict, label: str, file_name: str, key: str, help_text: str = None):
    """Chỉ tạo file Excel khi người dùng bấm 'Chuẩn bị' (tạo file mất vài giây, không làm ở mỗi lần chạy lại)."""
    flag = f"xl_ready_{key}"
    if not st.session_state.get(flag):
        if st.button("📦 Chuẩn bị file Excel", key=f"xl_prep_{key}", use_container_width=True, help=help_text):
            st.session_state[flag] = True
            st.rerun()
        return None
    data = _cached_export(df.drop(columns=["_order"], errors="ignore").reset_index(drop=True),
                          tuple(sorted((k, str(v)) for k, v in meta.items())), tuple(months))
    if st.download_button(label, data=data, file_name=file_name, mime=XLSX_MIME, use_container_width=True,
                          key=f"xl_dl_{key}", help=help_text):
        st.session_state[flag] = False
    return data


@st.cache_data(max_entries=4, show_spinner="Đang đọc file định biên...")
def _cached_roster(content: bytes, kit_codes: tuple, site_ov_json: str, kit_ov_json: str):
    import io as _io
    import json as _json
    return hi.read_roster(_io.BytesIO(content), set(kit_codes), _json.loads(site_ov_json), _json.loads(kit_ov_json))


def dept_key(name) -> str:
    return " ".join(str(name or "").lower().split())


def dept_mask(df: pd.DataFrame, dept: str) -> pd.Series:
    if dept == ALL_DEPTS or df.empty or "dept_proposing" not in df.columns:
        return pd.Series(True, index=df.index)
    return df["dept_proposing"].map(dept_key) == dept_key(dept)


def save_view(view_df: pd.DataFrame):
    """Lưu bảng đang xem (đã lọc theo phòng ban) vào site: giữ nguyên dòng của phòng ban khác và thứ tự dòng."""
    view = view_df.copy()
    if selected_dept != ALL_DEPTS:
        view["dept_proposing"] = selected_dept
        others = df_site[~dept_mask(df_site, selected_dept)]
        view = pd.concat([others, view], ignore_index=True)
    if "_order" in view.columns:
        view = view.assign(_order=view["_order"].fillna(float("inf"))).sort_values("_order", kind="stable")
    save_site(view.reset_index(drop=True), selected_site)


def distribute_by_location(df: pd.DataFrame):
    """Split an imported table by its 'location' column into {site_code: df}; returns (groups, unmatched_locations)."""
    def norm(name: str) -> str:
        n = " ".join(str(name).lower().split())
        for prefix in ("nm ", "vp ", "nx "):
            if n.startswith(prefix):
                n = n[len(prefix):]
        return n

    lookup = {}
    for s in SITES:
        lookup[norm(s["name"])] = s["code"]
        lookup[s["code"].lower()] = s["code"]

    groups, unmatched = {}, {}
    for loc, part in df.groupby(df["location"].fillna("").astype(str).str.strip()):
        code = lookup.get(norm(loc))
        if code:
            groups[code] = pd.concat([groups[code], part]) if code in groups else part
        else:
            unmatched[loc or "(trống)"] = len(part)
    return groups, unmatched


def _default_metadata():
    return {
        "date": datetime.date.today().strftime("%Y-%m-%d"),
        "proposing_dept": "Phòng CNTT & CĐS",
        "creator_name": current_user.name,
        "creator_email": current_user.email,
    }


if "metadata" not in st.session_state:
    st.session_state["metadata"] = _default_metadata()

# SIDEBAR CONTROLS
with st.sidebar:
    st.image("https://daidung.com/wp-content/uploads/2023/07/logo-dai-dung.png", width=180)

    # Thông tin người dùng
    st.markdown(f"""
    <div style="background:#F1F5F9;border-radius:10px;padding:10px 12px;margin-bottom:8px;">
        <div style="font-weight:700;color:#0F2C59;">👤 {_html.escape(current_user.name)}</div>
        <div style="font-size:12px;color:#475569;">{_html.escape(current_user.email)}</div>
        <div style="font-size:12px;margin-top:4px;"><span class="badge-code">{db.ROLE_LABELS.get(current_user.role, current_user.role)}</span></div>
    </div>
    """, unsafe_allow_html=True)
    if current_user.is_admin:
        st.caption("💾 CSDL: " + ("PostgreSQL (lưu bền)" if db.using_server_db() else "SQLite (file cục bộ)"))
    if st.button("🚪 Đăng xuất", use_container_width=True):
        auth.logout()

    if current_user.is_admin:
        admin_view = st.radio("Màn hình", ["📊 Ngân sách", "👥 Phân quyền & Tiến độ"], key="admin_view",
                              help="Phân quyền người dùng, tiến độ các site, nhật ký, sao lưu / khôi phục")
    else:
        admin_view = "📊 Ngân sách"

    st.markdown("### ⚙️ Thiết lập Ngân sách")

    budget_year = st.selectbox("Năm ngân sách", ["2026", "2025", "2027"], index=0)
    year_code = f"A{budget_year[-2:]}"
    months = fiscal_months(budget_year)

    visible_sites = current_user.visible_sites([s["code"] for s in SITES])
    site_options = ([ALL_SITES] if current_user.sees_all_sites else []) + visible_sites
    selected_site = st.selectbox("Site lập ngân sách", site_options, format_func=site_label)

    if selected_site == ALL_SITES:
        site_status = None
        can_edit = False
        st.caption("Chế độ xem tổng hợp. Chọn 1 site cụ thể để nhập liệu / duyệt.")
    else:
        site_status = db.get_status(budget_year, selected_site)
        can_edit = current_user.can_edit_site(selected_site, site_status["status"])
        st.markdown(f"**Trạng thái:** {db.STATUS_LABELS.get(site_status['status'], site_status['status'])}")
        if site_status.get("note"):
            st.caption(f"Ghi chú: {site_status['note']}")

    # Dữ liệu của site (toàn bộ phòng ban); "_order" giữ thứ tự dòng khi lưu bảng đã lọc
    scope_sites = visible_sites if selected_site == ALL_SITES else [selected_site]
    df_site = pd.DataFrame(db.load_lines(budget_year, scope_sites))
    if selected_site != ALL_SITES and "site_code" in df_site.columns:
        df_site = df_site.drop(columns=["site_code"])
    if current_user.is_dept_user and selected_site != ALL_SITES and "dept_proposing" in df_site.columns:
        _allowed = {dept_key(d) for d in current_user.allowed_depts(selected_site)}
        df_site = df_site[df_site["dept_proposing"].map(dept_key).isin(_allowed)].reset_index(drop=True)
    df_site["_order"] = range(len(df_site))

    # Phòng ban: danh mục chuẩn + tên phòng ban đang có trong dữ liệu (không trùng hoa/thường)
    hc_depts = sorted({r["dept"] for r in db.load_dept_rows("dept_headcount", budget_year, scope_sites)})
    dept_list = hc_depts + [d for d in master.get("departments", []) if dept_key(d) not in {dept_key(x) for x in hc_depts}]
    known = {dept_key(d) for d in dept_list}
    if "dept_proposing" in df_site.columns:
        for d in sorted(df_site["dept_proposing"].dropna().astype(str).unique()):
            if d.strip() and dept_key(d) not in known:
                dept_list.append(d.strip())
                known.add(dept_key(d))
    if current_user.is_dept_user:
        dept_list = current_user.allowed_depts(selected_site)
    selected_dept = st.selectbox("Phòng ban lập ngân sách", ([] if current_user.is_dept_user else [ALL_DEPTS]) + dept_list,
                                 help="Lọc bảng & báo cáo theo phòng ban đề xuất. Dòng thêm mới được gán cho phòng ban này.")
    dept_prop = selected_dept if selected_dept != ALL_DEPTS else "Tất cả phòng ban"

    st.markdown("---")
    st.markdown("#### 🏢 Thông tin Đề xuất")
    meta = st.session_state["metadata"]
    creator_name = st.text_input("Họ và tên người lập", value=meta.get("creator_name") or current_user.name)
    creator_email = st.text_input("Email người lập", value=current_user.email, disabled=True)
    plan_date = st.date_input("Ngày lập", value=datetime.date.today())

    st.session_state["metadata"]["proposing_dept"] = dept_prop
    st.session_state["metadata"]["creator_name"] = creator_name
    st.session_state["metadata"]["creator_email"] = creator_email
    st.session_state["metadata"]["date"] = plan_date.strftime("%Y-%m-%d")
    st.session_state["metadata"]["budget_year"] = budget_year

    st.markdown("---")
    st.markdown("#### 🔄 Hành động Nhanh")
    if st.button("🔄 Làm mới", use_container_width=True):
        st.rerun()
    if can_edit and not current_user.is_dept_user:
        with st.popover("🗑️ Xóa toàn bộ dòng của site", use_container_width=True):
            st.warning(f"Xóa toàn bộ hạng mục năm {budget_year} của {site_label(selected_site)}?")
            if st.button("Xác nhận xóa", type="primary"):
                db.replace_lines(budget_year, selected_site, [], actor=current_user.email)
                st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
                st.rerun()

    if current_user.is_admin and os.path.exists(SAMPLE_EXCEL_PATH):
        st.markdown("##### 📥 Nạp ngân sách cơ sở (Admin)")
        st.caption("Đọc file CAPEX và phân các dòng về đúng site theo cột Vị trí (ghi đè dữ liệu các site có trong file).")
        seed_sheet = st.selectbox("Sheet nguồn", ["CA.01_CAPEX (2)", "CA.01_CAPEX"])
        if st.button("Nạp & phân về các site", use_container_width=True):
            _, seed_df = load_capex_from_excel(SAMPLE_EXCEL_PATH, seed_sheet, months=months, year_code=year_code)
            groups, unmatched = distribute_by_location(seed_df)
            for code, part in groups.items():
                save_site(part, code)
            st.session_state["flash"] = (f"Đã nạp {sum(len(p) for p in groups.values())} dòng vào {len(groups)} site."
                                         + (f" Bỏ qua vị trí không khớp danh mục: {unmatched}" if unmatched else ""))
            st.rerun()

# Dữ liệu hiện hành theo site + phòng ban được chọn
df_curr = df_site[dept_mask(df_site, selected_dept)].reset_index(drop=True)

# MAIN HEADER BANNER
st.markdown(f"""
<div class="main-header">
    <h1>HỆ THỐNG QUẢN LÝ & TÍNH TOÁN NGÂN SÁCH ĐẦU TƯ CAPEX {budget_year}</h1>
    <p>CÔNG TY CỔ PHẦN CƠ KHÍ XÂY DỰNG THƯƠNG MẠI ĐẠI DŨNG | Site: <b>{site_label(selected_site)}</b> | Đơn vị đề xuất: <b>{_html.escape(dept_prop)}</b> | Người lập: <b>{_html.escape(creator_name or 'Chưa nhập')}</b></p>
</div>
""", unsafe_allow_html=True)

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

# THANH TRẠNG THÁI NỘP / DUYỆT NGÂN SÁCH SITE
if selected_site != ALL_SITES:
    status = site_status["status"]
    sc1, sc2 = st.columns([3, 2])
    with sc1:
        st.markdown(f"**Trạng thái ngân sách {budget_year} – {site_label(selected_site)}:** {db.STATUS_LABELS.get(status, status)}"
                    + (f"  ·  cập nhật bởi {site_status['updated_by']} lúc {site_status['updated_at']}" if site_status.get("updated_at") else ""))
        if not can_edit and status not in db.EDITABLE_STATUSES and not current_user.is_admin:
            st.caption("🔒 Ngân sách đã nộp/duyệt nên đang khóa chỉnh sửa. Liên hệ Admin nếu cần mở lại.")
        elif current_user.role == db.ROLE_VIEWER:
            st.caption("👁️ Tài khoản chỉ có quyền xem.")
    with sc2:
        invalid_rows = int((~df_site["pct_valid"].fillna(False).astype(bool)).sum()) if "pct_valid" in df_site.columns else 0
        if current_user.is_dept_user and status in db.EDITABLE_STATUSES:
            st.caption("Lập xong, báo IT site / admin nộp ngân sách của site.")
        if status in db.EDITABLE_STATUSES and can_edit and not current_user.is_dept_user:
            if st.button("📨 Nộp ngân sách site để duyệt", use_container_width=True, disabled=df_site.empty,
                         help="Nộp toàn bộ ngân sách của site (tất cả phòng ban)"):
                missing_reason = 0
                if "need_type" in df_site.columns:
                    reason = df_site["need_reason"] if "need_reason" in df_site.columns else pd.Series("", index=df_site.index)
                    missing_reason = int((df_site["need_type"].isin(qt.NEED_WITH_REASON) & (reason.fillna("").astype(str).str.strip() == "")).sum())
                if invalid_rows:
                    st.error(f"Còn {invalid_rows} dòng có tổng phân kỳ khác 100%. Vui lòng chỉnh trước khi nộp.")
                elif missing_reason:
                    st.error(f"Còn {missing_reason} dòng 'Phát sinh mới' / 'Hạ tầng dùng chung' chưa ghi lý do / căn cứ. Vui lòng bổ sung trước khi nộp.")
                else:
                    db.set_status(budget_year, selected_site, db.STATUS_SUBMITTED, current_user.email)
                    st.rerun()
        if current_user.is_admin and status == db.STATUS_SUBMITTED:
            note = st.text_input("Ghi chú duyệt / trả lại", key="approve_note")
            ac1, ac2 = st.columns(2)
            if ac1.button("✅ Duyệt", use_container_width=True):
                db.set_status(budget_year, selected_site, db.STATUS_APPROVED, current_user.email, note)
                st.rerun()
            if ac2.button("↩️ Trả lại", use_container_width=True):
                db.set_status(budget_year, selected_site, db.STATUS_RETURNED, current_user.email, note)
                st.rerun()
        if current_user.is_admin and status == db.STATUS_APPROVED:
            if st.button("🔓 Mở lại để chỉnh sửa", use_container_width=True):
                db.set_status(budget_year, selected_site, db.STATUS_DRAFT, current_user.email, "Mở lại")
                st.rerun()

# TABS NAVIGATION
tab_names = [
    "📊 Dashboard Phân tích",
    "📝 Lập & Nhập liệu CapEx",
    "👥 Định biên & Nhu cầu",
    "🏗️ Hạ tầng CNTT dùng chung",
    "📁 Nhập / Xuất Excel",
    "📈 Khấu hao & Thẩm định",
    "⚙️ Quản lý Danh mục",
]
# =====================================================================
# TRANG QUẢN TRỊ: PHÂN QUYỀN & TIẾN ĐỘ (mở từ thanh bên, chỉ Admin)
# =====================================================================
def render_admin_page():
    st.markdown("### 👥 Phân quyền Người dùng & Tiến độ Lập Ngân sách các Site")
    a_users, a_progress, a_audit, a_backup = st.tabs(["👤 Người dùng & Site được phân", "📋 Tiến độ các site",
                                                      "🧾 Nhật ký thao tác", "💾 Sao lưu / Khôi phục"])

    users = db.list_users()
    site_codes = [s["code"] for s in SITES]

    with a_users:
        pending = [u for u in users if u["role"] == db.ROLE_PENDING]
        if pending:
            st.warning(f"⏳ Có {len(pending)} tài khoản đã đăng nhập và đang chờ phân quyền: "
                       + ", ".join(u["email"] for u in pending))

        df_users = pd.DataFrame([{
            "Email": u["email"],
            "Họ tên": u.get("name") or "",
            "Vai trò": db.ROLE_LABELS.get(u["role"], u["role"]),
            "Site được phân": ", ".join(site_label(c) for c in u["sites"]),
            "Phòng ban được phân": "; ".join(f"{site_label(s)} · {d}" for s, d in u.get("depts", [])),
            "Đăng nhập qua": u.get("provider") or "",
            "Lần đăng nhập cuối": u.get("last_login") or "",
        } for u in users])
        st.dataframe(df_users, use_container_width=True, hide_index=True)

        st.markdown("#### ✏️ Thêm / Cập nhật quyền")
        st.caption("Thêm trước email UltraID/Google của IT site, hoặc chọn tài khoản đang chờ để phân site. "
                   "Vai trò **IT Site** chỉ thấy và lập ngân sách cho các site được chọn.")
        NEW_USER = "➕ Thêm email mới"
        pick = st.selectbox("Tài khoản", [NEW_USER] + [u["email"] for u in users],
                            format_func=lambda e: e if e == NEW_USER else
                            f"{e} – {db.ROLE_LABELS.get(next(u['role'] for u in users if u['email'] == e), '')}")
        existing = next((u for u in users if u["email"] == pick), None)
        with st.form("form_user", clear_on_submit=False):
            fu1, fu2 = st.columns(2)
            with fu1:
                u_email = st.text_input("Email đăng nhập", value="" if existing is None else existing["email"],
                                        disabled=existing is not None)
                u_name = st.text_input("Họ tên", value="" if existing is None else (existing.get("name") or ""))
            with fu2:
                role_keys = list(db.ROLE_LABELS)
                default_role = existing["role"] if existing else db.ROLE_SITE_IT
                if default_role == db.ROLE_PENDING:
                    default_role = db.ROLE_SITE_IT
                u_role = st.selectbox("Vai trò", role_keys, index=role_keys.index(default_role),
                                      format_func=lambda r: db.ROLE_LABELS[r])
                u_sites = st.multiselect("Site được phân lập ngân sách", site_codes,
                                         default=[] if existing is None else sorted(
                                             {c for c in existing["sites"] if c in site_codes}
                                             | {s for s, _ in existing.get("depts", []) if s in site_codes}),
                                         format_func=site_label)
                dept_choices = sorted(set(dept_list) | {d for _, d in (existing or {}).get("depts", [])})
                u_depts = st.multiselect("Phòng ban được phân (chỉ dùng cho vai trò Phòng ban)", dept_choices,
                                         default=sorted({d for _, d in (existing or {}).get("depts", [])}),
                                         help="Người dùng được lập & xem ngân sách của các phòng này tại các site đã chọn")
            fb1, fb2 = st.columns([3, 1])
            submitted = fb1.form_submit_button("💾 Lưu phân quyền", use_container_width=True, type="primary")
            deleted = fb2.form_submit_button("🗑️ Xóa tài khoản", use_container_width=True, disabled=existing is None)

        target_email = (existing["email"] if existing else u_email).strip().lower()
        removing_last_admin = (existing is not None and existing["role"] == db.ROLE_ADMIN
                               and db.count_admins() <= 1)
        if submitted:
            if "@" not in target_email:
                st.error("Email không hợp lệ.")
            elif u_role == db.ROLE_SITE_IT and not u_sites:
                st.error("Vai trò IT Site cần được phân ít nhất 1 site.")
            elif u_role == db.ROLE_DEPT and not (u_sites and u_depts):
                st.error("Vai trò Phòng ban cần chọn ít nhất 1 site và 1 phòng ban.")
            elif removing_last_admin and u_role != db.ROLE_ADMIN:
                st.error("Không thể hạ quyền Admin cuối cùng của hệ thống.")
            else:
                db.save_user(target_email, u_name, u_role, [] if u_role == db.ROLE_DEPT else u_sites,
                             actor=current_user.email,
                             depts=[(s, d) for s in u_sites for d in u_depts] if u_role == db.ROLE_DEPT else [])
                st.session_state["flash"] = f"Đã lưu quyền cho {target_email}: {db.ROLE_LABELS[u_role]}" + (
                    f" – site: {', '.join(u_sites)}" if u_sites else "")
                st.rerun()
        if deleted and existing is not None:
            if removing_last_admin:
                st.error("Không thể xóa Admin cuối cùng của hệ thống.")
            elif existing["email"] == current_user.email:
                st.error("Không thể tự xóa tài khoản đang đăng nhập.")
            else:
                db.delete_user(existing["email"], actor=current_user.email)
                st.session_state["flash"] = f"Đã xóa tài khoản {existing['email']}"
                st.rerun()

    with a_progress:
        st.markdown(f"#### Tiến độ lập ngân sách năm {budget_year}")
        statuses = db.all_statuses(budget_year)
        all_lines = pd.DataFrame(db.load_lines(budget_year, site_codes))
        totals = all_lines.groupby("site_code")["total_budget"].agg(["count", "sum"]) if not all_lines.empty else pd.DataFrame()
        summary = db.site_summary(budget_year)
        it_by_site = {}
        for u in users:
            if u["role"] == db.ROLE_SITE_IT:
                for c in u["sites"]:
                    it_by_site.setdefault(c, []).append(u["email"])
        prog = pd.DataFrame([{
            "Site": site_label(c),
            "IT phụ trách": ", ".join(it_by_site.get(c, [])) or "⚠️ Chưa phân",
            "Trạng thái": db.STATUS_LABELS.get(statuses.get(c, {}).get("status", db.STATUS_DRAFT)),
            "Số hạng mục": int(totals.loc[c, "count"]) if c in totals.index else 0,
            "Tổng ngân sách (VNĐ)": float(totals.loc[c, "sum"]) if c in totals.index else 0.0,
            "Cập nhật dữ liệu lúc": summary.get(c, {}).get("last_at") or "",
            "Ghi chú duyệt": statuses.get(c, {}).get("note") or "",
        } for c in site_codes])
        st.dataframe(prog, use_container_width=True, hide_index=True,
                     column_config={"Tổng ngân sách (VNĐ)": st.column_config.NumberColumn(format="%d")})
        done = sum(1 for c in site_codes if statuses.get(c, {}).get("status") == db.STATUS_APPROVED)
        st.progress(done / len(site_codes) if site_codes else 0.0, text=f"Đã duyệt {done}/{len(site_codes)} site")
        st.caption("Để duyệt / trả lại: chọn site ở thanh bên trái, nút thao tác nằm ngay dưới tiêu đề trang.")

    with a_audit:
        st.dataframe(pd.DataFrame(db.recent_audit()), use_container_width=True, hide_index=True)

    with a_backup:
        import io as _io
        import json as _json
        import zipfile as _zip
        from master_data import MASTER_DATA_FILE
        st.markdown("##### CSDL đang dùng")
        try:
            _si = db.storage_info()
            if _si["durable"]:
                st.success(f"✅ **{_si['backend']}** – lưu bền ({_si.get('server', '')}) · máy chủ `{_si['location']}`")
            else:
                st.warning(f"⚠️ **{_si['backend']}** – file `{_si['location']}`. Trên Streamlit Cloud dữ liệu có thể mất khi app "
                           "khởi động lại; thêm mục [database] url vào Secrets để dùng PostgreSQL.")
            st.dataframe(pd.DataFrame([{"Bảng": k, "Số dòng": v} for k, v in _si["rows"].items()]),
                         hide_index=True, use_container_width=False)
        except Exception as _exc:
            st.error(f"❌ Không kết nối được CSDL: {_exc}")
        st.markdown("##### Sao lưu toàn bộ dữ liệu")
        st.caption("Gồm CSDL (người dùng, phân quyền, ngân sách các năm, định biên, nhật ký) và danh mục CNTT. "
                   "Khi chạy trên dịch vụ miễn phí không có ổ đĩa lưu bền (vd. Streamlit Community Cloud), "
                   "hãy tải bản sao lưu cuối mỗi ngày làm việc và khôi phục sau khi app khởi động lại.")
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w", _zip.ZIP_DEFLATED) as zf:
            zf.writestr("icost.db", db.backup_bytes())
            zf.writestr("master_data.json", _json.dumps(load_master_data(), ensure_ascii=False, indent=2))
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        if st.download_button("⬇️ Tải bản sao lưu (.zip)", data=buf.getvalue(), file_name=f"icost_backup_{stamp}.zip",
                              mime="application/zip", use_container_width=True):
            db.log(current_user.email, "backup_download", stamp)
        st.markdown("##### Khôi phục từ bản sao lưu")
        st.warning("Khôi phục sẽ GHI ĐÈ toàn bộ dữ liệu hiện tại bằng nội dung trong file sao lưu.")
        up_bk = st.file_uploader("Chọn file sao lưu (.zip)", type=["zip"], key="restore_zip")
        confirm_rs = st.checkbox("Tôi hiểu dữ liệu hiện tại sẽ bị thay thế", key="restore_confirm")
        if st.button("♻️ Khôi phục dữ liệu", disabled=not (up_bk and confirm_rs), type="primary"):
            try:
                with _zip.ZipFile(up_bk) as zf:
                    names = set(zf.namelist())
                    if "icost.db" not in names:
                        raise ValueError("File sao lưu thiếu icost.db")
                    db.restore_bytes(zf.read("icost.db"))
                    if "master_data.json" in names:
                        restored_master = _json.loads(zf.read("master_data.json").decode("utf-8"))
                        if not isinstance(restored_master, dict) or "standard_items" not in restored_master:
                            raise ValueError("master_data.json trong file sao lưu không hợp lệ")
                        save_master_data(restored_master)
                db.log(current_user.email, "backup_restore", up_bk.name)
                st.session_state["flash"] = f"Đã khôi phục dữ liệu từ {up_bk.name}."
                st.rerun()
            except Exception as exc:
                st.error(f"Không khôi phục được: {exc}")


if current_user.is_admin and admin_view == "👥 Phân quyền & Tiến độ":
    render_admin_page()
    st.stop()

tab_dash, tab_input, tab_quota, tab_infra, tab_excel, tab_depreciation, tab_master = st.tabs(tab_names)

# =====================================================================
# TAB 1: DASHBOARD
# =====================================================================
with tab_dash:
    if df_curr.empty:
        st.info("💡 Chưa có dữ liệu CapEx. Bạn hãy chuyển sang tab **'Lập & Nhập liệu CapEx'** hoặc bấm nút **'Nạp dữ liệu mẫu'** ở thanh bên trái!")
    else:
        # Calculate summary metrics
        total_capex = df_curr["total_budget"].sum() if "total_budget" in df_curr.columns else 0.0
        total_items = len(df_curr)
        total_qty = df_curr["quantity"].sum() if "quantity" in df_curr.columns else 0
        num_entities = df_curr["entity"].nunique() if "entity" in df_curr.columns else 0

        # Quarter disbursements
        q1_cols = [f"val_{m}" for m in months[0:3] if f"val_{m}" in df_curr.columns]
        q2_cols = [f"val_{m}" for m in months[3:6] if f"val_{m}" in df_curr.columns]
        q3_cols = [f"val_{m}" for m in months[6:9] if f"val_{m}" in df_curr.columns]
        q4_cols = [f"val_{m}" for m in months[9:12] if f"val_{m}" in df_curr.columns]

        q1_val = df_curr[q1_cols].sum().sum() if q1_cols else 0.0
        q2_val = df_curr[q2_cols].sum().sum() if q2_cols else 0.0
        q3_val = df_curr[q3_cols].sum().sum() if q3_cols else 0.0
        q4_val = df_curr[q4_cols].sum().sum() if q4_cols else 0.0

        # Top entity / cat1
        top_cat = df_curr.groupby("asset_cat1")["total_budget"].sum().idxmax() if "asset_cat1" in df_curr.columns and not df_curr.empty else "N/A"
        top_cat_val = df_curr.groupby("asset_cat1")["total_budget"].sum().max() if "asset_cat1" in df_curr.columns and not df_curr.empty else 0

        # KPI Row
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-title">Tổng Ngân sách CapEx</div>
                <div class="kpi-value">{total_capex/1e9:,.2f} <span style="font-size:16px;font-weight:500;">tỷ VNĐ</span></div>
                <div class="kpi-sub">{total_capex:,.0f} VNĐ</div>
            </div>
            """, unsafe_allow_html=True)

        with k2:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-title">Tổng Hạng mục Đầu tư</div>
                <div class="kpi-value">{total_items} <span style="font-size:16px;font-weight:500;">mục</span></div>
                <div class="kpi-sub">Tổng số lượng tài sản: {int(total_qty):,} cái/bộ</div>
            </div>
            """, unsafe_allow_html=True)

        with k3:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-title">Nhóm Chiếm Tỷ trọng Cao Nhất</div>
                <div class="kpi-value" style="font-size:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{_html.escape(str(top_cat))}</div>
                <div class="kpi-sub">{top_cat_val/1e9:,.2f} tỷ VNĐ ({(top_cat_val/total_capex*100 if total_capex>0 else 0):.1f}%)</div>
            </div>
            """, unsafe_allow_html=True)

        with k4:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-title">Phạm vi Pháp nhân</div>
                <div class="kpi-value">{num_entities} <span style="font-size:16px;font-weight:500;">đơn vị</span></div>
                <div class="kpi-sub">DDC, DD2, DD3, DMT, DNS, DVT...</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

        # Filters Row
        with st.expander("🔍 Bộ lọc Phân tích Trực quan", expanded=False):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                filter_entity = st.multiselect("Lọc theo Pháp nhân", options=sorted(df_curr["entity"].dropna().unique().tolist()))
            with fc2:
                filter_cat1 = st.multiselect("Lọc theo Loại tài sản cấp 1", options=sorted(df_curr["asset_cat1"].dropna().unique().tolist()))
            with fc3:
                filter_site = st.multiselect("Lọc theo Vị trí / Nhà máy", options=sorted(df_curr["location"].dropna().unique().tolist()))

        df_filtered = df_curr.copy()
        if filter_entity:
            df_filtered = df_filtered[df_filtered["entity"].isin(filter_entity)]
        if filter_cat1:
            df_filtered = df_filtered[df_filtered["asset_cat1"].isin(filter_cat1)]
        if filter_site:
            df_filtered = df_filtered[df_filtered["location"].isin(filter_site)]

        # CHARTS ROW 1: Entity & Asset Category
        c1, c2 = st.columns([1, 1])

        with c1:
            st.markdown("##### 🏢 Phân bổ Ngân sách theo Pháp nhân")
            df_ent = df_filtered.groupby("entity")["total_budget"].sum().reset_index()
            fig_ent = px.pie(
                df_ent,
                names="entity",
                values="total_budget",
                hole=0.45,
                color_discrete_sequence=px.colors.qualitative.Prism
            )
            fig_ent.update_traces(
                textposition='inside',
                textinfo='percent+label',
                hovertemplate="<b>%{label}</b><br>Ngân sách: %{value:,.0f} VNĐ<br>Tỷ lệ: %{percent}"
            )
            fig_ent.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=320)
            st.plotly_chart(fig_ent, use_container_width=True)

        with c2:
            st.markdown("##### 🏗️ Phân bổ theo Loại Tài sản Cấp 1")
            df_cat = df_filtered.groupby("asset_cat1")["total_budget"].sum().reset_index().sort_values(by="total_budget", ascending=True)
            df_cat["budget_bil"] = df_cat["total_budget"] / 1e9
            fig_cat = px.bar(
                df_cat,
                x="budget_bil",
                y="asset_cat1",
                orientation='h',
                labels={"budget_bil": "Ngân sách (Tỷ VNĐ)", "asset_cat1": "Loại tài sản"},
                color="budget_bil",
                color_continuous_scale="Blues"
            )
            fig_cat.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=320, coloraxis_showscale=False)
            fig_cat.update_traces(hovertemplate="<b>%{y}</b><br>Ngân sách: %{x:.2f} tỷ VNĐ")
            st.plotly_chart(fig_cat, use_container_width=True)

        # CHARTS ROW 2: Monthly Disbursement Cash Flow & Site
        c3, c4 = st.columns([1.3, 1])

        with c3:
            st.markdown("##### 📅 Dòng tiền Giải ngân Phân kỳ 12 Tháng")
            val_cols = [f"val_{m}" for m in months if f"val_{m}" in df_filtered.columns]
            monthly_sums = [df_filtered[c].sum() / 1e9 for c in val_cols]
            cum_sums = np.cumsum(monthly_sums)

            fig_cash = go.Figure()
            fig_cash.add_trace(go.Bar(
                x=months,
                y=monthly_sums,
                name="Giải ngân tháng (Tỷ VNĐ)",
                marker_color="#1E4E8C",
                hovertemplate="Tháng: %{x}<br>Giải ngân: %{y:.2f} tỷ VNĐ"
            ))
            fig_cash.add_trace(go.Scatter(
                x=months,
                y=cum_sums,
                name="Lũy kế giải ngân (Tỷ VNĐ)",
                mode="lines+markers",
                line=dict(color="#E11D48", width=3),
                marker=dict(size=6),
                yaxis="y2",
                hovertemplate="Lũy kế đến %{x}: %{y:.2f} tỷ VNĐ"
            ))
            fig_cash.update_layout(
                margin=dict(t=20, b=20, l=20, r=20),
                height=340,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                yaxis=dict(title="Tháng (Tỷ VNĐ)"),
                yaxis2=dict(title="Lũy kế (Tỷ VNĐ)", overlaying="y", side="right")
            )
            st.plotly_chart(fig_cash, use_container_width=True)

        with c4:
            st.markdown("##### 📍 Phân bổ theo Vị trí / Nhà máy")
            df_loc = df_filtered.groupby("location")["total_budget"].sum().reset_index().sort_values(by="total_budget", ascending=False)
            df_loc["budget_bil"] = df_loc["total_budget"] / 1e9
            fig_site = px.pie(
                df_loc,
                names="location",
                values="budget_bil",
                color_discrete_sequence=px.colors.qualitative.Safe
            )
            fig_site.update_traces(
                textposition='inside',
                textinfo='percent+label',
                hovertemplate="<b>%{label}</b><br>Ngân sách: %{value:.2f} tỷ VNĐ"
            )
            fig_site.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=340)
            st.plotly_chart(fig_site, use_container_width=True)

        # CƠ CẤU: trang bị theo định biên / hạ tầng dùng chung / phát sinh mới
        if "need_type" in df_site.columns and not df_site.empty:
            st.markdown("##### 🧭 Cơ cấu ngân sách CNTT")
            nt = df_site["need_type"].fillna("Chưa phân loại")
            cc = st.columns(4)
            for col_box, (lbl, key) in zip(cc, [("Trang bị theo định biên", qt.NEED_QUOTA), ("Hạ tầng dùng chung", qt.NEED_INFRA),
                                                ("Phát sinh mới", qt.NEED_NEW), ("Chưa phân loại", "Chưa phân loại")]):
                col_box.metric(lbl, format_vnd_short(df_site.loc[nt == key, "total_budget"].sum()) + " VNĐ")

        # TỔNG HỢP THEO PHÒNG BAN (toàn bộ phòng ban trong phạm vi site)
        if "dept_proposing" in df_site.columns and not df_site.empty:
            st.markdown("##### 🏢 Tổng hợp Ngân sách theo Phòng ban")
            canon = {dept_key(d): d for d in dept_list}
            df_dept = df_site.assign(
                dept=df_site["dept_proposing"].map(lambda d: canon.get(dept_key(d), d) if str(d or "").strip() else "(Chưa ghi phòng ban)"),
                it_group=df_site["it_group"].fillna("(Chưa phân nhóm)") if "it_group" in df_site.columns else "(Chưa phân nhóm)")
            quarters = {"Q1 (T10-T12)": months[0:3], "Q2 (T1-T3)": months[3:6], "Q3 (T4-T6)": months[6:9], "Q4 (T7-T9)": months[9:12]}
            for q, ms in quarters.items():
                cols = [f"val_{m}" for m in ms if f"val_{m}" in df_dept.columns]
                df_dept[q] = df_dept[cols].sum(axis=1) if cols else 0.0
            d_tab1, d_tab2, d_tab3, d_tab4 = st.tabs(["Phòng ban × Quý giải ngân", "Phòng ban × Nhóm CNTT",
                                                      "Phòng ban × CAPEX/CCDC/OPEX", "Phòng ban × Định biên / Phát sinh"])
            money = st.column_config.NumberColumn(format="%d")

            def _with_total(t: pd.DataFrame) -> pd.DataFrame:
                t = t.sort_values("Tổng ngân sách", ascending=False)
                t.loc["TỔNG CỘNG"] = t.sum(numeric_only=True)
                return t

            with d_tab1:
                t1 = df_dept.groupby("dept").agg(**{"Số hạng mục": ("dept", "size"), "Tổng ngân sách": ("total_budget", "sum")},
                                                 **{q: (q, "sum") for q in quarters})
                t1["Tỷ trọng"] = t1["Tổng ngân sách"] / t1["Tổng ngân sách"].sum() if t1["Tổng ngân sách"].sum() else 0.0
                t1 = _with_total(t1)
                st.dataframe(t1, use_container_width=True,
                             column_config={**{c: money for c in ["Tổng ngân sách", *quarters]},
                                            "Tỷ trọng": st.column_config.ProgressColumn(format="%.1f%%", min_value=0.0, max_value=1.0)})
            with d_tab2:
                t2 = df_dept.pivot_table(index="dept", columns="it_group", values="total_budget", aggfunc="sum", fill_value=0)
                t2["Tổng ngân sách"] = t2.sum(axis=1)
                t2 = _with_total(t2)
                st.dataframe(t2, use_container_width=True, column_config={c: money for c in t2.columns})
            with d_tab3:
                ct = df_dept.get("capex_type", pd.Series(index=df_dept.index, dtype=object)).fillna("Chưa phân loại")
                t3 = df_dept.assign(capex_type=ct).pivot_table(index="dept", columns="capex_type", values="total_budget",
                                                               aggfunc="sum", fill_value=0)
                t3["Tổng ngân sách"] = t3.sum(axis=1)
                t3 = _with_total(t3)
                st.dataframe(t3, use_container_width=True, column_config={c: money for c in t3.columns})
            with d_tab4:
                kind_s = df_dept["item_kind"] if "item_kind" in df_dept.columns else pd.Series(index=df_dept.index, dtype=object)
                kind_grp = kind_s.map(lambda k: "Phần mềm" if str(k).startswith("software") else ("Dịch vụ" if k == "service" else
                                                                                                 ("Thiết bị" if isinstance(k, str) and k else "Chưa phân loại")))
                need_s = df_dept["need_type"] if "need_type" in df_dept.columns else pd.Series(index=df_dept.index, dtype=object)
                t4 = df_dept.assign(col=need_s.fillna("Chưa phân loại") + " – " + kind_grp).pivot_table(
                    index="dept", columns="col", values="total_budget", aggfunc="sum", fill_value=0)
                t4 = t4[sorted(t4.columns)]
                t4["Tổng ngân sách"] = t4.sum(axis=1)
                t4 = _with_total(t4)
                st.dataframe(t4, use_container_width=True, column_config={c: money for c in t4.columns})
                st.caption("Định biên: sinh từ định biên nhân sự × bộ trang bị tiêu chuẩn (tab 'Định biên & Nhu cầu'). "
                           "Phát sinh mới: nhu cầu ngoài định biên, có lý do. 'Chưa phân loại': dữ liệu cũ/nhập Excel.")
            st.caption("Bảng tổng hợp tính trên toàn bộ phòng ban của phạm vi site đang chọn (không áp bộ lọc phòng ban/biểu đồ).")

        # TOP 10 LARGEST CAPEX ITEMS
        # CHARTS ROW 3: Nhóm CNTT & phân loại hạch toán
        if "it_group" in df_filtered.columns:
            c5, c6 = st.columns([1.4, 1])
            with c5:
                st.markdown("##### 💻 Ngân sách theo Nhóm CNTT")
                df_grp = (df_filtered.assign(it_group=df_filtered["it_group"].fillna("(Chưa phân nhóm)"))
                          .groupby("it_group")["total_budget"].sum().reset_index().sort_values("total_budget"))
                df_grp["budget_bil"] = df_grp["total_budget"] / 1e9
                fig_grp = px.bar(df_grp, x="budget_bil", y="it_group", orientation="h",
                                 labels={"budget_bil": "Ngân sách (Tỷ VNĐ)", "it_group": "Nhóm CNTT"},
                                 color_discrete_sequence=["#1E4E8C"])
                fig_grp.update_traces(hovertemplate="<b>%{y}</b><br>Ngân sách: %{x:.2f} tỷ VNĐ")
                fig_grp.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=360)
                st.plotly_chart(fig_grp, use_container_width=True)
            with c6:
                st.markdown("##### 🧾 Phân loại Hạch toán")
                df_acc = (df_filtered.assign(capex_type=df_filtered.get("capex_type", pd.Series(dtype=str)).fillna("Chưa phân loại"))
                          .groupby("capex_type")["total_budget"].sum().reset_index())
                fig_acc = px.pie(df_acc, names="capex_type", values="total_budget", hole=0.45,
                                 color="capex_type",
                                 color_discrete_map={"CAPEX": "#0F2C59", "CCDC": "#3B82F6", "OPEX": "#F59E0B", "Chưa phân loại": "#CBD5E1"})
                fig_acc.update_traces(textinfo="percent+label", hovertemplate="<b>%{label}</b><br>%{value:,.0f} VNĐ<br>%{percent}")
                fig_acc.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=360, showlegend=False)
                st.plotly_chart(fig_acc, use_container_width=True)
                st.caption("CAPEX: TSCĐ (≥ 30tr/đơn vị) · CCDC: phân bổ dần TK 242 · OPEX: thuê bao, dịch vụ")

        st.markdown("##### 🏆 Top 10 Hạng mục Ngân sách Đầu tư Lớn nhất")
        top_items = df_filtered.sort_values(by="total_budget", ascending=False).head(10)[
            ["stt", "item_name", "entity", "location", "asset_cat1", "quantity", "unit_price", "total_budget", "project_code"]
        ].copy()

        top_items["unit_price"] = top_items["unit_price"].apply(format_vnd)
        top_items["total_budget"] = top_items["total_budget"].apply(format_vnd)
        top_items.columns = ["STT", "Tên Hạng mục / Tài sản", "Pháp nhân", "Vị trí", "Loại TS", "SL", "Đơn giá", "Tổng ngân sách", "Mã công trình"]

        st.dataframe(top_items, use_container_width=True, hide_index=True)


# =====================================================================
# TAB 2: LẬP & NHẬP LIỆU CAPEX
# =====================================================================
with tab_input:
    st.markdown("### 📝 Biểu mẫu Lập & Nhập liệu Ngân sách CAPEX")

    if selected_site == ALL_SITES:
        st.info("🌐 Đang xem tổng hợp nhiều site (chỉ đọc). Chọn một site cụ thể ở thanh bên trái để nhập liệu.")
    elif not can_edit:
        st.info("🔒 Bạn không có quyền chỉnh sửa ngân sách site này ở trạng thái hiện tại (chỉ xem).")

    # 1. Bộ chọn Phòng ban & Thẻ thông tin tiến độ
    col_d1, col_d2 = st.columns([1.6, 2.4])
    with col_d1:
        dept_options_input = [d for d in dept_list if d != ALL_DEPTS]
        default_d_idx = 0
        if selected_dept != ALL_DEPTS and selected_dept in dept_options_input:
            default_d_idx = dept_options_input.index(selected_dept)

        active_dept = st.selectbox(
            "🏢 Phòng ban lập ngân sách:",
            dept_options_input,
            index=default_d_idx,
            key="active_dept_selector",
            help="Chọn phòng ban cần trang bị thiết bị, phần mềm và dịch vụ CNTT"
        )

    dept_rows_now = df_site[df_site["dept_proposing"].map(dept_key) == dept_key(active_dept)] if not df_site.empty and "dept_proposing" in df_site.columns else pd.DataFrame()
    dept_cnt = len(dept_rows_now)
    dept_sum = dept_rows_now["total_budget"].sum() if not dept_rows_now.empty and "total_budget" in dept_rows_now.columns else 0.0
    _ctype = dept_rows_now["capex_type"] if "capex_type" in dept_rows_now.columns else pd.Series(index=dept_rows_now.index, dtype=object)
    dept_cx = dept_rows_now.loc[_ctype == "CAPEX", "total_budget"].sum() if not dept_rows_now.empty else 0.0
    dept_cc = dept_rows_now.loc[_ctype == "CCDC", "total_budget"].sum() if not dept_rows_now.empty else 0.0
    dept_op = dept_rows_now.loc[_ctype == "OPEX", "total_budget"].sum() if not dept_rows_now.empty else 0.0

    with col_d2:
        st.markdown(f"""
        <div style="background:#F8FAFC; border:1px solid #CBD5E1; border-radius:10px; padding:10px 16px; margin-top:2px;">
            <div style="font-size:13px; font-weight:700; color:#0F2C59;">
                🏢 Phòng ban: <span style="color:#1D4ED8; font-size:14px;">{_html.escape(active_dept)}</span>
                <span style="font-weight:400; color:#64748B; margin-left:8px;">({site_label(selected_site)})</span>
            </div>
            <div style="font-size:12px; color:#475569; margin-top:4px;">
                Đã lập: <b>{dept_cnt}</b> hạng mục · Tổng ngân sách: <b style="color:#0F2C59; font-size:13px;">{format_vnd(dept_sum)}</b>
                <span style="margin-left:8px; color:#64748B;">(TSCĐ: {format_vnd_short(dept_cx)} | CCDC: {format_vnd_short(dept_cc)} | OPEX: {format_vnd_short(dept_op)})</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    if can_edit:
        # Form nhập liệu thuận tiện: 2 phương thức nhập
        in_mode_tab1, in_mode_tab2 = st.tabs([
            "🛒 CHỌN NHANH THEO DANH MỤC CNTT (Nhiều thiết bị cùng lúc - Tiện lợi nhất)",
            "✍️ THÊM CHI TIẾT 1 HẠNG MỤC (Tùy chỉnh riêng)"
        ])

        # =========================================================
        # CHẾ ĐỘ 1: CHỌN NHANH THEO DANH MỤC CNTT (MULTI-ITEM BATCH)
        # =========================================================
        with in_mode_tab1:
            st.markdown("##### 🛒 Chọn nhanh danh sách thiết bị cần trang bị cho phòng ban")
            st.caption("Chọn nhóm CNTT, nhập số lượng cần mua vào cột 'Số lượng' (món không mua để 0), rồi bấm 'Thêm vào ngân sách' để tự động lập toàn bộ chỉ với 1 click!")

            catalog_all = master.get("standard_items", [])
            grp_list = it_groups(master)

            b_col1, b_col2, b_col3 = st.columns([1.5, 1, 1])
            with b_col1:
                b_grp_label = st.selectbox(
                    "1. Chọn Nhóm CNTT:",
                    [f"{g['code']}. {g['name']}" for g in grp_list],
                    key="batch_grp_picker"
                )
                b_grp_code = b_grp_label.split(".")[0].strip() if b_grp_label else "IT01"

            with b_col2:
                b_month = st.selectbox(
                    "2. Tháng đưa vào sử dụng:",
                    months,
                    index=3 if len(months) > 3 else 0,
                    key="batch_month_picker",
                    help="Toàn bộ thiết bị được chọn sẽ giải ngân 100% vào tháng này"
                )

            with b_col3:
                b_need_type = st.radio(
                    "3. Loại nhu cầu:",
                    qt.NEED_TYPES,
                    index=1,
                    horizontal=True,
                    key="batch_need_type_picker"
                )

            b_reason = ""
            if b_need_type == qt.NEED_NEW:
                b_reason = st.text_input("Lý do phát sinh / căn cứ trang bị:",
                                         placeholder="VD: Tuyển dụng nhân sự mới; phục vụ dự án X...",
                                         key="batch_reason_input")

            # Lấy danh sách thiết bị thuộc nhóm
            grp_items = [it for it in catalog_all if it.get("group") == b_grp_code or str(it.get("group", "")).startswith(b_grp_code)]

            if not grp_items:
                st.warning(f"Không có hạng mục nào thuộc nhóm {b_grp_label}.")
            else:
                batch_rows = []
                for it in grp_items:
                    cls_prev = classify_item(it, master)
                    acc_lbl, capex_tg = accounting_class(cls_prev.get("item_kind", KIND_HARDWARE), float(it.get("price", 0)), master)
                    batch_rows.append({
                        "Mã": it.get("code", ""),
                        "Tên thiết bị / Hạng mục": it["name"],
                        "ĐVT": it.get("unit", "Cái"),
                        "Giá tham chiếu (VNĐ)": float(it.get("price", 0)),
                        "Phân loại": f"{capex_tg}",
                        "Số lượng": 0,
                        "Ghi chú / Đối tượng": ""
                    })

                df_batch_grid = pd.DataFrame(batch_rows)
                edited_batch = st.data_editor(
                    df_batch_grid,
                    key=f"batch_editor_{b_grp_code}_{st.session_state.get('batch_ver', 0)}",
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Mã": st.column_config.TextColumn("Mã", disabled=True, width="small"),
                        "Tên thiết bị / Hạng mục": st.column_config.TextColumn("Tên thiết bị / Hạng mục", disabled=True, width="large"),
                        "ĐVT": st.column_config.TextColumn("ĐVT", disabled=True, width="small"),
                        "Giá tham chiếu (VNĐ)": st.column_config.NumberColumn("Đơn giá chuẩn (VNĐ)", disabled=True, format="%d"),
                        "Phân loại": st.column_config.TextColumn("Phân loại", disabled=True, width="small"),
                        "Số lượng": st.column_config.NumberColumn("Số lượng cần mua", min_value=0, step=1, format="%d", required=True),
                        "Ghi chú / Đối tượng": st.column_config.TextColumn("Ghi chú / Đối tượng sử dụng", width="medium")
                    }
                )

                selected_batch = edited_batch[edited_batch["Số lượng"] > 0]
                num_sel = len(selected_batch)
                total_batch_cost = (selected_batch["Số lượng"] * selected_batch["Giá tham chiếu (VNĐ)"]).sum() if num_sel > 0 else 0

                b_sub1, b_sub2 = st.columns([2, 1.2])
                with b_sub1:
                    st.markdown(f"Đã chọn: **{num_sel}** thiết bị | Tổng thành tiền dự tính: <b style='color:#0F2C59; font-size:16px;'>{format_vnd(total_batch_cost)}</b>", unsafe_allow_html=True)
                with b_sub2:
                    if st.button(f"➕ Thêm {num_sel} mục vào {active_dept}", type="primary", use_container_width=True, disabled=num_sel == 0):
                        if b_need_type == qt.NEED_NEW and not b_reason.strip():
                            st.error("Vui lòng ghi rõ 'Lý do phát sinh / căn cứ trang bị' trước khi thêm!")
                        else:
                            ent_names = [e["name"] for e in master.get("entities", [])]
                            target_ent = ent_names[0] if ent_names else "DDC"
                            target_div = master.get("divisions", ["Khối CNTT"])[0]
                            target_loc = SITE_NAME.get(selected_site, selected_site)
                            d_now = datetime.date.today().strftime("%Y-%m-%d")

                            new_items_list = []
                            for _, r_it in selected_batch.iterrows():
                                it_name = r_it["Tên thiết bị / Hạng mục"]
                                cat_it = next((x for x in catalog_all if x["name"] == it_name), None)
                                q = int(r_it["Số lượng"])
                                p = float(r_it["Giá tham chiếu (VNĐ)"])
                                note_txt = str(r_it.get("Ghi chú / Đối tượng", "")).strip()

                                row_dict = {
                                    "entity": target_ent,
                                    "division": target_div,
                                    "dept_proposing": active_dept,
                                    "dept_using": active_dept,
                                    "location": target_loc,
                                    "item_name": it_name,
                                    "detail_work": note_txt,
                                    "supplier": "Thạch Anh",
                                    "quantity": q,
                                    "unit_price": p,
                                    "contract_date": d_now,
                                    "completion_date": d_now,
                                    "handover_date": d_now,
                                    "need_type": b_need_type,
                                    "need_reason": b_reason if b_need_type == qt.NEED_NEW else "",
                                }
                                for m in months:
                                    row_dict[f"pct_{m}"] = 1.0 if m == b_month else 0.0

                                if cat_it:
                                    apply_it_catalog(row_dict, master, item=cat_it, invest_type="Mua mới")
                                else:
                                    row_dict.update({"it_group": b_grp_label, "invest_type": "Mua mới"})

                                calc_row = calculate_row(row_dict, months=months, year_code=year_code, master=master)
                                new_items_list.append(calc_row)

                            updated_df_all = pd.concat([df_site, pd.DataFrame(new_items_list)], ignore_index=True)
                            save_site(updated_df_all.reset_index(drop=True), selected_site)
                            st.session_state["batch_ver"] = st.session_state.get("batch_ver", 0) + 1
                            st.session_state["flash"] = f"🎉 Đã thêm thành công {len(new_items_list)} hạng mục vào ngân sách phòng ban '{active_dept}' (Tổng tiền: {format_vnd(total_batch_cost)})!"
                            st.rerun()

        # =========================================================
        # CHẾ ĐỘ 2: THÊM CHI TIẾT 1 HẠNG MỤC (SINGLE ITEM FORM)
        # =========================================================
        with in_mode_tab2:
            st.markdown("##### ✍️ Thêm chi tiết từng hạng mục (tùy chỉnh riêng phân kỳ, nhà cung cấp, cấu hình)")
            catalog = master.get("standard_items", [])
            ALL_GROUPS = "(Tất cả nhóm)"
            OTHER_ITEM = "-- Hạng mục ngoài danh mục (tự nhập) --"
            pc1, pc2, pc3 = st.columns([1.3, 2.2, 1])
            pick_group = pc1.selectbox("Nhóm CNTT", [ALL_GROUPS] + [f"{g['code']}. {g['name']}" for g in it_groups(master)], key="single_grp_pick")
            group_items = [it for it in catalog if pick_group == ALL_GROUPS or pick_group.startswith(f"{it.get('group')}.")]
            item_labels = {f"{it.get('code', '')} · {it['name']}": it for it in group_items}
            pick_item = pc2.selectbox("Hạng mục", [OTHER_ITEM] + list(item_labels), key="single_it_pick")
            cat_item = item_labels.get(pick_item)
            kind_default = (cat_item or {}).get("kind") or KIND_HARDWARE
            invest_type = pc3.selectbox("Hình thức đầu tư", INVEST_TYPES, key=f"invest_single_{pick_item}",
                                        index=INVEST_TYPES.index(default_invest_type(kind_default)))
            preview = {"item_name": cat_item["name"]} if cat_item else {}
            if cat_item:
                apply_it_catalog(preview, master, item=cat_item, invest_type=invest_type)
                acc_label, capex_tag = accounting_class(preview["item_kind"], float(cat_item.get("price", 0)), master)
                st.caption(f"📦 **{preview['it_group']}** · Loại: {it_kinds(master).get(preview['item_kind'], '')} · "
                           f"ĐVT: {preview.get('unit', '')} · Giá tham chiếu: {format_vnd(cat_item.get('price', 0))} · "
                           f"Hạch toán: **{acc_label}** ({capex_tag})"
                           + (f"  \n⚠️ {cat_item['note']}" if cat_item.get("note") else ""))
            wkey = (cat_item or {}).get("code", "other") + "_" + invest_type

            with st.form("form_add_single_item", clear_on_submit=False):
                f_col1, f_col2, f_col3 = st.columns(3)

                with f_col1:
                    st.markdown("##### 1. Đơn vị & Địa điểm")
                    ent_names = [e["name"] for e in master.get("entities", [])]
                    f_entity = st.selectbox("(*) Pháp nhân sở hữu", ent_names, index=0)
                    div_options = master.get("divisions", ["Khối Sản Xuất", "Khối CNTT"])
                    f_division = st.selectbox("Khối", div_options)
                    f_dept_prop_val = st.text_input("(*) Phòng ban đề xuất", value=active_dept, disabled=True)
                    dept_options = master.get("departments", ["Phòng CNTT", "Phòng Cơ điện"])
                    f_dept_using = st.selectbox("(*) Phòng ban sử dụng TS", dept_options,
                                                index=dept_options.index(active_dept) if active_dept in dept_options else 0)
                    f_location = SITE_NAME.get(selected_site, selected_site)
                    st.text_input("(*) Vị trí / Nhà máy", value=f_location, disabled=True)

                with f_col2:
                    st.markdown("##### 2. Thông tin Tài sản")
                    def _idx(options, value, fallback=0):
                        return options.index(value) if value in options else fallback

                    cat1_names = [c["name"] for c in master.get("asset_cat1", [])]
                    f_cat1 = st.selectbox("(*) Loại tài sản cấp 1", cat1_names, key=f"cat1_{wkey}",
                                          index=_idx(cat1_names, preview.get("asset_cat1", "D. Thiết bị, dụng cụ quản lý")))
                    cat2_names = master.get("asset_cat2", [])
                    f_cat2 = st.selectbox("(*) Loại tài sản cấp 2", cat2_names, key=f"cat2_{wkey}",
                                          index=_idx(cat2_names, preview.get("asset_cat2", "D1. TBQL: Mua mới")))
                    kind_keys = list(it_kinds(master))
                    f_kind = st.selectbox("(*) Loại hạng mục CNTT", kind_keys, key=f"kind_{wkey}",
                                          index=_idx(kind_keys, kind_default), format_func=lambda k: it_kinds(master)[k],
                                          disabled=cat_item is not None)
                    default_name = cat_item["name"] if cat_item else ""
                    default_price = float(cat_item.get("price", 0)) if cat_item else 0.0
                    f_item_name = st.text_input("(*) Tên hạng mục chính / Tài sản", value=default_name, key=f"name_{wkey}")
                    f_detail = st.text_input("Công việc chi tiết (Nếu có)", value="")
                    f_need_type = st.radio("(*) Loại nhu cầu", qt.NEED_TYPES, horizontal=True,
                                           index=2 if cat_item and item_scope(cat_item, master) == SCOPE_SHARED else 1)
                    f_need_reason = st.text_input("Lý do phát sinh / căn cứ", value="",
                                                  placeholder="VD: Dự án mới X cần thêm 3 license Tekla; tuyển mới 2 kỹ sư...")
                    f_supplier = st.text_input("Nhà cung cấp (Nếu có)", value="Thạch Anh")

                with f_col3:
                    st.markdown("##### 3. Số lượng & Đơn giá")
                    unit_lbl = f" ({preview['unit']})" if preview.get("unit") else ""
                    f_qty = st.number_input(f"(*) Số lượng{unit_lbl}", min_value=1, value=1, step=1)
                    f_price = st.number_input("(*) Đơn giá (VNĐ)", min_value=0.0, value=default_price, step=1000000.0,
                                              format="%.0f", key=f"price_{wkey}")
                    calc_total = f_qty * f_price
                    st.metric("Tổng ngân sách (chưa VAT)", format_vnd(calc_total))

                    st.markdown("##### 4. Kế hoạch Tiến độ")
                    fd1, fd2 = st.columns(2)
                    with fd1:
                        f_date_contract = st.date_input("Ký hợp đồng", value=datetime.date.today())
                    with fd2:
                        f_date_handover = st.date_input("Bàn giao sử dụng", value=datetime.date.today() + datetime.timedelta(days=60))

                st.markdown("---")
                st.markdown("##### 5. Phân kỳ Đầu tư theo Tỷ lệ (%) 12 Tháng (Tổng các tháng phải đạt 100%)")

                alloc_type = st.radio(
                    "Phương thức phân bổ phân kỳ:",
                    ["Giải ngân 100% vào tháng nghiệm thu", "Chia đều 12 tháng", "Tự nhập tỷ lệ từng tháng"],
                    horizontal=True,
                    key="single_alloc_type"
                )

                pct_inputs = {}
                if alloc_type == "Giải ngân 100% vào tháng nghiệm thu":
                    target_m = f"T{f_date_handover.month} {f_date_handover.year}"
                    if target_m not in months:
                        target_m = months[0]
                    for m in months:
                        pct_inputs[m] = 1.0 if m == target_m else 0.0
                    st.info(f"👉 Toàn bộ 100% giải ngân vào **{target_m}**")
                elif alloc_type == "Chia đều 12 tháng":
                    for m in months:
                        pct_inputs[m] = round(1.0 / 12.0, 4)
                    st.info("👉 Chia đều 8.33% cho mỗi tháng")
                else:
                    m_cols1 = st.columns(6)
                    m_cols2 = st.columns(6)
                    for i, m in enumerate(months[:6]):
                        with m_cols1[i]:
                            pct_inputs[m] = st.number_input(f"{m} (%)", min_value=0.0, max_value=100.0, value=0.0, step=5.0, key=f"p1_{m}") / 100.0
                    for i, m in enumerate(months[6:]):
                        with m_cols2[i]:
                            pct_inputs[m] = st.number_input(f"{m} (%)", min_value=0.0, max_value=100.0, value=0.0, step=5.0, key=f"p2_{m}") / 100.0

                sum_pct = sum(pct_inputs.values())
                if abs(sum_pct - 1.0) < 0.01:
                    st.success(f"✅ Tổng tỷ lệ phân kỳ: {sum_pct*100:.1f}% (Hợp lệ)")
                else:
                    st.warning(f"⚠️ Tổng tỷ lệ phân kỳ: {sum_pct*100:.1f}%. Lưu ý: Tổng phân kỳ cần đạt 100%!")

                st.markdown("##### 6. Phân loại Kế toán & Chi phí")
                cf1, cf2 = st.columns(2)
                with cf1:
                    lv1_opts = master.get("cost_lv1", [])
                    f_cost_lv1 = st.selectbox("Loại chi phí cấp 1", lv1_opts, key=f"lv1_{wkey}",
                                              index=_idx(lv1_opts, preview.get("cost_lv1", "04. Chi phí MMTB"), 3 if len(lv1_opts) > 3 else 0))
                with cf2:
                    lv2_opts = master.get("cost_lv2", [])
                    f_cost_lv2 = st.selectbox("Loại chi phí cấp 2", lv2_opts, key=f"lv2_{wkey}",
                                              index=_idx(lv2_opts, preview.get("cost_lv2", "04.03. Thiết bị quản lý - Thiết bị CNTT")))

                btn_submit = st.form_submit_button("💾 THÊM HẠNG MỤC VÀO PHÒNG BAN", use_container_width=True)

                if btn_submit:
                    if not f_item_name.strip():
                        st.error("Vui lòng nhập Tên hạng mục / Tài sản!")
                    elif f_need_type in qt.NEED_WITH_REASON and not f_need_reason.strip():
                        st.error(f"Hạng mục '{f_need_type}' cần ghi Lý do / căn cứ!")
                    elif cat_item and item_scope(cat_item, master) == SCOPE_SHARED and dept_key(active_dept) != dept_key(item_owner(cat_item, master)):
                        st.error(f"'{cat_item['name']}' là hạ tầng CNTT dùng chung, do {item_owner(cat_item, master)} đề xuất ngân sách. "
                                 "Vui lòng nhập ở tab '🏗️ Hạ tầng CNTT dùng chung'.")
                    else:
                        new_row = {
                            "entity": f_entity,
                            "division": f_division,
                            "dept_proposing": active_dept,
                            "dept_using": f_dept_using,
                            "location": f_location,
                            "asset_cat1": f_cat1,
                            "asset_cat2": f_cat2,
                            "item_name": f_item_name,
                            "detail_work": f_detail,
                            "supplier": f_supplier,
                            "quantity": f_qty,
                            "unit_price": f_price,
                            "contract_date": f_date_contract.strftime("%Y-%m-%d"),
                            "completion_date": f_date_contract.strftime("%Y-%m-%d"),
                            "handover_date": f_date_handover.strftime("%Y-%m-%d"),
                            "cost_lv1": f_cost_lv1,
                            "cost_lv2": f_cost_lv2,
                        }
                        for m in months:
                            new_row[f"pct_{m}"] = pct_inputs.get(m, 0.0)
                        if cat_item:
                            apply_it_catalog(new_row, master, item=cat_item, invest_type=invest_type)
                        else:
                            new_row.update({"it_group": "(Ngoài danh mục)", "item_kind": f_kind, "invest_type": invest_type})
                        new_row.update({"item_name": f_item_name.strip(), "asset_cat1": f_cat1, "asset_cat2": f_cat2,
                                        "cost_lv1": f_cost_lv1, "cost_lv2": f_cost_lv2,
                                        "need_type": f_need_type, "need_reason": f_need_reason.strip()})

                        calculated = calculate_row(new_row, months=months, year_code=year_code, master=master)
                        updated_site_df = pd.concat([df_site, pd.DataFrame([calculated])], ignore_index=True)
                        save_site(updated_site_df.reset_index(drop=True), selected_site)
                        st.session_state["flash"] = f"✅ Đã thêm hạng mục '{f_item_name}' vào phòng ban '{active_dept}' thành công! (Mã: {calculated['item_code']})"
                        st.rerun()

    # Bảng tính tương tác (Interactive Data Table Grid)
    # Bảng tính tương tác (Interactive Data Table Grid)
    grid_title = f"📋 Bảng Ngân sách Hiện hành – {active_dept}" if selected_dept != ALL_DEPTS else f"📋 Bảng Ngân sách Hiện hành – {site_label(selected_site)} (Tất cả phòng ban)"
    st.markdown(f"#### {grid_title}")

    if df_curr.empty:
        st.info("Bảng đang trống. Hãy thêm hạng mục mới bằng form phía trên hoặc nhập file Excel!")
    else:
        # Display summary row on top of grid
        tot_budget_all = df_curr["total_budget"].sum()
        col_m1, col_m2, col_m3, col_m4 = st.columns([2, 1, 1, 1])
        with col_m1:
            st.write(f"**Tổng số dòng:** {len(df_curr)} mục | **Tổng Ngân sách:** {format_vnd(tot_budget_all)}")
        with col_m2:
            if can_edit and st.button("⚡ Chuẩn hóa & Tính lại", use_container_width=True,
                                      help="Đổi tên theo danh mục chuẩn, gán nhóm CNTT, ĐVT, loại tài sản, loại chi phí và phân loại kế toán"):
                rows = [r.to_dict() for _, r in df_curr.iterrows()]
                matched = sum(apply_it_catalog(r, master) for r in rows)
                save_view(pd.DataFrame(rows))
                st.session_state["flash"] = (f"Đã chuẩn hóa {matched}/{len(rows)} dòng theo Danh mục CNTT và tính lại toàn bộ bảng!"
                                             + (" Các dòng còn lại không có trong danh mục - kiểm tra tên hoặc bổ sung danh mục." if matched < len(rows) else ""))
                st.rerun()
        with col_m3:
            if not dept_rows_now.empty:
                dept_meta = dict(st.session_state["metadata"])
                dept_meta["proposing_dept"] = active_dept
                lazy_excel_download(dept_rows_now, dept_meta, f"📥 Tải Excel ({active_dept[:15]}...)",
                                    f"CAPEX_{budget_year}_{active_dept.replace(' ', '_')}.xlsx",
                                    key=f"dept_{budget_year}_{selected_site}_{active_dept}",
                                    help_text=f"Tải riêng file Excel phiếu ngân sách của phòng ban {active_dept}")
        with col_m4:
            if can_edit:
                st.caption("💡 Chọn dòng và bấm Delete để xóa dòng.")

        # Setup columns for interactive editor
        core_cols = [
            "stt", "need_type", "need_reason", "it_group", "catalog_code", "item_name", "detail_work", "unit", "quantity", "unit_price",
            "total_budget", "invest_type", "item_kind_label", "capex_type", "accounting_class", "total_pct",
            "entity", "dept_using", "location", "asset_cat1", "asset_cat2", "cost_lv1", "cost_lv2",
            "handover_date", "project_code", "item_code", "budget_code"
        ]
        column_order = [c for c in core_cols if c in df_curr.columns] + [c for c in df_curr.columns if c not in core_cols]

        if not can_edit:
            st.dataframe(df_curr, use_container_width=True, height=450, hide_index=True,
                         column_order=[c for c in column_order if c != "_order"])
            edited_df = df_curr
        else:
            edited_df = st.data_editor(
                df_curr,
                key=f"editor_{budget_year}_{selected_site}_{st.session_state.get('editor_version', 0)}",
                column_order=column_order,
                num_rows="dynamic",
                use_container_width=True,
                height=450,
                column_config={
                    "stt": st.column_config.NumberColumn("STT", width="small", disabled=True),
                    "entity": st.column_config.SelectboxColumn("Pháp nhân", options=[e["name"] for e in master.get("entities", [])], required=True),
                    "location": st.column_config.TextColumn("Vị trí/Site", disabled=True),
                    "asset_cat1": st.column_config.SelectboxColumn("Loại TS 1", options=[c["name"] for c in master.get("asset_cat1", [])]),
                    "item_name": st.column_config.TextColumn("Tên Tài sản", width="large", required=True),
                    "quantity": st.column_config.NumberColumn("Số lượng", min_value=1, format="%d"),
                    "unit_price": st.column_config.NumberColumn("Đơn giá (VNĐ)", format="%d"),
                    "total_budget": st.column_config.NumberColumn("Tổng ngân sách (VNĐ)", format="%d", disabled=True),
                    "total_pct": st.column_config.ProgressColumn("Tổng % Phân kỳ", min_value=0.0, max_value=1.0, format="%.0f%%"),
                    "project_code": st.column_config.TextColumn("Mã công trình", disabled=True),
                    "item_code": st.column_config.TextColumn("Mã hạng mục", disabled=True),
                    "budget_code": st.column_config.TextColumn("Mã ngân sách", disabled=True),
                    "it_group": st.column_config.TextColumn("Nhóm CNTT", disabled=True),
                    "catalog_code": st.column_config.TextColumn("Mã danh mục", disabled=True),
                    "unit": st.column_config.TextColumn("ĐVT"),
                    "invest_type": st.column_config.SelectboxColumn("Hình thức đầu tư", options=INVEST_TYPES),
                    "item_kind": None,
                    "_order": None,
                    "item_kind_label": st.column_config.TextColumn("Loại hạng mục", disabled=True),
                    "accounting_class": st.column_config.TextColumn("Phân loại kế toán", disabled=True, width="large"),
                    "capex_type": st.column_config.TextColumn("CAPEX/CCDC/OPEX", disabled=True),
                    "need_type": st.column_config.SelectboxColumn("Loại nhu cầu", options=qt.NEED_TYPES),
                    "need_reason": st.column_config.TextColumn("Lý do / căn cứ", width="medium"),
                    "auto_quota": None
                }
            )

        # Check if edits happened
        if can_edit and not edited_df.equals(df_curr):
            # Recalculate totals and persist
            save_view(edited_df)
            st.rerun()


# =====================================================================
# TAB: ĐỊNH BIÊN & NHU CẦU THIẾT BỊ / PHẦN MỀM THEO PHÒNG BAN
# =====================================================================
with tab_quota:
    st.markdown("### 👥 Định biên & Nhu cầu Thiết bị / Phần mềm theo Phòng ban")
    st.caption("Định mức = Nhân sự định biên × Bộ trang bị tiêu chuẩn. Thiết bị & phần mềm vĩnh viễn: mua bổ sung phần thiếu so với hiện có "
               "+ thay thế thiết bị cũ. Phần mềm thuê bao: gia hạn số đang có + mua thêm phần thiếu. "
               "Nhu cầu ngoài định biên nhập ở tab 'Lập & Nhập liệu' với loại 'Phát sinh mới'.")
    kits_cfg = qt.standard_kits(master)
    kit_label = {k["code"]: f"{k['code']} · {k['name']}" for k in kits_cfg}
    cat_by_code = qt.catalog_by_code(master)
    item_label = {c: f"{c} · {it['name']}" for c, it in cat_by_code.items()}
    label_to_code = {v: k for k, v in item_label.items()}

    def needs_by_dept(hc_rows_all, inv_rows_all):
        """Nhu cầu theo (site, phòng ban) từ định biên + hiện có -> DataFrame gộp (thêm cột site, dept)."""
        frames = []
        for (sc, dp), hc in pd.DataFrame(hc_rows_all).groupby(["site_code", "dept"]):
            inv = [r for r in inv_rows_all if r["site_code"] == sc and r["dept"] == dp]
            n = qt.compute_needs(hc.to_dict("records"), inv, master)
            if not n.empty:
                frames.append(n.assign(site=sc, dept=dp))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def needs_summary(N: pd.DataFrame) -> pd.DataFrame:
        sw = N["kind"].astype(str).str.startswith("software") | (N["kind"] == "service")
        return N.assign(hw=(N["add_qty"] + N["replace_qty"]) * N["price"] * ~sw, sw_new=N["add_qty"] * N["price"] * sw,
                        sw_renew=N["renew_qty"] * N["price"] * sw).groupby(["site", "dept"]).agg(
            **{"Thiết bị mua thêm/thay (VNĐ)": ("hw", "sum"), "Phần mềm mua mới (VNĐ)": ("sw_new", "sum"),
               "Gia hạn bản quyền (VNĐ)": ("sw_renew", "sum"), "Tổng nhu cầu (VNĐ)": ("propose_value", "sum")}).reset_index()

    money_cfg = {c: st.column_config.NumberColumn(format="%d") for c in [
        "Thiết bị mua thêm/thay (VNĐ)", "Phần mềm mua mới (VNĐ)", "Gia hạn bản quyền (VNĐ)", "Tổng nhu cầu (VNĐ)",
        "Ngân sách định biên đã tạo (VNĐ)", "Thành tiền (VNĐ)", "Đơn giá"]}

    # ---- Nhập file định biên nhân sự (Khối QTNNL) ----
    if current_user.is_admin:
        with st.expander("📥 Nhập file định biên nhân sự (Khối QTNNL) – tính cho toàn bộ phòng ban", expanded=False):
            st.caption("File theo mẫu 'Tổng hợp định biên … - Gửi CNTT': mỗi dòng 1 vị trí; dùng Khối/Phòng, Vị trí, Cấp bậc, Nơi làm việc, "
                       "cột Thiết bị CNTT / Phần mềm (nếu có), Nhân sự thực tế, Định biên và nhân sự 12 tháng. "
                       "**Họ tên và mã nhân viên không được lưu.**")
            app_dir = os.path.dirname(os.path.abspath(__file__))
            local_files = sorted((f for f in os.listdir(app_dir)
                                  if f.lower().endswith(".xlsx") and "định biên" in unicodedata.normalize("NFC", f).lower()
                                  and not unicodedata.normalize("NFC", f).lower().startswith("phân tích")),
                                 key=lambda f: (not unicodedata.normalize("NFC", f).lower().startswith("tổng hợp định biên"), f))
            UPLOAD = "(Tải lên file khác)"
            src_choice = st.selectbox("Nguồn file định biên", local_files + [UPLOAD])
            source = st.file_uploader("File định biên (.xlsx)", type=["xlsx"], key="hc_upload") if src_choice == UPLOAD \
                else os.path.join(app_dir, src_choice)
            if source is not None:
                kit_codes = {k["code"] for k in kits_cfg}
                site_ov = master.get("hc_site_overrides", {})
                kit_ov = master.get("hc_kit_overrides", {})
                try:
                    import json as _json
                    if isinstance(source, str):
                        with open(source, "rb") as _f:
                            _content = _f.read()
                    else:
                        _content = source.getvalue()
                    roster = _cached_roster(_content, tuple(sorted(kit_codes)), _json.dumps(site_ov, sort_keys=True),
                                            _json.dumps(kit_ov, sort_keys=True))
                except Exception as exc:  # file sai mẫu
                    roster = None
                    st.error(f"Không đọc được file định biên: {exc}")
                if roster is not None and not roster["positions"].empty:
                    P = roster["positions"]
                    fy = roster["fiscal_year"]
                    year_ok = str(fy) == str(budget_year)
                    if not year_ok:
                        st.warning(f"File là định biên năm **{fy}** (T10/{fy - 1}–T9/{fy}), đang chọn năm ngân sách **{budget_year}**. "
                                   f"Chọn năm {fy} ở thanh bên trái trước khi áp dụng.")
                    h1, h2, h3, h4 = st.columns(4)
                    h1.metric("Vị trí", f"{len(P):,}")
                    h2.metric("Nhân sự thực tế", f"{P['actual'].sum():,.0f}")
                    h3.metric(f"Định biên {fy}", f"{P['plan'].sum():,.0f}")
                    h4.metric("Phòng ban × site", f"{P.groupby(['site', 'dept']).ngroups}")
                    if roster["issues"]:
                        with st.popover(f"⚠️ {len(roster['issues'])} dòng lỗi dữ liệu trong file (đã xử lý tạm)"):
                            st.write("\n".join(f"- {x}" for x in roster["issues"]))

                    t_site, t_kit, t_need = st.tabs(["Nơi làm việc → Site", "Bộ trang bị theo vị trí", "Nhu cầu ước tính"])
                    with t_site:
                        loc_df = P.groupby(["location", "site", "site_note"]).size().reset_index(name="Số vị trí")
                        ed_loc = st.data_editor(loc_df, key="hc_loc_editor", hide_index=True, use_container_width=True,
                                                disabled=["location", "site_note", "Số vị trí"],
                                                column_config={"location": "Nơi làm việc (file)",
                                                               "site": st.column_config.SelectboxColumn("Site", options=[s["code"] for s in SITES], required=True),
                                                               "site_note": "Ghi chú"})
                    with t_kit:
                        kit_names = {k["code"]: f"{k['code']} · {k['name']}" for k in kits_cfg}
                        pos_df = (P.groupby(["position_label", "level", "kit", "kit_reason"]).size().reset_index(name="Số vị trí")
                                  .sort_values("Số vị trí", ascending=False))
                        pos_df["kit"] = pos_df["kit"].map(kit_names)
                        flt = st.text_input("Lọc vị trí", key="hc_pos_filter", placeholder="vd. tekla, kế toán, lái xe")
                        view = pos_df[pos_df["position_label"].str.lower().str.contains(flt.lower(), regex=False)] if flt else pos_df
                        ed_pos = st.data_editor(view, key=f"hc_pos_editor_{flt}", hide_index=True, use_container_width=True, height=380,
                                                disabled=["position_label", "level", "kit_reason", "Số vị trí"],
                                                column_config={"position_label": st.column_config.TextColumn("Vị trí", width="large"),
                                                               "level": "Cấp bậc",
                                                               "kit": st.column_config.SelectboxColumn("Bộ trang bị", options=list(kit_names.values()), required=True, width="medium"),
                                                               "kit_reason": "Căn cứ gán"})
                        st.caption("Đổi 'Bộ trang bị' cho vị trí cần điều chỉnh rồi bấm Lưu điều chỉnh; nội dung từng bộ sửa ở tab Quản lý Danh mục.")
                    if st.button("💾 Lưu điều chỉnh site / bộ trang bị", key="hc_save_ov"):
                        new_site_ov = dict(site_ov)
                        for _, r in ed_loc.iterrows():
                            auto = hi.map_site(r["location"])[0]
                            if r["site"] != auto:
                                new_site_ov[r["location"]] = r["site"]
                            else:
                                new_site_ov.pop(r["location"], None)
                        new_kit_ov = dict(kit_ov)
                        name_to_code = {v: k for k, v in kit_names.items()}
                        before = {(r["position_label"], r["level"]): r["kit"] for _, r in view.iterrows()}
                        for _, r in ed_pos.iterrows():
                            if r["kit"] != before.get((r["position_label"], r["level"])):
                                new_kit_ov[hi.position_key(r["position_label"], r["level"])] = name_to_code.get(r["kit"])
                        master["hc_site_overrides"], master["hc_kit_overrides"] = new_site_ov, new_kit_ov
                        save_master_data(master)
                        st.session_state["flash"] = f"Đã lưu {len(new_site_ov)} điều chỉnh site và {len(new_kit_ov)} điều chỉnh bộ trang bị."
                        st.rerun()

                    agg_rows = hi.aggregate(P)
                    est_inv = []
                    for (sc, dp), g in pd.DataFrame(agg_rows).groupby(["site_code", "dept"]):
                        for code, qty in hi.estimate_inventory(g.to_dict("records"), kits_cfg).items():
                            est_inv.append({"site_code": sc, "dept": dp, "catalog_code": code, "current_qty": qty,
                                            "replace_qty": 0.0, "quota_override": None,
                                            "note": "Ước tính = nhân sự thực tế × bộ trang bị; cần đối chiếu kiểm kê"})
                    N_prev = needs_by_dept(agg_rows, est_inv)
                    with t_need:
                        if N_prev.empty:
                            st.info("Không có nhu cầu.")
                        else:
                            n1, n2, n3 = st.columns(3)
                            sw_mask = N_prev["kind"].astype(str).str.startswith("software") | (N_prev["kind"] == "service")
                            n1.metric("Thiết bị mua thêm", format_vnd(((N_prev["add_qty"] + N_prev["replace_qty"]) * N_prev["price"])[~sw_mask].sum()))
                            n2.metric("Phần mềm mua mới", format_vnd((N_prev["add_qty"] * N_prev["price"])[sw_mask].sum()))
                            n3.metric("Gia hạn bản quyền", format_vnd((N_prev["renew_qty"] * N_prev["price"])[sw_mask].sum()))
                            items = (N_prev.groupby(["catalog_code", "item_name", "unit", "price"])
                                     .agg(**{"Định biên": ("quota", "sum"), "Hiện có (ước tính)": ("current_qty", "sum"),
                                             "Mua thêm": ("add_qty", "sum"), "Gia hạn": ("renew_qty", "sum"),
                                             "Thành tiền (VNĐ)": ("propose_value", "sum")})
                                     .reset_index().sort_values("Thành tiền (VNĐ)", ascending=False)
                                     .rename(columns={"catalog_code": "Mã", "item_name": "Hạng mục", "unit": "ĐVT", "price": "Đơn giá"}))
                            st.dataframe(items, use_container_width=True, hide_index=True, column_config=money_cfg)
                            st.caption("Hiện có ước tính giả định nhân sự đang làm việc đã được cấp đủ bộ trang bị. "
                                       "Khi áp dụng, ước tính chỉ ghi cho hạng mục phòng ban chưa khai báo hiện có.")

                    o1, o2 = st.columns(2)
                    use_est = o1.checkbox("Ghi hiện có ước tính (hạng mục chưa khai báo)", value=True, key="hc_use_est")
                    gen_lines = o2.checkbox("Tạo luôn dòng ngân sách 'Định biên' cho các phòng ban", value=True, key="hc_gen_lines")
                    if st.button(f"⚡ Áp định biên vào năm ngân sách {budget_year}", type="primary", disabled=not year_ok, key="hc_apply"):
                        statuses = db.all_statuses(budget_year)
                        locked = {sc for sc, stt in statuses.items() if stt.get("status") not in db.EDITABLE_STATUSES}
                        done_depts, skipped, n_lines = 0, set(), 0
                        agg_df = pd.DataFrame(agg_rows)
                        for sc, site_grp in agg_df.groupby("site_code"):
                            if sc in locked:
                                skipped.add(sc)
                                continue
                            site_lines = pd.DataFrame(db.load_lines(budget_year, [sc]))
                            if "site_code" in site_lines.columns:
                                site_lines = site_lines.drop(columns=["site_code"])
                            drop_mask = pd.Series(False, index=site_lines.index)
                            new_lines = []
                            for dp, g in site_grp.groupby("dept"):
                                hc_rows_dp = g.drop(columns=["site_code", "dept"]).to_dict("records")
                                db.replace_dept_rows("dept_headcount", budget_year, sc, dp, hc_rows_dp, current_user.email)
                                inv_now = db.load_dept_rows("dept_inventory", budget_year, [sc], dp)
                                if use_est:
                                    have = {r["catalog_code"] for r in inv_now}
                                    inv_now = inv_now + [r for r in est_inv if r["site_code"] == sc and r["dept"] == dp and r["catalog_code"] not in have]
                                    db.replace_dept_rows("dept_inventory", budget_year, sc, dp, inv_now, current_user.email)
                                done_depts += 1
                                if gen_lines:
                                    n = qt.compute_needs(hc_rows_dp, inv_now, master)
                                    in_dp = dept_mask(site_lines, dp)
                                    auto = site_lines["auto_quota"].fillna(False).astype(bool) if "auto_quota" in site_lines.columns \
                                        else pd.Series(False, index=site_lines.index)
                                    old = [r.to_dict() for _, r in site_lines[in_dp & auto].iterrows()]
                                    drop_mask |= (in_dp & auto)
                                    defaults = {"entity": "DDC", "location": SITE_NAME.get(sc, sc), "division": "",
                                                "handover_date": "", "contract_date": "", "completion_date": ""}
                                    new_lines += qt.build_quota_lines(n, dp, old, months, master, defaults)
                            if gen_lines:
                                save_site(pd.concat([site_lines[~drop_mask], pd.DataFrame(new_lines)], ignore_index=True), sc)
                                n_lines += len(new_lines)
                        db.log(current_user.email, "import_headcount", f"{budget_year}: {done_depts} phòng ban, {n_lines} dòng ngân sách")
                        st.session_state["quota_version"] = st.session_state.get("quota_version", 0) + 1
                        st.session_state["flash"] = (f"Đã áp định biên cho {done_depts} phòng ban" + (f", tạo {n_lines} dòng ngân sách 'Định biên'" if gen_lines else "")
                                                     + (f". Bỏ qua site đã nộp/duyệt: {', '.join(sorted(skipped))}" if skipped else "") + ".")
                        st.rerun()

    if selected_site == ALL_SITES or selected_dept == ALL_DEPTS:
        st.info("Chọn **một site** và **một phòng ban** ở thanh bên trái để khai báo / điều chỉnh định biên. Bên dưới là tổng hợp định biên và nhu cầu các phòng ban.")
        hc_list = db.load_dept_rows("dept_headcount", budget_year, scope_sites)
        if not hc_list:
            st.caption("Chưa có phòng ban nào khai báo định biên.")
        else:
            hc_all = pd.DataFrame(hc_list)
            summary = hc_all.groupby(["site_code", "dept"]).agg(**{"Nhân sự hiện có": ("hc_current", "sum"),
                                                                    "Nhân sự định biên": ("hc_plan", "sum")}).reset_index()
            N_all = needs_by_dept(hc_list, db.load_dept_rows("dept_inventory", budget_year, scope_sites))
            if not N_all.empty:
                summary = summary.merge(needs_summary(N_all), left_on=["site_code", "dept"], right_on=["site", "dept"], how="left").drop(columns=["site"])
            if not df_site.empty and "need_type" in df_site.columns:
                val = df_site.assign(dk=df_site["dept_proposing"].map(dept_key))
                val = val[val["need_type"] == qt.NEED_QUOTA].groupby("dk")["total_budget"].sum()
                summary["Ngân sách định biên đã tạo (VNĐ)"] = summary["dept"].map(dept_key).map(val).fillna(0)
            summary = summary.sort_values("Tổng nhu cầu (VNĐ)" if "Tổng nhu cầu (VNĐ)" in summary.columns else "Nhân sự định biên", ascending=False)
            total_row = summary.sum(numeric_only=True)
            s1, s2, s3 = st.columns(3)
            s1.metric("Nhân sự hiện có → định biên", f"{total_row['Nhân sự hiện có']:,.0f} → {total_row['Nhân sự định biên']:,.0f}")
            s2.metric("Phòng ban × site", f"{len(summary)}")
            s3.metric("Tổng nhu cầu CNTT theo định biên", format_vnd(total_row.get("Tổng nhu cầu (VNĐ)", 0)))
            summary["site_code"] = summary["site_code"].map(site_label)
            st.dataframe(summary.rename(columns={"site_code": "Site", "dept": "Phòng ban"}), use_container_width=True, hide_index=True,
                         column_config=money_cfg)
    else:
        q_key = f"{budget_year}_{selected_site}_{selected_dept}_{st.session_state.get('quota_version', 0)}"
        headcount = db.load_dept_rows("dept_headcount", budget_year, [selected_site], selected_dept)
        inventory = db.load_dept_rows("dept_inventory", budget_year, [selected_site], selected_dept)

        # Bước 1: định biên nhân sự
        st.markdown(f"#### 1️⃣ Định biên nhân sự – {selected_dept}")
        df_hc = pd.DataFrame([{"kit": kit_label.get(h["kit_code"], h["kit_code"]), "hc_current": h["hc_current"],
                               "hc_plan": h["hc_plan"]} for h in headcount], columns=["kit", "hc_current", "hc_plan"])
        ed_hc = st.data_editor(
            df_hc, key=f"hc_{q_key}", num_rows="dynamic" if can_edit else "fixed", disabled=not can_edit,
            use_container_width=True, hide_index=True,
            column_config={
                "kit": st.column_config.SelectboxColumn("Vị trí / Bộ trang bị tiêu chuẩn", options=list(kit_label.values()),
                                                        required=True, width="large"),
                "hc_current": st.column_config.NumberColumn("Nhân sự hiện có", min_value=0, step=1, format="%d"),
                "hc_plan": st.column_config.NumberColumn(f"Nhân sự định biên {budget_year}", min_value=0, step=1, format="%d"),
            })
        k1, k2 = st.columns(2)
        k1.metric("Nhân sự hiện có", f"{int(pd.to_numeric(ed_hc['hc_current'], errors='coerce').fillna(0).sum())} người")
        k2.metric(f"Định biên {budget_year}", f"{int(pd.to_numeric(ed_hc['hc_plan'], errors='coerce').fillna(0).sum())} người")
        with st.expander("Xem bộ trang bị tiêu chuẩn"):
            st.dataframe(pd.DataFrame([{"Bộ trang bị": f"{k['code']} · {k['name']}",
                                        "Hạng mục": item_label.get(i["catalog_code"], i["catalog_code"]),
                                        "Số lượng / người": i["qty_per_person"]} for k in kits_cfg for i in k["items"]]),
                         use_container_width=True, hide_index=True)

        # Bước 2: hiện có & thay thế
        needs = qt.compute_needs(
            [{"kit_code": next((c for c, l in kit_label.items() if l == r["kit"]), None),
              "hc_current": r["hc_current"], "hc_plan": r["hc_plan"]} for _, r in ed_hc.iterrows() if r.get("kit")],
            inventory, master)
        st.markdown("#### 2️⃣ Thiết bị / phần mềm hiện có & cần thay thế")
        st.caption("Nhập số đang có của phòng ban và số thiết bị cần thay (hỏng, hết khấu hao). "
                   "Có thể thêm dòng cho hạng mục định biên riêng (vd. máy in A3 dùng chung) và nhập 'Định biên điều chỉnh'.")
        df_inv = pd.DataFrame({
            "item": needs["catalog_code"].map(item_label), "dinh_muc": needs["dinh_muc"],
            "quota_override": pd.to_numeric(needs["quota_override"], errors="coerce"),
            "current_qty": needs["current_qty"], "replace_qty": needs["replace_qty"], "note": needs["note"],
        }, columns=["item", "dinh_muc", "quota_override", "current_qty", "replace_qty", "note"])
        ed_inv = st.data_editor(
            df_inv, key=f"inv_{q_key}", num_rows="dynamic" if can_edit else "fixed", disabled=not can_edit,
            use_container_width=True, hide_index=True,
            column_config={
                "item": st.column_config.SelectboxColumn("Hạng mục", options=list(item_label.values()), required=True, width="large"),
                "dinh_muc": st.column_config.NumberColumn("Định mức (tự tính)", disabled=True, format="%d"),
                "quota_override": st.column_config.NumberColumn("Định biên điều chỉnh", min_value=0, step=1, format="%d",
                                                                help="Để trống = dùng định mức tự tính"),
                "current_qty": st.column_config.NumberColumn("Hiện có", min_value=0, step=1, format="%d"),
                "replace_qty": st.column_config.NumberColumn("Cần thay thế", min_value=0, step=1, format="%d"),
                "note": st.column_config.TextColumn("Ghi chú"),
            })

        inv_rows = []
        for _, r in ed_inv.iterrows():
            code = label_to_code.get(r.get("item"))
            if not code:
                continue
            ov = r.get("quota_override")
            inv_rows.append({"catalog_code": code, "current_qty": qt._num(pd.to_numeric(r.get("current_qty"), errors="coerce")),
                             "replace_qty": qt._num(pd.to_numeric(r.get("replace_qty"), errors="coerce")),
                             "quota_override": None if ov is None or pd.isna(ov) else float(ov),
                             "note": r.get("note") or ""})
        months_by_kit = {h["kit_code"]: h.get("hc_months") for h in headcount}
        hc_rows = [{"kit_code": next((c for c, l in kit_label.items() if l == r["kit"]), None),
                    "hc_current": qt._num(pd.to_numeric(r.get("hc_current"), errors="coerce")),
                    "hc_plan": qt._num(pd.to_numeric(r.get("hc_plan"), errors="coerce"))}
                   for _, r in ed_hc.iterrows() if r.get("kit")]
        for h in hc_rows:
            h["hc_months"] = months_by_kit.get(h["kit_code"])
        needs = qt.compute_needs(hc_rows, inv_rows, master)

        # Bước 3: nhu cầu đề xuất
        st.markdown("#### 3️⃣ Nhu cầu đề xuất theo định biên")
        if needs.empty:
            st.info("Chưa có nhu cầu. Khai báo định biên nhân sự ở bước 1 hoặc thêm hạng mục ở bước 2.")
        else:
            kind_name = it_kinds(master)
            show = needs.assign(kind=needs["kind"].map(kind_name))[
                ["catalog_code", "item_name", "kind", "unit", "quota", "current_qty", "add_qty", "renew_qty", "replace_qty",
                 "propose_qty", "price", "propose_value", "basis"]]
            st.dataframe(show, use_container_width=True, hide_index=True, column_config={
                "catalog_code": "Mã", "item_name": st.column_config.TextColumn("Hạng mục", width="medium"), "kind": "Loại", "unit": "ĐVT",
                "quota": st.column_config.NumberColumn("Định biên", format="%d"),
                "current_qty": st.column_config.NumberColumn("Hiện có", format="%d"),
                "add_qty": st.column_config.NumberColumn("Mua bổ sung", format="%d"),
                "renew_qty": st.column_config.NumberColumn("Gia hạn", format="%d"),
                "replace_qty": st.column_config.NumberColumn("Thay thế", format="%d"),
                "propose_qty": st.column_config.NumberColumn("Tổng đề xuất", format="%d"),
                "price": st.column_config.NumberColumn("Đơn giá", format="%d"),
                "propose_value": st.column_config.NumberColumn("Thành tiền (VNĐ)", format="%d"),
                "basis": st.column_config.TextColumn("Căn cứ", width="large"),
            })
            is_sw = needs["kind"].astype(str).str.startswith("software")
            m1, m2, m3 = st.columns(3)
            m1.metric("Thiết bị theo định biên", format_vnd(needs.loc[~is_sw, "propose_value"].sum()))
            m2.metric("Phần mềm theo định biên", format_vnd(needs.loc[is_sw, "propose_value"].sum()))
            m3.metric("Tổng theo định biên", format_vnd(needs["propose_value"].sum()))

        if can_edit:
            b1, b2 = st.columns(2)
            if b1.button("💾 Lưu định biên & hiện có", use_container_width=True):
                db.replace_dept_rows("dept_headcount", budget_year, selected_site, selected_dept, hc_rows, current_user.email)
                db.replace_dept_rows("dept_inventory", budget_year, selected_site, selected_dept, inv_rows, current_user.email)
                st.session_state["quota_version"] = st.session_state.get("quota_version", 0) + 1
                st.session_state["flash"] = f"Đã lưu định biên của {selected_dept}."
                st.rerun()
            if b2.button("⚡ Lưu & tạo dòng ngân sách theo định biên", use_container_width=True, type="primary",
                         help="Thay các dòng 'Định biên' tự sinh trước đó của phòng ban này; giữ nguyên dòng 'Phát sinh mới' và phân kỳ đã chỉnh"):
                db.replace_dept_rows("dept_headcount", budget_year, selected_site, selected_dept, hc_rows, current_user.email)
                db.replace_dept_rows("dept_inventory", budget_year, selected_site, selected_dept, inv_rows, current_user.email)
                st.session_state["quota_version"] = st.session_state.get("quota_version", 0) + 1
                in_dept = dept_mask(df_site, selected_dept)
                auto = df_site["auto_quota"].fillna(False).astype(bool) if "auto_quota" in df_site.columns else pd.Series(False, index=df_site.index)
                old = [r.to_dict() for _, r in df_site[in_dept & auto].iterrows()]
                entity = (df_site["entity"].mode().iloc[0] if "entity" in df_site.columns and not df_site["entity"].dropna().empty else "DDC")
                defaults = {"entity": entity, "location": SITE_NAME.get(selected_site, selected_site),
                            "handover_date": "", "contract_date": "", "completion_date": ""}
                new_lines = qt.build_quota_lines(needs, selected_dept, old, months, master, defaults)
                kept = df_site[~(in_dept & auto)]
                save_site(pd.concat([kept, pd.DataFrame(new_lines)], ignore_index=True), selected_site)
                st.session_state["flash"] = (f"Đã tạo {len(new_lines)} dòng ngân sách theo định biên cho {selected_dept} "
                                             f"({format_vnd(needs['propose_value'].sum() if not needs.empty else 0)}). "
                                             "Kiểm tra phân kỳ ở tab 'Lập & Nhập liệu' (mặc định 100% tháng đầu năm ngân sách).")
                st.rerun()


# =====================================================================
# TAB: HẠ TẦNG CNTT DÙNG CHUNG (phòng phụ trách: PHÒNG CNTT) THEO SITE
# =====================================================================
with tab_infra:
    st.markdown("### 🏗️ Hạ tầng CNTT dùng chung theo site")
    st.caption("Máy chủ, lưu trữ, mạng, an ninh mạng, camera, phòng họp, phòng máy chủ & UPS, Cloud / đường truyền / dịch vụ, "
               "phần mềm hệ thống dùng chung. Ngân sách đứng tên phòng phụ trách (mặc định PHÒNG CNTT), site = nơi lắp đặt; "
               "không tính theo định biên. Phạm vi & phòng phụ trách từng nhóm sửa ở tab Quản lý Danh mục.")
    shared_items = [it for it in master.get("standard_items", []) if item_scope(it, master) == SCOPE_SHARED]
    sh_label = {it["code"]: f"{it['code']} · {it['name']}" for it in shared_items}
    sh_by_label = {v: k for k, v in sh_label.items()}
    sh_by_code = {it["code"]: it for it in shared_items}
    infra_mask = (df_site["need_type"] == qt.NEED_INFRA) if "need_type" in df_site.columns else pd.Series(False, index=df_site.index)

    if current_user.is_dept_user:
        st.info("Hạ tầng CNTT dùng chung do Phòng CNTT lập. Tài khoản phòng ban chỉ lập ngân sách của phòng mình.")
    elif selected_site == ALL_SITES:
        df_inf_all = df_site[infra_mask]
        if df_inf_all.empty:
            st.info("Chưa có site nào khai báo hạ tầng dùng chung. Chọn một site ở thanh bên trái để nhập.")
        else:
            st.metric("Tổng hạ tầng dùng chung", format_vnd(df_inf_all["total_budget"].sum()))
            pv = df_inf_all.assign(site=df_inf_all["site_code"].map(site_label)).pivot_table(
                index="site", columns="it_group", values="total_budget", aggfunc="sum", fill_value=0)
            pv["Tổng (VNĐ)"] = pv.sum(axis=1)
            st.dataframe(pv.sort_values("Tổng (VNĐ)", ascending=False), use_container_width=True,
                         column_config={c: st.column_config.NumberColumn(format="%d") for c in pv.columns})
    else:
        df_inf = df_site[infra_mask]
        st.markdown(f"#### {site_label(selected_site)}")

        def first_month(r):
            for m in months:
                if qt._num(r.get(f"pct_{m}")) > 0:
                    return m
            return months[0]

        df_edit = pd.DataFrame([{
            "item": sh_label.get(r.get("catalog_code"), r.get("item_name")), "invest_type": r.get("invest_type") or "Mua mới",
            "quantity": r.get("quantity"), "unit_price": r.get("unit_price"), "month": first_month(r),
            "dept_proposing": r.get("dept_proposing"), "need_reason": r.get("need_reason") or "",
        } for _, r in df_inf.iterrows()], columns=["item", "invest_type", "quantity", "unit_price", "month", "dept_proposing", "need_reason"])
        owners = sorted({item_owner(it, master) for it in shared_items} | set(dept_list))
        ed_inf = st.data_editor(
            df_edit, key=f"infra_{budget_year}_{selected_site}_{st.session_state.get('editor_version', 0)}",
            num_rows="dynamic" if can_edit else "fixed", disabled=not can_edit, use_container_width=True, hide_index=True,
            column_config={
                "item": st.column_config.SelectboxColumn("Hạng mục hạ tầng", options=list(sh_label.values()), required=True, width="large"),
                "invest_type": st.column_config.SelectboxColumn("Hình thức", options=INVEST_TYPES, required=True),
                "quantity": st.column_config.NumberColumn("Số lượng", min_value=1, step=1, format="%d", required=True),
                "unit_price": st.column_config.NumberColumn("Đơn giá (VNĐ, trống = giá danh mục)", min_value=0, format="%d"),
                "month": st.column_config.SelectboxColumn("Tháng triển khai", options=months, required=True),
                "dept_proposing": st.column_config.SelectboxColumn("Phòng đề xuất (trống = phòng phụ trách)", options=owners),
                "need_reason": st.column_config.TextColumn("Căn cứ / lý do (bắt buộc)", width="large"),
            })
        if not df_inf.empty:
            g = df_inf.groupby("it_group")["total_budget"].sum().sort_values(ascending=False)
            st.caption("Tổng hạ tầng của site: **" + format_vnd(df_inf["total_budget"].sum()) + "** · "
                       + " · ".join(f"{k}: {format_vnd_short(v)}" for k, v in g.items()))
        if can_edit and st.button("💾 Lưu hạ tầng CNTT của site", type="primary", key="infra_save"):
            new_rows, errs = [], []
            entity = (df_site["entity"].mode().iloc[0] if "entity" in df_site.columns and not df_site["entity"].dropna().empty else "DDC")
            for i, r in ed_inf.iterrows():
                code = sh_by_label.get(r.get("item"))
                if not code:
                    continue
                item = sh_by_code[code]
                reason = str(r.get("need_reason") or "").strip()
                if not reason:
                    errs.append(f"Dòng {i + 1} ({item['name']}): thiếu căn cứ / lý do")
                    continue
                price = r.get("unit_price")
                row = {"entity": entity, "location": SITE_NAME.get(selected_site, selected_site),
                       "quantity": qt._num(r.get("quantity"), 1.0) or 1.0,
                       "unit_price": float(item.get("price", 0)) if price is None or pd.isna(price) else float(price),
                       "dept_proposing": r.get("dept_proposing") or item_owner(item, master), "dept_using": "Dùng chung toàn site",
                       "need_type": qt.NEED_INFRA, "need_reason": reason, "detail_work": "Hạ tầng CNTT dùng chung"}
                apply_it_catalog(row, master, item=item, invest_type=r.get("invest_type") or "Mua mới")
                for m in months:
                    row[f"pct_{m}"] = 1.0 if m == r.get("month") else 0.0
                new_rows.append(row)
            if errs:
                st.error("Chưa lưu – " + "; ".join(errs))
            else:
                save_site(pd.concat([df_site[~infra_mask], pd.DataFrame(new_rows)], ignore_index=True), selected_site)
                st.session_state["flash"] = f"Đã lưu {len(new_rows)} hạng mục hạ tầng CNTT dùng chung của {site_label(selected_site)}."
                st.rerun()


# =====================================================================
# TAB 3: NHẬP / XUẤT EXCEL
# =====================================================================
with tab_excel:
    st.markdown("### 📁 Nhập & Xuất File Excel Chuẩn Biểu mẫu Doanh nghiệp")

    ex_c1, ex_c2 = st.columns(2)

    with ex_c1:
        st.markdown("""
        <div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:10px; padding:20px;">
            <h4 style="color:#166534; margin-top:0;">📤 Xuất File Excel CAPEX</h4>
            <p style="color:#15803D; font-size:13px;">
                Xuất toàn bộ bảng ngân sách hiện hành thành file Excel (.xlsx) chuẩn biểu mẫu <b>CA.01_CAPEX</b> của Công ty Đại Dũng.
                Đầy đủ công thức tính toán, định dạng màu sắc doanh nghiệp, tỷ lệ phân kỳ 12 tháng và mã ngân sách kế toán.
            </p>
        </div>
        """, unsafe_allow_html=True)

        if df_curr.empty:
            st.warning("⚠️ Bảng dữ liệu đang trống, không thể xuất file.")
        else:
            scope_tag = "TONGHOP" if selected_site == ALL_SITES else selected_site
            file_name = f"CAPEX_{budget_year}_{scope_tag}_{dept_prop.replace(' ', '_')}_{datetime.date.today().strftime('%Y%m%d')}.xlsx"
            excel_bytes = lazy_excel_download(df_curr, st.session_state["metadata"],
                                              f"📥 TẢI XUỐNG FILE EXCEL ({len(df_curr)} HẠNG MỤC)", file_name,
                                              key=f"all_{budget_year}_{selected_site}_{selected_dept}")
            if excel_bytes:
                st.caption(f"File: {file_name} (~{len(excel_bytes)//1024} KB)")

    with ex_c2:
        st.markdown("""
        <div style="background:#EFF6FF; border:1px solid #BFDBFE; border-radius:10px; padding:20px;">
            <h4 style="color:#1E40AF; margin-top:0;">📥 Nhập File Excel từ Phòng Ban</h4>
            <p style="color:#1D4ED8; font-size:13px;">
                Tải lên file Excel (.xlsx) theo biểu mẫu nhập liệu CAPEX để hệ thống tự động đọc, chuẩn hóa, tính toán và phân tích.
            </p>
        </div>
        """, unsafe_allow_html=True)

        import_to_all = selected_site == ALL_SITES and current_user.is_admin
        if not (can_edit or import_to_all):
            st.info("🔒 Bạn không có quyền nhập dữ liệu vào phạm vi đang chọn.")
            uploaded_file = None
        else:
            if import_to_all:
                st.caption("Chế độ Admin – tổng hợp: các dòng được phân về site theo cột **Vị trí**; dữ liệu các site có trong file sẽ bị ghi đè.")
                import_mode = "replace"
            else:
                st.caption(f"Toàn bộ dòng trong file sẽ được gán vào site **{site_label(selected_site)}**"
                           + (f", phòng ban **{selected_dept}** (chế độ thay thế chỉ thay các dòng của phòng ban này)."
                              if selected_dept != ALL_DEPTS else "."))
                import_mode = st.radio("Cách nhập", ["append", "replace"], horizontal=True,
                                       format_func=lambda m: "Thêm vào cuối bảng" if m == "append" else "Thay thế toàn bộ bảng của site")
            uploaded_file = st.file_uploader("Chọn file Excel CAPEX (.xlsx)", type=["xlsx"])
        if uploaded_file is not None:
            try:
                wb_preview = openpyxl.load_workbook(uploaded_file, read_only=True)
                sheet_choices = wb_preview.sheetnames
                wb_preview.close()
                uploaded_file.seek(0)

                sel_sheet = st.selectbox("Chọn Sheet cần đọc:", sheet_choices)

                if st.button("⚡ ĐỌC DỮ LIỆU TỪ FILE EXCEL", use_container_width=True):
                    up_meta, up_df = load_capex_from_excel(uploaded_file, sel_sheet, months=months, year_code=year_code)
                    up_meta.pop("creator_email", None)
                    st.session_state["metadata"].update(up_meta)
                    if up_df.empty:
                        st.warning("Không tìm thấy dòng dữ liệu nào trong sheet đã chọn.")
                    elif import_to_all:
                        groups, unmatched = distribute_by_location(up_df)
                        for code, part in groups.items():
                            save_site(part, code)
                        st.session_state["flash"] = (f"🎉 Đã nhập {sum(len(p) for p in groups.values())} hạng mục vào {len(groups)} site."
                                                     + (f" Bỏ qua vị trí không khớp danh mục: {unmatched}" if unmatched else ""))
                        st.rerun()
                    else:
                        base = df_curr if import_mode == "append" else pd.DataFrame()
                        save_view(pd.concat([base, up_df], ignore_index=True))
                        st.session_state["flash"] = f"🎉 Đã nhập thành công {len(up_df)} hạng mục từ sheet '{sel_sheet}' vào {site_label(selected_site)}!"
                        st.rerun()
            except Exception as e:
                st.error(f"Lỗi khi đọc file Excel: {e}")


# =====================================================================
# TAB 4: KHẤU HAO & THẨM ĐỊNH HIỆU QUẢ ĐẦU TƯ
# =====================================================================
with tab_depreciation:
    st.markdown("### 📈 Phân tích Khấu hao TSCĐ & Đánh giá Hiệu quả Dự án")

    sub_tab1, sub_tab2 = st.tabs(["📉 Dự phóng Khấu hao TSCĐ", "💰 Thẩm định Hiệu quả Đầu tư (NPV / IRR / ROI)"])

    with sub_tab1:
        st.markdown("#### Dự phóng Khấu hao Đường thẳng (Theo Thông tư 45/2013/TT-BTC)")
        st.caption("Khung thời gian trích khấu hao: Nhà xưởng (25 năm), MMTB (8 năm), PTVT (6 năm), Thiết bị QL (4 năm), Phần mềm (3 năm).")

        if df_curr.empty:
            st.info("Chưa có dữ liệu để tính khấu hao.")
        else:
            dep_years = st.slider("Số năm dự phóng khấu hao:", min_value=3, max_value=10, value=5)
            dep_df = calculate_depreciation_schedule(df_curr, num_years=dep_years)

            if not dep_df.empty:
                tot_annual_dep = dep_df["annual_depreciation"].sum()
                tot_month_dep = dep_df["monthly_depreciation"].sum()

                d1, d2, d3 = st.columns(3)
                with d1:
                    st.metric("Khấu hao hàng năm", format_vnd(tot_annual_dep))
                with d2:
                    st.metric("Khấu hao hàng tháng", format_vnd(tot_month_dep))
                with d3:
                    st.metric("Tỷ lệ khấu hao TB/năm", f"{(tot_annual_dep/df_curr['total_budget'].sum()*100):.1f}%")

                # Depreciation bar chart by year
                dep_summary_by_year = [dep_df[f"Năm {y}"].sum() / 1e9 for y in range(1, dep_years + 1)]
                fig_dep = px.bar(
                    x=[f"Năm {y}" for y in range(1, dep_years + 1)],
                    y=dep_summary_by_year,
                    labels={"x": "Năm tài chính", "y": "Chi phí Khấu hao (Tỷ VNĐ)"},
                    title="Chi phí Khấu hao TSCĐ qua các Năm (Tỷ VNĐ)",
                    color_discrete_sequence=["#0F2C59"]
                )
                fig_dep.update_layout(margin=dict(t=30, b=10, l=10, r=10), height=300)
                st.plotly_chart(fig_dep, use_container_width=True)

                # Dataframe of depreciation
                disp_dep = dep_df.copy()
                disp_dep["total_budget"] = disp_dep["total_budget"].apply(format_vnd)
                disp_dep["annual_depreciation"] = disp_dep["annual_depreciation"].apply(format_vnd)
                disp_dep["monthly_depreciation"] = disp_dep["monthly_depreciation"].apply(format_vnd)
                for y in range(1, dep_years + 1):
                    disp_dep[f"Năm {y}"] = disp_dep[f"Năm {y}"].apply(format_vnd)

                disp_dep.columns = ["Tên Tài sản", "Pháp nhân", "Loại TS", "Nguyên giá", "Số năm KH", "KH Năm", "KH Tháng"] + [f"Năm {y}" for y in range(1, dep_years + 1)]
                st.dataframe(disp_dep, use_container_width=True, hide_index=True)

    with sub_tab2:
        st.markdown("#### Công cụ Thẩm định Hiệu quả Tài chính Dự án CAPEX")
        st.caption("Đánh giá các chỉ số tài chính: Net Present Value (NPV), Internal Rate of Return (IRR), Thời gian hoàn vốn (Payback Period).")

        total_capex_proj = df_curr["total_budget"].sum() if not df_curr.empty else 10_000_000_000.0

        tc1, tc2 = st.columns(2)
        with tc1:
            in_capex = st.number_input("Tổng vốn đầu tư ban đầu CapEx (VNĐ):", min_value=0.0, value=float(total_capex_proj), step=100_000_000.0, format="%.0f")
            in_savings = st.number_input("Doanh thu tăng thêm / Tiết kiệm chi phí hàng năm (VNĐ):", min_value=0.0, value=float(total_capex_proj * 0.35), step=50_000_000.0, format="%.0f")
            in_opex = st.number_input("Chi phí vận hành tăng thêm hàng năm OpEx (VNĐ):", min_value=0.0, value=float(total_capex_proj * 0.05), step=10_000_000.0, format="%.0f")

        with tc2:
            in_years = st.number_input("Vòng đời dự án đánh giá (Số năm):", min_value=1, max_value=20, value=5, step=1)
            in_discount = st.slider("Tỷ suất chiết khấu (WACC %):", min_value=1.0, max_value=25.0, value=10.0, step=0.5) / 100.0

            fin_result = calculate_project_financials(
                initial_capex=in_capex,
                annual_savings=in_savings,
                opex_annual=in_opex,
                life_years=in_years,
                discount_rate=in_discount
            )

            st.markdown("##### 🎯 Kết quả Thẩm định")
            res_npv = fin_result["npv"]
            res_irr = fin_result["irr"]
            res_pb = fin_result["payback_years"]
            res_roi = fin_result["roi_pct"]

            if res_npv > 0 and res_irr > (in_discount * 100):
                st.success(f"✅ **DỰ ÁN KHẢ THI CAO** (NPV > 0 và IRR > WACC {in_discount*100:.1f}%)")
            else:
                st.error("⚠️ **DỰ ÁN CẦN XEM XÉT LẠI** (Hiệu quả chưa đạt tỷ suất kỳ vọng)")

        rc1, rc2, rc3, rc4 = st.columns(4)
        with rc1:
            st.metric("NPV (Hiện giá thuần)", format_vnd(res_npv))
        with rc2:
            st.metric("IRR (Suất sinh lời nội bộ)", f"{res_irr:.1f}%")
        with rc3:
            st.metric("Thời gian Hoàn vốn", f"{res_pb} năm")
        with rc4:
            st.metric("Tỷ suất ROI", f"{res_roi:.1f}%")

        # Cash flow projection chart
        cfs = fin_result["cash_flows"]
        fig_cf = go.Figure()
        fig_cf.add_trace(go.Bar(
            x=[f"Năm {i}" for i in range(len(cfs))],
            y=[cf / 1e9 for cf in cfs],
            marker_color=["#EF4444" if cf < 0 else "#10B981" for cf in cfs],
            name="Dòng tiền ròng (Tỷ VNĐ)",
            hovertemplate="Năm: %{x}<br>Dòng tiền: %{y:.2f} tỷ VNĐ"
        ))
        fig_cf.update_layout(
            title="Dòng tiền Dự án theo các Năm (Tỷ VNĐ)",
            yaxis_title="Tỷ VNĐ",
            height=280,
            margin=dict(t=35, b=10, l=10, r=10)
        )
        st.plotly_chart(fig_cf, use_container_width=True)


# =====================================================================
# TAB 5: QUẢN LÝ DANH MỤC MASTER DATA
# =====================================================================
with tab_master:
    st.markdown("### ⚙️ Danh mục Tham chiếu Master Data & Bảng giá Chuẩn")
    st.caption("Các danh mục chuẩn được đồng bộ với hệ thống ERP / Biểu mẫu quản lý tài sản Tập đoàn Đại Dũng.")

    m_sub1, m_sub2, m_sub3 = st.tabs(["💻 Danh mục CNTT & Giá chuẩn", "🏢 Pháp nhân & Nhà máy", "🏷️ Loại Tài sản & Chi phí"])

    with m_sub1:
        groups_cfg = it_groups(master)
        kinds_cfg = it_kinds(master)
        group_codes = [g["code"] for g in groups_cfg]
        group_label = {g["code"]: f"{g['code']}. {g['name']}" for g in groups_cfg}
        catalog_all = master.get("standard_items", [])

        st.markdown("##### Danh mục hạng mục CNTT & giá tham chiếu")
        flagged = [it for it in catalog_all if it.get("note")]
        st.caption(f"{len(catalog_all)} hạng mục trong {len(groups_cfg)} nhóm. "
                   f"Đơn giá là giá 1 đơn vị (chưa VAT); thiết bị/bản quyền vĩnh viễn có đơn giá ≥ "
                   f"{int(master.get('tscd_threshold', 30_000_000)):,} VNĐ được hạch toán TSCĐ, thấp hơn là CCDC; "
                   f"thuê bao & dịch vụ là chi phí trả trước."
                   + (f" ⚠️ {len(flagged)} hạng mục có ghi chú cần kiểm tra lại giá/tên." if flagged else ""))

        mc1, mc2 = st.columns([2, 1])
        cat_filter = mc1.selectbox("Lọc theo nhóm", ["(Tất cả)"] + group_codes,
                                   format_func=lambda c: c if c == "(Tất cả)" else group_label[c])
        only_flagged = mc2.checkbox("Chỉ hiện hạng mục cần kiểm tra", value=False)

        def _in_view(it):
            return (cat_filter == "(Tất cả)" or it.get("group") == cat_filter) and (not only_flagged or it.get("note"))

        view_items = [it for it in catalog_all if _in_view(it)]
        df_cat = pd.DataFrame([{
            "code": it.get("code", ""), "group": it.get("group", ""), "name": it.get("name", ""),
            "unit": it.get("unit", ""), "kind": it.get("kind", ""), "price": it.get("price", 0),
            "aliases": "; ".join(it.get("aliases", [])), "note": it.get("note", ""),
        } for it in view_items], columns=["code", "group", "name", "unit", "kind", "price", "aliases", "note"])

        edited_cat = st.data_editor(
            df_cat,
            key=f"catalog_{cat_filter}_{only_flagged}",
            disabled=not current_user.is_admin,
            num_rows="dynamic" if current_user.is_admin else "fixed",
            use_container_width=True,
            hide_index=True,
            height=520,
            column_config={
                "code": st.column_config.TextColumn("Mã", disabled=True, help="Tự sinh khi lưu"),
                "group": st.column_config.SelectboxColumn("Nhóm CNTT", options=group_codes, required=True),
                "name": st.column_config.TextColumn("Tên hạng mục chuẩn", required=True, width="large"),
                "unit": st.column_config.TextColumn("ĐVT"),
                "kind": st.column_config.SelectboxColumn("Loại", options=list(kinds_cfg), required=True,
                                                         help=" | ".join(f"{k}: {v}" for k, v in kinds_cfg.items())),
                "price": st.column_config.NumberColumn("Đơn giá tham chiếu (VNĐ)", min_value=0, format="%d", required=True),
                "aliases": st.column_config.TextColumn("Tên cũ / tên gọi khác (cách nhau bởi ;)", width="medium",
                                                       help="Dùng để tự nhận diện dòng ngân sách cũ hoặc file Excel"),
                "note": st.column_config.TextColumn("Ghi chú"),
            }
        )
        if current_user.is_admin and st.button("💾 Lưu Danh mục CNTT", type="primary"):
            kept = [it for it in catalog_all if not _in_view(it)]
            used = {it.get("code") for it in kept}
            saved, errors = [], []
            for _, r in edited_cat.iterrows():
                name = str(r.get("name") or "").strip()
                if not name:
                    continue
                group = r.get("group") if r.get("group") in group_codes else (cat_filter if cat_filter in group_codes else None)
                if not group:
                    errors.append(name)
                    continue
                kind = r.get("kind") if r.get("kind") in kinds_cfg else next(g["kind"] for g in groups_cfg if g["code"] == group)
                saved.append({
                    "code": str(r.get("code") or "").strip(), "group": group, "name": name,
                    "unit": str(r.get("unit") or "").strip(), "kind": kind,
                    "price": int(clean_number(r.get("price"), 0)),
                    "aliases": [a.strip() for a in str(r.get("aliases") or "").split(";") if a.strip()],
                    "note": str(r.get("note") or "").strip(),
                })
                orig = next((it for it in catalog_all if it.get("code") == saved[-1]["code"] and saved[-1]["code"]), None)
                for extra_key in ("scope", "owner", "cost_lv2", "useful_months"):  # thuộc tính riêng không hiện trên bảng
                    if orig and orig.get(extra_key) not in (None, ""):
                        saved[-1][extra_key] = orig[extra_key]
            if errors:
                st.error(f"Chưa chọn nhóm CNTT cho: {', '.join(errors)}")
            else:
                # Sinh mã cho hạng mục mới / đổi nhóm: <nhóm>-<số thứ tự>
                for it in saved:
                    if not it["code"].startswith(it["group"] + "-") or it["code"] in used:
                        n = 1
                        while f"{it['group']}-{n:03d}" in used:
                            n += 1
                        it["code"] = f"{it['group']}-{n:03d}"
                    used.add(it["code"])
                order = {c: i for i, c in enumerate(group_codes)}
                master["standard_items"] = sorted(kept + saved, key=lambda it: (order.get(it["group"], 99), it["code"]))
                save_master_data(master)
                st.session_state["flash"] = f"Đã lưu Danh mục CNTT ({len(master['standard_items'])} hạng mục)."
                st.rerun()

        with st.expander("🗂️ Nhóm CNTT & quy tắc hạch toán"):
            df_groups = pd.DataFrame(groups_cfg, columns=["code", "name", "kind", "scope", "owner", "asset_cat1", "cost_lv2", "useful_months"])
            edited_groups = st.data_editor(
                df_groups,
                key="it_groups_editor",
                disabled=not current_user.is_admin,
                num_rows="dynamic" if current_user.is_admin else "fixed",
                use_container_width=True,
                hide_index=True,
                column_config={
                    "code": st.column_config.TextColumn("Mã nhóm", required=True),
                    "name": st.column_config.TextColumn("Tên nhóm CNTT", required=True, width="medium"),
                    "kind": st.column_config.SelectboxColumn("Loại mặc định", options=list(kinds_cfg), required=True),
                    "scope": st.column_config.SelectboxColumn("Phạm vi", options=list(SCOPE_LABELS),
                                                              help=" | ".join(f"{k}: {v}" for k, v in SCOPE_LABELS.items())),
                    "owner": st.column_config.TextColumn("Phòng phụ trách (hạ tầng)"),
                    "asset_cat1": st.column_config.SelectboxColumn("Loại tài sản cấp 1",
                                                                   options=[c["name"] for c in master.get("asset_cat1", [])]),
                    "cost_lv2": st.column_config.SelectboxColumn("Loại chi phí cấp 2", options=master.get("cost_lv2", []), width="medium"),
                    "useful_months": st.column_config.NumberColumn("Thời gian phân bổ / khấu hao (tháng)", min_value=1, step=1),
                }
            )
            threshold = st.number_input("Ngưỡng nguyên giá ghi nhận TSCĐ (VNĐ / đơn vị)", min_value=0,
                                        value=int(master.get("tscd_threshold", 30_000_000)), step=1_000_000,
                                        disabled=not current_user.is_admin)
            st.caption("Phần mềm thuê bao luôn ghi nhận loại tài sản E & chi phí 04.04; phần cứng/linh kiện ghi nhận D & chi phí theo nhóm.")
            if current_user.is_admin and st.button("💾 Lưu Nhóm CNTT"):
                master["it_groups"] = [
                    {k: (int(v) if k == "useful_months" else v) for k, v in r.items()
                     if not (v is None or (isinstance(v, float) and pd.isna(v)) or v == "")}
                    for r in edited_groups.dropna(subset=["code", "name"]).to_dict(orient="records")]
                master["tscd_threshold"] = int(threshold)
                save_master_data(master)
                st.session_state["flash"] = "Đã lưu Nhóm CNTT & quy tắc hạch toán."
                st.rerun()

        with st.expander("🎒 Bộ trang bị tiêu chuẩn theo vị trí (dùng tính định biên)"):
            st.caption("Mỗi dòng: 1 hạng mục trong bộ trang bị của 1 vị trí và số lượng cho 1 nhân sự "
                       "(số lẻ = dùng chung, vd. 0,1 máy in/người = 1 máy/10 người; kết quả làm tròn lên theo phòng ban).")
            kit_items_label = {it["code"]: f"{it['code']} · {it['name']}" for it in master.get("standard_items", []) if it.get("code")}
            kit_label_to_code = {v: k for k, v in kit_items_label.items()}
            df_kits = pd.DataFrame([{"kit_code": k["code"], "kit_name": k["name"],
                                     "item": kit_items_label.get(i["catalog_code"], i["catalog_code"]),
                                     "qty_per_person": i["qty_per_person"]}
                                    for k in qt.standard_kits(master) for i in k["items"]],
                                   columns=["kit_code", "kit_name", "item", "qty_per_person"])
            edited_kits = st.data_editor(
                df_kits, key="kits_editor", disabled=not current_user.is_admin,
                num_rows="dynamic" if current_user.is_admin else "fixed", use_container_width=True, hide_index=True,
                column_config={
                    "kit_code": st.column_config.TextColumn("Mã bộ", required=True),
                    "kit_name": st.column_config.TextColumn("Vị trí / tên bộ trang bị", required=True, width="medium"),
                    "item": st.column_config.SelectboxColumn("Hạng mục", options=list(kit_items_label.values()), required=True, width="large"),
                    "qty_per_person": st.column_config.NumberColumn("Số lượng / người", min_value=0.0, step=0.1, format="%.2f", required=True),
                })
            if current_user.is_admin and st.button("💾 Lưu Bộ trang bị tiêu chuẩn"):
                kits_out = {}
                for _, r in edited_kits.iterrows():
                    code = str(r.get("kit_code") or "").strip()
                    item_code = kit_label_to_code.get(r.get("item"))
                    if not code or not item_code:
                        continue
                    kit = kits_out.setdefault(code, {"code": code, "name": str(r.get("kit_name") or code).strip(), "items": []})
                    kit["items"].append({"catalog_code": item_code, "qty_per_person": float(clean_number(r.get("qty_per_person"), 0))})
                master["standard_kits"] = list(kits_out.values())
                save_master_data(master)
                st.session_state["flash"] = f"Đã lưu {len(kits_out)} bộ trang bị tiêu chuẩn."
                st.rerun()

    with m_sub2:
        c_ent, c_site = st.columns(2)
        with c_ent:
            st.markdown("##### Danh sách Pháp nhân (Entities)")
            df_ent_m = pd.DataFrame(master.get("entities", []))
            st.dataframe(df_ent_m, use_container_width=True, hide_index=True)
        with c_site:
            st.markdown("##### Danh sách Nhà máy / Vị trí (Sites)")
            df_site_m = pd.DataFrame(master.get("sites", []))
            st.dataframe(df_site_m, use_container_width=True, hide_index=True)

    with m_sub3:
        c_cat1, c_cat2 = st.columns(2)
        with c_cat1:
            st.markdown("##### Loại tài sản cấp 1")
            df_cat1_m = pd.DataFrame(master.get("asset_cat1", []))
            st.dataframe(df_cat1_m, use_container_width=True, hide_index=True)
        with c_cat2:
            st.markdown("##### Loại chi phí cấp 1 & 2")
            st.write("**Cấp 1:**", master.get("cost_lv1", []))
            with st.expander("Chi tiết Loại chi phí cấp 2"):
                st.write(master.get("cost_lv2", []))

# FOOTER
st.markdown("---")
st.markdown("""
<div style="text-align:center; color:#94A3B8; font-size:12px;">
    Hệ thống Quản lý & Tính toán Ngân sách Đầu tư CAPEX © 2026 - Công ty Cổ phần Cơ khí Xây dựng Thương mại Đại Dũng (DDC)
</div>
""", unsafe_allow_html=True)
