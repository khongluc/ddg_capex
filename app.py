"""
HỆ THỐNG QUẢN LÝ & TÍNH TOÁN NGÂN SÁCH ĐẦU TƯ CAPEX
"""
import os
import html as _html
import datetime
import pandas as pd
import numpy as np
import streamlit as st

import auth
import db
from master_data import (
    load_master_data,
    division_of,
    fiscal_months,
    find_catalog_item,
    apply_it_catalog,
    classify_item,
    KIND_SW_PERPETUAL,
    KIND_SW_SUBSCRIPTION,
)
import quota as qt
import reports
import ui.styles
import ui.admin
import ui.dept_workflow
import ui.dialogs
import ui.price_update
import ui.tab_appraisal
import ui.tab_dashboard
import ui.tab_excel
import ui.tab_exec
import ui.tab_infra
import ui.tab_input
import ui.tab_master
import ui.tab_quota
import ui.tab_scenario
import ui.tab_software
import ui.tab_versions
import workflow as wf
import validators
import headcount_import as hi
from capex_engine import (
    load_capex_from_excel,
    export_capex_to_excel,
    calculate_row,
    assign_item_seqs,
    even_units,
    phase_presets,
)

from types import SimpleNamespace


def app_context() -> SimpleNamespace:
    """Giá trị dùng chung của lượt chạy cho các tab trong ui/ (cấu hình, dữ liệu site / phòng ban, quyền, hàm hỗ trợ).
    Mỗi tab tự lấy đúng tên cần dùng ở đầu render(ctx) - nhìn đó biết tab phụ thuộc gì."""
    return SimpleNamespace(**globals())


# Page configuration
st.set_page_config(
    page_title="Hệ thống ngân sách",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for executive corporate look
ui.styles.inject()

# Format currency helper
# Định dạng số tiền: phân cách hàng nghìn theo nhóm 3 chữ số.
# Bảng (data_editor/dataframe) dùng định dạng "localized" của trình duyệt -> chữ trong app cũng theo
# cùng ngôn ngữ trình duyệt để thống nhất: tiếng Việt 1.234.567,89 – tiếng Anh 1,234,567.89.
MONEY_FMT = "localized"


def _vi_locale() -> bool:
    try:
        return str(st.context.locale or "").lower().startswith("vi")
    except Exception:
        return False


def fmt_num(x, decimals: int = 0) -> str:
    """Số có phân cách hàng nghìn (theo ngôn ngữ trình duyệt)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        x = 0.0
    if pd.isna(x):
        x = 0.0
    out = f"{x:,.{decimals}f}"
    if _vi_locale():
        out = out.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return out


def plot_separators() -> str:
    """Ký tự thập phân + nghìn cho Plotly."""
    return ",." if _vi_locale() else ".,"


def format_vnd(amount: float) -> str:
    """Format money into VND with billions notation"""
    if amount is None or pd.isna(amount):
        return "0 VNĐ"
    amount = float(amount)
    if abs(amount) >= 1_000_000_000:
        return f"{fmt_num(amount)} VNĐ ({fmt_num(amount / 1e9, 2)} tỷ)"
    elif abs(amount) >= 1_000_000:
        return f"{fmt_num(amount)} VNĐ ({fmt_num(amount / 1e6, 2)} tr)"
    return f"{fmt_num(amount)} VNĐ"

def plot_chart(fig, **kw):
    fig.update_layout(
        template="plotly_white",
        colorway=ui.styles.CHART_COLORS,
        separators=plot_separators(),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif", size=12, color="#334155"),
        hoverlabel=dict(
            bgcolor="#0F2C59",
            font_size=12,
            font_family="Inter, sans-serif",
            font_color="#FFFFFF"
        )
    )
    try:
        fig.update_xaxes(gridcolor="rgba(226, 232, 240, 0.7)", zerolinecolor="rgba(203, 213, 225, 0.8)")
        fig.update_yaxes(gridcolor="rgba(226, 232, 240, 0.7)", zerolinecolor="rgba(203, 213, 225, 0.8)")
    except Exception:
        pass
    st.plotly_chart(fig, **kw)


def format_vnd_short(amount: float) -> str:
    """Short format for charts"""
    if amount is None or pd.isna(amount):
        return "0"
    amount = float(amount)
    if abs(amount) >= 1_000_000_000:
        return f"{fmt_num(amount / 1e9, 2)} tỷ"
    elif abs(amount) >= 1_000_000:
        return f"{fmt_num(amount / 1e6, 1)} tr"
    return fmt_num(amount)

# =====================================================================
# ĐĂNG NHẬP & PHÂN QUYỀN
# =====================================================================
current_user = auth.require_login()

master = load_master_data()
DEFAULT_CONTINGENCY = 0.05  # dự phòng phát sinh mặc định 5% trên tổng hạng mục


def contingency_pct() -> float:
    """Tỷ lệ dự phòng phát sinh của ngân sách CAPEX thường niên (Admin chỉnh ở tab Quản lý Danh mục)."""
    try:
        v = float(master.get("contingency_pct", DEFAULT_CONTINGENCY))
    except (TypeError, ValueError):
        v = DEFAULT_CONTINGENCY
    return min(max(v, 0.0), 0.5)


SITES = master.get("sites", [])
SITE_NAME = {s["code"]: s["name"] for s in SITES}
SITE_BY_NAME = {s["name"]: s["code"] for s in SITES}
def resolve_template_path(filename: str) -> str:
    for sub in ("templates", "data/templates", ""):
        p = os.path.join(os.path.dirname(__file__), sub, filename) if sub else os.path.join(os.path.dirname(__file__), filename)
        if os.path.exists(p):
            return p
    return os.path.join(os.path.dirname(__file__), "templates", filename)

ALL_SITES = "__ALL__"
SAMPLE_EXCEL_PATH = resolve_template_path("2. Form file nhập liệu CAPEX 2026.xlsx")


def site_label(code: str) -> str:
    if code == ALL_SITES:
        return "Tất cả site được xem"
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


def save_site(df: pd.DataFrame, site_code: str, allow_locked: bool = False, base=None, overwrite: bool = False):
    """Lưu dòng ngân sách 1 site. Mặc định GỘP theo Mã hạng mục so với bản người dùng đã xem (base, mặc định là bản tải
    lúc mở trang): chỉ áp dòng họ thêm / sửa / xóa, giữ thay đổi người khác vừa lưu, báo xung đột. Cả bước đọc - gộp - ghi
    nằm trong 1 giao dịch khóa site. overwrite=True: thay toàn bộ site (nạp dữ liệu mẫu / nhập Excel cho nhiều site)."""
    if current_user.is_dept_user:  # phòng ban chỉ lưu được dòng của phòng mình
        allowed = {dept_key(d) for d in current_user.allowed_depts(site_code)}
        df = df[df["dept_proposing"].map(dept_key).isin(allowed)] if "dept_proposing" in df.columns else df.iloc[0:0]
        overwrite = False
    new_rows = rows_for_site(df, site_code, months, year_code)
    if base is None and not overwrite:
        base = SITE_BASE.get(site_code)
    if base is None and not overwrite:  # không có bản đã xem -> coi như đọc ngay trước khi lưu
        base = [{k: v for k, v in l.items() if k != "site_code"} for l in db.load_lines(budget_year, [site_code])]
    if current_user.is_dept_user and base is not None:  # bản đã xem của phòng ban = chỉ dòng phòng mình
        base = [r for r in base if dept_key(r.get("dept_proposing")) in allowed]
    locked = set() if allow_locked else {k for k, v in db.dept_statuses(budget_year, site_code).items()
                                         if v["status"] in db.DEPT_LOCKED_STATUSES}
    notes = {}

    def _merge(current, counters):
        if overwrite:
            rows, conflicts = list(new_rows), []
        else:
            rows, conflicts = wf.merge_site_rows(base, new_rows, current)
        rows, ignored = wf.keep_locked_rows(rows, current, locked)
        counters = assign_item_seqs(rows, counters)
        notes.update(conflicts=conflicts, ignored=ignored)
        return rows, counters

    rows = db.merge_site_lines(budget_year, site_code, _merge, actor=current_user.email)
    warn = []
    if notes.get("conflicts"):
        c = notes["conflicts"]
        warn.append(f"{len(c)} dòng vừa được người khác cập nhật nên không lưu thay đổi của bạn (bảng đã tải lại bản mới): "
                    + "; ".join(c[:5]) + (f"; … và {len(c) - 5} dòng khác" if len(c) > 5 else ""))
    if notes.get("ignored"):
        warn.append("Giữ nguyên dòng của phòng ban đã nộp/duyệt (IT site trả lại hoặc mở lại mới sửa được): "
                    + ", ".join(sorted(notes["ignored"])))
    if warn:
        st.session_state["flash_warn"] = " | ".join(warn)
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
    if site_code in SITE_BASE:  # lần lưu tiếp theo trong cùng lượt chạy dựa trên bản vừa ghi
        SITE_BASE[site_code] = [dict(r) for r in rows]
    return rows


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
    meta = {**meta, "contingency_pct": contingency_pct()}
    data = _cached_export(df.drop(columns=["_order"], errors="ignore").reset_index(drop=True),
                          tuple(sorted((k, str(v)) for k, v in meta.items())), tuple(months))
    if st.download_button(label, data=data, file_name=file_name, mime=XLSX_MIME, use_container_width=True,
                          key=f"xl_dl_{key}", help=help_text):
        st.session_state[flag] = False
    return data


def lazy_download_button(label: str, data_fn, file_name: str, key: str, mime: str = XLSX_MIME, help_text: str = None):
    """Chỉ gọi data_fn tạo file khi người dùng bấm 'Chuẩn bị' (tránh chạy openpyxl ở mỗi lượt chạy trang)."""
    flag = f"lazy_ready_{key}"
    if not st.session_state.get(flag):
        if st.button(f"📦 Chuẩn bị {label}", key=f"lazy_prep_{key}", use_container_width=True, help=help_text):
            st.session_state[flag] = True
            st.rerun()
        return None
    data = data_fn()
    if st.download_button(label, data=data, file_name=file_name, mime=mime, use_container_width=True,
                          key=f"lazy_dl_{key}", help=help_text):
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


# Bộ lọc theo hạng mục: (nhãn, cột dữ liệu); cột "_item_label" ghép mã danh mục + tên hạng mục
ITEM_FILTERS = [("Nhóm CNTT", "it_group"), ("Hạng mục", "_item_label"),
                ("Loại nhu cầu", "need_type"), ("CAPEX / CCDC / OPEX", "capex_type")]
FILTER_BLANK = "(Trống)"


def filter_values(df: pd.DataFrame, col: str) -> pd.Series:
    """Giá trị dùng để lọc của 1 cột (ô trống -> '(Trống)')."""
    if col == "_item_label":
        name = df["item_name"].fillna("").astype(str).str.strip() if "item_name" in df.columns else pd.Series("", index=df.index)
        code = df["catalog_code"].fillna("").astype(str).str.strip() if "catalog_code" in df.columns else pd.Series("", index=df.index)
        s = code.where(code == "", code + " · ") + name
    elif col in df.columns:
        s = df[col].fillna("").astype(str).str.strip()
    else:
        s = pd.Series("", index=df.index)
    return s.replace("", FILTER_BLANK)


def item_filter_widgets(df: pd.DataFrame, key_prefix: str, cols=None) -> pd.Series:
    """Hàng multiselect lọc theo hạng mục; trả về mask (True = giữ dòng). Không chọn gì = không lọc."""
    mask = pd.Series(True, index=df.index)
    boxes = cols or st.columns(len(ITEM_FILTERS))
    for box, (label, col) in zip(boxes, ITEM_FILTERS):
        vals = filter_values(df, col)
        opts = sorted(vals.unique().tolist(), key=lambda v: (v == FILTER_BLANK, v))
        k = f"{key_prefix}_{col}"
        if k in st.session_state:
            st.session_state[k] = [v for v in st.session_state[k] if v in opts]
        chosen = box.multiselect(f"Lọc theo {label}", opts, key=k, placeholder="Tất cả")
        if chosen:
            mask &= vals.isin(chosen)
    return mask


def dept_state(dept: str) -> dict:
    """Trạng thái duyệt của 1 phòng ban ở site đang chọn (mặc định Đang lập)."""
    return dept_status_map.get(dept_key(dept)) or {"status": db.STATUS_DRAFT, "note": None, "updated_by": None, "updated_at": None}


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


def render_dept_workflow(dept: str, rows: pd.DataFrame):
    return ui.dept_workflow.render_dept_workflow(app_context(), dept, rows)


def render_dept_overview():
    return ui.dept_workflow.render_dept_overview(app_context())


def render_price_update():
    return ui.price_update.render_price_update(app_context())


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


def code_version() -> str:
    """Commit đang chạy (đọc .git, không gọi lệnh ngoài) - để biết bản online đã lấy code mới chưa."""
    root = os.path.dirname(os.path.abspath(__file__))
    try:
        def _read(*parts):
            with open(os.path.join(root, ".git", *parts), encoding="utf-8") as f:
                return f.read()

        head = _read("HEAD").strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1].strip()
            if os.path.exists(os.path.join(root, ".git", *ref.split("/"))):
                return _read(*ref.split("/")).strip()[:7]
            for line in _read("packed-refs").splitlines():
                if line.strip().endswith(" " + ref):
                    return line.split(" ", 1)[0][:7]
            return "?"
        return head[:7]
    except OSError:
        return "?"


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
    # Thông tin người dùng
    user_initials = "".join([p[0].upper() for p in (current_user.name or "U").split() if p])[:2] or "U"
    role_key = current_user.role
    role_badge_class = {
        db.ROLE_ADMIN: "role-badge-admin",
        db.ROLE_SITE_IT: "role-badge-it",
        db.ROLE_DEPT: "role-badge-dept",
        db.ROLE_VIEWER: "role-badge-viewer"
    }.get(role_key, "role-badge-viewer")

    st.markdown(f"""
    <div class="user-profile-card">
        <div class="user-avatar-circle">{user_initials}</div>
        <div class="user-info-text">
            <div class="user-name">{_html.escape(current_user.name)}</div>
            <div class="user-email">{_html.escape(current_user.email)}</div>
            <div><span class="role-badge {role_badge_class}">{db.ROLE_LABELS.get(current_user.role, current_user.role)}</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    if current_user.is_admin:
        st.caption("CSDL: " + ("PostgreSQL (lưu bền)" if db.using_server_db() else "SQLite (file cục bộ)")
                   + f" · Phiên bản code: {code_version()}")
    if st.button("🚪 Đăng xuất", use_container_width=True):
        auth.logout()

    if current_user.is_admin:
        admin_view = st.radio("Màn hình", ["Ngân sách", "Phân quyền & Tiến độ"], key="admin_view",
                              help="Phân quyền người dùng, tiến độ các site, nhật ký, sao lưu / khôi phục")
    else:
        admin_view = "Ngân sách"

    st.markdown("### Thiết lập Ngân sách")

    budget_year = st.selectbox("Năm ngân sách", ["2027", "2026", "2025"], index=0)
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
    _site_raw = db.load_lines(budget_year, scope_sites)
    df_site = pd.DataFrame(_site_raw)
    if selected_site != ALL_SITES and "site_code" in df_site.columns:
        df_site = df_site.drop(columns=["site_code"])
    if current_user.is_dept_user and selected_site != ALL_SITES and "dept_proposing" in df_site.columns:
        _allowed = {dept_key(d) for d in current_user.allowed_depts(selected_site)}
        df_site = df_site[df_site["dept_proposing"].map(dept_key).isin(_allowed)].reset_index(drop=True)
        _site_raw = [r for r in _site_raw if dept_key(r.get("dept_proposing")) in _allowed]
    df_site["_order"] = range(len(df_site))
    # Bản người dùng đang xem (đúng phạm vi họ thấy): khi lưu chỉ áp thay đổi so với bản này, không ghi đè cả site
    SITE_BASE = {selected_site: [{k: v for k, v in r.items() if k != "site_code"} for r in _site_raw]} if selected_site != ALL_SITES else {}

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
    # Ô chọn ở thanh bên và ô chọn trong tab Lập & Nhập liệu dùng chung 1 phòng ban (đồng bộ 2 chiều)
    sb_dept_options = ([] if current_user.is_dept_user else [ALL_DEPTS]) + dept_list
    _pending_dept = st.session_state.pop("pending_dept", None)  # phòng ban vừa sửa trong popup
    if _pending_dept in sb_dept_options:
        st.session_state["sb_dept"] = _pending_dept
        st.session_state["active_dept_selector"] = _pending_dept
    if st.session_state.get("sb_dept") not in sb_dept_options:
        st.session_state.pop("sb_dept", None)

    def _sync_dept_from_sidebar():
        if st.session_state.get("sb_dept") not in (None, ALL_DEPTS):
            st.session_state["active_dept_selector"] = st.session_state["sb_dept"]

    selected_dept = st.selectbox("Phòng ban lập ngân sách", sb_dept_options, key="sb_dept", on_change=_sync_dept_from_sidebar,
                                 help="Lọc bảng & báo cáo theo phòng ban đề xuất. Dòng thêm mới được gán cho phòng ban này.")
    dept_prop = selected_dept if selected_dept != ALL_DEPTS else "Tất cả phòng ban"

    # Nộp & duyệt theo phòng ban
    site_can_edit = can_edit
    dept_status_map = db.dept_statuses(budget_year, selected_site) if selected_site != ALL_SITES else {}
    can_review = (selected_site != ALL_SITES and site_status["status"] in db.EDITABLE_STATUSES
                  and (current_user.is_admin or (current_user.role == db.ROLE_SITE_IT and selected_site in current_user.sites)))
    if selected_dept != ALL_DEPTS and selected_site != ALL_SITES:
        _ds = dept_state(selected_dept)
        st.markdown(f"**Phòng ban:** {db.DEPT_STATUS_LABELS.get(_ds['status'], _ds['status'])}")
        if _ds.get("note"):
            st.caption(f"Ghi chú duyệt: {_ds['note']}")
        if _ds["status"] in db.DEPT_LOCKED_STATUSES:
            can_edit = False  # phòng đã nộp / đã duyệt: khóa sửa

    st.markdown("---")
    st.markdown("#### Thông tin Đề xuất")
    meta = st.session_state.setdefault("metadata", _default_metadata())  # có thể vừa bị xóa (đăng xuất) trong lượt chạy này
    creator_name = st.text_input("Họ và tên người lập", value=meta.get("creator_name") or current_user.name)
    creator_email = st.text_input("Email người lập", value=current_user.email, disabled=True)
    plan_date = st.date_input("Ngày lập", value=datetime.date.today())

    st.session_state["metadata"]["proposing_dept"] = dept_prop
    st.session_state["metadata"]["creator_name"] = creator_name
    st.session_state["metadata"]["creator_email"] = creator_email
    st.session_state["metadata"]["date"] = plan_date.strftime("%Y-%m-%d")
    st.session_state["metadata"]["budget_year"] = budget_year

    st.markdown("---")
    st.markdown("#### Hành động Nhanh")
    if st.button("🔄 Làm mới", use_container_width=True):
        st.rerun()
    if site_can_edit and not current_user.is_dept_user:
        with st.popover("Xóa toàn bộ dòng của site", use_container_width=True):
            st.warning(f"Xóa toàn bộ hạng mục năm {budget_year} của {site_label(selected_site)}?")
            if st.button("Xác nhận xóa", type="primary"):
                save_site(pd.DataFrame(), selected_site)  # dòng của phòng ban đã nộp/duyệt được giữ lại
                st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
                st.rerun()

    if current_user.is_admin and os.path.exists(SAMPLE_EXCEL_PATH):
        st.markdown("##### Nạp ngân sách cơ sở (Admin)")
        st.caption("Đọc file CAPEX và phân các dòng về đúng site theo cột Vị trí (ghi đè dữ liệu các site có trong file).")
        seed_sheet = st.selectbox("Sheet nguồn", ["CA.01_CAPEX (2)", "CA.01_CAPEX"])
        if st.button("Nạp & phân về các site", use_container_width=True):
            _, seed_df = load_capex_from_excel(SAMPLE_EXCEL_PATH, seed_sheet, months=months, year_code=year_code)
            groups, unmatched = distribute_by_location(seed_df)
            for code, part in groups.items():
                save_site(part, code, overwrite=True)
            st.session_state["flash"] = (f"Đã nạp {sum(len(p) for p in groups.values())} dòng vào {len(groups)} site."
                                         + (f" Bỏ qua vị trí không khớp danh mục: {unmatched}" if unmatched else ""))
            st.rerun()

# Dữ liệu hiện hành theo site + phòng ban được chọn
df_curr = df_site[dept_mask(df_site, selected_dept)].reset_index(drop=True)


@st.cache_data(max_entries=16)
def _cached_prev_lines(prev_year: str, scope_sites_tuple: tuple) -> list:
    return db.load_lines(prev_year, list(scope_sites_tuple))


def prev_year_lines() -> pd.DataFrame:
    """Dòng ngân sách năm trước cùng phạm vi site + phòng ban (để so sánh)."""
    prev = pd.DataFrame(_cached_prev_lines(str(int(budget_year) - 1), tuple(scope_sites)))
    if prev.empty:
        return prev
    if current_user.is_dept_user and "dept_proposing" in prev.columns:
        allowed = {dept_key(d) for d in current_user.allowed_depts(selected_site)}
        prev = prev[prev["dept_proposing"].map(dept_key).isin(allowed)]
    return prev[dept_mask(prev, selected_dept)].reset_index(drop=True)


@st.cache_data(max_entries=8, show_spinner="Đang tạo báo cáo theo Khối...")
def _cached_division_report(df: pd.DataFrame, prev: pd.DataFrame, meta_items: tuple) -> bytes:
    return reports.report_xlsx(df, prev, master, dict(meta_items))


@st.cache_data(max_entries=8, show_spinner="Đang tạo Kế hoạch Mua sắm theo Tháng / Quý...")
def _cached_purchasing_plan_report(df: pd.DataFrame, months_tuple: tuple, meta_items: tuple) -> bytes:
    return reports.purchasing_plan_xlsx(df, list(months_tuple), dict(meta_items))

# MAIN HEADER BANNER
if selected_site == ALL_SITES:
    status_pill_html = '<span class="header-status-pill status-pill-all">🌐 Tổng hợp tất cả site</span>'
else:
    status_code = site_status["status"] if site_status else db.STATUS_DRAFT
    status_lbl = db.STATUS_LABELS.get(status_code, status_code)
    pill_cls = {
        db.STATUS_DRAFT: "status-pill-draft",
        db.STATUS_SUBMITTED: "status-pill-submitted",
        db.STATUS_APPROVED: "status-pill-approved",
        db.STATUS_RETURNED: "status-pill-returned",
    }.get(status_code, "status-pill-draft")
    status_pill_html = f'<span class="header-status-pill {pill_cls}">{status_lbl}</span>'

st.markdown(f"""
<div class="main-header">
    <div class="header-top-row">
        <div class="header-brand-title">
            <div class="header-title-text">
                <div class="sub-corp">Ngân sách đầu tư CNTT · Năm tài chính T10/{int(budget_year) - 1} – T9/{budget_year}</div>
                <h1>Ngân sách CAPEX thường niên {budget_year}</h1>
            </div>
        </div>
        <div>
            {status_pill_html}
        </div>
    </div>
    <div class="header-meta-chips">
        <span class="meta-chip">Site: <strong>{site_label(selected_site)}</strong></span>
        <span class="meta-chip">Đơn vị đề xuất: <strong>{_html.escape(dept_prop)}</strong></span>
        <span class="meta-chip">Người lập: <strong>{_html.escape(creator_name or 'Chưa nhập')}</strong></span>
        <span class="meta-chip">Ngày: <strong>{meta.get('date', '')}</strong></span>
    </div>
</div>
""", unsafe_allow_html=True)

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"), icon="✅")
if "flash_warn" in st.session_state:
    # Cảnh báo (vd. thay đổi bị bỏ qua vì phòng đã khóa, phòng chưa duyệt được) giữ cố định - toast tự tắt dễ bị bỏ lỡ
    st.warning(st.session_state.pop("flash_warn"), icon="⚠️")

# THANH TRẠNG THÁI NỘP / DUYỆT NGÂN SÁCH SITE
if selected_site != ALL_SITES:
    status = site_status["status"]
    ribbon_cls = {
        db.STATUS_DRAFT: "status-ribbon-draft",
        db.STATUS_SUBMITTED: "status-ribbon-submitted",
        db.STATUS_APPROVED: "status-ribbon-approved",
        db.STATUS_RETURNED: "status-ribbon-returned",
    }.get(status, "status-ribbon-draft")

    # HTML 1 dòng, không thụt lề: dòng trắng / thụt lề trong st.markdown làm phần còn lại hiện thành khung code
    _upd = (f"Cập nhật bởi {_html.escape(str(site_status['updated_by']))} lúc {_html.escape(str(site_status['updated_at']))}"
            if site_status.get("updated_at") else "Chưa ghi nhận cập nhật")
    if not site_can_edit and status not in db.EDITABLE_STATUSES and not current_user.is_admin:
        _upd += "  |  🔒 Đang khóa chỉnh sửa"
    if current_user.role == db.ROLE_VIEWER:
        _upd += "  |  👁️ Tài khoản chỉ có quyền xem"
    st.markdown(
        f'<div class="status-ribbon-card {ribbon_cls}"><div>'
        f'<div style="font-size:13px;font-weight:700;color:#0F2C59;">Trạng thái ngân sách {budget_year} – {_html.escape(site_label(selected_site))}:'
        f'<span style="color:#1D4ED8;margin-left:4px;">{db.STATUS_LABELS.get(status, status)}</span></div>'
        f'<div style="font-size:12px;color:#64748B;margin-top:2px;">{_upd}</div>'
        f'</div></div>', unsafe_allow_html=True)

    invalid_rows = int((~df_site["pct_valid"].fillna(False).astype(bool)).sum()) if "pct_valid" in df_site.columns else 0
    if current_user.is_dept_user and status in db.EDITABLE_STATUSES:
        st.caption("Lập xong, bấm **📨 Nộp phòng ban** ở tab Lập & Nhập liệu để IT site duyệt.")
    site_pending = wf.pending_depts(wf.dept_overview(df_site, dept_status_map)) if selected_site != ALL_SITES else []
    if status in db.EDITABLE_STATUSES and site_can_edit and not current_user.is_dept_user:
        if site_pending:
            st.caption(f"Còn {len(site_pending)} phòng ban chưa duyệt - duyệt đủ mới nộp được site "
                       "(xem bảng Tiến độ phòng ban ở tab Lập & Nhập liệu, chọn Tất cả phòng ban).")
        site_val = validators.validate_budget_rows(df_site, months=months, master=master)
        btn_disabled = df_site.empty or bool(site_pending) or not site_val.is_valid
        if not site_val.is_valid:
            btn_help = f"Chưa đủ điều kiện nộp site: còn {site_val.critical_count} lỗi critical ({'; '.join(site_val.summary_messages[:2])})"
        else:
            btn_help = "Nộp toàn bộ ngân sách của site (tất cả phòng ban đã được IT site duyệt)"
        if site_val.warning_count > 0 and site_val.is_valid:
            st.caption(f"Lưu ý: Toàn site còn {site_val.warning_count} cảnh báo rà soát (vẫn cho phép nộp).")
        if st.button("📨 Nộp ngân sách site để duyệt", use_container_width=True, disabled=btn_disabled,
                     help=btn_help):
            if not site_val.is_valid:
                st.error("Chưa đủ điều kiện nộp ngân sách site: " + "; ".join(site_val.summary_messages))
            else:
                db.set_status(budget_year, selected_site, db.STATUS_SUBMITTED, current_user.email)
                st.rerun()
    if current_user.is_admin and status == db.STATUS_SUBMITTED:
        note = st.text_input("Ghi chú duyệt / trả lại", key="approve_note")
        ac1, ac2 = st.columns(2)
        if ac1.button("✅ Phê duyệt ngân sách", use_container_width=True, type="primary"):
            db.set_status(budget_year, selected_site, db.STATUS_APPROVED, current_user.email, note)
            rev_key = f"rev_reason|{budget_year}|{selected_site}"
            ver = db.save_version(budget_year, selected_site, db.load_lines(budget_year, [selected_site]), current_user.email,
                                  reason=db.get_setting(rev_key) or note)
            db.set_setting(rev_key, "")
            st.session_state["flash"] = (f"Đã duyệt ngân sách {site_label(selected_site)} và chốt phiên bản v{ver['version_no']} "
                                         f"({ver['label']}, {ver['n_lines']} dòng, {format_vnd(ver['total'])}).")
            st.rerun()
        if ac2.button("↩️ Trả lại yêu cầu chỉnh sửa", use_container_width=True):
            db.set_status(budget_year, selected_site, db.STATUS_RETURNED, current_user.email, note)
            st.rerun()
    if current_user.is_admin and status == db.STATUS_APPROVED:
        with st.popover("Mở điều chỉnh ngân sách", use_container_width=True):
            st.caption("Bản đã duyệt được giữ làm phiên bản để so sánh; theo dõi thực hiện vẫn tính theo bản duyệt cho tới khi duyệt bản điều chỉnh. "
                       "Các phòng ban giữ trạng thái đã duyệt - IT site mở lại đúng phòng cần điều chỉnh.")
            rev_reason = st.text_area("Lý do điều chỉnh (bắt buộc)", key="rev_reason_input")
            if st.button("Xác nhận mở điều chỉnh", type="primary", key="rev_open"):
                if not rev_reason.strip():
                    st.error("Ghi lý do điều chỉnh.")
                else:
                    db.set_setting(f"rev_reason|{budget_year}|{selected_site}", rev_reason.strip())
                    db.set_status(budget_year, selected_site, db.STATUS_DRAFT, current_user.email, f"Điều chỉnh: {rev_reason.strip()}")
                    st.session_state["flash"] = f"Đã mở điều chỉnh ngân sách {site_label(selected_site)}."
                    st.rerun()

# TABS NAVIGATION
tab_names = [
    "Tổng quan",
    "Lập CapEx",
    "Định biên",
    "Hạ tầng",
    "Phần mềm",
    "Nhập / Xuất",
    "Kịch bản",
    "Giải ngân",
    "Phiên bản",
    "Thẩm định",
    "Danh mục",
]
# =====================================================================
# TRANG QUẢN TRỊ: PHÂN QUYỀN & TIẾN ĐỘ (mở từ thanh bên, chỉ Admin)
# =====================================================================
def render_admin_page():
    return ui.admin.render_admin_page(app_context())


if current_user.is_admin and admin_view == "Phân quyền & Tiến độ":
    render_admin_page()
    st.stop()

tab_dash, tab_input, tab_quota, tab_infra, tab_software, tab_excel, tab_scenario, tab_exec, tab_versions, tab_depreciation, tab_master = st.tabs(tab_names)

# =====================================================================
# TAB 1: DASHBOARD
# =====================================================================
with tab_dash:
    ui.tab_dashboard.render(app_context())


def _commit_checklist_items(selected_items_df: pd.DataFrame, target_dept: str, target_site: str,
                            target_month: str, need_type: str, need_reason: str):
    ent_names = [e["name"] for e in master.get("entities", [])]
    target_ent = ent_names[0] if ent_names else "DDC"
    target_div = division_of(target_dept, master)
    target_loc = SITE_NAME.get(target_site, target_site)
    cat_all = master.get("standard_items", [])

    new_items_list = []
    for _, r_it in selected_items_df.iterrows():
        it_code = str(r_it.get("Mã", "")).strip()
        it_name = str(r_it.get("Tên thiết bị / Hạng mục", "")).strip()
        cat_it = next((x for x in cat_all if it_code and x.get("code") == it_code), None) or find_catalog_item(it_name, master)
        units = r_it.get("_units")
        units = units if isinstance(units, list) and len(units) == len(months) and sum(units) > 0 else None
        q = int(sum(units)) if units else int(r_it.get("Số lượng", 1))
        p = float(r_it.get("Đơn giá (VNĐ)", 0))
        note_txt = str(r_it.get("Ghi chú", "")).strip()

        row_dict = {
            "entity": target_ent,
            "division": target_div,
            "dept_proposing": target_dept,
            "dept_using": target_dept,
            "location": target_loc,
            "item_name": it_name,
            "detail_work": note_txt,
            "supplier": "",
            "quantity": q,
            "unit_price": p,
            "contract_date": "",
            "completion_date": "",
            "handover_date": "",
            "need_type": need_type,
            "need_reason": need_reason if need_type in qt.NEED_WITH_REASON else "",
        }
        for i, m in enumerate(months):  # phân kỳ theo SL nguyên từng tháng; không có -> cả SL vào 1 tháng
            row_dict[f"pct_{m}"] = units[i] / q if units else (1.0 if m == target_month else 0.0)

        inv = str(r_it.get("Hình thức") or "").strip() or None
        if cat_it:
            apply_it_catalog(row_dict, master, item=cat_it, invest_type=inv or "Mua mới")
        else:  # ngoài danh mục: hạch toán theo Nhóm CNTT + Loại người lập chọn (cùng quy tắc với danh mục)
            grp = str(r_it.get("Nhóm") or "").split(".")[0].strip()
            kind = str(r_it.get("Loại") or "").strip() or None
            cls = classify_item({"group": grp, "kind": kind}, master, inv) if grp else {}
            row_dict.update({k: v for k, v in cls.items() if k != "useful_months" and v})
            if cls:
                row_dict["useful_life"] = max(cls["useful_months"] / 12.0, 1.0)
            row_dict.update({"it_group": "(Ngoài danh mục)", "catalog_code": "",
                             "invest_type": inv or cls.get("invest_type") or "Mua mới",
                             "unit": str(r_it.get("ĐVT") or "").strip()})

        calc_row = calculate_row(row_dict, months=months, year_code=year_code, master=master)
        new_items_list.append(calc_row)

    current_stored_df = pd.DataFrame(db.load_lines(budget_year, [target_site]))
    if not current_stored_df.empty:
        current_stored_df = current_stored_df.drop(columns=["site_code"], errors="ignore")
    updated_df_all = pd.concat([current_stored_df, pd.DataFrame(new_items_list)], ignore_index=True)
    save_site(updated_df_all.reset_index(drop=True), target_site)
    total_cost = (selected_items_df["Số lượng"] * selected_items_df["Đơn giá (VNĐ)"]).sum()
    st.session_state["flash"] = f"Đã thêm thành công {len(new_items_list)} hạng mục vào ngân sách phòng ban '{target_dept}' ({format_vnd(total_cost)})!"
    st.session_state["pending_dept"] = target_dept
    st.rerun()


PHASE_ONE, PHASE_EVEN, PHASE_MANUAL = "1 tháng", "Chia đều nhiều tháng", "Tự nhập SL từng tháng"


def phasing_picker(sel_df: pd.DataFrame, key: str) -> tuple:
    """Popup: chọn cách phân kỳ cho các hạng mục đã chọn - cả SL vào 1 tháng, chia đều các tháng chọn, hoặc nhập SL từng tháng.
    Trả về (bảng có thêm cột _units = SL nguyên từng tháng và Số lượng = tổng, lỗi hoặc None)."""
    mode = st.radio("Phân kỳ mua:", [PHASE_ONE, PHASE_EVEN, PHASE_MANUAL], horizontal=True, key=f"{key}_mode",
                    help="Chia đều: SL nguyên chia đều các tháng chọn, dư dồn tháng sớm (10 máy / 4 quý = 3-3-2-2). "
                         "Tự nhập: gõ SL từng tháng, Số lượng = tổng các tháng.")
    out = sel_df.copy()
    qtys = [int(q) for q in pd.to_numeric(out.get("Số lượng", pd.Series(dtype=float)), errors="coerce").fillna(0)]
    names = out["Tên thiết bị / Hạng mục"].astype(str).tolist() if not out.empty else []
    if mode == PHASE_ONE:
        m1 = st.selectbox("Tháng sử dụng:", months, index=0, key=f"{key}_month")
        units = [[q if m == m1 else 0 for m in months] for q in qtys]
    elif mode == PHASE_EVEN:
        presets = phase_presets(months)
        pc1, pc2 = st.columns([1, 2.4])
        with pc1:
            pre = st.selectbox("Mẫu nhanh:", list(presets), index=2, key=f"{key}_preset")
        with pc2:
            chosen = st.multiselect("Các tháng mua:", months, default=presets[pre] or months[:1], key=f"{key}_months_{pre}")
        if not chosen:
            return out, "Chọn ít nhất 1 tháng mua."
        units = [even_units(q, months, chosen) or [0] * len(months) for q in qtys]
        if not out.empty:
            prev = pd.DataFrame([u for u in units], columns=months)
            prev.insert(0, "Hạng mục", names)
            st.dataframe(prev[["Hạng mục"] + [m for m in months if m in chosen]], hide_index=True, use_container_width=True)
            few = [n for n, q in zip(names, qtys) if 0 < q < len(chosen)]
            if few:
                st.caption("SL ít hơn số tháng, các tháng cuối không mua: " + ", ".join(few))
    else:
        if out.empty:
            return out, None
        grid = pd.DataFrame([[q if i == 0 else 0 for i in range(len(months))] for q in qtys], columns=months)
        grid.insert(0, "Hạng mục", names)
        sig = abs(hash(tuple(names))) % 10**8
        ed = st.data_editor(grid, key=f"{key}_grid_{sig}", hide_index=True, use_container_width=True,
                            column_config={"Hạng mục": st.column_config.TextColumn("Hạng mục", disabled=True, width="medium"),
                                           **{m: st.column_config.NumberColumn(m, min_value=0, step=1, format="%d") for m in months}})
        units = [[int(pd.to_numeric(v, errors="coerce") or 0) for v in ed.loc[i, months]] for i in ed.index]
        empty = [n for n, u in zip(names, units) if sum(u) <= 0]
        if empty:
            return out, "Nhập số lượng ít nhất 1 tháng cho: " + ", ".join(empty)
    if not out.empty:
        out["_units"] = pd.Series(units, index=out.index, dtype=object)
        out["Số lượng"] = [sum(u) for u in units]
    return out, None


def dialog_dept_picker(default_dept: str, key: str):
    return ui.dialogs.dialog_dept_picker(app_context(), default_dept, key)


@st.dialog('Checklist Lập Ngân Sách CNTT Thông Minh', width='large')
def render_item_picker_dialog(target_dept: str, target_site: str):
    return ui.dialogs.render_item_picker_dialog(app_context(), target_dept, target_site)


@st.dialog('Checklist Rà Soát & Điều Chỉnh Nhanh Phòng Ban', width='large')
def render_batch_adjust_dialog(target_dept: str, target_site: str):
    return ui.dialogs.render_batch_adjust_dialog(app_context(), target_dept, target_site)


# =====================================================================
# TAB 2: LẬP & NHẬP LIỆU CAPEX
# =====================================================================
with tab_input:
    ui.tab_input.render(app_context())


# =====================================================================
# TAB: ĐỊNH BIÊN & NHU CẦU THIẾT BỊ / PHẦN MỀM THEO PHÒNG BAN
# =====================================================================
with tab_quota:
    ui.tab_quota.render(app_context())


# =====================================================================
# TAB: HẠ TẦNG CNTT DÙNG CHUNG (phòng phụ trách: PHÒNG CNTT) THEO SITE
# =====================================================================
with tab_infra:
    ui.tab_infra.render(app_context())


# =====================================================================
# TAB: ĐẦU TƯ PHẦN MỀM (danh mục phần mềm & tổng hợp ngân sách phần mềm)
# =====================================================================
SW_KINDS = (KIND_SW_PERPETUAL, KIND_SW_SUBSCRIPTION)

with tab_software:
    ui.tab_software.render(app_context())


# =====================================================================
# TAB 3: NHẬP / XUẤT EXCEL
# =====================================================================
with tab_excel:
    ui.tab_excel.render(app_context())


# =====================================================================
# TAB 7: KỊCH BẢN & MUA SẮM TẬP TRUNG (SCENARIOS & PROCUREMENT)
# =====================================================================
with tab_scenario:
    ui.tab_scenario.render(app_context())


# =====================================================================
# TAB: THỰC HIỆN NGÂN SÁCH
# =====================================================================
with tab_exec:
    ui.tab_exec.render(app_context())


with tab_versions:
    ui.tab_versions.render(app_context())


with tab_depreciation:
    ui.tab_appraisal.render(app_context())


# =====================================================================
# TAB 5: QUẢN LÝ DANH MỤC MASTER DATA
# =====================================================================
with tab_master:
    ui.tab_master.render(app_context())

# FOOTER
st.markdown("---")
st.markdown("""
<div style="text-align:center; color:#94A3B8; font-size:12px;">
    Hệ thống lập ngân sách đầu tư CAPEX – sử dụng nội bộ
</div>
""", unsafe_allow_html=True)
