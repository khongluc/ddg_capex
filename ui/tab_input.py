"""Lập CapEx: chọn phòng ban, bảng ngân sách sửa trực tiếp, chọn nhanh theo danh mục, thêm 1 hạng mục."""
import datetime
import html as _html

import pandas as pd
import streamlit as st

import smart_advisor as advisor
import db
import quota as qt
import validators
from capex_engine import calculate_row, even_units, phase_presets
from master_data import (
    INVEST_TYPES,
    KIND_HARDWARE,
    SCOPE_SHARED,
    accounting_class,
    apply_it_catalog,
    classify_item,
    default_invest_type,
    division_of,
    it_groups,
    it_kinds,
    item_owner,
    item_scope,
)


def render(ctx):
    """Nội dung tab - ctx: giá trị dùng chung của lượt chạy (app.app_context())."""
    ALL_DEPTS, ALL_SITES, ITEM_FILTERS, MONEY_FMT = ctx.ALL_DEPTS, ctx.ALL_SITES, ctx.ITEM_FILTERS, ctx.MONEY_FMT
    SITE_NAME, _commit_checklist_items, budget_year, can_edit = ctx.SITE_NAME, ctx._commit_checklist_items, ctx.budget_year, ctx.can_edit
    dept_key, dept_list, dept_state, df_curr = ctx.dept_key, ctx.dept_list, ctx.dept_state, ctx.df_curr
    df_site, format_vnd, format_vnd_short, item_filter_widgets = ctx.df_site, ctx.format_vnd, ctx.format_vnd_short, ctx.item_filter_widgets
    lazy_excel_download, master, months, phasing_picker = ctx.lazy_excel_download, ctx.master, ctx.months, ctx.phasing_picker
    render_batch_adjust_dialog, render_dept_overview, render_dept_workflow, render_item_picker_dialog = ctx.render_batch_adjust_dialog, ctx.render_dept_overview, ctx.render_dept_workflow, ctx.render_item_picker_dialog
    save_site, save_view, selected_dept, selected_site = ctx.save_site, ctx.save_view, ctx.selected_dept, ctx.selected_site
    site_can_edit, site_label, year_code = ctx.site_can_edit, ctx.site_label, ctx.year_code

    st.markdown("### 📝 Biểu mẫu Lập & Nhập liệu Ngân sách CAPEX")

    if selected_site == ALL_SITES:
        st.info("🌐 Đang xem tổng hợp nhiều site (chỉ đọc). Chọn một site cụ thể ở thanh bên trái để nhập liệu.")
    elif not can_edit:
        if site_can_edit and selected_dept != ALL_DEPTS and dept_state(selected_dept)["status"] in db.DEPT_LOCKED_STATUSES:
            st.info(f"🔒 {selected_dept} đã nộp / đã duyệt - chỉ xem. IT site trả lại hoặc mở lại phòng ban nếu cần chỉnh sửa.")
        else:
            st.info("🔒 Bạn không có quyền chỉnh sửa ngân sách site này ở trạng thái hiện tại (chỉ xem).")

    # 1. Bộ chọn Phòng ban & Thẻ thông tin tiến độ
    col_d1, col_d2 = st.columns([1.6, 2.4])
    with col_d1:
        dept_options_input = [d for d in dept_list if d != ALL_DEPTS]
        if selected_dept != ALL_DEPTS and selected_dept in dept_options_input:
            st.session_state["active_dept_selector"] = selected_dept
        elif st.session_state.get("active_dept_selector") not in dept_options_input:
            st.session_state.pop("active_dept_selector", None)

        def _sync_dept_from_input():
            st.session_state["sb_dept"] = st.session_state["active_dept_selector"]

        active_dept = st.selectbox(
            "🏢 Phòng ban lập ngân sách:",
            dept_options_input,
            key="active_dept_selector",
            on_change=_sync_dept_from_input,
            help="Chọn phòng ban cần trang bị thiết bị, phần mềm và dịch vụ CNTT. Bảng & báo cáo lọc theo phòng ban này."
        )
        if selected_dept == ALL_DEPTS:
            st.caption("Bảng bên dưới đang hiện **tất cả phòng ban**. Chọn một phòng ban ở ô trên để lọc.")

    dept_rows_now = df_site[df_site["dept_proposing"].map(dept_key) == dept_key(active_dept)] if not df_site.empty and "dept_proposing" in df_site.columns else pd.DataFrame()
    dept_cnt = len(dept_rows_now)
    dept_sum = dept_rows_now["total_budget"].sum() if not dept_rows_now.empty and "total_budget" in dept_rows_now.columns else 0.0
    _ctype = dept_rows_now["capex_type"] if "capex_type" in dept_rows_now.columns else pd.Series(index=dept_rows_now.index, dtype=object)
    dept_cx = dept_rows_now.loc[_ctype == "CAPEX", "total_budget"].sum() if not dept_rows_now.empty else 0.0
    dept_cc = dept_rows_now.loc[_ctype == "CCDC", "total_budget"].sum() if not dept_rows_now.empty else 0.0
    dept_op = dept_rows_now.loc[_ctype == "OPEX", "total_budget"].sum() if not dept_rows_now.empty else 0.0

    with col_d2:
        st.markdown(f"""
        <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:12px; padding:12px 18px; box-shadow:0 1px 3px rgba(0,0,0,0.03); display:flex; justify-content:space-between; align-items:center;">
            <div>
                <div style="font-size:11.5px; font-weight:700; color:#64748B; text-transform:uppercase; letter-spacing:0.05em;">Tiến độ lập ngân sách phòng ban</div>
                <div style="font-size:15px; font-weight:800; color:#0F2C59; margin-top:2px;">
                    🏢 {_html.escape(active_dept)}
                    <span style="font-size:12px; font-weight:500; color:#64748B; margin-left:6px;">({site_label(selected_site)})</span>
                </div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:17px; font-weight:800; color:#1E40AF;">{format_vnd(dept_sum)}</div>
                <div style="font-size:12px; color:#475569; margin-top:2px;">
                    <b>{dept_cnt}</b> hạng mục · <span style="color:#059669; font-weight:600;">TSCĐ: {format_vnd_short(dept_cx)}</span> | <span style="color:#2563EB; font-weight:600;">CCDC: {format_vnd_short(dept_cc)}</span> | <span style="color:#7C3AED; font-weight:600;">OPEX: {format_vnd_short(dept_op)}</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Nộp & duyệt theo phòng ban
    if selected_site != ALL_SITES:
        if selected_dept == ALL_DEPTS:
            render_dept_overview()
        else:
            render_dept_workflow(selected_dept, dept_rows_now)

    # KIỂM ĐỊNH CHẤT LƯỢNG HỒ SƠ & ĐIỂM SỨC KHỎE NGÂN SÁCH (SMART AUDIT)
    audit_target_df = dept_rows_now if selected_dept != ALL_DEPTS else df_site
    if not audit_target_df.empty:
        audit_res = advisor.audit_budget(audit_target_df, master, months)
        with st.expander(f"🛡️ Kiểm định Chất lượng Hồ sơ & Điểm Sức khỏe: {audit_res['score']}/100 điểm ({audit_res['status_label']})", expanded=(audit_res["score"] < 80)):
            ak1, ak2, ak3, ak4 = st.columns(4)
            ak1.metric("Điểm sức khỏe", f"{audit_res['score']} / 100", audit_res["status_label"], delta_color="normal")
            ak2.metric("Lỗi nghiêm trọng (Critical)", f"{audit_res['metrics']['critical']} cờ", delta_color="inverse" if audit_res['metrics']['critical'] > 0 else "normal")
            ak3.metric("Cảnh báo lưu ý (Warning)", f"{audit_res['metrics']['warning']} cờ", delta_color="off")
            ak4.metric("Tổng hạng mục rà soát", f"{audit_res['metrics']['total_items']} mục")

            if audit_res["issues"]:
                st.markdown("###### Chi tiết các vấn đề cần lưu ý:")
                for iss in audit_res["issues"]:
                    icon = "🚨" if iss["severity"] == advisor.SEV_CRITICAL else ("⚠️" if iss["severity"] == advisor.SEV_WARNING else "ℹ️")
                    color = "#EF4444" if iss["severity"] == advisor.SEV_CRITICAL else ("#F59E0B" if iss["severity"] == advisor.SEV_WARNING else "#3B82F6")
                    st.markdown(f"""
                    <div style="background:#FFFFFF;border-left:4px solid {color};border-radius:6px;padding:8px 12px;margin-bottom:8px;box-shadow:0 1px 3px rgba(0,0,0,0.03);">
                        <div style="font-weight:700;color:#0F2C59;font-size:13px;">{icon} {iss['title']}</div>
                        <div style="font-size:12px;color:#475569;margin-top:2px;">{iss['desc']}</div>
                        <div style="font-size:11.5px;color:#1D4ED8;font-weight:600;margin-top:3px;">👉 Hướng xử lý: {iss['action']}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.success("✅ Tuyệt vời! Toàn bộ hạng mục đã đáp ứng chuẩn mực phân kỳ, phân loại kế toán và căn cứ thẩm định.")

    # Bảng chi tiết của phòng ban đang chọn (đặt ngay dưới ô chọn phòng ban)
    grid_title = f"📋 Bảng Ngân sách Hiện hành – {active_dept}" if selected_dept != ALL_DEPTS else f"📋 Bảng Ngân sách Hiện hành – {site_label(selected_site)} (Tất cả phòng ban)"
    st.markdown(f"#### {grid_title}")

    if df_curr.empty:
        st.info("Bảng đang trống. Hãy thêm hạng mục mới bằng form phía dưới hoặc nhập file Excel!")
    else:
        # Lọc theo hạng mục (riêng cho từng site + phòng ban)
        grid_filter_key = f"gridflt_{budget_year}_{selected_site}_{dept_key(selected_dept)}"
        grid_mask = item_filter_widgets(df_curr, grid_filter_key)

        # Kiểm tra tính hợp lệ & cờ cảnh báo của bảng hiện hành
        val_report = validators.validate_budget_rows(df_curr, months=months, master=master)
        only_errors = False
        if val_report.invalid_item_codes:
            crit_c = len(val_report.critical_item_codes)
            warn_c = len(val_report.warning_item_codes)
            badge_details = []
            if crit_c:
                badge_details.append(f"{crit_c} lỗi nghiêm trọng")
            if warn_c:
                badge_details.append(f"{warn_c} cảnh báo")
            lbl = f"🚨 Chỉ hiện các dòng cần xử lý ({len(val_report.invalid_item_codes)} dòng · {', '.join(badge_details)})"
            only_errors = st.toggle(
                lbl,
                key=f"flterr_{budget_year}_{selected_site}_{dept_key(selected_dept)}",
                help="Bật để chỉ hiển thị các dòng bị lỗi phân kỳ, thiếu đơn giá/số lượng, thiếu căn cứ hoặc cảnh báo giá/danh mục"
            )
            if only_errors and "item_code" in df_curr.columns:
                is_err_row = df_curr["item_code"].isin(val_report.invalid_item_codes)
                grid_mask = grid_mask & is_err_row

        grid_filtered = not bool(grid_mask.all())
        df_grid = df_curr[grid_mask]

        # Display summary row on top of grid
        tot_budget_all = df_grid["total_budget"].sum()
        col_m1, col_m2, col_m3, col_m4 = st.columns([2, 1, 1, 1])
        with col_m1:
            if grid_filtered:
                st.write(f"**Đang lọc:** {len(df_grid)}/{len(df_curr)} mục | **Tổng Ngân sách (đã lọc):** {format_vnd(tot_budget_all)}")
                st.caption(f"Tổng cả phòng ban: {format_vnd(df_curr['total_budget'].sum())}. Tải Excel / Chuẩn hóa vẫn tính toàn bộ dòng.")
            else:
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
            if can_edit and not dept_rows_now.empty:
                if st.button("📋 Rà soát & Sửa nhanh", use_container_width=True, key="btn_tbl_adj_dlg", help="Mở popup checklist để đổi tháng hoặc xóa hàng loạt"):
                    render_batch_adjust_dialog(active_dept, selected_site)
            elif can_edit:
                st.caption("💡 Chọn dòng và bấm Delete để xóa.")

        # Setup columns for interactive editor
        core_cols = [
            "stt", "review_note", "need_type", "need_reason", "it_group", "catalog_code", "item_name", "detail_work", "unit", "quantity", "unit_price",
            "total_budget", "invest_type", "item_kind_label", "capex_type", "accounting_class", "total_pct",
            "entity", "dept_using", "location", "asset_cat1", "asset_cat2", "cost_lv1", "cost_lv2",
            "handover_date", "project_code", "item_code", "budget_code"
        ]
        column_order = [c for c in core_cols if c in df_curr.columns] + [c for c in df_curr.columns if c not in core_cols]

        if not can_edit:
            st.dataframe(df_grid, use_container_width=True, height=450, hide_index=True,
                         column_order=[c for c in column_order if c not in ("_order", "item_seq", "item_code_base", "handover_auto")],
                         column_config={**{c: st.column_config.NumberColumn(format=MONEY_FMT) for c in df_curr.columns
                                           if c in ("quantity", "unit_price", "total_budget", "total_val") or c.startswith("val_")},
                                        "total_pct": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.0f%%")})
            edited_df = df_grid
        else:
            # Khóa gồm cả bộ lọc: đổi bộ lọc -> bảng sửa tạo lại (tránh áp chỗ sửa dở sang dòng khác)
            _flt_sig = abs(hash((tuple(tuple(st.session_state.get(f"{grid_filter_key}_{c}", [])) for _, c in ITEM_FILTERS), bool(only_errors))))
            main_editor_key = f"editor_{budget_year}_{selected_site}_{dept_key(selected_dept)}_{_flt_sig}_{st.session_state.get('editor_version', 0)}"
            edited_df = st.data_editor(
                df_grid,
                key=main_editor_key,
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
                    "quantity": st.column_config.NumberColumn("Số lượng", min_value=1, format=MONEY_FMT),
                    "unit_price": st.column_config.NumberColumn("Đơn giá (VNĐ)", format=MONEY_FMT),
                    "total_budget": st.column_config.NumberColumn("Tổng ngân sách (VNĐ)", format=MONEY_FMT, disabled=True),
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
                    "auto_quota": None,
                    "item_seq": None,
                    "item_code_base": None,
                    "handover_auto": None,
                    "review_note": st.column_config.TextColumn("Ghi chú duyệt", disabled=True, help="Ghi chú của IT site khi duyệt / trả lại"),
                    "handover_date": st.column_config.TextColumn("Ngày bàn giao", help="YYYY-MM-DD. Để trống = cuối tháng giải ngân cuối"),
                    **{c: st.column_config.NumberColumn(format=MONEY_FMT, disabled=True) for c in df_curr.columns if c.startswith("val_") or c == "total_val"},
                }
            )

        # Check if edits happened
        # Chỉ lưu khi người dùng thật sự sửa bảng (Streamlit ghi nhận ô sửa / dòng thêm / dòng xóa).
        # So sánh DataFrame đơn thuần có thể khác do kiểu dữ liệu -> tự lưu & chạy lại trang ngoài ý muốn,
        # làm mất các dòng đang nhập ở bảng khác (vd. Hạ tầng CNTT).
        _ed_state = st.session_state.get(main_editor_key) if can_edit else None
        _has_edits = isinstance(_ed_state, dict) and any(_ed_state.get(k) for k in ("edited_rows", "added_rows", "deleted_rows"))
        if can_edit and _has_edits and not edited_df.equals(df_grid):
            # Đang lọc: giữ nguyên các dòng bị ẩn của phòng ban, chỉ thay các dòng đang hiển thị
            save_view(pd.concat([df_curr[~grid_mask], edited_df], ignore_index=True) if grid_filtered else edited_df)
            st.rerun()

    if can_edit and dept_state(active_dept)["status"] in db.DEPT_LOCKED_STATUSES:
        st.info(f"🔒 {active_dept} đã nộp / đã duyệt - không thêm hạng mục. IT site trả lại hoặc mở lại phòng ban nếu cần bổ sung.")
    elif can_edit:
        st.markdown(f"#### ⚡ Lập & Điều chỉnh Ngân sách – {active_dept}")
        col_dlg_btn1, col_dlg_btn2 = st.columns([1.6, 1.4])
        with col_dlg_btn1:
            if st.button("✨ MỞ POPUP CHECKLIST THÔNG MINH (Gói Chức Danh & Chọn Nhanh)", type="primary", use_container_width=True, key="btn_open_picker_dlg"):
                render_item_picker_dialog(active_dept, selected_site)
        with col_dlg_btn2:
            if not dept_rows_now.empty and st.button("📋 POPUP CHECKLIST RÀ SOÁT & SỬA NHANH", use_container_width=True, key="btn_open_adj_dlg"):
                render_batch_adjust_dialog(active_dept, selected_site)

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
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
            st.caption("Chọn một hoặc nhiều nhóm CNTT, nhập số lượng cần mua vào cột 'Số lượng' (món không mua để 0), chọn cách phân bổ tháng (1 tháng, chia đều nhiều tháng hoặc tự nhập SL từng tháng) rồi bấm 'Thêm'.")

            catalog_all = master.get("standard_items", [])
            grp_list = it_groups(master)

            grp_labels = [f"{g['code']}. {g['name']}" for g in grp_list]
            b_col1, b_col3 = st.columns([2.5, 1])
            with b_col1:
                b_grp_labels = st.multiselect(
                    "1. Chọn Nhóm CNTT (chọn được nhiều nhóm):",
                    grp_labels,
                    default=grp_labels[:1],
                    key="batch_grp_picker",
                    help="Số lượng đã nhập được giữ lại khi thêm / bớt nhóm"
                )
                b_grp_codes = [lbl.split(".")[0].strip() for lbl in b_grp_labels]

            with b_col3:
                b_need_type = st.radio(
                    "2. Loại nhu cầu:",
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

            # Lấy danh sách thiết bị thuộc các nhóm đã chọn
            grp_items = [it for it in catalog_all if any(it.get("group") == c or str(it.get("group", "")).startswith(c) for c in b_grp_codes)]
            # SL / ghi chú đã nhập theo mã hạng mục, giữ qua các lần đổi nhóm
            b_kept = st.session_state.setdefault(f"batch_kept_{st.session_state.get('batch_ver', 0)}", {})

            if not b_grp_codes:
                st.info("Chọn ít nhất 1 nhóm CNTT.")
            elif not grp_items:
                st.warning(f"Không có hạng mục nào thuộc nhóm {', '.join(b_grp_labels)}.")
            else:
                batch_rows = []
                for it in grp_items:
                    cls_prev = classify_item(it, master)
                    acc_lbl, capex_tg = accounting_class(cls_prev.get("item_kind", KIND_HARDWARE), float(it.get("price", 0)), master)
                    kept_q, kept_note = b_kept.get(it.get("code", "") or it["name"], (0, ""))
                    batch_rows.append({
                        "Mã": it.get("code", ""),
                        "Tên thiết bị / Hạng mục": it["name"],
                        "ĐVT": it.get("unit", "Cái"),
                        "Giá tham chiếu (VNĐ)": float(it.get("price", 0)),
                        "Phân loại": f"{capex_tg}",
                        "Số lượng": kept_q,
                        "Ghi chú / Đối tượng": kept_note
                    })

                df_batch_grid = pd.DataFrame(batch_rows)
                edited_batch = st.data_editor(
                    df_batch_grid,
                    key=f"batch_editor_{'_'.join(b_grp_codes)}_{st.session_state.get('batch_ver', 0)}",
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Mã": st.column_config.TextColumn("Mã", disabled=True, width="small"),
                        "Tên thiết bị / Hạng mục": st.column_config.TextColumn("Tên thiết bị / Hạng mục", disabled=True, width="large"),
                        "ĐVT": st.column_config.TextColumn("ĐVT", disabled=True, width="small"),
                        "Giá tham chiếu (VNĐ)": st.column_config.NumberColumn("Đơn giá chuẩn (VNĐ)", disabled=True, format=MONEY_FMT),
                        "Phân loại": st.column_config.TextColumn("Phân loại", disabled=True, width="small"),
                        "Số lượng": st.column_config.NumberColumn("Số lượng cần mua", min_value=0, step=1, format=MONEY_FMT, required=True),
                        "Ghi chú / Đối tượng": st.column_config.TextColumn("Ghi chú / Đối tượng sử dụng", width="medium")
                    }
                )
                for _, r_b in edited_batch.iterrows():
                    b_kept[r_b["Mã"] or r_b["Tên thiết bị / Hạng mục"]] = (int(pd.to_numeric(r_b["Số lượng"], errors="coerce") or 0),
                                                                          str(r_b["Ghi chú / Đối tượng"] or ""))

                selected_batch = edited_batch[edited_batch["Số lượng"] > 0].rename(
                    columns={"Giá tham chiếu (VNĐ)": "Đơn giá (VNĐ)", "Ghi chú / Đối tượng": "Ghi chú"})
                st.markdown("**3. Phân bổ theo tháng:**")
                selected_batch, b_err = phasing_picker(selected_batch, "batch")
                num_sel = len(selected_batch)
                total_batch_cost = (selected_batch["Số lượng"] * selected_batch["Đơn giá (VNĐ)"]).sum() if num_sel > 0 else 0

                b_sub1, b_sub2 = st.columns([2, 1.2])
                with b_sub1:
                    st.markdown(f"""
                    <div style="background:#EFF6FF; border:1px solid #BFDBFE; border-radius:10px; padding:8px 14px; display:flex; align-items:center; gap:10px;">
                        <span style="font-size:20px;">🛒</span>
                        <div>
                            <div style="font-size:11px; color:#1E40AF; font-weight:700; text-transform:uppercase;">Đã chọn cho {_html.escape(active_dept)}</div>
                            <div style="font-size:14px; font-weight:700; color:#0F2C59;">{num_sel} thiết bị · Dự toán: {format_vnd(total_batch_cost)}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                with b_sub2:
                    if st.button(f"➕ Thêm {num_sel} mục vào {active_dept}", type="primary", use_container_width=True, disabled=num_sel == 0):
                        if b_err:
                            st.error(b_err)
                        elif b_need_type == qt.NEED_NEW and not b_reason.strip():
                            st.error("Vui lòng ghi rõ 'Lý do phát sinh / căn cứ trang bị' trước khi thêm!")
                        else:
                            st.session_state["batch_ver"] = st.session_state.get("batch_ver", 0) + 1
                            _commit_checklist_items(selected_batch, active_dept, selected_site, None, b_need_type, b_reason)

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
                    _mapped_div = division_of(active_dept, master)
                    div_options = [""] + list(dict.fromkeys(([_mapped_div] if _mapped_div else []) + master.get("divisions", [])))
                    f_division = st.selectbox("Khối", div_options, index=div_options.index(_mapped_div),
                                              format_func=lambda v: v or "(Trống – tự lấy theo phòng ban)")
                    st.text_input("(*) Phòng ban đề xuất", value=active_dept, disabled=True)
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
                    f_supplier = st.text_input("Nhà cung cấp (Nếu có)", value="")

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
                    ["Giải ngân 100% vào tháng nghiệm thu", "Chia đều 12 tháng", "Chia đều SL các tháng chọn", "Tự nhập tỷ lệ từng tháng"],
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
                elif alloc_type == "Chia đều SL các tháng chọn":
                    f_months = st.multiselect("Các tháng mua (SL nguyên chia đều, dư dồn tháng sớm):", months,
                                              default=phase_presets(months)["Đầu mỗi quý"], key="single_alloc_months")
                    f_units = even_units(f_qty, months, f_months)
                    for j, m in enumerate(months):
                        pct_inputs[m] = (f_units[j] / f_qty if f_units else (1.0 / len(f_months) if m in f_months else 0.0)) if f_months else 0.0
                    if f_units:
                        st.info("👉 " + " · ".join(f"{m}: {u}" for m, u in zip(months, f_units) if u))
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
                        saved_rows = save_site(updated_site_df.reset_index(drop=True), selected_site)
                        st.session_state["flash"] = f"✅ Đã thêm hạng mục '{f_item_name}' vào phòng ban '{active_dept}' thành công! (Mã: {saved_rows[-1]['item_code']})"
                        st.rerun()
