"""Hạ tầng CNTT dùng chung theo site."""
import json

import pandas as pd
import streamlit as st

import db
import quota as qt
from capex_engine import phase_text, regrid_pcts
from master_data import DEFAULT_INFRA_OWNER, INVEST_TYPES, SCOPE_SHARED, apply_it_catalog, item_owner, item_scope


def render(ctx):
    """Nội dung tab - ctx: giá trị dùng chung của lượt chạy (app.app_context())."""
    ALL_DEPTS, ALL_SITES, MONEY_FMT, SITE_NAME = ctx.ALL_DEPTS, ctx.ALL_SITES, ctx.MONEY_FMT, ctx.SITE_NAME
    budget_year, can_edit, current_user, dept_list = ctx.budget_year, ctx.can_edit, ctx.current_user, ctx.dept_list
    df_site, format_vnd, format_vnd_short, master = ctx.df_site, ctx.format_vnd, ctx.format_vnd_short, ctx.master
    months, phasing_picker, save_site, selected_dept = ctx.months, ctx.phasing_picker, ctx.save_site, ctx.selected_dept
    selected_site, site_label = ctx.selected_site, ctx.site_label

    st.markdown("### Hạ tầng CNTT dùng chung theo site")
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
                         column_config={c: st.column_config.NumberColumn(format=MONEY_FMT) for c in pv.columns})
    else:
        df_inf = df_site[infra_mask]
        st.markdown(f"#### {site_label(selected_site)}")
        if selected_dept != ALL_DEPTS:
            st.caption("Hạ tầng dùng chung lập theo site, nên hiển thị toàn bộ hạ tầng của site (không lọc theo phòng ban đang chọn).")

        def _infra_row(item, invest_type, qty, price, units, dept, reason):
            entity = (df_site["entity"].mode().iloc[0] if "entity" in df_site.columns and not df_site["entity"].dropna().empty else "DDC")
            row = {"entity": entity, "location": SITE_NAME.get(selected_site, selected_site), "quantity": float(qty),
                   "unit_price": float(price), "dept_proposing": dept or item_owner(item, master),
                   "dept_using": "Dùng chung toàn site", "need_type": qt.NEED_INFRA, "need_reason": reason,
                   "detail_work": "Hạ tầng CNTT dùng chung"}
            apply_it_catalog(row, master, item=item, invest_type=invest_type)
            for m, u in zip(months, units):  # SL nguyên từng tháng
                row[f"pct_{m}"] = u / qty
            return row

        def _confirm_infra_saved(expected: int, action: str):
            saved = [l for l in db.load_lines(budget_year, [selected_site]) if l.get("need_type") == qt.NEED_INFRA]
            where = "PostgreSQL" if db.using_server_db() else "SQLite"
            if len(saved) == expected:
                st.session_state["flash"] = (f"{action} – CSDL {where} hiện có {len(saved)} hạng mục hạ tầng của {site_label(selected_site)} "
                                             f"(tổng {format_vnd(sum(l.get('total_budget', 0) for l in saved))}).")
            else:
                st.session_state["flash"] = (f"{action} nhưng CSDL {where} đang có {len(saved)} dòng hạ tầng (mong đợi {expected}) – "
                                             "vui lòng kiểm tra lại.")

        # Thêm nhiều hạng mục 1 lần (ổn định hơn nhập trực tiếp trên lưới), phân kỳ 1 / nhiều tháng
        if can_edit:
            inf_ver = st.session_state.get("infra_version", 0)
            with st.expander("Thêm hạng mục hạ tầng", expanded=df_inf.empty):
                f_items = st.multiselect("(*) Hạng mục hạ tầng (chọn được nhiều)", list(sh_label.values()),
                                         placeholder="Chọn hạng mục...", key=f"infra_add_items_{inf_ver}")
                add_ed, f_err = pd.DataFrame(), None
                if f_items:
                    add_df = pd.DataFrame([{"Mã": sh_by_label[l], "Tên thiết bị / Hạng mục": sh_by_code[sh_by_label[l]]["name"],
                                            "Hình thức": INVEST_TYPES[0], "Số lượng": 1,
                                            "Đơn giá (VNĐ)": float(sh_by_code[sh_by_label[l]].get("price", 0) or 0)} for l in f_items])
                    add_ed = st.data_editor(add_df, key=f"infra_add_grid_{inf_ver}_{abs(hash(tuple(f_items))) % 10**8}",
                                            hide_index=True, use_container_width=True,
                                            column_config={
                                                "Mã": st.column_config.TextColumn("Mã", disabled=True, width="small"),
                                                "Tên thiết bị / Hạng mục": st.column_config.TextColumn("Hạng mục", disabled=True, width="large"),
                                                "Hình thức": st.column_config.SelectboxColumn("Hình thức", options=INVEST_TYPES, required=True),
                                                "Số lượng": st.column_config.NumberColumn("Số lượng", min_value=1, step=1, format="%d", required=True),
                                                "Đơn giá (VNĐ)": st.column_config.NumberColumn("Đơn giá (VNĐ)", min_value=0, format=MONEY_FMT),
                                            })
                    add_ed, f_err = phasing_picker(add_ed, f"infra_add_{inf_ver}")
                fb3, fb4 = st.columns([1.2, 2])
                owners_list = sorted({item_owner(it, master) for it in shared_items} | set(dept_list))
                f_dept = fb3.selectbox("Phòng đề xuất", owners_list, key=f"infra_add_dept_{inf_ver}",
                                       index=owners_list.index(DEFAULT_INFRA_OWNER) if DEFAULT_INFRA_OWNER in owners_list else 0)
                f_reason = fb4.text_input("(*) Căn cứ / lý do", key=f"infra_add_reason_{inf_ver}",
                                          placeholder="VD: Triển khai hệ thống DWH; thay firewall hết hỗ trợ...")
                if st.button(f"➕ Thêm {len(add_ed)} hạng mục vào ngân sách hạ tầng", type="primary", use_container_width=True,
                             disabled=add_ed.empty, key=f"infra_add_btn_{inf_ver}"):
                    if f_err:
                        st.error(f_err)
                    elif (add_ed["Số lượng"] <= 0).any():
                        st.error("Nhập số lượng lớn hơn 0 cho mọi hạng mục.")
                    elif not f_reason.strip():
                        st.error("Cần ghi Căn cứ / lý do.")
                    else:
                        new = []
                        for _, r in add_ed.iterrows():
                            it = sh_by_code[r["Mã"]]
                            price = r.get("Đơn giá (VNĐ)")
                            price = float(it.get("price", 0)) if price is None or pd.isna(price) or price <= 0 else float(price)
                            new.append(_infra_row(it, r.get("Hình thức") or INVEST_TYPES[0], sum(r["_units"]), price, r["_units"],
                                                  f_dept, f_reason.strip()))
                        st.session_state["infra_version"] = inf_ver + 1
                        save_site(pd.concat([df_site, pd.DataFrame(new)], ignore_index=True), selected_site)
                        _confirm_infra_saved(len(df_inf) + len(new), f"Đã thêm {len(new)} hạng mục hạ tầng")
                        st.rerun()

        st.markdown("##### Danh sách hạng mục hạ tầng của site (sửa / xóa trực tiếp trên bảng)")

        def first_month(r):
            for m in months:
                if qt._num(r.get(f"pct_{m}")) > 0:
                    return m
            return months[0]

        df_edit = pd.DataFrame([{
            "item": sh_label.get(r.get("catalog_code"), r.get("item_name")), "invest_type": r.get("invest_type") or "Mua mới",
            "quantity": r.get("quantity"), "unit_price": r.get("unit_price"), "month": first_month(r),
            "phase": phase_text([qt._num(r.get(f"pct_{m}")) for m in months], qt._num(r.get("quantity"), 0.0), months),
            "dept_proposing": r.get("dept_proposing"), "need_reason": r.get("need_reason") or "",
            "item_seq": r.get("item_seq"), "item_code_base": r.get("item_code_base"),  # ẩn: giữ Mã hạng mục cố định
            "pcts": json.dumps([qt._num(r.get(f"pct_{m}")) for m in months]),  # ẩn: giữ phân kỳ nhiều tháng khi lưu
        } for _, r in df_inf.iterrows()], columns=["item", "invest_type", "quantity", "unit_price", "month", "phase", "dept_proposing",
                                                    "need_reason", "item_seq", "item_code_base", "pcts"])
        owners = sorted({item_owner(it, master) for it in shared_items} | set(dept_list))
        ed_inf = st.data_editor(
            df_edit, key=f"infra_{budget_year}_{selected_site}_{st.session_state.get('infra_version', 0)}",
            num_rows="dynamic" if can_edit else "fixed", disabled=not can_edit, use_container_width=True, hide_index=True,
            column_config={
                "item": st.column_config.SelectboxColumn("Hạng mục hạ tầng", options=list(sh_label.values()), required=True, width="large"),
                "invest_type": st.column_config.SelectboxColumn("Hình thức", options=INVEST_TYPES, required=True),
                "quantity": st.column_config.NumberColumn("Số lượng", min_value=1, step=1, format=MONEY_FMT, required=True),
                "unit_price": st.column_config.NumberColumn("Đơn giá (VNĐ, trống = giá danh mục)", min_value=0, format=MONEY_FMT),
                "month": st.column_config.SelectboxColumn("Tháng triển khai (đầu)", options=months, required=True,
                                                          help="Đổi tháng: cả SL dồn vào tháng mới. Giữ nguyên: giữ phân kỳ nhiều tháng đang có"),
                "phase": st.column_config.TextColumn("Phân kỳ hiện tại", disabled=True, width="medium"),
                "dept_proposing": st.column_config.SelectboxColumn("Phòng đề xuất (trống = phòng phụ trách)", options=owners),
                "need_reason": st.column_config.TextColumn("Căn cứ / lý do (bắt buộc)", width="large"),
                "item_seq": None, "item_code_base": None, "pcts": None,
            })
        if not df_inf.empty:
            g = df_inf.groupby("it_group")["total_budget"].sum().sort_values(ascending=False)
            st.caption("Tổng hạ tầng của site: **" + format_vnd(df_inf["total_budget"].sum()) + "** · "
                       + " · ".join(f"{k}: {format_vnd_short(v)}" for k, v in g.items()))
        if can_edit:
            st.caption("Nhập xong ô cuối cùng, nhấn **Enter** (hoặc bấm ra ngoài bảng) rồi mới bấm Lưu, để ô vừa gõ được ghi nhận.")
        if can_edit and not df_inf.empty:
            st.checkbox("Xác nhận xóa toàn bộ hạ tầng của site (chỉ khi muốn lưu bảng trống)", key="infra_confirm_clear")
        if can_edit and st.button("💾 Lưu hạ tầng CNTT của site", type="primary", key="infra_save"):
            new_rows, errs = [], []
            entity = (df_site["entity"].mode().iloc[0] if "entity" in df_site.columns and not df_site["entity"].dropna().empty else "DDC")
            for i, r in ed_inf.iterrows():
                code = sh_by_label.get(r.get("item"))
                filled = any(str(r.get(k) or "").strip() for k in ("item", "quantity", "unit_price", "need_reason"))
                if not code:
                    if filled:  # dòng có nhập nhưng chưa chọn hạng mục -> báo, không bỏ qua lặng lẽ
                        errs.append(f"Dòng {i + 1}: chưa chọn 'Hạng mục hạ tầng'")
                    continue
                item = sh_by_code[code]
                reason = str(r.get("need_reason") or "").strip()
                if not reason:
                    errs.append(f"Dòng {i + 1} ({item['name']}): thiếu căn cứ / lý do")
                    continue
                if r.get("month") not in months:
                    errs.append(f"Dòng {i + 1} ({item['name']}): chưa chọn 'Tháng triển khai'")
                    continue
                price = r.get("unit_price")
                row = {"entity": entity, "location": SITE_NAME.get(selected_site, selected_site),
                       "quantity": qt._num(r.get("quantity"), 1.0) or 1.0,
                       "unit_price": float(item.get("price", 0)) if price is None or pd.isna(price) else float(price),
                       "dept_proposing": r.get("dept_proposing") or item_owner(item, master), "dept_using": "Dùng chung toàn site",
                       "need_type": qt.NEED_INFRA, "need_reason": reason, "detail_work": "Hạ tầng CNTT dùng chung",
                       "item_seq": r.get("item_seq"), "item_code_base": r.get("item_code_base")}
                apply_it_catalog(row, master, item=item, invest_type=r.get("invest_type") or "Mua mới")
                try:
                    old_pcts = json.loads(r.get("pcts") or "null")
                except (TypeError, ValueError):
                    old_pcts = None
                for m, pc in zip(months, regrid_pcts(old_pcts, r.get("month"), months)):
                    row[f"pct_{m}"] = pc
                new_rows.append(row)
            if not new_rows and df_inf.empty:
                errs.append("Bảng chưa có dòng nào được ghi nhận. Dùng mục 'Thêm hạng mục hạ tầng' ở trên để thêm, "
                            "hoặc khi nhập trên bảng hãy nhấn Enter sau ô cuối trước khi bấm Lưu")
            if not new_rows and not df_inf.empty and not st.session_state.get("infra_confirm_clear"):
                errs.append(f"Bảng đang trống – không lưu để tránh xóa {len(df_inf)} dòng hạ tầng hiện có. "
                            "Nếu muốn xóa hết, tích 'Xác nhận xóa toàn bộ hạ tầng của site' rồi bấm Lưu")
            if errs:
                st.error("Chưa lưu – " + "; ".join(errs))
            else:
                st.session_state["infra_version"] = st.session_state.get("infra_version", 0) + 1
                st.session_state.pop("infra_confirm_clear", None)
                save_site(pd.concat([df_site[~infra_mask], pd.DataFrame(new_rows)], ignore_index=True), selected_site)
                _confirm_infra_saved(len(new_rows), f"Đã lưu bảng hạ tầng ({len(new_rows)} dòng)")
                st.rerun()
