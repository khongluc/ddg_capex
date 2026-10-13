"""Nộp / duyệt theo phòng ban: khung trạng thái phòng đang lập, bảng tiến độ các phòng."""
import pandas as pd
import streamlit as st

import db
import workflow as wf


def render_dept_workflow(ctx, dept: str, rows: pd.DataFrame):
    """Nộp & duyệt 1 phòng ban: phòng ban nộp; IT site / Admin duyệt, trả lại (ghi chú), mở lại, ghi chú từng dòng."""
    MONEY_FMT, budget_year, can_review, current_user = ctx.MONEY_FMT, ctx.budget_year, ctx.can_review, ctx.current_user
    dept_key, dept_state, df_site = ctx.dept_key, ctx.dept_state, ctx.df_site
    save_site, selected_site, site_status = ctx.save_site, ctx.selected_site, ctx.site_status

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


def render_dept_overview(ctx):
    """Tiến độ nộp & duyệt các phòng ban của site; IT site duyệt nhiều phòng cùng lúc."""
    MONEY_FMT, budget_year, can_review, current_user = ctx.MONEY_FMT, ctx.budget_year, ctx.can_review, ctx.current_user
    dept_key, dept_status_map, df_site = ctx.dept_key, ctx.dept_status_map, ctx.df_site
    selected_site = ctx.selected_site

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
