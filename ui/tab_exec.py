"""Giải ngân: theo dõi đề nghị mua / hợp đồng / thanh toán theo Mã hạng mục."""
import datetime

import pandas as pd
import streamlit as st

import db
import execution as ex


def render(ctx):
    """Nội dung tab - ctx: giá trị dùng chung của lượt chạy (app.app_context())."""
    ALL_DEPTS, ALL_SITES, MONEY_FMT, budget_year = ctx.ALL_DEPTS, ctx.ALL_SITES, ctx.MONEY_FMT, ctx.budget_year
    current_user, dept_key, dept_mask, df_curr = ctx.current_user, ctx.dept_key, ctx.dept_mask, ctx.df_curr
    format_vnd, format_vnd_short, months, scope_sites = ctx.format_vnd, ctx.format_vnd_short, ctx.months, ctx.scope_sites
    selected_dept, selected_site, site_label, site_status = ctx.selected_dept, ctx.selected_site, ctx.site_label, ctx.site_status

    st.markdown("### Thực hiện ngân sách")
    st.caption("Ghi nhận đề nghị mua, hợp đồng / PO và thanh toán theo Mã hạng mục đã duyệt. "
               "Còn lại = Ngân sách − max(Hợp đồng, Đề nghị). Số tiền chưa VAT, cùng cơ sở với ngân sách.")
    exec_rows = db.load_exec(budget_year, scope_sites)
    lines_exec = df_curr.drop(columns=["_order"], errors="ignore").copy()
    if "site_code" not in lines_exec.columns:
        lines_exec["site_code"] = selected_site
    # Ngân sách để so = bản duyệt gần nhất của site (đang điều chỉnh vẫn tính theo bản đã duyệt); chưa duyệt -> bản hiện tại
    approved_v = db.latest_version_lines(budget_year, scope_sites)
    if approved_v:
        parts = []
        for sc in scope_sites:
            if sc in approved_v:
                vdf = pd.DataFrame(approved_v[sc]["rows"]).assign(site_code=sc)
                parts.append(vdf[dept_mask(vdf, selected_dept)] if not vdf.empty else vdf)
            else:
                parts.append(lines_exec[lines_exec["site_code"] == sc])
        lines_exec = pd.concat(parts, ignore_index=True) if parts else lines_exec
        if current_user.is_dept_user and "dept_proposing" in lines_exec.columns:
            _allowed_x = {dept_key(d) for d in current_user.allowed_depts(selected_site)}
            lines_exec = lines_exec[lines_exec["dept_proposing"].map(dept_key).isin(_allowed_x)]
        st.caption("Ngân sách so sánh theo bản duyệt gần nhất: " + " · ".join(
            f"{sc} v{v['info']['version_no']} ({v['info']['label']}, {str(v['info']['created_at'])[:10]})" for sc, v in approved_v.items()))
    in_scope = set(lines_exec["item_code"]) if "item_code" in lines_exec.columns else set()
    if selected_dept != ALL_DEPTS:  # theo phòng ban: chỉ chứng từ của mã thuộc phòng
        exec_rows = [r for r in exec_rows if r["item_code"] in in_scope]
    summ = ex.summarize(lines_exec, exec_rows)
    tt = ex.totals(summ)
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Ngân sách", format_vnd_short(tt["budget"]))
    k2.metric("Đã đề nghị", format_vnd_short(tt["requested"]))
    k3.metric("Đã ký HĐ / PO", format_vnd_short(tt["contracted"]))
    k4.metric("Đã thanh toán", format_vnd_short(tt["paid"]), f"{tt['paid_pct'] * 100:.1f}% ngân sách", delta_color="off")
    k5.metric("Còn lại", format_vnd_short(tt["remaining"]))
    if tt["n_flag"]:
        st.warning(f"{tt['n_flag']} hạng mục có cảnh báo (vượt ngân sách / thanh toán vượt hợp đồng / mã không còn trong ngân sách) - xem đầu bảng.")

    site_approved = selected_site != ALL_SITES and site_status["status"] == db.STATUS_APPROVED
    can_record = selected_site != ALL_SITES and (current_user.is_admin or (current_user.role == db.ROLE_SITE_IT and selected_site in current_user.sites))
    ex_t1, ex_t2, ex_t3 = st.tabs(["Theo hạng mục", "Sổ chứng từ", "Kế hoạch vs thực chi"])
    money_ex = st.column_config.NumberColumn(format=MONEY_FMT)
    with ex_t1:
        only_used = st.checkbox("Chỉ hiện hạng mục đã có chứng từ", value=False, key="exec_only_used")
        view = summ[(summ[["requested", "contracted", "paid"]].sum(axis=1) > 0)] if only_used else summ
        st.dataframe(view.assign(site_code=view["site_code"].map(site_label)), use_container_width=True, hide_index=True, height=420,
                     column_config={"site_code": "Site", "item_code": "Mã hạng mục", "dept": "Phòng ban", "item_name": "Hạng mục",
                                    "budget": st.column_config.NumberColumn("Ngân sách", format=MONEY_FMT),
                                    "requested": st.column_config.NumberColumn("Đề nghị", format=MONEY_FMT),
                                    "contracted": st.column_config.NumberColumn("Hợp đồng / PO", format=MONEY_FMT),
                                    "paid": st.column_config.NumberColumn("Thanh toán", format=MONEY_FMT),
                                    "remaining": st.column_config.NumberColumn("Còn lại", format=MONEY_FMT),
                                    "paid_pct": st.column_config.ProgressColumn("% thanh toán", format="%.0f%%", min_value=0.0, max_value=1.0),
                                    "flag": "Cảnh báo"})
        st.download_button("📥 Tải báo cáo thực hiện (.csv)", view.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"ThucHien_{budget_year}_{'TONGHOP' if selected_site == ALL_SITES else selected_site}_{datetime.date.today():%Y%m%d}.csv",
                           mime="text/csv", key="exec_csv")

        if not can_record:
            st.caption("Chỉ Admin và IT site của site này ghi nhận thực hiện; tài khoản của bạn xem.")
        elif not site_approved:
            st.info("Ghi nhận thực hiện sau khi ngân sách site được Admin duyệt.")
        elif summ.empty:
            st.caption("Chưa có hạng mục ngân sách trong phạm vi đang chọn.")
        else:
            with st.form(f"exec_add_{st.session_state.get('exec_form_ver', 0)}"):  # giữ dữ liệu khi báo lỗi, làm trống sau khi ghi
                st.markdown("##### Ghi nhận chứng từ")
                opts = summ[summ["flag"] != ex.FLAG_NO_LINE].sort_values("budget", ascending=False)
                labels = {r["item_code"]: f"{r['item_code']} · {r['item_name']} · {r['dept']} (còn {r['remaining']:,.0f})"
                          for r in opts.to_dict("records")}
                f1, f2 = st.columns([3, 1])
                code = f1.selectbox("Hạng mục", list(labels), format_func=labels.get)
                kind = f2.selectbox("Loại chứng từ", list(db.EXEC_LABELS), format_func=db.EXEC_LABELS.get)
                g1, g2, g3 = st.columns(3)
                amount = g1.number_input("Số tiền (VNĐ, chưa VAT)", min_value=0.0, step=1_000_000.0, format="%.0f")
                doc_no = g2.text_input("Số chứng từ (ĐN / HĐ / UNC)")
                doc_date = g3.date_input("Ngày chứng từ", value=datetime.date.today())
                h1, h2 = st.columns(2)
                vendor = h1.text_input("Nhà cung cấp")
                note = h2.text_input("Ghi chú")
                force = st.checkbox("Vẫn ghi khi vượt ngân sách / hợp đồng", value=False)
                if st.form_submit_button("💾 Ghi nhận", type="primary"):
                    row = opts[opts["item_code"] == code].iloc[0].to_dict()
                    warn = ex.check_new(row, kind, float(amount))
                    if amount <= 0:
                        st.error("Số tiền phải lớn hơn 0.")
                    elif warn and not force:
                        st.error(warn + ". Kiểm tra lại, hoặc tích 'Vẫn ghi khi vượt' nếu đúng.")
                    else:
                        site_of = row["site_code"] or selected_site
                        db.add_exec(budget_year, site_of, code, kind, float(amount), current_user.email, doc_no.strip(),
                                    doc_date.strftime("%Y-%m-%d"), vendor.strip(), (note.strip() + (" [ghi khi vượt]" if warn else "")).strip())
                        st.session_state["flash"] = f"Đã ghi {db.EXEC_LABELS[kind]} {format_vnd(amount)} cho {code}."
                        st.session_state["exec_form_ver"] = st.session_state.get("exec_form_ver", 0) + 1
                        st.rerun()
        if can_record and site_approved and not summ.empty:
            with st.expander("Nạp nhiều chứng từ từ file (Excel / CSV xuất từ ERP)"):
                st.caption("Mỗi dòng 1 chứng từ: Mã hạng mục, Loại chứng từ, Số chứng từ, Ngày, Số tiền (chưa VAT), Nhà cung cấp, Ghi chú. "
                           "Xem trước trạng thái từng dòng rồi mới ghi; dòng lỗi và dòng trùng với sổ được bỏ qua.")
                st.download_button("📄 Tải file mẫu", ex.import_template(), file_name="Mau_ChungTu_GiaiNgan.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="exec_tpl")
                imp_ver = st.session_state.get("exec_imp_ver", 0)
                up = st.file_uploader("File chứng từ (.xlsx / .csv)", type=["xlsx", "xls", "csv"], key=f"exec_imp_file_{imp_ver}")
                if up is not None:
                    try:
                        raw_imp = (pd.read_csv(up, dtype=str, encoding="utf-8-sig") if up.name.lower().endswith(".csv")
                                   else pd.read_excel(up, sheet_name=0))
                    except (ValueError, UnicodeDecodeError, OSError) as e:
                        raw_imp = None
                        st.error(f"Không đọc được file: {e}")
                    if raw_imp is not None:
                        prev = ex.parse_import(raw_imp, summ, exec_rows)
                        n_ok = int((prev["status"] == ex.IMPORT_STATUS_OK).sum())
                        n_over = int((prev["status"] == ex.IMPORT_STATUS_OVER).sum())
                        n_skip = len(prev) - n_ok - n_over
                        st.write(f"**{len(prev)}** dòng: {n_ok} hợp lệ · {n_over} vượt ngân sách / hợp đồng · {n_skip} bỏ qua (lỗi / trùng)")
                        st.dataframe(prev.assign(site_code=prev["site_code"].map(site_label)), use_container_width=True, hide_index=True,
                                     column_order=["row", "status", "message", "item_code", "item_name", "kind_label", "doc_no",
                                                   "doc_date", "amount", "vendor", "note"],
                                     column_config={"row": "Dòng", "status": "Trạng thái", "message": "Lý do",
                                                    "item_code": "Mã hạng mục", "item_name": "Hạng mục", "kind_label": "Loại",
                                                    "doc_no": "Số chứng từ", "doc_date": "Ngày",
                                                    "amount": st.column_config.NumberColumn("Số tiền", format=MONEY_FMT),
                                                    "vendor": "Nhà cung cấp", "note": "Ghi chú"})
                        with_over = st.checkbox("Ghi cả dòng vượt ngân sách / hợp đồng", value=False, key=f"exec_imp_over_{imp_ver}")
                        take = prev[(prev["status"] == ex.IMPORT_STATUS_OK) | (with_over & (prev["status"] == ex.IMPORT_STATUS_OVER))]
                        if st.button(f"💾 Ghi {len(take)} chứng từ ({format_vnd(take['amount'].sum())})", type="primary",
                                     disabled=take.empty, key=f"exec_imp_go_{imp_ver}"):
                            rows_imp = [{**r, "site_code": r["site_code"] or selected_site,
                                         "note": (r["note"] + (" [ghi khi vượt]" if r["status"] == ex.IMPORT_STATUS_OVER else "")).strip()}
                                        for r in take.to_dict("records")]
                            n = db.add_exec_many(budget_year, rows_imp, current_user.email, source=up.name)
                            st.session_state["flash"] = f"Đã nạp {n} chứng từ ({format_vnd(take['amount'].sum())}) từ {up.name}."
                            st.session_state["exec_imp_ver"] = imp_ver + 1
                            st.rerun()
    with ex_t2:
        led = pd.DataFrame(exec_rows)
        if led.empty:
            st.caption("Chưa có chứng từ nào.")
        else:
            names = dict(zip(summ["item_code"], summ["item_name"]))
            led = led.assign(kind=led["kind"].map(db.EXEC_LABELS), item_name=led["item_code"].map(names))
            st.dataframe(led[["id", "doc_date", "kind", "doc_no", "item_code", "item_name", "amount", "vendor", "note", "created_by", "created_at"]]
                         .sort_values(["doc_date", "id"], ascending=False),
                         use_container_width=True, hide_index=True,
                         column_config={"id": "ID", "doc_date": "Ngày", "kind": "Loại", "doc_no": "Số chứng từ", "item_code": "Mã hạng mục",
                                        "item_name": "Hạng mục", "amount": st.column_config.NumberColumn("Số tiền", format=MONEY_FMT),
                                        "vendor": "Nhà cung cấp", "note": "Ghi chú", "created_by": "Người ghi", "created_at": "Lúc ghi"})
            if can_record and site_approved:
                with st.popover("Xóa chứng từ ghi nhầm"):
                    del_id = st.selectbox("Chọn chứng từ", led["id"].tolist(),
                                          format_func=lambda i: (lambda r: f"#{r['id']} · {r['doc_date']} · {r['kind']} {r['doc_no'] or ''} · "
                                                                           f"{r['item_code']} · {r['amount']:,.0f}")(led[led["id"] == i].iloc[0]))
                    if st.button("Xác nhận xóa", type="primary", key="exec_del"):
                        db.delete_exec(int(del_id), current_user.email)
                        st.session_state["flash"] = f"Đã xóa chứng từ #{del_id} (có ghi nhật ký)."
                        st.rerun()
    with ex_t3:
        pva = ex.plan_vs_actual(lines_exec, exec_rows, months)
        st.dataframe(pva, use_container_width=True, hide_index=True,
                     column_config={c: money_ex for c in pva.columns if c != "Tháng"})
        if pva.attrs.get("outside"):
            st.caption(f"Ngoài ra {format_vnd(pva.attrs['outside'])} thanh toán có ngày ngoài năm ngân sách {budget_year} (T10/{int(budget_year) - 1} – T9/{budget_year}).")
