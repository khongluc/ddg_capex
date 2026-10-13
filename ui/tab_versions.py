"""Phiên bản ngân sách: so sánh 2 bản / bản duyệt với hiện tại."""
import datetime

import pandas as pd
import streamlit as st

import db
import versions as vs


def render(ctx):
    """Nội dung tab - ctx: giá trị dùng chung của lượt chạy (app.app_context())."""
    ALL_DEPTS, ALL_SITES, MONEY_FMT, budget_year = ctx.ALL_DEPTS, ctx.ALL_SITES, ctx.MONEY_FMT, ctx.budget_year
    current_user, dept_key, format_vnd_short, scope_sites = ctx.current_user, ctx.dept_key, ctx.format_vnd_short, ctx.scope_sites
    selected_dept, selected_site, site_label = ctx.selected_dept, ctx.selected_site, ctx.site_label

    st.markdown("### Phiên bản & điều chỉnh ngân sách")
    st.caption("Mỗi lần Admin duyệt site, toàn bộ ngân sách được chốt thành 1 phiên bản (Bản duyệt, Điều chỉnh lần 1, 2...). "
               "So sánh theo Mã hạng mục cố định.")
    if selected_site == ALL_SITES:
        vl = pd.DataFrame(db.list_versions(budget_year, scope_sites))
        if vl.empty:
            st.info(f"Chưa site nào được duyệt ngân sách năm {budget_year}.")
        else:
            st.dataframe(vl.assign(site_code=vl["site_code"].map(site_label))[["site_code", "version_no", "label", "reason", "n_lines", "total", "created_by", "created_at"]],
                         use_container_width=True, hide_index=True,
                         column_config={"site_code": "Site", "version_no": "Phiên bản", "label": "Loại", "reason": "Lý do", "n_lines": "Số dòng",
                                        "total": st.column_config.NumberColumn("Tổng ngân sách", format=MONEY_FMT),
                                        "created_by": "Người duyệt", "created_at": "Lúc chốt"})
            st.caption("Chọn 1 site ở thanh bên trái để so sánh chi tiết.")
    else:
        vl = db.list_versions(budget_year, [selected_site])
        if not vl:
            st.info(f"{site_label(selected_site)} chưa có phiên bản nào - phiên bản đầu tiên được chốt khi Admin duyệt ngân sách site.")
        else:
            st.dataframe(pd.DataFrame(vl)[["version_no", "label", "reason", "n_lines", "total", "created_by", "created_at"]],
                         use_container_width=True, hide_index=True,
                         column_config={"version_no": "Phiên bản", "label": "Loại", "reason": "Lý do", "n_lines": "Số dòng",
                                        "total": st.column_config.NumberColumn("Tổng ngân sách", format=MONEY_FMT),
                                        "created_by": "Người duyệt", "created_at": "Lúc chốt"})
            CURRENT = "__current__"
            vlabel = {v["id"]: f"v{v['version_no']} · {v['label']} · {str(v['created_at'])[:10]}" for v in vl}
            vlabel[CURRENT] = "Hiện tại (đang lập / điều chỉnh)"
            c1, c2 = st.columns(2)
            old_id = c1.selectbox("So sánh từ", [v["id"] for v in vl], format_func=vlabel.get, key="ver_old")
            new_opts = [CURRENT] + [v["id"] for v in vl if v["id"] != old_id]
            new_id = c2.selectbox("Đến", new_opts, format_func=vlabel.get, key="ver_new")
            old_rows = db.load_version(old_id)
            new_rows = [{k: v for k, v in r.items() if k != "site_code"} for r in db.load_lines(budget_year, [selected_site])] \
                if new_id == CURRENT else db.load_version(new_id)
            if selected_dept != ALL_DEPTS:
                old_rows = [r for r in old_rows if dept_key(r.get("dept_proposing")) == dept_key(selected_dept)]
                new_rows = [r for r in new_rows if dept_key(r.get("dept_proposing")) == dept_key(selected_dept)]
            if current_user.is_dept_user:
                _al = {dept_key(d) for d in current_user.allowed_depts(selected_site)}
                old_rows = [r for r in old_rows if dept_key(r.get("dept_proposing")) in _al]
                new_rows = [r for r in new_rows if dept_key(r.get("dept_proposing")) in _al]
            dv = vs.diff(old_rows, new_rows)
            sm = vs.summary(dv, old_rows, new_rows)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Tổng (từ)", format_vnd_short(sm["total_old"]))
            m2.metric("Tổng (đến)", format_vnd_short(sm["total_new"]),
                      f"{'+' if sm['total_new'] >= sm['total_old'] else ''}{format_vnd_short(sm['total_new'] - sm['total_old'])}", delta_color="off")
            m3.metric("Hạng mục thêm / bỏ", f"{sm['added']} / {sm['removed']}")
            m4.metric("Hạng mục đổi", sm["changed"])
            if dv.empty:
                st.success("Hai bản giống nhau trong phạm vi đang chọn.")
            else:
                money_v = st.column_config.NumberColumn(format=MONEY_FMT)
                vt1, vt2 = st.tabs(["Theo hạng mục", "Theo phòng ban"])
                with vt1:
                    st.dataframe(dv, use_container_width=True, hide_index=True, height=420,
                                 column_config={"item_code": "Mã hạng mục", "status": "Thay đổi", "dept": "Phòng ban", "item_name": "Hạng mục",
                                                "qty_old": "SL (từ)", "qty_new": "SL (đến)",
                                                "total_old": st.column_config.NumberColumn("Thành tiền (từ)", format=MONEY_FMT),
                                                "total_new": st.column_config.NumberColumn("Thành tiền (đến)", format=MONEY_FMT),
                                                "delta": st.column_config.NumberColumn("Chênh lệch", format=MONEY_FMT), "what": "Nội dung đổi"})
                    st.download_button("📥 Tải bảng so sánh (.csv)", dv.to_csv(index=False).encode("utf-8-sig"),
                                       file_name=f"SoSanh_{budget_year}_{selected_site}_{datetime.date.today():%Y%m%d}.csv", mime="text/csv", key="ver_csv")
                with vt2:
                    st.dataframe(vs.by_dept(old_rows, new_rows), use_container_width=True, hide_index=True,
                                 column_config={"dept": "Phòng ban", "total_old": st.column_config.NumberColumn("Từ", format=MONEY_FMT),
                                                "total_new": st.column_config.NumberColumn("Đến", format=MONEY_FMT), "delta": money_v})
