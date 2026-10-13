"""Popup lập ngân sách: checklist (gói chức danh, tìm danh mục, ngoài danh mục) và rà soát & sửa nhanh."""
import html as _html
import math

import pandas as pd
import streamlit as st

import db
import quota as qt
from capex_engine import calculate_row, clean_number, current_units, even_units, phase_presets, phase_text
from master_data import (
    INVEST_TYPES,
    KIND_HARDWARE,
    accounting_class,
    classify_item,
    find_catalog_item,
    it_groups,
    it_kinds,
)


def dialog_dept_picker(ctx, default_dept: str, key: str):
    """Ô chọn phòng ban trong popup: chỉ phòng tài khoản được sửa, kèm trạng thái duyệt. Trả về (phòng, đang khóa?)."""
    ALL_DEPTS, dept_key, dept_list = ctx.ALL_DEPTS, ctx.dept_key, ctx.dept_list
    dept_state = ctx.dept_state

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


def render_item_picker_dialog(ctx, target_dept: str, target_site: str):
    MONEY_FMT, _commit_checklist_items, budget_year, dept_key = ctx.MONEY_FMT, ctx._commit_checklist_items, ctx.budget_year, ctx.dept_key
    format_vnd, master, phasing_picker = ctx.format_vnd, ctx.master, ctx.phasing_picker
    site_label = ctx.site_label

    target_dept, _locked = dialog_dept_picker(ctx, target_dept, "dlg_pick_dept")
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


def render_batch_adjust_dialog(ctx, target_dept: str, target_site: str):
    MONEY_FMT, PHASE_EVEN, PHASE_MANUAL, PHASE_ONE = ctx.MONEY_FMT, ctx.PHASE_EVEN, ctx.PHASE_MANUAL, ctx.PHASE_ONE
    budget_year, dept_key, format_vnd = ctx.budget_year, ctx.dept_key, ctx.format_vnd
    master, months, save_site, year_code = ctx.master, ctx.months, ctx.save_site, ctx.year_code

    target_dept, _locked = dialog_dept_picker(ctx, target_dept, "dlg_adj_dept")
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
