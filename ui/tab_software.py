"""Phần mềm: ngân sách phần mềm, nhắc gia hạn, danh mục phần mềm & giá."""
import pandas as pd
import plotly.express as px
import streamlit as st

import db
import renewals
from capex_engine import calculate_row, clean_number
from master_data import KIND_SW_PERPETUAL, KIND_SW_SUBSCRIPTION, it_groups, it_kinds, save_master_data


def render(ctx):
    """Nội dung tab - ctx: giá trị dùng chung của lượt chạy (app.app_context())."""
    ALL_SITES, MONEY_FMT, SITE_NAME, SW_KINDS = ctx.ALL_SITES, ctx.MONEY_FMT, ctx.SITE_NAME, ctx.SW_KINDS
    budget_year, current_user, dept_key, df_curr = ctx.budget_year, ctx.current_user, ctx.dept_key, ctx.df_curr
    fmt_num, format_vnd, format_vnd_short, master = ctx.fmt_num, ctx.format_vnd, ctx.format_vnd_short, ctx.master
    months, phasing_picker, plot_chart, prev_year_lines = ctx.months, ctx.phasing_picker, ctx.plot_chart, ctx.prev_year_lines
    save_site, selected_dept, selected_site, site_can_edit = ctx.save_site, ctx.selected_dept, ctx.selected_site, ctx.site_can_edit
    site_label, year_code = ctx.site_label, ctx.year_code

    st.markdown("### 💿 Đầu tư Phần mềm & Bản quyền")
    st.caption("Danh mục phần mềm chuẩn và tổng hợp ngân sách phần mềm trong phạm vi đang chọn. "
               "Bản quyền vĩnh viễn: TSCĐ vô hình nếu ≥ 30 triệu/đơn vị, thấp hơn là CCDC; "
               "thuê bao theo năm: chi phí trả trước phân bổ theo thời hạn.")
    sw_catalog = [it for it in master.get("standard_items", []) if it.get("kind") in SW_KINDS]
    sw_by_code = {it["code"]: it for it in sw_catalog}
    sw_sum_tab, sw_renew_tab, sw_cat_tab = st.tabs(["📊 Ngân sách phần mềm", "🔔 Nhắc gia hạn", "📚 Danh mục phần mềm & giá"])

    with sw_sum_tab:
        kinds_s = df_curr["item_kind"] if "item_kind" in df_curr.columns else pd.Series(index=df_curr.index, dtype=object)
        code_s = df_curr["catalog_code"] if "catalog_code" in df_curr.columns else pd.Series(index=df_curr.index, dtype=object)
        sw_mask = kinds_s.isin(SW_KINDS) | code_s.isin(sw_by_code.keys())
        df_sw = df_curr[sw_mask].copy()
        if df_sw.empty:
            st.info("Chưa có hạng mục phần mềm trong phạm vi đang chọn. Phần mềm được đưa vào ngân sách khi lập theo định biên "
                    "(tab 'Định biên & Nhu cầu'), thêm ở tab 'Lập & Nhập liệu CapEx' hoặc tab 'Hạ tầng CNTT dùng chung'.")
        else:
            df_sw["sw_kind"] = df_sw.get("item_kind", pd.Series(index=df_sw.index, dtype=object)).where(
                df_sw.get("item_kind", pd.Series(index=df_sw.index, dtype=object)).isin(SW_KINDS),
                df_sw.get("catalog_code", pd.Series(index=df_sw.index, dtype=object)).map(lambda c: sw_by_code.get(c, {}).get("kind")))
            tot = df_sw["total_budget"].sum()
            perp = df_sw.loc[df_sw["sw_kind"] == KIND_SW_PERPETUAL, "total_budget"].sum()
            subs = df_sw.loc[df_sw["sw_kind"] == KIND_SW_SUBSCRIPTION, "total_budget"].sum()
            inv_s = df_sw["invest_type"] if "invest_type" in df_sw.columns else pd.Series("", index=df_sw.index)
            renew = df_sw.loc[inv_s == "Gia hạn, bảo trì", "total_budget"].sum()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Tổng ngân sách phần mềm", format_vnd_short(tot) + " VNĐ",
                      f"{fmt_num(tot / df_curr['total_budget'].sum() * 100 if df_curr['total_budget'].sum() else 0, 1)}% tổng ngân sách",
                      delta_color="off")
            m2.metric("Bản quyền vĩnh viễn", format_vnd_short(perp) + " VNĐ")
            m3.metric("Thuê bao theo năm", format_vnd_short(subs) + " VNĐ")
            m4.metric("Trong đó gia hạn", format_vnd_short(renew) + " VNĐ")

            df_sw["Hình thức cấp phép"] = df_sw["sw_kind"].map(it_kinds(master)).fillna("Chưa phân loại")
            df_sw["Hãng"] = df_sw.get("catalog_code", pd.Series(index=df_sw.index, dtype=object)).map(
                lambda c: sw_by_code.get(c, {}).get("vendor", "")).fillna("")
            by_item = df_sw.groupby(["item_name", "Hãng", "Hình thức cấp phép"], dropna=False).agg(
                **{"Số lượng": ("quantity", "sum"), "Đơn giá TB": ("unit_price", "mean"),
                   "Thành tiền (VNĐ)": ("total_budget", "sum"),
                   "Số site": ("location", "nunique"),
                   "Số phòng ban": ("dept_proposing", "nunique")}).reset_index().rename(columns={"item_name": "Phần mềm"})
            by_item = by_item.sort_values("Thành tiền (VNĐ)", ascending=False)
            money_c = st.column_config.NumberColumn(format=MONEY_FMT)
            st.markdown("##### Theo phần mềm")
            st.dataframe(by_item, use_container_width=True, hide_index=True,
                         column_config={"Số lượng": money_c, "Đơn giá TB": money_c, "Thành tiền (VNĐ)": money_c})

            c_l, c_r = st.columns([1.3, 1])
            with c_l:
                st.markdown("##### Theo phòng ban")
                by_dept = df_sw.assign(dept=df_sw["dept_proposing"].replace("", None).fillna("(Chưa ghi phòng ban)")).pivot_table(
                    index="dept", columns="Hình thức cấp phép", values="total_budget", aggfunc="sum", fill_value=0)
                by_dept["Tổng (VNĐ)"] = by_dept.sum(axis=1)
                by_dept = by_dept.sort_values("Tổng (VNĐ)", ascending=False)
                st.dataframe(by_dept, use_container_width=True, column_config={c: money_c for c in by_dept.columns})
            with c_r:
                st.markdown("##### Cơ cấu theo hình thức đầu tư")
                df_inv = df_sw.assign(inv=inv_s.replace("", None).fillna("Chưa phân loại")).groupby("inv")["total_budget"].sum().reset_index()
                fig_sw = px.pie(df_inv, names="inv", values="total_budget", hole=0.45,
                                color_discrete_sequence=["#0F2C59", "#3B82F6", "#F59E0B", "#CBD5E1"])
                fig_sw.update_traces(textinfo="percent+label", hovertemplate="<b>%{label}</b><br>%{value:,.0f} VNĐ<br>%{percent}")
                fig_sw.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=300, showlegend=False)
                plot_chart(fig_sw, use_container_width=True)
            st.caption("Phạm vi theo năm / site / phòng ban đang chọn ở thanh bên trái. Muốn sửa số lượng, vào tab nơi hạng mục được lập.")

    with sw_renew_tab:
        prev_y = int(budget_year) - 1
        st.caption(f"Thuê bao phần mềm, dịch vụ theo năm / tháng (cloud, đường truyền, thuê thiết bị) và dòng 'Gia hạn, bảo trì' "
                   f"có trong ngân sách {prev_y} nhưng {budget_year} chưa có hoặc ít số lượng hơn. So theo site + mã danh mục, "
                   "không phân biệt phòng ban. Tiền ước tính = SL thiếu × đơn giá bình quân năm trước.")
        cur_rn = df_curr if "site_code" in df_curr.columns else df_curr.assign(site_code=selected_site)
        gaps = renewals.renewal_gaps(prev_year_lines(), cur_rn, master)
        if gaps.empty:
            st.success(f"✅ Không thiếu hạng mục định kỳ nào so với {prev_y} trong phạm vi đang chọn.")
        else:
            n_miss = int((gaps["status"] == renewals.STATUS_MISSING).sum())
            r1, r2, r3 = st.columns(3)
            r1.metric("Hạng mục cần xem lại", f"{len(gaps)}")
            r2.metric("Chưa có trong năm nay", f"{n_miss}")
            r3.metric("Tiền ước tính còn thiếu", format_vnd_short(gaps["est_amount"].sum()) + " VNĐ")
            show = gaps.assign(site=gaps["site_code"].map(site_label), pick=False, add_qty=gaps["missing_qty"])
            can_add = selected_site != ALL_SITES and site_can_edit
            rn_ver = st.session_state.get("renew_ver", 0)
            ed_rn = st.data_editor(
                show, key=f"renew_grid_{budget_year}_{selected_site}_{dept_key(selected_dept)}_{rn_ver}",
                use_container_width=True, hide_index=True, disabled=[c for c in show.columns if c not in ("pick", "add_qty")],
                column_order=(["pick", "add_qty"] if can_add else []) + [
                    "status", "site", "catalog_code", "item_name", "unit", "depts", "prev_qty", "cur_qty",
                    "missing_qty", "prev_amount", "est_amount"],
                column_config={"pick": st.column_config.CheckboxColumn("Gia hạn", default=False),
                               "add_qty": st.column_config.NumberColumn("SL thêm", min_value=0, step=1, format=MONEY_FMT),
                               "status": "Tình trạng", "site": "Site", "catalog_code": "Mã danh mục",
                               "item_name": st.column_config.TextColumn("Hạng mục", width="large"), "unit": "ĐVT",
                               "depts": f"Phòng ban năm {prev_y}",
                               "prev_qty": st.column_config.NumberColumn(f"SL {prev_y}", format=MONEY_FMT),
                               "cur_qty": st.column_config.NumberColumn(f"SL {budget_year}", format=MONEY_FMT),
                               "missing_qty": st.column_config.NumberColumn("SL thiếu", format=MONEY_FMT),
                               "prev_amount": st.column_config.NumberColumn(f"Tiền {prev_y} (VNĐ)", format=MONEY_FMT),
                               "est_amount": st.column_config.NumberColumn("Tiền ước tính thiếu (VNĐ)", format=MONEY_FMT)})
            st.download_button("📥 Tải danh sách nhắc gia hạn (CSV)",
                               show.drop(columns=["site_code", "pick", "add_qty", "entity", "need_type", "invest_type"])
                               .to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"NhacGiaHan_{budget_year}.csv", mime="text/csv", key="renew_csv")
            if not can_add:
                st.caption("Chọn 1 site ở thanh bên trái (và có quyền sửa) để tick hạng mục cần gia hạn rồi thêm thẳng vào ngân sách.")
            else:
                sel_rn = ed_rn[(ed_rn["pick"] == True) & (pd.to_numeric(ed_rn["add_qty"], errors="coerce").fillna(0) > 0)]
                st.caption("Tick 'Gia hạn', sửa 'SL thêm' nếu cần. Dòng thêm vào: hình thức Gia hạn, bảo trì; đơn giá danh mục hiện hành "
                           "(không có thì bình quân năm trước); phòng đề xuất = phòng đầu tiên năm trước. "
                           "Hạng mục theo định biên (vd. Microsoft 365 theo người) nên sinh lại ở tab Định biên thay vì thêm ở đây.")
                rn_pick = pd.DataFrame({"Tên thiết bị / Hạng mục": sel_rn["item_name"].tolist(),
                                        "Số lượng": [int(round(q)) for q in pd.to_numeric(sel_rn["add_qty"], errors="coerce").fillna(0)]},
                                       index=sel_rn.index)
                rn_pick, rn_err = phasing_picker(rn_pick, f"renew_{rn_ver}")
                if st.button(f"🔁 Thêm {len(sel_rn)} hạng mục gia hạn vào ngân sách {budget_year}", type="primary",
                             disabled=sel_rn.empty, key=f"renew_add_{rn_ver}"):
                    if rn_err:
                        st.error(rn_err)
                    else:
                        loc = SITE_NAME.get(selected_site, selected_site)
                        new_rn = [calculate_row(renewals.renewal_line(ed_rn.loc[ix].to_dict(), sum(rn_pick.at[ix, "_units"]),
                                                                      rn_pick.at[ix, "_units"], months, master, prev_y, loc),
                                                months=months, year_code=year_code, master=master)
                                  for ix in rn_pick.index]
                        base_rn = pd.DataFrame(db.load_lines(budget_year, [selected_site])).drop(columns=["site_code"], errors="ignore")
                        save_site(pd.concat([base_rn, pd.DataFrame(new_rn)], ignore_index=True), selected_site)
                        st.session_state["renew_ver"] = rn_ver + 1
                        st.session_state["flash"] = (f"🔁 Đã thêm {len(new_rn)} hạng mục gia hạn vào ngân sách {budget_year} "
                                                     f"({format_vnd(sum(r.get('total_budget', 0) for r in new_rn))}).")
                        st.rerun()

    with sw_cat_tab:
        groups_cfg = it_groups(master)
        group_codes = [g["code"] for g in groups_cfg]
        sw_group_codes = [g["code"] for g in groups_cfg if g.get("kind") in SW_KINDS] or group_codes
        group_label = {g["code"]: f"{g['code']}. {g['name']}" for g in groups_cfg}
        kind_lbl = {k: it_kinds(master).get(k, k) for k in SW_KINDS}
        st.caption(f"{len(sw_catalog)} phần mềm / bản quyền "
                   f"({sum(1 for it in sw_catalog if it['kind'] == KIND_SW_PERPETUAL)} vĩnh viễn, "
                   f"{sum(1 for it in sw_catalog if it['kind'] == KIND_SW_SUBSCRIPTION)} thuê bao). "
                   "Thêm dòng mới ở cuối bảng; mã tự sinh theo nhóm khi lưu. Đơn giá chưa VAT, theo 1 đơn vị cấp phép.")
        sf1, sf2 = st.columns([2, 1])
        sw_grp_filter = sf1.selectbox("Lọc theo nhóm", ["(Tất cả)"] + sorted({it["group"] for it in sw_catalog} | set(sw_group_codes)),
                                      format_func=lambda c: c if c == "(Tất cả)" else group_label.get(c, c), key="sw_grp_filter")
        sw_kind_filter = sf2.selectbox("Hình thức cấp phép", ["(Tất cả)", *SW_KINDS],
                                       format_func=lambda k: kind_lbl.get(k, k), key="sw_kind_filter")

        def _sw_in_view(it):
            return ((sw_grp_filter == "(Tất cả)" or it.get("group") == sw_grp_filter)
                    and (sw_kind_filter == "(Tất cả)" or it.get("kind") == sw_kind_filter))

        sw_view = [it for it in sw_catalog if _sw_in_view(it)]
        df_swc = pd.DataFrame([{
            "code": it.get("code", ""), "group": it.get("group", ""), "name": it.get("name", ""),
            "vendor": it.get("vendor", ""), "kind": kind_lbl.get(it.get("kind"), it.get("kind")),
            "unit": it.get("unit", ""), "price": it.get("price", 0),
            "useful_months": it.get("useful_months") or (12 if it.get("kind") == KIND_SW_SUBSCRIPTION else None),
            "note": it.get("note", ""),
        } for it in sw_view], columns=["code", "group", "name", "vendor", "kind", "unit", "price", "useful_months", "note"])
        ed_swc = st.data_editor(
            df_swc, key=f"sw_catalog_{sw_grp_filter}_{sw_kind_filter}_{st.session_state.get('sw_cat_version', 0)}",
            disabled=not current_user.is_admin, num_rows="dynamic" if current_user.is_admin else "fixed",
            use_container_width=True, hide_index=True, height=520,
            column_config={
                "code": st.column_config.TextColumn("Mã", disabled=True, help="Tự sinh khi lưu"),
                "group": st.column_config.SelectboxColumn("Nhóm", options=group_codes, required=True,
                                                          default=sw_grp_filter if sw_grp_filter in group_codes else sw_group_codes[0]),
                "name": st.column_config.TextColumn("Tên phần mềm / bản quyền", required=True, width="large"),
                "vendor": st.column_config.TextColumn("Hãng"),
                "kind": st.column_config.SelectboxColumn("Hình thức cấp phép", options=list(kind_lbl.values()), required=True,
                                                         default=kind_lbl[KIND_SW_SUBSCRIPTION]),
                "unit": st.column_config.TextColumn("Đơn vị cấp phép", help="VD: User/năm, Máy/năm, License, Gói/năm"),
                "price": st.column_config.NumberColumn("Đơn giá (VNĐ)", min_value=0, format=MONEY_FMT, required=True),
                "useful_months": st.column_config.NumberColumn("Thời hạn / phân bổ (tháng)", min_value=1, step=1, format=MONEY_FMT,
                                                               help="Thuê bao: chu kỳ gia hạn (thường 12). Vĩnh viễn: thời gian khấu hao/phân bổ."),
                "note": st.column_config.TextColumn("Ghi chú"),
            })
        zero_price = [it["name"] for it in sw_view if not it.get("price")]
        if zero_price:
            st.caption(f"⚠️ {len(zero_price)} phần mềm chưa có đơn giá: {', '.join(zero_price[:5])}{'…' if len(zero_price) > 5 else ''}")
        if current_user.is_admin and st.button("💾 Lưu danh mục phần mềm", type="primary", key="sw_cat_save"):
            kind_by_lbl = {v: k for k, v in kind_lbl.items()}
            all_items = master.get("standard_items", [])
            view_codes = {it["code"] for it in sw_view}
            kept = [it for it in all_items if it.get("code") not in view_codes]
            used = {it.get("code") for it in kept}
            saved, errs = [], []
            for _, r in ed_swc.iterrows():
                name = str(r.get("name") or "").strip()
                if not name:
                    continue
                group = r.get("group") if r.get("group") in group_codes else None
                kind = kind_by_lbl.get(r.get("kind")) or (r.get("kind") if r.get("kind") in SW_KINDS else None)
                if not group or not kind:
                    errs.append(name)
                    continue
                code = str(r.get("code") or "").strip()
                orig = next((it for it in all_items if code and it.get("code") == code), {})
                item = {**orig, "code": code, "group": group, "name": name, "kind": kind,
                        "unit": str(r.get("unit") or "").strip(), "price": int(clean_number(r.get("price"), 0)),
                        "note": str(r.get("note") or "").strip()}
                vendor = str(r.get("vendor") or "").strip()
                if vendor:
                    item["vendor"] = vendor
                else:
                    item.pop("vendor", None)
                months_v = clean_number(r.get("useful_months"), 0)
                if months_v and int(months_v) > 0:
                    item["useful_months"] = int(months_v)
                else:
                    item.pop("useful_months", None)
                item.setdefault("aliases", [])
                saved.append(item)
            if errs:
                st.error(f"Chưa chọn Nhóm / Hình thức cấp phép cho: {', '.join(errs)}")
            else:
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
                db.log(current_user.email, "software_catalog_save", f"{len(saved)} phần mềm")
                st.session_state["sw_cat_version"] = st.session_state.get("sw_cat_version", 0) + 1
                st.session_state["flash"] = (f"Đã lưu danh mục phần mềm ({len(saved)} hạng mục trong bộ lọc; "
                                             f"toàn danh mục {len(master['standard_items'])} hạng mục).")
                st.rerun()
        elif not current_user.is_admin:
            st.caption("Chỉ Quản trị được sửa danh mục. Cần thêm phần mềm, vui lòng liên hệ Phòng CNTT.")
