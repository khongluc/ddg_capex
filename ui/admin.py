"""Trang Phân quyền & Tiến độ (Admin): tài khoản, vai trò, site / phòng ban được phân, sao lưu CSDL."""
import datetime

import pandas as pd
import streamlit as st

import db
from master_data import load_master_data, save_master_data


def render_admin_page(ctx):
    MONEY_FMT, SITES, budget_year, current_user = ctx.MONEY_FMT, ctx.SITES, ctx.budget_year, ctx.current_user
    dept_list, site_label = ctx.dept_list, ctx.site_label

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
