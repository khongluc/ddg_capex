"""Cập nhật đơn giá danh mục từ file báo giá (Admin)."""
import datetime

import pandas as pd
import streamlit as st

import db
import pricing
from master_data import save_master_data


def render_price_update(ctx):
    """Cập nhật đơn giá danh mục từ file báo giá: xem trước -> áp dụng cho danh mục + dòng ngân sách site đang lập."""
    MONEY_FMT, SITES, XLSX_MIME, budget_year = ctx.MONEY_FMT, ctx.SITES, ctx.XLSX_MIME, ctx.budget_year
    current_user, format_vnd, master, save_site = ctx.current_user, ctx.format_vnd, ctx.master, ctx.save_site
    site_label = ctx.site_label

    with st.expander("Cập nhật đơn giá từ báo giá", expanded=False):
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
            with st.popover(f"{len(issues)} dòng không áp dụng được"):
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
