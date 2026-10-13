"""Danh mục: danh mục CNTT & giá chuẩn, pháp nhân & nhà máy, loại tài sản & chi phí."""
import pandas as pd
import streamlit as st

import db
import quota as qt
from capex_engine import clean_number
from master_data import SCOPE_LABELS, it_groups, it_kinds, save_master_data


def render(ctx):
    """Nội dung tab - ctx: giá trị dùng chung của lượt chạy (app.app_context())."""
    MONEY_FMT, contingency_pct, current_user, master = ctx.MONEY_FMT, ctx.contingency_pct, ctx.current_user, ctx.master
    render_price_update = ctx.render_price_update

    st.markdown("### ⚙️ Danh mục Tham chiếu Master Data & Bảng giá Chuẩn")
    st.caption("Các danh mục chuẩn dùng chung cho biểu mẫu quản lý tài sản và lập ngân sách.")
    cp1, cp2 = st.columns([1, 2])
    new_cont = cp1.number_input("Dự phòng phát sinh (% trên tổng hạng mục)", min_value=0.0, max_value=50.0, step=0.5,
                                value=round(contingency_pct() * 100, 2), disabled=not current_user.is_admin, key="cont_pct_input",
                                help="Cộng vào tổng CAPEX thường niên trên Dashboard và dòng 'Dự phòng phát sinh' trong file Excel xuất ra")
    if current_user.is_admin and abs(new_cont / 100 - contingency_pct()) > 1e-9:
        if cp2.button("💾 Lưu tỷ lệ dự phòng", key="cont_pct_save"):
            master["contingency_pct"] = round(new_cont / 100, 4)
            save_master_data(master)
            db.log(current_user.email, "contingency_pct", f"{new_cont:g}%")
            st.session_state["flash"] = f"Đã đặt dự phòng phát sinh {new_cont:g}%."
            st.rerun()

    m_sub1, m_sub2, m_sub3 = st.tabs(["💻 Danh mục CNTT & Giá chuẩn", "🏢 Pháp nhân & Nhà máy", "🏷️ Loại Tài sản & Chi phí"])

    with m_sub1:
        groups_cfg = it_groups(master)
        kinds_cfg = it_kinds(master)
        group_codes = [g["code"] for g in groups_cfg]
        group_label = {g["code"]: f"{g['code']}. {g['name']}" for g in groups_cfg}
        catalog_all = master.get("standard_items", [])

        st.markdown("##### Danh mục hạng mục CNTT & giá tham chiếu")
        flagged = [it for it in catalog_all if it.get("note")]
        st.caption(f"{len(catalog_all)} hạng mục trong {len(groups_cfg)} nhóm. "
                   f"Đơn giá là giá 1 đơn vị (chưa VAT); thiết bị/bản quyền vĩnh viễn có đơn giá ≥ "
                   f"{int(master.get('tscd_threshold', 30_000_000)):,} VNĐ được hạch toán TSCĐ, thấp hơn là CCDC; "
                   f"thuê bao & dịch vụ là chi phí trả trước."
                   + (f" ⚠️ {len(flagged)} hạng mục có ghi chú cần kiểm tra lại giá/tên." if flagged else ""))

        mc1, mc2 = st.columns([2, 1])
        cat_filter = mc1.selectbox("Lọc theo nhóm", ["(Tất cả)"] + group_codes,
                                   format_func=lambda c: c if c == "(Tất cả)" else group_label[c])
        only_flagged = mc2.checkbox("Chỉ hiện hạng mục cần kiểm tra", value=False)

        def _in_view(it):
            return (cat_filter == "(Tất cả)" or it.get("group") == cat_filter) and (not only_flagged or it.get("note"))

        view_items = [it for it in catalog_all if _in_view(it)]
        df_cat = pd.DataFrame([{
            "code": it.get("code", ""), "group": it.get("group", ""), "name": it.get("name", ""),
            "unit": it.get("unit", ""), "kind": it.get("kind", ""), "price": it.get("price", 0),
            "aliases": "; ".join(it.get("aliases", [])), "note": it.get("note", ""),
        } for it in view_items], columns=["code", "group", "name", "unit", "kind", "price", "aliases", "note"])

        edited_cat = st.data_editor(
            df_cat,
            key=f"catalog_{cat_filter}_{only_flagged}",
            disabled=not current_user.is_admin,
            num_rows="dynamic" if current_user.is_admin else "fixed",
            use_container_width=True,
            hide_index=True,
            height=520,
            column_config={
                "code": st.column_config.TextColumn("Mã", disabled=True, help="Tự sinh khi lưu"),
                "group": st.column_config.SelectboxColumn("Nhóm CNTT", options=group_codes, required=True),
                "name": st.column_config.TextColumn("Tên hạng mục chuẩn", required=True, width="large"),
                "unit": st.column_config.TextColumn("ĐVT"),
                "kind": st.column_config.SelectboxColumn("Loại", options=list(kinds_cfg), required=True,
                                                         help=" | ".join(f"{k}: {v}" for k, v in kinds_cfg.items())),
                "price": st.column_config.NumberColumn("Đơn giá tham chiếu (VNĐ)", min_value=0, format=MONEY_FMT, required=True),
                "aliases": st.column_config.TextColumn("Tên cũ / tên gọi khác (cách nhau bởi ;)", width="medium",
                                                       help="Dùng để tự nhận diện dòng ngân sách cũ hoặc file Excel"),
                "note": st.column_config.TextColumn("Ghi chú"),
            }
        )
        if current_user.is_admin and st.button("💾 Lưu Danh mục CNTT", type="primary"):
            kept = [it for it in catalog_all if not _in_view(it)]
            used = {it.get("code") for it in kept}
            saved, errors = [], []
            for _, r in edited_cat.iterrows():
                name = str(r.get("name") or "").strip()
                if not name:
                    continue
                group = r.get("group") if r.get("group") in group_codes else (cat_filter if cat_filter in group_codes else None)
                if not group:
                    errors.append(name)
                    continue
                kind = r.get("kind") if r.get("kind") in kinds_cfg else next(g["kind"] for g in groups_cfg if g["code"] == group)
                saved.append({
                    "code": str(r.get("code") or "").strip(), "group": group, "name": name,
                    "unit": str(r.get("unit") or "").strip(), "kind": kind,
                    "price": int(clean_number(r.get("price"), 0)),
                    "aliases": [a.strip() for a in str(r.get("aliases") or "").split(";") if a.strip()],
                    "note": str(r.get("note") or "").strip(),
                })
                orig = next((it for it in catalog_all if it.get("code") == saved[-1]["code"] and saved[-1]["code"]), None)
                for extra_key in ("scope", "owner", "cost_lv2", "useful_months", "vendor"):  # thuộc tính riêng không hiện trên bảng
                    if orig and orig.get(extra_key) not in (None, ""):
                        saved[-1][extra_key] = orig[extra_key]
            if errors:
                st.error(f"Chưa chọn nhóm CNTT cho: {', '.join(errors)}")
            else:
                # Sinh mã cho hạng mục mới / đổi nhóm: <nhóm>-<số thứ tự>
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
                st.session_state["flash"] = f"Đã lưu Danh mục CNTT ({len(master['standard_items'])} hạng mục)."
                st.rerun()

        if current_user.is_admin:
            render_price_update()

        with st.expander("🗂️ Nhóm CNTT & quy tắc hạch toán"):
            df_groups = pd.DataFrame(groups_cfg, columns=["code", "name", "kind", "scope", "owner", "asset_cat1", "cost_lv2", "useful_months"])
            edited_groups = st.data_editor(
                df_groups,
                key="it_groups_editor",
                disabled=not current_user.is_admin,
                num_rows="dynamic" if current_user.is_admin else "fixed",
                use_container_width=True,
                hide_index=True,
                column_config={
                    "code": st.column_config.TextColumn("Mã nhóm", required=True),
                    "name": st.column_config.TextColumn("Tên nhóm CNTT", required=True, width="medium"),
                    "kind": st.column_config.SelectboxColumn("Loại mặc định", options=list(kinds_cfg), required=True),
                    "scope": st.column_config.SelectboxColumn("Phạm vi", options=list(SCOPE_LABELS),
                                                              help=" | ".join(f"{k}: {v}" for k, v in SCOPE_LABELS.items())),
                    "owner": st.column_config.TextColumn("Phòng phụ trách (hạ tầng)"),
                    "asset_cat1": st.column_config.SelectboxColumn("Loại tài sản cấp 1",
                                                                   options=[c["name"] for c in master.get("asset_cat1", [])]),
                    "cost_lv2": st.column_config.SelectboxColumn("Loại chi phí cấp 2", options=master.get("cost_lv2", []), width="medium"),
                    "useful_months": st.column_config.NumberColumn("Thời gian phân bổ / khấu hao (tháng)", min_value=1, step=1),
                }
            )
            threshold = st.number_input("Ngưỡng nguyên giá ghi nhận TSCĐ (VNĐ / đơn vị)", min_value=0,
                                        value=int(master.get("tscd_threshold", 30_000_000)), step=1_000_000,
                                        disabled=not current_user.is_admin)
            st.caption("Phần mềm thuê bao luôn ghi nhận loại tài sản E & chi phí 04.04; phần cứng/linh kiện ghi nhận D & chi phí theo nhóm.")
            if current_user.is_admin and st.button("💾 Lưu Nhóm CNTT"):
                master["it_groups"] = [
                    {k: (int(v) if k == "useful_months" else v) for k, v in r.items()
                     if not (v is None or (isinstance(v, float) and pd.isna(v)) or v == "")}
                    for r in edited_groups.dropna(subset=["code", "name"]).to_dict(orient="records")]
                master["tscd_threshold"] = int(threshold)
                save_master_data(master)
                st.session_state["flash"] = "Đã lưu Nhóm CNTT & quy tắc hạch toán."
                st.rerun()

        with st.expander("🎒 Bộ trang bị tiêu chuẩn theo vị trí (dùng tính định biên)"):
            st.caption("Mỗi dòng: 1 hạng mục trong bộ trang bị của 1 vị trí và số lượng cho 1 nhân sự "
                       "(số lẻ = dùng chung, vd. 0,1 máy in/người = 1 máy/10 người; kết quả làm tròn lên theo phòng ban).")
            kit_items_label = {it["code"]: f"{it['code']} · {it['name']}" for it in master.get("standard_items", []) if it.get("code")}
            kit_label_to_code = {v: k for k, v in kit_items_label.items()}
            df_kits = pd.DataFrame([{"kit_code": k["code"], "kit_name": k["name"],
                                     "item": kit_items_label.get(i["catalog_code"], i["catalog_code"]),
                                     "qty_per_person": i["qty_per_person"]}
                                    for k in qt.standard_kits(master) for i in k["items"]],
                                   columns=["kit_code", "kit_name", "item", "qty_per_person"])
            edited_kits = st.data_editor(
                df_kits, key="kits_editor", disabled=not current_user.is_admin,
                num_rows="dynamic" if current_user.is_admin else "fixed", use_container_width=True, hide_index=True,
                column_config={
                    "kit_code": st.column_config.TextColumn("Mã bộ", required=True),
                    "kit_name": st.column_config.TextColumn("Vị trí / tên bộ trang bị", required=True, width="medium"),
                    "item": st.column_config.SelectboxColumn("Hạng mục", options=list(kit_items_label.values()), required=True, width="large"),
                    "qty_per_person": st.column_config.NumberColumn("Số lượng / người", min_value=0.0, step=0.1, format="%.2f", required=True),
                })
            if current_user.is_admin and st.button("💾 Lưu Bộ trang bị tiêu chuẩn"):
                kits_out = {}
                for _, r in edited_kits.iterrows():
                    code = str(r.get("kit_code") or "").strip()
                    item_code = kit_label_to_code.get(r.get("item"))
                    if not code or not item_code:
                        continue
                    kit = kits_out.setdefault(code, {"code": code, "name": str(r.get("kit_name") or code).strip(), "items": []})
                    kit["items"].append({"catalog_code": item_code, "qty_per_person": float(clean_number(r.get("qty_per_person"), 0))})
                master["standard_kits"] = list(kits_out.values())
                save_master_data(master)
                st.session_state["flash"] = f"Đã lưu {len(kits_out)} bộ trang bị tiêu chuẩn."
                st.rerun()

    with m_sub2:
        c_ent, c_site = st.columns(2)
        with c_ent:
            st.markdown("##### Danh sách Pháp nhân (Entities)")
            df_ent_m = pd.DataFrame(master.get("entities", []))
            st.dataframe(df_ent_m, use_container_width=True, hide_index=True)
        with c_site:
            st.markdown("##### Danh sách Nhà máy / Vị trí (Sites)")
            df_site_m = pd.DataFrame(master.get("sites", []))
            st.dataframe(df_site_m, use_container_width=True, hide_index=True)

    with m_sub3:
        c_cat1, c_cat2 = st.columns(2)
        with c_cat1:
            st.markdown("##### Loại tài sản cấp 1")
            df_cat1_m = pd.DataFrame(master.get("asset_cat1", []))
            st.dataframe(df_cat1_m, use_container_width=True, hide_index=True)
        with c_cat2:
            st.markdown("##### Loại chi phí cấp 1 & 2")
            st.write("**Cấp 1:**", master.get("cost_lv1", []))
            with st.expander("Chi tiết Loại chi phí cấp 2"):
                st.write(master.get("cost_lv2", []))
