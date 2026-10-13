"""Nhập / Xuất Excel, báo cáo theo Khối, kế hoạch mua sắm theo tháng / quý."""
import datetime

import openpyxl
import pandas as pd
import streamlit as st

import reports
from capex_engine import load_capex_from_excel


def render(ctx):
    """Nội dung tab - ctx: giá trị dùng chung của lượt chạy (app.app_context())."""
    ALL_DEPTS, ALL_SITES, MONEY_FMT, XLSX_MIME = ctx.ALL_DEPTS, ctx.ALL_SITES, ctx.MONEY_FMT, ctx.XLSX_MIME
    _cached_division_report, _cached_purchasing_plan_report, budget_year, can_edit = ctx._cached_division_report, ctx._cached_purchasing_plan_report, ctx.budget_year, ctx.can_edit
    current_user, dept_prop, df_curr, distribute_by_location = ctx.current_user, ctx.dept_prop, ctx.df_curr, ctx.distribute_by_location
    lazy_excel_download, months, prev_year_lines, save_site = ctx.lazy_excel_download, ctx.months, ctx.prev_year_lines, ctx.save_site
    save_view, selected_dept, selected_site, site_label = ctx.save_view, ctx.selected_dept, ctx.selected_site, ctx.site_label
    year_code = ctx.year_code

    st.markdown("### Nhập & Xuất File Excel Chuẩn Biểu mẫu Doanh nghiệp")

    ex_c1, ex_c2 = st.columns(2)

    with ex_c1:
        st.markdown("""
        <div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:10px; padding:20px;">
            <h4 style="color:#166534; margin-top:0;">Xuất file Excel CAPEX</h4>
            <p style="color:#15803D; font-size:13px;">
                Xuất toàn bộ bảng ngân sách hiện hành thành file Excel (.xlsx) chuẩn biểu mẫu <b>CA.01_CAPEX</b>.
                Đầy đủ công thức tính toán, định dạng màu sắc doanh nghiệp, tỷ lệ phân kỳ 12 tháng và mã ngân sách kế toán.
            </p>
        </div>
        """, unsafe_allow_html=True)

        if df_curr.empty:
            st.warning("Bảng dữ liệu đang trống, không thể xuất file.")
        else:
            scope_tag = "TONGHOP" if selected_site == ALL_SITES else selected_site
            file_name = f"CAPEX_{budget_year}_{scope_tag}_{dept_prop.replace(' ', '_')}_{datetime.date.today().strftime('%Y%m%d')}.xlsx"
            excel_bytes = lazy_excel_download(df_curr, st.session_state["metadata"],
                                              f"TẢI XUỐNG FILE EXCEL ({len(df_curr)} HẠNG MỤC)", file_name,
                                              key=f"all_{budget_year}_{selected_site}_{selected_dept}")
            if excel_bytes:
                st.caption(f"File: {file_name} (~{len(excel_bytes)//1024} KB)")

            # Báo cáo tổng hợp theo Khối -> Phòng ban -> Hạng mục
            scope_txt = (site_label(selected_site) if selected_site != ALL_SITES else "Tất cả site được xem") +                         ("" if selected_dept == ALL_DEPTS else f" · {selected_dept}")
            rep_meta = (("budget_year", budget_year), ("scope", scope_txt), ("date", datetime.date.today().strftime("%d/%m/%Y")))
            st.download_button("🏛️ Tải báo cáo theo Khối (.xlsx)",
                               _cached_division_report(df_curr.drop(columns=["_order"], errors="ignore"), prev_year_lines(), rep_meta),
                               file_name=f"BaoCao_Khoi_{budget_year}_{scope_tag}_{datetime.date.today():%Y%m%d}.xlsx",
                               mime=XLSX_MIME, use_container_width=True, key=f"div_rep_{budget_year}_{selected_site}_{selected_dept}",
                               help=f"Sheet 'Theo Khối' (so sánh năm {int(budget_year) - 1}) và 'Khối - Phòng - Hạng mục' (thu gọn được)")
            st.download_button("📅 Tải Kế hoạch Mua sắm & Phân kỳ (.xlsx)",
                               _cached_purchasing_plan_report(df_curr.drop(columns=["_order"], errors="ignore"), tuple(months), rep_meta),
                               file_name=f"KeHoach_MuaSam_{budget_year}_{scope_tag}_{datetime.date.today():%Y%m%d}.xlsx",
                               mime=XLSX_MIME, use_container_width=True, key=f"plan_rep_{budget_year}_{selected_site}_{selected_dept}",
                               help="Báo cáo 3 sheet: Kế hoạch theo Tháng (12 tháng), Kế hoạch theo Quý (4 quý), và Tổng hợp theo Nhóm CNTT")

    with ex_c2:
        st.markdown("""
        <div style="background:#EFF6FF; border:1px solid #BFDBFE; border-radius:10px; padding:20px;">
            <h4 style="color:#1E40AF; margin-top:0;">Nhập file Excel từ phòng ban</h4>
            <p style="color:#1D4ED8; font-size:13px;">
                Tải lên file Excel (.xlsx) theo biểu mẫu nhập liệu CAPEX để hệ thống tự động đọc, chuẩn hóa, tính toán và phân tích.
            </p>
        </div>
        """, unsafe_allow_html=True)

        import_to_all = selected_site == ALL_SITES and current_user.is_admin
        if not (can_edit or import_to_all):
            st.info("Bạn không có quyền nhập dữ liệu vào phạm vi đang chọn.")
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

                if st.button("⚡ Đọc dữ liệu từ file Excel", use_container_width=True):
                    up_meta, up_df = load_capex_from_excel(uploaded_file, sel_sheet, months=months, year_code=year_code)
                    up_meta.pop("creator_email", None)
                    st.session_state["metadata"].update(up_meta)
                    if up_df.empty:
                        st.warning("Không tìm thấy dòng dữ liệu nào trong sheet đã chọn.")
                    elif import_to_all:
                        groups, unmatched = distribute_by_location(up_df)
                        for code, part in groups.items():
                            save_site(part, code, overwrite=True)
                        st.session_state["flash"] = (f"Đã nhập {sum(len(p) for p in groups.values())} hạng mục vào {len(groups)} site."
                                                     + (f" Bỏ qua vị trí không khớp danh mục: {unmatched}" if unmatched else ""))
                        st.rerun()
                    else:
                        base = df_curr if import_mode == "append" else pd.DataFrame()
                        save_view(pd.concat([base, up_df], ignore_index=True))
                        st.session_state["flash"] = f"Đã nhập thành công {len(up_df)} hạng mục từ sheet '{sel_sheet}' vào {site_label(selected_site)}!"
                        st.rerun()
            except Exception as e:
                st.error(f"Lỗi khi đọc file Excel: {e}")

    if not df_curr.empty:
        st.divider()
        st.markdown("### Kế hoạch Mua sắm & Phân kỳ (Tháng / Quý)")
        st.caption("Xem trước và lọc chi tiết số lượng và số tiền theo 12 tháng (T10 → T9) hoặc 4 quý. Số lượng nguyên chuẩn xác theo phân kỳ.")

        kp_c1, kp_c2, kp_c3 = st.columns([1.5, 1, 1])
        with kp_c1:
            view_mode = st.radio("Chế độ hiển thị:", ["Theo Quý (4 quý)", "Theo Tháng (12 tháng)", "Tổng hợp theo Nhóm CNTT"],
                                 horizontal=True, key="plan_view_mode")
        with kp_c2:
            grp_opts = sorted(list({str(x).strip() for x in df_curr.get("it_group", pd.Series(dtype=object)).dropna() if str(x).strip()}))
            sel_plan_grps = st.multiselect("Lọc nhóm CNTT:", grp_opts, default=[], key="plan_filter_grp", help="Trống = tất cả nhóm")
        with kp_c3:
            dept_opts = sorted(list({str(x).strip() for x in df_curr.get("dept_proposing", pd.Series(dtype=object)).dropna() if str(x).strip()}))
            sel_plan_depts = st.multiselect("Lọc phòng ban:", dept_opts, default=[], key="plan_filter_dept", help="Trống = tất cả phòng")

        df_plan_src = df_curr.copy()
        if sel_plan_grps:
            df_plan_src = df_plan_src[df_plan_src.get("it_group").isin(sel_plan_grps)]
        if sel_plan_depts:
            df_plan_src = df_plan_src[df_plan_src.get("dept_proposing").isin(sel_plan_depts)]

        if view_mode == "Tổng hợp theo Nhóm CNTT":
            summ_tbl = reports.purchasing_plan_summary(df_plan_src, months, "it_group")
            if not summ_tbl.empty:
                st.dataframe(
                    summ_tbl,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Số hạng mục": st.column_config.NumberColumn(format=MONEY_FMT),
                        "Tổng SL": st.column_config.NumberColumn(format=MONEY_FMT),
                        "Tổng ngân sách": st.column_config.NumberColumn(format=MONEY_FMT),
                        "SL Q1": st.column_config.NumberColumn(format=MONEY_FMT),
                        "Tiền Q1": st.column_config.NumberColumn(format=MONEY_FMT),
                        "SL Q2": st.column_config.NumberColumn(format=MONEY_FMT),
                        "Tiền Q2": st.column_config.NumberColumn(format=MONEY_FMT),
                        "SL Q3": st.column_config.NumberColumn(format=MONEY_FMT),
                        "Tiền Q3": st.column_config.NumberColumn(format=MONEY_FMT),
                        "SL Q4": st.column_config.NumberColumn(format=MONEY_FMT),
                        "Tiền Q4": st.column_config.NumberColumn(format=MONEY_FMT),
                    }
                )
            else:
                st.info("Không có dữ liệu phù hợp với bộ lọc.")
        elif view_mode == "Theo Quý (4 quý)":
            plan_df = reports.purchasing_plan_df(df_plan_src, months)
            if not plan_df.empty:
                q_cols = [
                    "item_code", "item_name", "location", "dept_proposing", "it_group", "unit",
                    "unit_price", "quantity", "total_budget",
                    "qty_Q1", "amt_Q1", "qty_Q2", "amt_Q2", "qty_Q3", "amt_Q3", "qty_Q4", "amt_Q4"
                ]
                st.dataframe(
                    plan_df[q_cols],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "item_code": "Mã",
                        "item_name": "Tên hạng mục",
                        "location": "Site",
                        "dept_proposing": "Phòng ban",
                        "it_group": "Nhóm CNTT",
                        "unit": "ĐVT",
                        "unit_price": st.column_config.NumberColumn("Đơn giá", format=MONEY_FMT),
                        "quantity": st.column_config.NumberColumn("Tổng SL", format=MONEY_FMT),
                        "total_budget": st.column_config.NumberColumn("Thành tiền", format=MONEY_FMT),
                        "qty_Q1": st.column_config.NumberColumn("SL Q1", format=MONEY_FMT),
                        "amt_Q1": st.column_config.NumberColumn("Tiền Q1", format=MONEY_FMT),
                        "qty_Q2": st.column_config.NumberColumn("SL Q2", format=MONEY_FMT),
                        "amt_Q2": st.column_config.NumberColumn("Tiền Q2", format=MONEY_FMT),
                        "qty_Q3": st.column_config.NumberColumn("SL Q3", format=MONEY_FMT),
                        "amt_Q3": st.column_config.NumberColumn("Tiền Q3", format=MONEY_FMT),
                        "qty_Q4": st.column_config.NumberColumn("SL Q4", format=MONEY_FMT),
                        "amt_Q4": st.column_config.NumberColumn("Tiền Q4", format=MONEY_FMT),
                    }
                )
            else:
                st.info("Không có dữ liệu phù hợp với bộ lọc.")
        else:
            plan_df = reports.purchasing_plan_df(df_plan_src, months)
            if not plan_df.empty:
                m_cfg = {
                    "item_code": "Mã",
                    "item_name": "Tên hạng mục",
                    "location": "Site",
                    "dept_proposing": "Phòng ban",
                    "it_group": "Nhóm CNTT",
                    "unit": "ĐVT",
                    "unit_price": st.column_config.NumberColumn("Đơn giá", format=MONEY_FMT),
                    "quantity": st.column_config.NumberColumn("Tổng SL", format=MONEY_FMT),
                    "total_budget": st.column_config.NumberColumn("Thành tiền", format=MONEY_FMT),
                }
                for m in months:
                    m_cfg[f"qty_{m}"] = st.column_config.NumberColumn(f"SL {m}", format=MONEY_FMT)
                    m_cfg[f"amt_{m}"] = st.column_config.NumberColumn(f"Tiền {m}", format=MONEY_FMT)
                disp_cols = ["item_code", "item_name", "location", "dept_proposing", "it_group", "unit",
                             "unit_price", "quantity", "total_budget"] + [c for m in months for c in (f"qty_{m}", f"amt_{m}")]
                st.dataframe(
                    plan_df[disp_cols],
                    use_container_width=True,
                    hide_index=True,
                    column_config=m_cfg
                )
            else:
                st.info("Không có dữ liệu phù hợp với bộ lọc.")
