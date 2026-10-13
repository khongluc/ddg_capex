"""
HỆ THỐNG QUẢN LÝ & TÍNH TOÁN NGÂN SÁCH ĐẦU TƯ CAPEX
"""
import os
import html as _html
import datetime
import math
import pandas as pd
import numpy as np
import streamlit as st

import auth
import db
from master_data import (
    load_master_data,
    save_master_data,
    division_of,
    fiscal_months,
    it_groups,
    it_kinds,
    find_catalog_item,
    apply_it_catalog,
    classify_item,
    accounting_class,
    INVEST_TYPES,
    KIND_HARDWARE,
    KIND_SW_PERPETUAL,
    KIND_SW_SUBSCRIPTION,
)
import quota as qt
import pricing
import reports
import ui.styles
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
import headcount_import as hi
from capex_engine import (
    load_capex_from_excel,
    export_capex_to_excel,
    calculate_row,
    assign_item_seqs,
    clean_number,
    current_units,
    even_units,
    phase_presets,
    phase_text,
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
    """Nộp & duyệt 1 phòng ban: phòng ban nộp; IT site / Admin duyệt, trả lại (ghi chú), mở lại, ghi chú từng dòng."""
    ds = dept_state(dept)
    status = ds["status"]
    site_open = site_status["status"] in db.EDITABLE_STATUSES
    is_owner = current_user.is_dept_user and dept_key(dept) in {dept_key(d) for d in current_user.allowed_depts(selected_site)}
    problems = wf.dept_problems(rows)
    with st.container(border=True):
        c1, c2 = st.columns([1.3, 2.7])
        c1.markdown(f"**Duyệt phòng ban:** {db.DEPT_STATUS_LABELS.get(status, status)}")
        if ds.get("updated_at"):
            c1.caption(f"{ds.get('updated_by') or ''} · {ds['updated_at']}")
        if ds.get("note"):
            c2.info(f"Ghi chú: {ds['note']}")
        if not site_open:
            c2.caption("Site đã nộp / đã duyệt - không đổi trạng thái phòng ban.")
            return
        if status in db.DEPT_LOCKED_STATUSES:
            c2.caption("🔒 Dòng của phòng ban đang khóa sửa." + ("" if can_review else " IT site trả lại hoặc mở lại nếu cần chỉnh."))
        note = ""
        if can_review and status != db.STATUS_APPROVED:
            note = c2.text_input("Ghi chú duyệt / lý do trả lại", key=f"dept_note_{selected_site}_{dept_key(dept)}")
        b = c2.columns(3)
        if is_owner and status in db.EDITABLE_STATUSES:
            if b[0].button("📨 Nộp phòng ban", type="primary", use_container_width=True, disabled=rows.empty):
                if problems:
                    st.error("Chưa nộp được: " + "; ".join(problems))
                else:
                    db.set_dept_status(budget_year, selected_site, dept, db.STATUS_SUBMITTED, current_user.email)
                    st.session_state["flash"] = f"Đã nộp ngân sách {dept} - chờ IT site duyệt."
                    st.rerun()
        if can_review and status != db.STATUS_APPROVED:
            if b[0].button("✅ Duyệt phòng ban", type="primary", use_container_width=True, disabled=rows.empty,
                           help=None if status == db.STATUS_SUBMITTED else "Duyệt cả khi phòng chưa nộp (phòng không có tài khoản lập)"):
                if problems:
                    st.error("Chưa duyệt được: " + "; ".join(problems))
                else:
                    db.set_dept_status(budget_year, selected_site, dept, db.STATUS_APPROVED, current_user.email, note.strip())
                    st.session_state["flash"] = f"Đã duyệt ngân sách {dept}."
                    st.rerun()
            if status == db.STATUS_SUBMITTED and b[1].button("↩️ Trả lại", use_container_width=True):
                if not note.strip():
                    st.error("Ghi lý do trả lại để phòng ban biết cần chỉnh gì.")
                else:
                    db.set_dept_status(budget_year, selected_site, dept, db.STATUS_RETURNED, current_user.email, note.strip())
                    st.session_state["flash"] = f"Đã trả lại {dept}."
                    st.rerun()
        if can_review and status == db.STATUS_APPROVED:
            if b[0].button("🔓 Mở lại để chỉnh sửa", use_container_width=True):
                db.set_dept_status(budget_year, selected_site, dept, db.STATUS_DRAFT, current_user.email, "Mở lại")
                st.rerun()
        if can_review and status == db.STATUS_SUBMITTED and not rows.empty:
            with st.expander("📝 Ghi chú duyệt từng dòng"):
                blank = pd.Series("", index=rows.index)
                view = pd.DataFrame({
                    "item_code": rows["item_code"], "item_name": rows["item_name"], "quantity": rows["quantity"],
                    "unit_price": rows["unit_price"], "total_budget": rows["total_budget"],
                    "need_reason": rows["need_reason"] if "need_reason" in rows.columns else blank,
                    "review_note": (rows["review_note"] if "review_note" in rows.columns else blank).fillna(""),
                })
                ed = st.data_editor(view, key=f"review_{budget_year}_{selected_site}_{dept_key(dept)}", hide_index=True,
                                    use_container_width=True, disabled=[c for c in view.columns if c != "review_note"],
                                    column_config={"item_code": "Mã hạng mục", "item_name": "Hạng mục", "quantity": "SL",
                                                   "unit_price": st.column_config.NumberColumn("Đơn giá", format=MONEY_FMT),
                                                   "total_budget": st.column_config.NumberColumn("Thành tiền", format=MONEY_FMT),
                                                   "need_reason": "Căn cứ",
                                                   "review_note": st.column_config.TextColumn("Ghi chú duyệt", width="large")})
                if st.button("💾 Lưu ghi chú duyệt", key=f"review_save_{dept_key(dept)}"):
                    notes = dict(zip(ed["item_code"], ed["review_note"].fillna("").astype(str).str.strip()))
                    upd = df_site.copy()
                    if "review_note" not in upd.columns:
                        upd["review_note"] = ""
                    m = upd["item_code"].isin(notes)
                    upd.loc[m, "review_note"] = upd.loc[m, "item_code"].map(notes)
                    save_site(upd, selected_site, allow_locked=True)
                    st.session_state["flash"] = f"Đã lưu ghi chú duyệt cho {sum(1 for v in notes.values() if v)} dòng của {dept}."
                    st.rerun()


def render_dept_overview():
    """Tiến độ nộp & duyệt các phòng ban của site; IT site duyệt nhiều phòng cùng lúc."""
    ov = wf.dept_overview(df_site, dept_status_map)
    if ov.empty:
        return
    with st.container(border=True):
        cnt = ov["status"].value_counts()
        st.markdown(f"**Tiến độ phòng ban:** ✅ {cnt.get(db.STATUS_APPROVED, 0)} đã duyệt · 📨 {cnt.get(db.STATUS_SUBMITTED, 0)} chờ duyệt · "
                    f"↩️ {cnt.get(db.STATUS_RETURNED, 0)} trả lại · 📝 {cnt.get(db.STATUS_DRAFT, 0)} đang lập / {len(ov)} phòng có ngân sách")
        with st.expander("Xem bảng tiến độ" + (" và duyệt nhiều phòng" if can_review else ""), expanded=False):
            st.dataframe(ov.drop(columns=["status"]), use_container_width=True, hide_index=True,
                         column_config={"Tổng ngân sách": st.column_config.NumberColumn(format=MONEY_FMT)})
            if can_review:
                todo = ov.loc[ov["status"] != db.STATUS_APPROVED, "Phòng ban"].tolist()
                pick = st.multiselect("Chọn phòng ban để duyệt", todo,
                                      default=ov.loc[ov["status"] == db.STATUS_SUBMITTED, "Phòng ban"].tolist(),
                                      key=f"bulk_pick_{budget_year}_{selected_site}",
                                      help="Mặc định chọn các phòng đã nộp. Phòng không có tài khoản lập có thể duyệt trực tiếp.")
                if st.button(f"✅ Duyệt {len(pick)} phòng ban đã chọn", disabled=not pick, key="bulk_approve"):
                    ok, bad = [], []
                    for d in pick:
                        probs = wf.dept_problems(df_site[df_site["dept_proposing"].map(dept_key) == dept_key(d)])
                        if probs:
                            bad.append(f"{d}: {'; '.join(probs)}")
                        else:
                            db.set_dept_status(budget_year, selected_site, d, db.STATUS_APPROVED, current_user.email, "Duyệt hàng loạt")
                            ok.append(d)
                    st.session_state["flash"] = f"Đã duyệt {len(ok)} phòng ban."
                    if bad:
                        st.session_state["flash_warn"] = "Chưa duyệt được: " + " | ".join(bad)
                    st.rerun()


def render_price_update():
    """Cập nhật đơn giá danh mục từ file báo giá: xem trước -> áp dụng cho danh mục + dòng ngân sách site đang lập."""
    with st.expander("📥 Cập nhật đơn giá từ báo giá", expanded=False):
        st.caption("Tải mẫu (danh mục + giá hiện tại), điền cột **Giá mới** (chưa VAT), nhà cung cấp, ngày báo giá rồi nạp lại. "
                   "Khớp theo Mã; file không có mã thì khớp theo tên / tên gọi khác. Ô Giá mới để trống = giữ giá.")
        st.download_button("📄 Tải mẫu báo giá (.xlsx)", pricing.template_bytes(master),
                           file_name=f"Mau_bao_gia_danh_muc_CNTT_{datetime.date.today():%Y%m%d}.xlsx", mime=XLSX_MIME)
        up = st.file_uploader("File báo giá (.xlsx / .csv)", type=["xlsx", "xls", "csv"], key="quote_file")
        if up is None:
            return
        try:
            quotes = pricing.read_quote_file(up.getvalue(), up.name)
        except Exception as e:  # file sai định dạng -> báo, không dừng trang
            st.error(f"Không đọc được file báo giá: {e}")
            return
        changes, issues = pricing.match_quotes(quotes, master)
        if issues:
            with st.popover(f"⚠️ {len(issues)} dòng không áp dụng được"):
                st.write("\n".join(f"- {x}" for x in issues))
        if not changes:
            st.info("File không có giá nào khác giá hiện tại.")
            return
        df_ch = pd.DataFrame(changes)
        st.markdown(f"**{len(df_ch)} hạng mục** · tăng {int((df_ch['new_price'] > df_ch['old_price']).sum())}, "
                    f"giảm {int((df_ch['new_price'] < df_ch['old_price']).sum())}")
        st.dataframe(df_ch[["code", "name", "unit", "old_price", "new_price", "pct", "vendor", "quote_date"]],
                     use_container_width=True, hide_index=True,
                     column_config={"code": "Mã", "name": "Hạng mục", "unit": "ĐVT", "vendor": "Nhà cung cấp", "quote_date": "Ngày báo giá",
                                    "old_price": st.column_config.NumberColumn("Giá hiện tại", format=MONEY_FMT),
                                    "new_price": st.column_config.NumberColumn("Giá mới", format=MONEY_FMT),
                                    "pct": st.column_config.NumberColumn("Thay đổi", format="percent")})

        all_codes = [s["code"] for s in SITES]
        statuses = db.all_statuses(budget_year)
        editable = {sc for sc in all_codes if statuses.get(sc, {}).get("status", db.STATUS_DRAFT) in db.EDITABLE_STATUSES}
        locked_depts = {sc: {k for k, v in db.dept_statuses(budget_year, sc).items() if v["status"] in db.DEPT_LOCKED_STATUSES}
                        for sc in editable}
        lines_by_site = {}
        for l in db.load_lines(budget_year, all_codes):
            lines_by_site.setdefault(l.pop("site_code"), []).append(l)
        include_manual = st.checkbox("Đổi cả dòng người lập đã sửa giá tay", value=False, key="quote_manual",
                                     help="Mặc định chỉ đổi dòng đang dùng đúng giá danh mục cũ")
        imp = pricing.line_impact(changes, lines_by_site, editable, include_manual, locked_depts)
        if imp.empty:
            st.caption(f"Không có dòng ngân sách năm {budget_year} nào dùng các hạng mục này - chỉ cập nhật danh mục.")
        else:
            chg = imp[imp["action"] == "Đổi"]
            delta = chg["new_total"].sum() - chg["old_total"].sum()
            st.markdown(f"**Ngân sách năm {budget_year}:** đổi giá {len(chg)}/{len(imp)} dòng, "
                        f"chênh lệch **{'+' if delta >= 0 else ''}{format_vnd(delta)}** (chưa VAT)")
            by_site = imp.groupby(["site", "action"]).agg(**{"Số dòng": ("idx", "size"), "Trước": ("old_total", "sum"),
                                                             "Sau": ("new_total", "sum")}).reset_index()
            by_site["site"] = by_site["site"].map(site_label)
            st.dataframe(by_site.rename(columns={"site": "Site", "action": "Xử lý"}), use_container_width=True, hide_index=True,
                         column_config={c: st.column_config.NumberColumn(format=MONEY_FMT) for c in ("Trước", "Sau")})
        if st.button(f"✅ Áp dụng giá mới ({len(df_ch)} hạng mục)", type="primary", key="quote_apply"):
            n_items = pricing.apply_catalog_prices(master, changes)
            save_master_data(master)
            n_lines = 0
            if not imp.empty:
                for sc, grp in imp[imp["action"] == "Đổi"].groupby("site"):
                    save_site(pd.DataFrame(pricing.reprice_lines(lines_by_site[sc], grp)), sc, base=lines_by_site[sc])
                    n_lines += len(grp)
            db.log(current_user.email, "price_update", f"{budget_year}: {n_items} hạng mục, {n_lines} dòng ngân sách ({up.name})")
            st.session_state["flash"] = f"Đã cập nhật giá {n_items} hạng mục và tính lại {n_lines} dòng ngân sách năm {budget_year}."
            st.session_state.pop("quote_file", None)
            st.rerun()


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
        st.caption("💾 CSDL: " + ("PostgreSQL (lưu bền)" if db.using_server_db() else "SQLite (file cục bộ)")
                   + f" · Phiên bản code: {code_version()}")
    if st.button("🚪 Đăng xuất", use_container_width=True):
        auth.logout()

    if current_user.is_admin:
        admin_view = st.radio("Màn hình", ["📊 Ngân sách", "👥 Phân quyền & Tiến độ"], key="admin_view",
                              help="Phân quyền người dùng, tiến độ các site, nhật ký, sao lưu / khôi phục")
    else:
        admin_view = "📊 Ngân sách"

    st.markdown("### ⚙️ Thiết lập Ngân sách")

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
    st.markdown("#### 🏢 Thông tin Đề xuất")
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
    st.markdown("#### 🔄 Hành động Nhanh")
    if st.button("🔄 Làm mới", use_container_width=True):
        st.rerun()
    if site_can_edit and not current_user.is_dept_user:
        with st.popover("🗑️ Xóa toàn bộ dòng của site", use_container_width=True):
            st.warning(f"Xóa toàn bộ hạng mục năm {budget_year} của {site_label(selected_site)}?")
            if st.button("Xác nhận xóa", type="primary"):
                save_site(pd.DataFrame(), selected_site)  # dòng của phòng ban đã nộp/duyệt được giữ lại
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
                save_site(part, code, overwrite=True)
            st.session_state["flash"] = (f"Đã nạp {sum(len(p) for p in groups.values())} dòng vào {len(groups)} site."
                                         + (f" Bỏ qua vị trí không khớp danh mục: {unmatched}" if unmatched else ""))
            st.rerun()

# Dữ liệu hiện hành theo site + phòng ban được chọn
df_curr = df_site[dept_mask(df_site, selected_dept)].reset_index(drop=True)


def prev_year_lines() -> pd.DataFrame:
    """Dòng ngân sách năm trước cùng phạm vi site + phòng ban (để so sánh)."""
    prev = pd.DataFrame(db.load_lines(str(int(budget_year) - 1), scope_sites))
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
    dot_icon = {
        db.STATUS_DRAFT: "🟢",
        db.STATUS_SUBMITTED: "🟡",
        db.STATUS_APPROVED: "🔵",
        db.STATUS_RETURNED: "🔴",
    }.get(status_code, "⚪")
    status_pill_html = f'<span class="header-status-pill {pill_cls}">{dot_icon} {status_lbl}</span>'

st.markdown(f"""
<div class="main-header">
    <div class="header-top-row">
        <div class="header-brand-title">
            <div class="brand-icon-box">💼</div>
            <div class="header-title-text">
                <div class="sub-corp">Ngân sách đầu tư CNTT · Năm tài chính T10/{int(budget_year) - 1} – T9/{budget_year}</div>
                <h1>NGÂN SÁCH CAPEX THƯỜNG NIÊN {budget_year}</h1>
            </div>
        </div>
        <div>
            {status_pill_html}
        </div>
    </div>
    <div class="header-meta-chips">
        <span class="meta-chip">📍 Site: <strong>{site_label(selected_site)}</strong></span>
        <span class="meta-chip">🏛️ Đơn vị đề xuất: <strong>{_html.escape(dept_prop)}</strong></span>
        <span class="meta-chip">👤 Người lập: <strong>{_html.escape(creator_name or 'Chưa nhập')}</strong></span>
        <span class="meta-chip">📅 Ngày: <strong>{meta.get('date', '')}</strong></span>
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
        st.caption("ℹ️ Lập xong, bấm **📨 Nộp phòng ban** ở tab Lập & Nhập liệu để IT site duyệt.")
    site_pending = wf.pending_depts(wf.dept_overview(df_site, dept_status_map)) if selected_site != ALL_SITES else []
    if status in db.EDITABLE_STATUSES and site_can_edit and not current_user.is_dept_user:
        if site_pending:
            st.caption(f"⏳ Còn {len(site_pending)} phòng ban chưa duyệt - duyệt đủ mới nộp được site "
                       "(xem bảng Tiến độ phòng ban ở tab Lập & Nhập liệu, chọn Tất cả phòng ban).")
        if st.button("📨 Nộp ngân sách site để duyệt", use_container_width=True, disabled=df_site.empty or bool(site_pending),
                     help="Nộp toàn bộ ngân sách của site (tất cả phòng ban đã được IT site duyệt)"):
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
        with st.popover("🔓 Mở điều chỉnh ngân sách", use_container_width=True):
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
    "📊 Tổng quan",
    "📝 Lập CapEx",
    "👥 Định biên",
    "🏗️ Hạ tầng",
    "💿 Phần mềm",
    "📁 Nhập / Xuất",
    "🎯 Kịch bản",
    "💳 Giải ngân",
    "🗂️ Phiên bản",
    "📈 Thẩm định",
    "⚙️ Danh mục",
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
                     column_config={"Tổng ngân sách (VNĐ)": st.column_config.NumberColumn(format=MONEY_FMT)})
        done = sum(1 for c in site_codes if statuses.get(c, {}).get("status") == db.STATUS_APPROVED)
        st.progress(done / len(site_codes) if site_codes else 0.0, text=f"Đã duyệt {done}/{len(site_codes)} site")
        st.caption("Để duyệt / trả lại: chọn site ở thanh bên trái, nút thao tác nằm ngay dưới tiêu đề trang.")

    with a_audit:
        st.dataframe(pd.DataFrame(db.recent_audit()), use_container_width=True, hide_index=True)

    with a_backup:
        import io as _io
        import json as _json
        import zipfile as _zip
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
    st.session_state["flash"] = f"🎉 Đã thêm thành công {len(new_items_list)} hạng mục vào ngân sách phòng ban '{target_dept}' ({format_vnd(total_cost)})!"
    st.session_state["pending_dept"] = target_dept
    st.rerun()


PHASE_ONE, PHASE_EVEN, PHASE_MANUAL = "1 tháng", "Chia đều nhiều tháng", "Tự nhập SL từng tháng"


def phasing_picker(sel_df: pd.DataFrame, key: str) -> tuple:
    """Popup: chọn cách phân kỳ cho các hạng mục đã chọn - cả SL vào 1 tháng, chia đều các tháng chọn, hoặc nhập SL từng tháng.
    Trả về (bảng có thêm cột _units = SL nguyên từng tháng và Số lượng = tổng, lỗi hoặc None)."""
    mode = st.radio("📅 Phân kỳ mua:", [PHASE_ONE, PHASE_EVEN, PHASE_MANUAL], horizontal=True, key=f"{key}_mode",
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


def dialog_dept_picker(default_dept: str, key: str) -> tuple:
    """Ô chọn phòng ban trong popup: chỉ phòng tài khoản được sửa, kèm trạng thái duyệt. Trả về (phòng, đang khóa?)."""
    options = [d for d in dept_list if d != ALL_DEPTS]
    if not options:
        return default_dept, True
    idx = next((i for i, d in enumerate(options) if dept_key(d) == dept_key(default_dept)), 0)

    def _label(d):
        stt = dept_state(d)["status"]
        return f"{d}  ·  {db.DEPT_STATUS_LABELS.get(stt, stt)}"
    dept = st.selectbox("🏢 Chọn phòng ban cần lập / chỉnh sửa", options, index=idx, key=key, format_func=_label,
                        help="Đổi phòng ngay trong popup; lưu xong trang chính chuyển sang phòng này")
    locked = dept_state(dept)["status"] in db.DEPT_LOCKED_STATUSES
    if locked:
        st.warning(f"🔒 {dept} đã nộp / đã duyệt - không thêm / sửa được. IT site trả lại hoặc mở lại phòng ban nếu cần điều chỉnh.")
    return dept, locked


@st.dialog("🛒 Checklist Lập Ngân Sách CNTT Thông Minh", width="large")
def render_item_picker_dialog(target_dept: str, target_site: str):
    target_dept, _locked = dialog_dept_picker(target_dept, "dlg_pick_dept")
    if _locked:
        return
    st.markdown(f"""
    <div style="background:#EFF6FF; border:1px solid #BFDBFE; border-radius:10px; padding:10px 14px; margin-bottom:12px; display:flex; justify-content:space-between; align-items:center;">
        <div>
            <div style="font-size:11px; font-weight:700; color:#1E40AF; text-transform:uppercase;">Phòng ban lập ngân sách</div>
            <div style="font-size:16px; font-weight:800; color:#0F2C59;">🏢 {_html.escape(target_dept)} <span style="font-size:12px; font-weight:500; color:#64748B;">({site_label(target_site)})</span></div>
        </div>
        <div style="text-align:right;">
            <div style="font-size:11px; color:#64748B;">Năm tài chính</div>
            <div style="font-size:15px; font-weight:700; color:#1E40AF;">{budget_year}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    dlg_tab1, dlg_tab2, dlg_tab3 = st.tabs([
        "📦 GÓI TRANG BỊ THEO CHỨC DANH (1-Click Presets)",
        "🔍 CHECKLIST TÌM KIẾM TOÀN DANH MỤC",
        "✍️ HẠNG MỤC NGOÀI DANH MỤC",
    ])

    standard_kits = qt.standard_kits(master)
    cat_all = master.get("standard_items", [])
    cat_by_code = {x.get("code"): x for x in cat_all if x.get("code")}

    # Tab 1: Bundles
    with dlg_tab1:
        st.caption("Chọn chức danh và số lượng nhân sự. Hệ thống tự động tính toán số lượng toàn bộ thiết bị & bản quyền theo định mức.")
        b1, b2 = st.columns([2, 1])
        with b1:
            kit_codes = [k["code"] for k in standard_kits]
            kit_labels = {k["code"]: f"{k['code']} · {k['name']}" for k in standard_kits}
            sel_k_code = st.selectbox("1. Vị trí / Chức danh cần trang bị:", kit_codes, format_func=lambda c: kit_labels.get(c, c), key="dlg_kit_pick")
        with b2:
            n_people = st.number_input("2. Số lượng nhân sự (người):", min_value=1, value=1, step=1, key="dlg_kit_people")

        kit_obj = next((k for k in standard_kits if k["code"] == sel_k_code), None)
        k_rows = []
        if kit_obj:
            for it_entry in kit_obj.get("items", []):
                cc = it_entry.get("catalog_code", "")
                cat_it = cat_by_code.get(cc)
                if not cat_it:
                    continue
                q_ratio = float(it_entry.get("qty_per_person", 1))
                raw_q = q_ratio * n_people  # như sinh dòng định biên (BR-05): dùng chung (< 1/người) làm tròn gần nhất, còn lại làm tròn lên
                calc_q = int(math.floor(raw_q + 0.5)) if q_ratio < 1 else int(math.ceil(round(raw_q, 6)))
                p = float(cat_it.get("price", 0))
                cls_prev = classify_item(cat_it, master)
                _, capex_tg = accounting_class(cls_prev.get("item_kind", KIND_HARDWARE), p, master)
                k_rows.append({
                    "Chọn": True,
                    "Mã": cc,
                    "Tên thiết bị / Hạng mục": cat_it["name"],
                    "ĐVT": cat_it.get("unit", "Cái"),
                    "Đơn giá (VNĐ)": p,
                    "Phân loại": capex_tg,
                    "Số lượng": calc_q,
                    "Ghi chú": f"Trang bị {n_people} {kit_obj['name']}",
                })

        df_k = pd.DataFrame(k_rows)
        ed_kit = st.data_editor(
            df_k,
            key=f"ed_dlg_kit_{dept_key(target_dept)}_{sel_k_code}_{n_people}",
            use_container_width=True,
            hide_index=True,
            column_config={
                "Chọn": st.column_config.CheckboxColumn("Chọn", default=True),
                "Mã": st.column_config.TextColumn("Mã", disabled=True, width="small"),
                "Tên thiết bị / Hạng mục": st.column_config.TextColumn("Tên thiết bị", disabled=True, width="large"),
                "ĐVT": st.column_config.TextColumn("ĐVT", disabled=True, width="small"),
                "Đơn giá (VNĐ)": st.column_config.NumberColumn("Đơn giá (VNĐ)", disabled=True, format=MONEY_FMT),
                "Phân loại": st.column_config.TextColumn("Phân loại", disabled=True, width="small"),
                "Số lượng": st.column_config.NumberColumn("Số lượng", min_value=0, step=1, format=MONEY_FMT),
                "Ghi chú": st.column_config.TextColumn("Ghi chú", width="medium"),
            }
        )
        sel_kit_df = ed_kit[(ed_kit["Chọn"] == True) & (ed_kit["Số lượng"] > 0)]
        st.markdown("---")
        sel_kit_df, k_err = phasing_picker(sel_kit_df, "dlg_k")
        cost_kit = (sel_kit_df["Số lượng"] * sel_kit_df["Đơn giá (VNĐ)"]).sum() if not sel_kit_df.empty else 0.0

        kb2, kb3 = st.columns([2.4, 1.6])
        with kb2:
            k_need = st.radio("Nhu cầu:", qt.NEED_TYPES, index=qt.NEED_TYPES.index(qt.NEED_NEW), horizontal=True, key="dlg_k_need",
                              help="Dòng 'Định biên' nên sinh từ tab Định biên (tránh tính trùng); thêm tay mặc định là Phát sinh mới, bắt buộc ghi lý do")
        with kb3:
            st.markdown(f"""
            <div style="background:#F8FAFC; border:1px solid #CBD5E1; border-radius:8px; padding:8px 12px; text-align:right;">
                <div style="font-size:11px; color:#64748B;">Đã chọn: <b>{len(sel_kit_df)}</b> món</div>
                <div style="font-size:15px; font-weight:800; color:#1E40AF;">{format_vnd(cost_kit)}</div>
            </div>
            """, unsafe_allow_html=True)

        k_reason = ""
        if k_need in qt.NEED_WITH_REASON:
            k_reason = st.text_input("Lý do phát sinh / căn cứ trang bị:", value=f"Tuyển mới {n_people} {kit_obj['name'] if kit_obj else ''}", key="dlg_k_reason")

        if st.button(f"💾 XÁC NHẬN THÊM {len(sel_kit_df)} MỤC TRONG GÓI VÀO {target_dept}", type="primary", use_container_width=True, disabled=sel_kit_df.empty, key="btn_apply_dlg_kit"):
            if k_err:
                st.error(k_err)
            elif k_need in qt.NEED_WITH_REASON and not k_reason.strip():
                st.error("Vui lòng nhập lý do / căn cứ phát sinh trước khi thêm!")
            else:
                _commit_checklist_items(sel_kit_df, target_dept, target_site, None, k_need, k_reason)

    # Tab 2: Universal Search Checklist
    with dlg_tab2:
        st.caption(f"Tìm kiếm nhanh trong toàn bộ {len(cat_all)} hạng mục CNTT chuẩn hóa, tick chọn và điều chỉnh số lượng.")
        sc1, sc2 = st.columns([2, 1.2])
        with sc1:
            search_kw = st.text_input("🔍 Gõ từ khóa tìm kiếm (tên thiết bị, phần mềm, mã...):", placeholder="VD: laptop, dell, tekla, autocad, màn hình, máy in...", key="dlg_search_kw")
        with sc2:
            all_groups_label = f"(Tất cả {len(it_groups(master))} nhóm CNTT)"
            grp_choices = [all_groups_label] + [f"{g['code']}. {g['name']}" for g in it_groups(master)]
            sel_g_filter = st.selectbox("Lọc theo nhóm:", grp_choices, key="dlg_grp_filter")

        items_pool = cat_all
        if sel_g_filter != all_groups_label:
            pfx = sel_g_filter.split(".")[0].strip()
            items_pool = [x for x in items_pool if str(x.get("group", "")).startswith(pfx)]
        if search_kw.strip():
            kw_l = search_kw.strip().lower()
            items_pool = [x for x in items_pool if kw_l in x.get("name", "").lower() or kw_l in x.get("code", "").lower() or kw_l in str(x.get("note", "")).lower()]

        c_rows = []
        for it in items_pool[:60]:
            p = float(it.get("price", 0))
            cls_prev = classify_item(it, master)
            _, capex_tg = accounting_class(cls_prev.get("item_kind", KIND_HARDWARE), p, master)
            c_rows.append({
                "Chọn": False,
                "Mã": it.get("code", ""),
                "Tên thiết bị / Hạng mục": it["name"],
                "ĐVT": it.get("unit", "Cái"),
                "Đơn giá (VNĐ)": p,
                "Phân loại": capex_tg,
                "Số lượng": 1,
                "Ghi chú": "",
            })

        if not c_rows:
            st.info("Không tìm thấy hạng mục nào phù hợp với từ khóa.")
        else:
            df_c = pd.DataFrame(c_rows)
            ed_cat = st.data_editor(
                df_c,
                key=f"ed_dlg_cat_{dept_key(target_dept)}_{sel_g_filter}_{search_kw}",
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Chọn": st.column_config.CheckboxColumn("Chọn", default=False),
                    "Mã": st.column_config.TextColumn("Mã", disabled=True, width="small"),
                    "Tên thiết bị / Hạng mục": st.column_config.TextColumn("Tên thiết bị", disabled=True, width="large"),
                    "ĐVT": st.column_config.TextColumn("ĐVT", disabled=True, width="small"),
                    "Đơn giá (VNĐ)": st.column_config.NumberColumn("Đơn giá (VNĐ)", disabled=True, format=MONEY_FMT),
                    "Phân loại": st.column_config.TextColumn("Phân loại", disabled=True, width="small"),
                    "Số lượng": st.column_config.NumberColumn("Số lượng", min_value=1, step=1, format=MONEY_FMT),
                    "Ghi chú": st.column_config.TextColumn("Ghi chú", width="medium"),
                }
            )
            sel_cat_df = ed_cat[ed_cat["Chọn"] == True]
            st.markdown("---")
            sel_cat_df, c_err = phasing_picker(sel_cat_df, "dlg_c")
            cost_cat = (sel_cat_df["Số lượng"] * sel_cat_df["Đơn giá (VNĐ)"]).sum() if not sel_cat_df.empty else 0.0

            cb2, cb3 = st.columns([2.4, 1.6])
            with cb2:
                c_need = st.radio("Nhu cầu:", qt.NEED_TYPES, index=qt.NEED_TYPES.index(qt.NEED_NEW), horizontal=True, key="dlg_c_need")
            with cb3:
                st.markdown(f"""
                <div style="background:#F8FAFC; border:1px solid #CBD5E1; border-radius:8px; padding:8px 12px; text-align:right;">
                    <div style="font-size:11px; color:#64748B;">Đã chọn: <b>{len(sel_cat_df)}</b> món</div>
                    <div style="font-size:15px; font-weight:800; color:#1E40AF;">{format_vnd(cost_cat)}</div>
                </div>
                """, unsafe_allow_html=True)

            c_reason = ""
            if c_need in qt.NEED_WITH_REASON:
                c_reason = st.text_input("Lý do phát sinh / căn cứ trang bị:", placeholder="VD: Tuyển thêm nhân sự, nâng cấp máy...", key="dlg_c_reason")

            if st.button(f"💾 XÁC NHẬN THÊM {len(sel_cat_df)} MỤC ĐÃ TICK VÀO {target_dept}", type="primary", use_container_width=True, disabled=sel_cat_df.empty, key="btn_apply_dlg_cat"):
                if c_err:
                    st.error(c_err)
                elif c_need in qt.NEED_WITH_REASON and not c_reason.strip():
                    st.error("Vui lòng nhập lý do / căn cứ phát sinh trước khi thêm!")
                else:
                    _commit_checklist_items(sel_cat_df, target_dept, target_site, None, c_need, c_reason)

    # Tab 3: hạng mục chưa có trong danh mục (nhập tay)
    with dlg_tab3:
        st.caption("Nhập hạng mục chưa có trong danh mục CNTT (mỗi dòng 1 hạng mục). Hạch toán TSCĐ / CCDC / OPEX, loại tài sản "
                   "và mã chi phí tự gán theo Nhóm CNTT + Loại. Tên trùng hạng mục trong danh mục sẽ lấy theo danh mục.")
        groups_cfg = it_groups(master)
        grp_labels = [f"{g['code']}. {g['name']}" for g in groups_cfg]
        kinds_cfg = it_kinds(master)
        df_new = pd.DataFrame([{"Tên thiết bị / Hạng mục": "", "Nhóm": None, "Loại": None, "Hình thức": "Mua mới", "ĐVT": "",
                                "Số lượng": 1, "Đơn giá (VNĐ)": 0.0, "Ghi chú": ""}])
        ed_new = st.data_editor(
            df_new, key=f"ed_dlg_new_{dept_key(target_dept)}", num_rows="dynamic", use_container_width=True, hide_index=True,
            column_config={
                "Tên thiết bị / Hạng mục": st.column_config.TextColumn("Tên hạng mục", width="large", required=True),
                "Nhóm": st.column_config.SelectboxColumn("Nhóm CNTT", options=grp_labels, required=True, width="medium"),
                "Loại": st.column_config.SelectboxColumn("Loại", options=list(kinds_cfg), width="small",
                                                         help="Trống = theo nhóm. " + " | ".join(f"{k}: {v}" for k, v in kinds_cfg.items())),
                "Hình thức": st.column_config.SelectboxColumn("Hình thức", options=INVEST_TYPES, width="small"),
                "ĐVT": st.column_config.TextColumn("ĐVT", width="small"),
                "Số lượng": st.column_config.NumberColumn("Số lượng", min_value=1, step=1, format=MONEY_FMT),
                "Đơn giá (VNĐ)": st.column_config.NumberColumn("Đơn giá (VNĐ, chưa VAT)", min_value=0, format=MONEY_FMT),
                "Ghi chú": st.column_config.TextColumn("Ghi chú", width="medium"),
            })
        names = ed_new["Tên thiết bị / Hạng mục"].fillna("").astype(str).str.strip()
        sel_new = ed_new[names != ""].copy()
        sel_new["Số lượng"] = pd.to_numeric(sel_new["Số lượng"], errors="coerce").fillna(0)
        sel_new["Đơn giá (VNĐ)"] = pd.to_numeric(sel_new["Đơn giá (VNĐ)"], errors="coerce").fillna(0)
        in_cat = [n for n in sel_new["Tên thiết bị / Hạng mục"] if find_catalog_item(n, master)]
        if in_cat:
            st.info("Có trong danh mục, sẽ lấy theo danh mục (mã, nhóm, hạch toán): " + ", ".join(in_cat))
        st.markdown("---")
        sel_new, n_err = phasing_picker(sel_new, "dlg_n")
        cost_new = (sel_new["Số lượng"] * sel_new["Đơn giá (VNĐ)"]).sum() if not sel_new.empty else 0.0
        nb2, nb3 = st.columns([2.4, 1.6])
        with nb2:
            n_need = st.radio("Nhu cầu:", qt.NEED_TYPES, index=qt.NEED_TYPES.index(qt.NEED_NEW), horizontal=True, key="dlg_n_need")
        with nb3:
            st.markdown(f"""
            <div style="background:#F8FAFC; border:1px solid #CBD5E1; border-radius:8px; padding:8px 12px; text-align:right;">
                <div style="font-size:11px; color:#64748B;">Đã nhập: <b>{len(sel_new)}</b> hạng mục</div>
                <div style="font-size:15px; font-weight:800; color:#1E40AF;">{format_vnd(cost_new)}</div>
            </div>
            """, unsafe_allow_html=True)
        n_reason = st.text_input("Lý do phát sinh / căn cứ trang bị:", key="dlg_n_reason",
                                 placeholder="VD: Dự án mới cần thiết bị đo đạc, phần mềm chuyên dụng...") if n_need in qt.NEED_WITH_REASON else ""
        if st.button(f"💾 XÁC NHẬN THÊM {len(sel_new)} HẠNG MỤC VÀO {target_dept}", type="primary", use_container_width=True,
                     disabled=sel_new.empty, key="btn_apply_dlg_new"):
            missing_grp = [n for n, g in zip(sel_new["Tên thiết bị / Hạng mục"], sel_new["Nhóm"])
                           if not find_catalog_item(n, master) and not str(g or "").strip()]
            if missing_grp:
                st.error("Chọn Nhóm CNTT cho: " + ", ".join(missing_grp))
            elif n_err:
                st.error(n_err)
            elif (sel_new["Số lượng"] <= 0).any():
                st.error("Nhập số lượng lớn hơn 0 cho mọi hạng mục.")
            elif (sel_new["Đơn giá (VNĐ)"] <= 0).any():
                st.error("Nhập đơn giá lớn hơn 0 cho mọi hạng mục.")
            elif n_need in qt.NEED_WITH_REASON and not n_reason.strip():
                st.error("Vui lòng nhập lý do / căn cứ phát sinh trước khi thêm!")
            else:
                _commit_checklist_items(sel_new, target_dept, target_site, None, n_need, n_reason)


@st.dialog("📋 Checklist Rà Soát & Điều Chỉnh Nhanh Phòng Ban", width="large")
def render_batch_adjust_dialog(target_dept: str, target_site: str):
    target_dept, _locked = dialog_dept_picker(target_dept, "dlg_adj_dept")
    if _locked:
        return
    lines = db.load_lines(budget_year, [target_site])
    stored_df = pd.DataFrame(lines).drop(columns=["site_code"], errors="ignore") if lines else pd.DataFrame()
    dept_rows = stored_df[stored_df["dept_proposing"].map(dept_key) == dept_key(target_dept)].reset_index(drop=True) if not stored_df.empty and "dept_proposing" in stored_df.columns else pd.DataFrame()

    if dept_rows.empty:
        st.info(f"Phòng ban {target_dept} hiện chưa có hạng mục nào trong ngân sách {budget_year}.")
        if st.button("Đóng", use_container_width=True):
            st.rerun()
        return

    st.markdown(f"""
    <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:10px; padding:10px 14px; margin-bottom:12px;">
        <div style="font-size:11px; font-weight:700; color:#64748B; text-transform:uppercase;">Danh sách hiện có</div>
        <div style="font-size:15px; font-weight:800; color:#0F2C59;">🏢 {_html.escape(target_dept)} · <b>{len(dept_rows)}</b> hạng mục · Tổng: <b>{format_vnd(dept_rows['total_budget'].sum())}</b></div>
    </div>
    """, unsafe_allow_html=True)

    adj_rows = []
    for idx, r in dept_rows.iterrows():
        adj_rows.append({
            "Chọn": False,
            "ID": idx,
            "Mã": r.get("item_code", ""),
            "Tên hạng mục": r.get("item_name", ""),
            "Số lượng": clean_number(r.get("quantity", 1)),
            "Đơn giá": clean_number(r.get("unit_price", 0)),
            "Thành tiền": clean_number(r.get("total_budget", 0)),
            "Phân loại": r.get("capex_type", ""),
            "Loại nhu cầu": r.get("need_type", ""),
            "Phân kỳ": phase_text([clean_number(r.get(f"pct_{m}", 0), 0.0) for m in months], clean_number(r.get("quantity", 0), 0.0), months),
        })

    df_adj = pd.DataFrame(adj_rows)
    ed_adj = st.data_editor(
        df_adj,
        key=f"ed_dlg_adj_{dept_key(target_dept)}_{len(dept_rows)}",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Chọn": st.column_config.CheckboxColumn("Chọn", default=False),
            "ID": None,
            "Mã": st.column_config.TextColumn("Mã", disabled=True, width="small"),
            "Tên hạng mục": st.column_config.TextColumn("Tên hạng mục", disabled=True, width="large"),
            "Số lượng": st.column_config.NumberColumn("Số lượng", disabled=True, format=MONEY_FMT),
            "Đơn giá": st.column_config.NumberColumn("Đơn giá", disabled=True, format=MONEY_FMT),
            "Thành tiền": st.column_config.NumberColumn("Thành tiền", disabled=True, format=MONEY_FMT),
            "Phân loại": st.column_config.TextColumn("Phân loại", disabled=True, width="small"),
            "Loại nhu cầu": st.column_config.TextColumn("Nhu cầu", disabled=True, width="small"),
            "Phân kỳ": st.column_config.TextColumn("Phân kỳ hiện tại", disabled=True, width="medium"),
        }
    )
    sel_adj = ed_adj[ed_adj["Chọn"] == True]
    n_sel = len(sel_adj)

    st.markdown("---")
    st.markdown(f"##### 🛠️ Thao tác hàng loạt cho **{n_sel}** mục đã chọn:")

    act_col1, act_col2 = st.columns(2)
    with act_col1:
        st.markdown("**1. Đổi tháng giải ngân / chia nhiều tháng:**")
        adj_mode = st.radio("Cách phân kỳ:", [PHASE_ONE, PHASE_EVEN, PHASE_MANUAL], horizontal=True, key="dlg_adj_mode",
                            help="Chia đều: SL nguyên của mỗi dòng chia đều các tháng chọn, dư dồn tháng sớm. "
                                 "Tự nhập: sửa SL từng tháng, Số lượng của dòng = tổng các tháng")
        manual_units, adj_err = {}, None
        if adj_mode == PHASE_ONE:
            new_m = st.selectbox("Chọn tháng giải ngân mới:", months, key="dlg_adj_new_m")
            adj_months, adj_lbl = [new_m], new_m
        elif adj_mode == PHASE_EVEN:
            adj_presets = phase_presets(months)
            adj_pre = st.selectbox("Mẫu nhanh:", list(adj_presets), index=2, key="dlg_adj_preset")
            adj_months = st.multiselect("Các tháng mua:", months, default=adj_presets[adj_pre] or months[:1],
                                        key=f"dlg_adj_months_{adj_pre}")
            adj_lbl = f"{len(adj_months)} tháng"
        else:  # tự nhập SL từng tháng, điền sẵn theo phân kỳ hiện có
            adj_months, adj_lbl = list(months), "SL từng tháng đã nhập"
            if n_sel:
                cur = dept_rows.loc[sel_adj["ID"]]
                mgrid = pd.DataFrame([current_units([clean_number(r.get(f"pct_{m}", 0), 0.0) for m in months],
                                                    clean_number(r.get("quantity", 0), 0.0)) for _, r in cur.iterrows()], columns=months)
                mgrid.insert(0, "Mã", cur["item_code"].tolist())
                mgrid.insert(1, "Tên hạng mục", cur["item_name"].astype(str).tolist())
                med = st.data_editor(mgrid, key=f"dlg_adj_manual_{abs(hash(tuple(mgrid['Mã']))) % 10**8}", hide_index=True,
                                     use_container_width=True,
                                     column_config={"Mã": st.column_config.TextColumn("Mã", disabled=True, width="small"),
                                                    "Tên hạng mục": st.column_config.TextColumn("Tên hạng mục", disabled=True, width="medium"),
                                                    **{m: st.column_config.NumberColumn(m, min_value=0, step=1, format="%d") for m in months}})
                for _, r in med.iterrows():
                    manual_units[r["Mã"]] = [int(pd.to_numeric(r[m], errors="coerce") or 0) for m in months]
                empty = [n for n, u in zip(med["Tên hạng mục"], manual_units.values()) if sum(u) <= 0]
                if empty:
                    adj_err = "Nhập số lượng ít nhất 1 tháng cho: " + ", ".join(empty)
                st.caption("Số lượng của dòng = tổng các tháng (thành tiền tính lại theo đơn giá).")
        if (adj_go := st.button(f"📅 Phân kỳ {n_sel} mục vào {adj_lbl}", use_container_width=True, disabled=n_sel == 0 or not adj_months,
                                key="btn_move_month")) and adj_err:
            st.error(adj_err)
        elif adj_go:
            sel_codes = set(sel_adj["Mã"])
            updated_stored = stored_df.copy()
            match_mask = (updated_stored["dept_proposing"].map(dept_key) == dept_key(target_dept)) & (updated_stored["item_code"].isin(sel_codes))
            for i in updated_stored[match_mask].index:
                if adj_mode == PHASE_MANUAL:
                    units_i = manual_units.get(updated_stored.at[i, "item_code"])
                    if not units_i:
                        continue
                    updated_stored.at[i, "quantity"] = float(sum(units_i))
                qty_i = clean_number(updated_stored.at[i, "quantity"], 0.0)
                if adj_mode != PHASE_MANUAL:
                    units_i = even_units(qty_i, months, adj_months)
                for j, m in enumerate(months):  # SL không nguyên -> chia đều theo tỷ lệ
                    updated_stored.at[i, f"pct_{m}"] = (units_i[j] / qty_i if units_i
                                                        else (1.0 / len(adj_months) if m in adj_months else 0.0))
                r_dict = updated_stored.loc[i].to_dict()
                c_dict = calculate_row(r_dict, months=months, year_code=year_code, master=master)
                for k, v in c_dict.items():
                    updated_stored.at[i, k] = v
            save_site(updated_stored.reset_index(drop=True), target_site)
            st.session_state["flash"] = (f"✅ Đã cập nhật SL từng tháng cho {n_sel} hạng mục của {target_dept}!" if adj_mode == PHASE_MANUAL
                                         else f"✅ Đã phân kỳ {n_sel} hạng mục của {target_dept} vào {', '.join(adj_months)}!")
            st.session_state["pending_dept"] = target_dept
            st.rerun()

    with act_col2:
        st.markdown("**2. Xóa bỏ các mục không cần thiết:**")
        st.caption("Các dòng được tick chọn sẽ bị xóa vĩnh viễn khỏi ngân sách phòng ban.")
        if st.button(f"🗑️ Xóa {n_sel} mục đã chọn", use_container_width=True, disabled=n_sel == 0, key="btn_del_batch"):
            sel_codes = set(sel_adj["Mã"])
            del_mask = (stored_df["dept_proposing"].map(dept_key) == dept_key(target_dept)) & (stored_df["item_code"].isin(sel_codes))
            updated_stored = stored_df[~del_mask].reset_index(drop=True)
            save_site(updated_stored, target_site)
            st.session_state["flash"] = f"🗑️ Đã xóa thành công {n_sel} hạng mục khỏi phòng ban {target_dept}!"
            st.session_state["pending_dept"] = target_dept
            st.rerun()


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
