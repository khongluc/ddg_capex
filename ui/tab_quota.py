"""Định biên: nạp định biên, nơi làm việc → site, bộ trang bị theo vị trí, nhu cầu ước tính."""
import json
import os

import pandas as pd
import streamlit as st

import db
import headcount_import as hi
import quota as qt
import unicodedata
from master_data import SCOPE_SHARED, it_kinds, item_scope, save_master_data


def render(ctx):
    """Nội dung tab - ctx: giá trị dùng chung của lượt chạy (app.app_context())."""
    ALL_DEPTS, ALL_SITES, MONEY_FMT, SITES = ctx.ALL_DEPTS, ctx.ALL_SITES, ctx.MONEY_FMT, ctx.SITES
    SITE_NAME, _cached_roster, budget_year, can_edit = ctx.SITE_NAME, ctx._cached_roster, ctx.budget_year, ctx.can_edit
    current_user, dept_key, dept_mask, df_site = ctx.current_user, ctx.dept_key, ctx.dept_mask, ctx.df_site
    fmt_num, format_vnd, master, months = ctx.fmt_num, ctx.format_vnd, ctx.master, ctx.months
    resolve_template_path, save_site, scope_sites, selected_dept = ctx.resolve_template_path, ctx.save_site, ctx.scope_sites, ctx.selected_dept
    selected_site, site_label = ctx.selected_site, ctx.site_label

    st.markdown("### Định biên & Nhu cầu Thiết bị / Phần mềm theo Phòng ban")
    st.caption("Định mức = Nhân sự định biên × Bộ trang bị tiêu chuẩn. Thiết bị & phần mềm vĩnh viễn: mua bổ sung phần thiếu so với hiện có "
               "+ thay thế thiết bị cũ. Phần mềm thuê bao: gia hạn số đang có + mua thêm phần thiếu. "
               "Nhu cầu ngoài định biên nhập ở tab 'Lập & Nhập liệu' với loại 'Phát sinh mới'.")
    kits_cfg = qt.standard_kits(master)
    kit_label = {k["code"]: f"{k['code']} · {k['name']}" for k in kits_cfg}
    cat_by_code = qt.catalog_by_code(master)
    item_label = {c: f"{c} · {it['name']}" for c, it in cat_by_code.items()}
    label_to_code = {v: k for k, v in item_label.items()}

    def needs_by_dept(hc_rows_all, inv_rows_all):
        """Nhu cầu theo (site, phòng ban) từ định biên + hiện có -> DataFrame gộp (thêm cột site, dept)."""
        frames = []
        for (sc, dp), hc in pd.DataFrame(hc_rows_all).groupby(["site_code", "dept"]):
            inv = [r for r in inv_rows_all if r["site_code"] == sc and r["dept"] == dp]
            n = qt.compute_needs(hc.to_dict("records"), inv, master)
            if not n.empty:
                frames.append(n.assign(site=sc, dept=dp))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def needs_summary(N: pd.DataFrame) -> pd.DataFrame:
        sw = N["kind"].astype(str).str.startswith("software") | (N["kind"] == "service")
        return N.assign(hw=(N["add_qty"] + N["replace_qty"]) * N["price"] * ~sw, sw_new=N["add_qty"] * N["price"] * sw,
                        sw_renew=N["renew_qty"] * N["price"] * sw).groupby(["site", "dept"]).agg(
            **{"Thiết bị mua thêm/thay (VNĐ)": ("hw", "sum"), "Phần mềm mua mới (VNĐ)": ("sw_new", "sum"),
               "Gia hạn bản quyền (VNĐ)": ("sw_renew", "sum"), "Tổng nhu cầu (VNĐ)": ("propose_value", "sum")}).reset_index()

    money_cfg = {c: st.column_config.NumberColumn(format=MONEY_FMT) for c in [
        "Thiết bị mua thêm/thay (VNĐ)", "Phần mềm mua mới (VNĐ)", "Gia hạn bản quyền (VNĐ)", "Tổng nhu cầu (VNĐ)",
        "Ngân sách định biên đã tạo (VNĐ)", "Thành tiền (VNĐ)", "Đơn giá"]}

    # ---- Nhập file định biên nhân sự (Khối QTNNL) ----
    if current_user.is_admin:
        with st.expander("Nhập file định biên nhân sự (Khối QTNNL) – tính cho toàn bộ phòng ban", expanded=False):
            st.caption("File theo mẫu 'Tổng hợp định biên … - Gửi CNTT': mỗi dòng 1 vị trí; dùng Khối/Phòng, Vị trí, Cấp bậc, Nơi làm việc, "
                       "cột Thiết bị CNTT / Phần mềm (nếu có), Nhân sự thực tế, Định biên và nhân sự 12 tháng. "
                       "**Họ tên và mã nhân viên không được lưu.**")
            app_dir = os.path.dirname(os.path.abspath(__file__))
            tpl_dir = os.path.join(app_dir, "templates")
            all_scan = set()
            for d in (tpl_dir, app_dir):
                if os.path.exists(d):
                    for f in os.listdir(d):
                        if f.lower().endswith(".xlsx") and "định biên" in unicodedata.normalize("NFC", f).lower() and not unicodedata.normalize("NFC", f).lower().startswith("phân tích"):
                            all_scan.add(f)
            local_files = sorted(all_scan, key=lambda f: (not unicodedata.normalize("NFC", f).lower().startswith("tổng hợp định biên"), f))
            UPLOAD = "(Tải lên file khác)"
            src_choice = st.selectbox("Nguồn file định biên", local_files + [UPLOAD])
            source = st.file_uploader("File định biên (.xlsx)", type=["xlsx"], key="hc_upload") if src_choice == UPLOAD \
                else resolve_template_path(src_choice)
            if source is not None:
                kit_codes = {k["code"] for k in kits_cfg}
                site_ov = master.get("hc_site_overrides", {})
                kit_ov = master.get("hc_kit_overrides", {})
                try:
                    import json as _json
                    if isinstance(source, str):
                        with open(source, "rb") as _f:
                            _content = _f.read()
                    else:
                        _content = source.getvalue()
                    roster = _cached_roster(_content, tuple(sorted(kit_codes)), _json.dumps(site_ov, sort_keys=True),
                                            _json.dumps(kit_ov, sort_keys=True))
                except Exception as exc:  # file sai mẫu
                    roster = None
                    st.error(f"Không đọc được file định biên: {exc}")
                if roster is not None and not roster["positions"].empty:
                    P = roster["positions"]
                    fy = roster["fiscal_year"]
                    year_ok = str(fy) == str(budget_year)
                    if not year_ok:
                        st.warning(f"File là định biên năm **{fy}** (T10/{fy - 1}–T9/{fy}), đang chọn năm ngân sách **{budget_year}**. "
                                   f"Chọn năm {fy} ở thanh bên trái trước khi áp dụng.")
                    h1, h2, h3, h4 = st.columns(4)
                    h1.metric("Vị trí", f"{len(P):,}")
                    h2.metric("Nhân sự thực tế", fmt_num(P['actual'].sum()))
                    h3.metric(f"Định biên {fy}", fmt_num(P['plan'].sum()))
                    h4.metric("Phòng ban × site", f"{P.groupby(['site', 'dept']).ngroups}")
                    if roster["issues"]:
                        with st.popover(f"{len(roster['issues'])} dòng lỗi dữ liệu trong file (đã xử lý tạm)"):
                            st.write("\n".join(f"- {x}" for x in roster["issues"]))

                    t_site, t_kit, t_need = st.tabs(["Nơi làm việc → Site", "Bộ trang bị theo vị trí", "Nhu cầu ước tính"])
                    with t_site:
                        loc_df = P.groupby(["location", "site", "site_note"]).size().reset_index(name="Số vị trí")
                        ed_loc = st.data_editor(loc_df, key="hc_loc_editor", hide_index=True, use_container_width=True,
                                                disabled=["location", "site_note", "Số vị trí"],
                                                column_config={"location": "Nơi làm việc (file)",
                                                               "site": st.column_config.SelectboxColumn("Site", options=[s["code"] for s in SITES], required=True),
                                                               "site_note": "Ghi chú"})
                    with t_kit:
                        kit_names = {k["code"]: f"{k['code']} · {k['name']}" for k in kits_cfg}
                        pos_df = (P.groupby(["position_label", "level", "kit", "kit_reason"]).size().reset_index(name="Số vị trí")
                                  .sort_values("Số vị trí", ascending=False))
                        pos_df["kit"] = pos_df["kit"].map(kit_names)
                        flt = st.text_input("Lọc vị trí", key="hc_pos_filter", placeholder="vd. tekla, kế toán, lái xe")
                        view = pos_df[pos_df["position_label"].str.lower().str.contains(flt.lower(), regex=False)] if flt else pos_df
                        ed_pos = st.data_editor(view, key=f"hc_pos_editor_{flt}", hide_index=True, use_container_width=True, height=380,
                                                disabled=["position_label", "level", "kit_reason", "Số vị trí"],
                                                column_config={"position_label": st.column_config.TextColumn("Vị trí", width="large"),
                                                               "level": "Cấp bậc",
                                                               "kit": st.column_config.SelectboxColumn("Bộ trang bị", options=list(kit_names.values()), required=True, width="medium"),
                                                               "kit_reason": "Căn cứ gán"})
                        st.caption("Đổi 'Bộ trang bị' cho vị trí cần điều chỉnh rồi bấm Lưu điều chỉnh; nội dung từng bộ sửa ở tab Quản lý Danh mục.")
                    if st.button("💾 Lưu điều chỉnh site / bộ trang bị", key="hc_save_ov"):
                        new_site_ov = dict(site_ov)
                        for _, r in ed_loc.iterrows():
                            auto = hi.map_site(r["location"])[0]
                            if r["site"] != auto:
                                new_site_ov[r["location"]] = r["site"]
                            else:
                                new_site_ov.pop(r["location"], None)
                        new_kit_ov = dict(kit_ov)
                        name_to_code = {v: k for k, v in kit_names.items()}
                        before = {(r["position_label"], r["level"]): r["kit"] for _, r in view.iterrows()}
                        for _, r in ed_pos.iterrows():
                            if r["kit"] != before.get((r["position_label"], r["level"])):
                                new_kit_ov[hi.position_key(r["position_label"], r["level"])] = name_to_code.get(r["kit"])
                        master["hc_site_overrides"], master["hc_kit_overrides"] = new_site_ov, new_kit_ov
                        save_master_data(master)
                        st.session_state["flash"] = f"Đã lưu {len(new_site_ov)} điều chỉnh site và {len(new_kit_ov)} điều chỉnh bộ trang bị."
                        st.rerun()

                    agg_rows = hi.aggregate(P)
                    est_inv = []
                    for (sc, dp), g in pd.DataFrame(agg_rows).groupby(["site_code", "dept"]):
                        for code, qty in hi.estimate_inventory(g.to_dict("records"), kits_cfg).items():
                            est_inv.append({"site_code": sc, "dept": dp, "catalog_code": code, "current_qty": qty,
                                            "replace_qty": 0.0, "quota_override": None,
                                            "note": "Ước tính = nhân sự thực tế × bộ trang bị; cần đối chiếu kiểm kê"})
                    N_prev = needs_by_dept(agg_rows, est_inv)
                    with t_need:
                        if N_prev.empty:
                            st.info("Không có nhu cầu.")
                        else:
                            n1, n2, n3 = st.columns(3)
                            sw_mask = N_prev["kind"].astype(str).str.startswith("software") | (N_prev["kind"] == "service")
                            n1.metric("Thiết bị mua thêm", format_vnd(((N_prev["add_qty"] + N_prev["replace_qty"]) * N_prev["price"])[~sw_mask].sum()))
                            n2.metric("Phần mềm mua mới", format_vnd((N_prev["add_qty"] * N_prev["price"])[sw_mask].sum()))
                            n3.metric("Gia hạn bản quyền", format_vnd((N_prev["renew_qty"] * N_prev["price"])[sw_mask].sum()))
                            items = (N_prev.groupby(["catalog_code", "item_name", "unit", "price"])
                                     .agg(**{"Định biên": ("quota", "sum"), "Hiện có (ước tính)": ("current_qty", "sum"),
                                             "Mua thêm": ("add_qty", "sum"), "Gia hạn": ("renew_qty", "sum"),
                                             "Thành tiền (VNĐ)": ("propose_value", "sum")})
                                     .reset_index().sort_values("Thành tiền (VNĐ)", ascending=False)
                                     .rename(columns={"catalog_code": "Mã", "item_name": "Hạng mục", "unit": "ĐVT", "price": "Đơn giá"}))
                            st.dataframe(items, use_container_width=True, hide_index=True, column_config=money_cfg)
                            st.caption("Hiện có ước tính giả định nhân sự đang làm việc đã được cấp đủ bộ trang bị. "
                                       "Khi áp dụng, ước tính chỉ ghi cho hạng mục phòng ban chưa khai báo hiện có.")

                    o1, o2 = st.columns(2)
                    use_est = o1.checkbox("Ghi hiện có ước tính (hạng mục chưa khai báo)", value=True, key="hc_use_est")
                    gen_lines = o2.checkbox("Tạo luôn dòng ngân sách 'Định biên' cho các phòng ban", value=True, key="hc_gen_lines")
                    if st.button(f"⚡ Áp định biên vào năm ngân sách {budget_year}", type="primary", disabled=not year_ok, key="hc_apply"):
                        # Cập nhật bảng phòng ban -> khối theo file (chỉ tên khối/phòng)
                        if "division" in P.columns:
                            _divs = dict(master.get("dept_divisions") or {})
                            for _dp, _dv in P[["dept", "division"]].dropna().drop_duplicates("dept").itertuples(index=False):
                                if str(_dv).strip():
                                    _divs[str(_dp).strip()] = str(_dv).strip()
                            if _divs != (master.get("dept_divisions") or {}):
                                master["dept_divisions"] = dict(sorted(_divs.items()))
                                save_master_data(master)
                        statuses = db.all_statuses(budget_year)
                        locked = {sc for sc, stt in statuses.items() if stt.get("status") not in db.EDITABLE_STATUSES}
                        done_depts, skipped, n_lines = 0, set(), 0
                        agg_df = pd.DataFrame(agg_rows)
                        for sc, site_grp in agg_df.groupby("site_code"):
                            if sc in locked:
                                skipped.add(sc)
                                continue
                            site_lines = pd.DataFrame(db.load_lines(budget_year, [sc]))
                            if "site_code" in site_lines.columns:
                                site_lines = site_lines.drop(columns=["site_code"])
                            drop_mask = pd.Series(False, index=site_lines.index)
                            new_lines = []
                            for dp, g in site_grp.groupby("dept"):
                                hc_rows_dp = g.drop(columns=["site_code", "dept"]).to_dict("records")
                                old_kit_items = {r["kit_code"]: r.get("kit_items")
                                                 for r in db.load_dept_rows("dept_headcount", budget_year, [sc], dp)}
                                for r in hc_rows_dp:  # giữ trang bị phòng ban đã tự chọn cho vị trí
                                    r["kit_items"] = old_kit_items.get(r.get("kit_code"))
                                db.replace_dept_rows("dept_headcount", budget_year, sc, dp, hc_rows_dp, current_user.email)
                                inv_now = db.load_dept_rows("dept_inventory", budget_year, [sc], dp)
                                if use_est:
                                    have = {r["catalog_code"] for r in inv_now}
                                    inv_now = inv_now + [r for r in est_inv if r["site_code"] == sc and r["dept"] == dp and r["catalog_code"] not in have]
                                    db.replace_dept_rows("dept_inventory", budget_year, sc, dp, inv_now, current_user.email)
                                done_depts += 1
                                if gen_lines:
                                    n = qt.compute_needs(hc_rows_dp, inv_now, master)
                                    in_dp = dept_mask(site_lines, dp)
                                    auto = site_lines["auto_quota"].fillna(False).astype(bool) if "auto_quota" in site_lines.columns \
                                        else pd.Series(False, index=site_lines.index)
                                    old = [r.to_dict() for _, r in site_lines[in_dp & auto].iterrows()]
                                    drop_mask |= (in_dp & auto)
                                    defaults = {"entity": "DDC", "location": SITE_NAME.get(sc, sc), "division": "",
                                                "handover_date": "", "contract_date": "", "completion_date": ""}
                                    new_lines += qt.build_quota_lines(n, dp, old, months, master, defaults)
                            if gen_lines:
                                save_site(pd.concat([site_lines[~drop_mask], pd.DataFrame(new_lines)], ignore_index=True), sc,
                                          base=[{k: v for k, v in r.items() if k != "site_code" and not (isinstance(v, float) and v != v)}
                                                for r in site_lines.to_dict("records")])
                                n_lines += len(new_lines)
                        db.log(current_user.email, "import_headcount", f"{budget_year}: {done_depts} phòng ban, {n_lines} dòng ngân sách")
                        st.session_state["quota_version"] = st.session_state.get("quota_version", 0) + 1
                        st.session_state["flash"] = (f"Đã áp định biên cho {done_depts} phòng ban" + (f", tạo {n_lines} dòng ngân sách 'Định biên'" if gen_lines else "")
                                                     + (f". Bỏ qua site đã nộp/duyệt: {', '.join(sorted(skipped))}" if skipped else "") + ".")
                        st.rerun()

    if selected_site == ALL_SITES or selected_dept == ALL_DEPTS:
        st.info("Chọn **một site** và **một phòng ban** ở thanh bên trái để khai báo / điều chỉnh định biên. Bên dưới là tổng hợp định biên và nhu cầu các phòng ban.")
        hc_list = db.load_dept_rows("dept_headcount", budget_year, scope_sites)
        if not hc_list:
            st.caption("Chưa có phòng ban nào khai báo định biên.")
        else:
            hc_all = pd.DataFrame(hc_list)
            summary = hc_all.groupby(["site_code", "dept"]).agg(**{"Nhân sự hiện có": ("hc_current", "sum"),
                                                                    "Nhân sự định biên": ("hc_plan", "sum")}).reset_index()
            N_all = needs_by_dept(hc_list, db.load_dept_rows("dept_inventory", budget_year, scope_sites))
            if not N_all.empty:
                summary = summary.merge(needs_summary(N_all), left_on=["site_code", "dept"], right_on=["site", "dept"], how="left").drop(columns=["site"])
            if not df_site.empty and "need_type" in df_site.columns:
                val = df_site.assign(dk=df_site["dept_proposing"].map(dept_key))
                val = val[val["need_type"] == qt.NEED_QUOTA].groupby("dk")["total_budget"].sum()
                summary["Ngân sách định biên đã tạo (VNĐ)"] = summary["dept"].map(dept_key).map(val).fillna(0)
            summary = summary.sort_values("Tổng nhu cầu (VNĐ)" if "Tổng nhu cầu (VNĐ)" in summary.columns else "Nhân sự định biên", ascending=False)
            total_row = summary.sum(numeric_only=True)
            s1, s2, s3 = st.columns(3)
            s1.metric("Nhân sự hiện có → định biên", f"{fmt_num(total_row['Nhân sự hiện có'])} → {fmt_num(total_row['Nhân sự định biên'])}")
            s2.metric("Phòng ban × site", f"{len(summary)}")
            s3.metric("Tổng nhu cầu CNTT theo định biên", format_vnd(total_row.get("Tổng nhu cầu (VNĐ)", 0)))
            summary["site_code"] = summary["site_code"].map(site_label)
            st.dataframe(summary.rename(columns={"site_code": "Site", "dept": "Phòng ban"}), use_container_width=True, hide_index=True,
                         column_config=money_cfg)
    else:
        q_key = f"{budget_year}_{selected_site}_{selected_dept}_{st.session_state.get('quota_version', 0)}"
        headcount = db.load_dept_rows("dept_headcount", budget_year, [selected_site], selected_dept)
        inventory = db.load_dept_rows("dept_inventory", budget_year, [selected_site], selected_dept)

        # Bước 1: định biên nhân sự
        st.markdown(f"#### 1️⃣ Định biên nhân sự – {selected_dept}")
        df_hc = pd.DataFrame([{"kit": kit_label.get(h["kit_code"], h["kit_code"]), "hc_current": h["hc_current"],
                               "hc_plan": h["hc_plan"]} for h in headcount], columns=["kit", "hc_current", "hc_plan"])
        ed_hc = st.data_editor(
            df_hc, key=f"hc_{q_key}", num_rows="dynamic" if can_edit else "fixed", disabled=not can_edit,
            use_container_width=True, hide_index=True,
            column_config={
                "kit": st.column_config.SelectboxColumn("Vị trí / Bộ trang bị tiêu chuẩn", options=list(kit_label.values()),
                                                        required=True, width="large"),
                "hc_current": st.column_config.NumberColumn("Nhân sự hiện có", min_value=0, step=1, format=MONEY_FMT),
                "hc_plan": st.column_config.NumberColumn(f"Nhân sự định biên {budget_year}", min_value=0, step=1, format=MONEY_FMT),
            })
        k1, k2 = st.columns(2)
        k1.metric("Nhân sự hiện có", f"{int(pd.to_numeric(ed_hc['hc_current'], errors='coerce').fillna(0).sum())} người")
        k2.metric(f"Định biên {budget_year}", f"{int(pd.to_numeric(ed_hc['hc_plan'], errors='coerce').fillna(0).sum())} người")
        with st.expander("Xem bộ trang bị tiêu chuẩn"):
            st.dataframe(pd.DataFrame([{"Bộ trang bị": f"{k['code']} · {k['name']}",
                                        "Hạng mục": item_label.get(i["catalog_code"], i["catalog_code"]),
                                        "Số lượng / người": i["qty_per_person"]} for k in kits_cfg for i in k["items"]]),
                         use_container_width=True, hide_index=True)

        # Bước 1b: chọn trang bị (phần cứng + phần mềm) cho từng vị trí – bộ tiêu chuẩn chỉ là cấu hình gợi ý ban đầu
        kits_by_code = {k["code"]: k for k in kits_cfg}
        kit_store = st.session_state.setdefault(f"kitcfg_{q_key}", {
            h["kit_code"]: qt.parse_kit_items(h.get("kit_items")) for h in headcount})

        def _item_cat(it):
            kind = str(it.get("kind") or "")
            if kind.startswith("software"):
                return "Phần mềm cơ bản" if it.get("group") in ("IT04", "IT05", "IT09") else "Phần mềm chuyên dụng"
            return "Dịch vụ" if kind == "service" else "Phần cứng"

        def _kit_key(items):
            return sorted((i["catalog_code"], round(qt._num(i.get("qty_per_person")), 4), round(qt._num(i.get("fixed_qty")), 4))
                          for i in items)

        def _kit_items_json(kit_code):
            items = kit_store.get(kit_code)
            return None if items is None else json.dumps(items, ensure_ascii=False)

        st.markdown("#### Chọn trang bị cho từng vị trí (phần cứng & phần mềm)")
        st.caption("Bộ trang bị tiêu chuẩn chỉ là gợi ý ban đầu. Chọn vị trí rồi: bỏ tích 'Dùng' để bỏ hạng mục, bấm ô Hạng mục "
                   "để đổi model / phiên bản, thêm phần cứng / phần mềm cơ bản / phần mềm chuyên dụng bằng ô 'Thêm nhanh'. "
                   "'Số lượng / người' nhân với định biên; 'Số lượng cố định' dùng khi chỉ một số người "
                   "cần (vd. 3 bản quyền Tekla cho 10 kỹ sư). Lựa chọn được lưu cùng định biên ở nút Lưu bên dưới.")
        pos_codes = [c for c in dict.fromkeys(next((c for c, l in kit_label.items() if l == r["kit"]), None)
                                              for _, r in ed_hc.iterrows() if r.get("kit")) if c]
        if not pos_codes:
            st.info("Khai báo vị trí & định biên nhân sự ở bảng trên trước, sau đó chọn trang bị cho từng vị trí.")
        else:
            plan_by_code = {next((c for c, l in kit_label.items() if l == r["kit"]), None): qt._num(pd.to_numeric(r.get("hc_plan"), errors="coerce"))
                            for _, r in ed_hc.iterrows() if r.get("kit")}
            # nhãn phải cố định (không đổi theo định biên / trạng thái tự chọn) để ô chọn không bị đặt lại
            sel_pos = st.selectbox("Vị trí", pos_codes, key=f"kitpos_{q_key}", format_func=lambda c: kit_label.get(c, c))
            st.caption(f"Định biên {fmt_num(plan_by_code.get(sel_pos, 0))} người · "
                       + ("trang bị tự chọn" if kit_store.get(sel_pos) is not None else "theo bộ tiêu chuẩn")
                       + " · Vị trí đã tự chọn: "
                       + (", ".join(c for c in pos_codes if kit_store.get(c) is not None) or "chưa có"))
            std_items = [dict(i, fixed_qty=0, note="") for i in kits_by_code.get(sel_pos, {}).get("items", [])]
            ver = st.session_state.get(f"kitver_{q_key}", 0)
            kit_ed_key = f"kited_{q_key}_{sel_pos}_{ver}"
            # Bảng sửa phải dựng từ ảnh chụp cố định: Streamlit áp các thay đổi của người dùng lên dữ liệu gốc mỗi lần chạy lại
            kit_base = st.session_state.setdefault(f"kitbase_{q_key}", {})
            if kit_ed_key not in kit_base:
                kit_base[kit_ed_key] = std_items if kit_store.get(sel_pos) is None else list(kit_store[sel_pos])
            cur_items = kit_base[kit_ed_key]
            df_k = pd.DataFrame([{
                "use": True,
                "cat": _item_cat(cat_by_code.get(i["catalog_code"], {})),
                "item": item_label.get(i["catalog_code"], i["catalog_code"]),
                "price": qt._num(cat_by_code.get(i["catalog_code"], {}).get("price")),
                "qty_per_person": qt._num(i.get("qty_per_person")) or None,
                "fixed_qty": qt._num(i.get("fixed_qty")) or None,
                "note": i.get("note") or "",
            } for i in cur_items], columns=["use", "cat", "item", "price", "qty_per_person", "fixed_qty", "note"])
            cat_order = {"Phần cứng": 0, "Phần mềm cơ bản": 1, "Phần mềm chuyên dụng": 2, "Dịch vụ": 3}
            df_k = df_k.sort_values("cat", key=lambda x: x.map(cat_order), kind="stable").reset_index(drop=True)
            ed_k = st.data_editor(
                df_k, key=kit_ed_key, num_rows="fixed", disabled=not can_edit,
                use_container_width=True, hide_index=True,
                column_config={
                    "use": st.column_config.CheckboxColumn("Dùng", help="Bỏ tích để bỏ hạng mục khỏi vị trí"),
                    "cat": st.column_config.TextColumn("Loại", disabled=True),
                    "item": st.column_config.SelectboxColumn("Hạng mục (bấm để đổi model / phiên bản)", options=list(item_label.values()), required=True, width="large"),
                    "price": st.column_config.NumberColumn("Đơn giá (VNĐ)", disabled=True, format=MONEY_FMT),
                    "qty_per_person": st.column_config.NumberColumn("Số lượng / người", min_value=0.0, step=0.1, format="%.2f"),
                    "fixed_qty": st.column_config.NumberColumn("Số lượng cố định (cả vị trí)", min_value=0, step=1, format=MONEY_FMT,
                                                               help="Điền khi chỉ một số người dùng; khi có số này sẽ không nhân theo định biên"),
                    "note": st.column_config.TextColumn("Ghi chú / người dùng"),
                })
            new_items = []
            for _, r in ed_k.iterrows():
                code = label_to_code.get(r.get("item"))
                if not code or not bool(r.get("use")):
                    continue
                qpp = qt._num(pd.to_numeric(r.get("qty_per_person"), errors="coerce"))
                fx = qt._num(pd.to_numeric(r.get("fixed_qty"), errors="coerce"))
                if qpp <= 0 and fx <= 0:
                    qpp = 1.0  # dòng mới chưa nhập số lượng: mặc định 1 / người
                new_items.append({"catalog_code": code, "qty_per_person": qpp, "fixed_qty": fx, "note": str(r.get("note") or "")})
            if can_edit:
                kit_store[sel_pos] = None if _kit_key(new_items) == _kit_key(std_items) else new_items

                ac1, ac2, ac3 = st.columns([1.2, 3, 1.3])
                add_cat = ac1.selectbox("Thêm nhanh", ["Phần mềm chuyên dụng", "Phần mềm cơ bản", "Phần cứng", "Dịch vụ"],
                                        key=f"kitaddcat_{q_key}")
                have = {i["catalog_code"] for i in new_items}
                add_opts = [item_label[c] for c, it in cat_by_code.items()
                            if _item_cat(it) == add_cat and c not in have and item_scope(it, master) != SCOPE_SHARED]
                add_sel = ac2.multiselect(f"Chọn {add_cat.lower()} ({len(add_opts)} hạng mục)", add_opts, key=f"kitaddsel_{q_key}_{sel_pos}_{ver}",
                                          placeholder="Gõ tên để tìm, chọn được nhiều...")
                ac3.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if ac3.button("➕ Thêm vào vị trí", disabled=not add_sel, use_container_width=True, key=f"kitaddbtn_{q_key}"):
                    kit_store[sel_pos] = new_items + [{"catalog_code": label_to_code[l], "qty_per_person": 1.0, "fixed_qty": 0.0, "note": ""}
                                                      for l in add_sel]
                    st.session_state[f"kitver_{q_key}"] = ver + 1
                    st.rerun()
                if kit_store.get(sel_pos) is not None:
                    rc1, rc2 = st.columns([3, 1])
                    rc1.caption("Vị trí này đang dùng trang bị tự chọn (khác bộ tiêu chuẩn). Nhớ bấm Lưu ở cuối trang.")
                    if rc2.button("↩️ Về bộ tiêu chuẩn", use_container_width=True, key=f"kitreset_{q_key}"):
                        kit_store[sel_pos] = None
                        st.session_state[f"kitver_{q_key}"] = ver + 1
                        st.rerun()
            per_head = sum(qt._num(cat_by_code.get(i["catalog_code"], {}).get("price")) * i["qty_per_person"]
                           for i in new_items if i["fixed_qty"] <= 0)
            fixed_val = sum(qt._num(cat_by_code.get(i["catalog_code"], {}).get("price")) * i["fixed_qty"] for i in new_items)
            st.caption(f"Chi phí trang bị đầy đủ: {format_vnd(per_head)} / người"
                       + (f" + {format_vnd(fixed_val)} cố định cho vị trí" if fixed_val else "")
                       + " (chưa trừ thiết bị / bản quyền đang có).")

        # Bước 2: hiện có & thay thế
        needs = qt.compute_needs(
            [{"kit_code": next((c for c, l in kit_label.items() if l == r["kit"]), None),
              "hc_current": r["hc_current"], "hc_plan": r["hc_plan"],
              "kit_items": _kit_items_json(next((c for c, l in kit_label.items() if l == r["kit"]), None))}
             for _, r in ed_hc.iterrows() if r.get("kit")],
            inventory, master)
        st.markdown("#### 2️⃣ Thiết bị / phần mềm hiện có & cần thay thế")
        st.caption("Nhập số đang có của phòng ban và số thiết bị cần thay (hỏng, hết khấu hao). "
                   "Có thể thêm dòng cho hạng mục định biên riêng (vd. máy in A3 dùng chung) và nhập 'Định biên điều chỉnh'.")
        df_inv = pd.DataFrame({
            "item": needs["catalog_code"].map(item_label), "dinh_muc": needs["dinh_muc"],
            "quota_override": pd.to_numeric(needs["quota_override"], errors="coerce"),
            "current_qty": needs["current_qty"], "replace_qty": needs["replace_qty"], "note": needs["note"],
        }, columns=["item", "dinh_muc", "quota_override", "current_qty", "replace_qty", "note"])
        ed_inv = st.data_editor(
            df_inv, key=f"inv_{q_key}", num_rows="dynamic" if can_edit else "fixed", disabled=not can_edit,
            use_container_width=True, hide_index=True,
            column_config={
                "item": st.column_config.SelectboxColumn("Hạng mục", options=list(item_label.values()), required=True, width="large"),
                "dinh_muc": st.column_config.NumberColumn("Định mức (tự tính)", disabled=True, format=MONEY_FMT),
                "quota_override": st.column_config.NumberColumn("Định biên điều chỉnh", min_value=0, step=1, format=MONEY_FMT,
                                                                help="Để trống = dùng định mức tự tính"),
                "current_qty": st.column_config.NumberColumn("Hiện có", min_value=0, step=1, format=MONEY_FMT),
                "replace_qty": st.column_config.NumberColumn("Cần thay thế", min_value=0, step=1, format=MONEY_FMT),
                "note": st.column_config.TextColumn("Ghi chú"),
            })

        inv_rows = []
        for _, r in ed_inv.iterrows():
            code = label_to_code.get(r.get("item"))
            if not code:
                continue
            ov = r.get("quota_override")
            inv_rows.append({"catalog_code": code, "current_qty": qt._num(pd.to_numeric(r.get("current_qty"), errors="coerce")),
                             "replace_qty": qt._num(pd.to_numeric(r.get("replace_qty"), errors="coerce")),
                             "quota_override": None if ov is None or pd.isna(ov) else float(ov),
                             "note": r.get("note") or ""})
        months_by_kit = {h["kit_code"]: h.get("hc_months") for h in headcount}
        hc_rows = [{"kit_code": next((c for c, l in kit_label.items() if l == r["kit"]), None),
                    "hc_current": qt._num(pd.to_numeric(r.get("hc_current"), errors="coerce")),
                    "hc_plan": qt._num(pd.to_numeric(r.get("hc_plan"), errors="coerce"))}
                   for _, r in ed_hc.iterrows() if r.get("kit")]
        for h in hc_rows:
            h["hc_months"] = months_by_kit.get(h["kit_code"])
            h["kit_items"] = _kit_items_json(h["kit_code"])
        needs = qt.compute_needs(hc_rows, inv_rows, master)

        # Bước 3: nhu cầu đề xuất
        st.markdown("#### 3️⃣ Nhu cầu đề xuất theo định biên")
        if needs.empty:
            st.info("Chưa có nhu cầu. Khai báo định biên nhân sự ở bước 1 hoặc thêm hạng mục ở bước 2.")
        else:
            kind_name = it_kinds(master)
            show = needs.assign(kind=needs["kind"].map(kind_name))[
                ["catalog_code", "item_name", "kind", "unit", "quota", "current_qty", "add_qty", "renew_qty", "replace_qty",
                 "propose_qty", "price", "propose_value", "basis"]]
            st.dataframe(show, use_container_width=True, hide_index=True, column_config={
                "catalog_code": "Mã", "item_name": st.column_config.TextColumn("Hạng mục", width="medium"), "kind": "Loại", "unit": "ĐVT",
                "quota": st.column_config.NumberColumn("Định biên", format=MONEY_FMT),
                "current_qty": st.column_config.NumberColumn("Hiện có", format=MONEY_FMT),
                "add_qty": st.column_config.NumberColumn("Mua bổ sung", format=MONEY_FMT),
                "renew_qty": st.column_config.NumberColumn("Gia hạn", format=MONEY_FMT),
                "replace_qty": st.column_config.NumberColumn("Thay thế", format=MONEY_FMT),
                "propose_qty": st.column_config.NumberColumn("Tổng đề xuất", format=MONEY_FMT),
                "price": st.column_config.NumberColumn("Đơn giá", format=MONEY_FMT),
                "propose_value": st.column_config.NumberColumn("Thành tiền (VNĐ)", format=MONEY_FMT),
                "basis": st.column_config.TextColumn("Căn cứ", width="large"),
            })
            is_sw = needs["kind"].astype(str).str.startswith("software")
            m1, m2, m3 = st.columns(3)
            m1.metric("Thiết bị theo định biên", format_vnd(needs.loc[~is_sw, "propose_value"].sum()))
            m2.metric("Phần mềm theo định biên", format_vnd(needs.loc[is_sw, "propose_value"].sum()))
            m3.metric("Tổng theo định biên", format_vnd(needs["propose_value"].sum()))

        if can_edit:
            b1, b2 = st.columns(2)
            if b1.button("💾 Lưu định biên & hiện có", use_container_width=True):
                db.replace_dept_rows("dept_headcount", budget_year, selected_site, selected_dept, hc_rows, current_user.email)
                db.replace_dept_rows("dept_inventory", budget_year, selected_site, selected_dept, inv_rows, current_user.email)
                st.session_state["quota_version"] = st.session_state.get("quota_version", 0) + 1
                st.session_state["flash"] = f"Đã lưu định biên & trang bị theo vị trí của {selected_dept}."
                st.rerun()
            if b2.button("⚡ Lưu & tạo dòng ngân sách theo định biên", use_container_width=True, type="primary",
                         help="Thay các dòng 'Định biên' tự sinh trước đó của phòng ban này; giữ nguyên dòng 'Phát sinh mới' và phân kỳ đã chỉnh"):
                db.replace_dept_rows("dept_headcount", budget_year, selected_site, selected_dept, hc_rows, current_user.email)
                db.replace_dept_rows("dept_inventory", budget_year, selected_site, selected_dept, inv_rows, current_user.email)
                st.session_state["quota_version"] = st.session_state.get("quota_version", 0) + 1
                in_dept = dept_mask(df_site, selected_dept)
                auto = df_site["auto_quota"].fillna(False).astype(bool) if "auto_quota" in df_site.columns else pd.Series(False, index=df_site.index)
                old = [r.to_dict() for _, r in df_site[in_dept & auto].iterrows()]
                entity = (df_site["entity"].mode().iloc[0] if "entity" in df_site.columns and not df_site["entity"].dropna().empty else "DDC")
                defaults = {"entity": entity, "location": SITE_NAME.get(selected_site, selected_site),
                            "handover_date": "", "contract_date": "", "completion_date": ""}
                new_lines = qt.build_quota_lines(needs, selected_dept, old, months, master, defaults)
                kept = df_site[~(in_dept & auto)]
                save_site(pd.concat([kept, pd.DataFrame(new_lines)], ignore_index=True), selected_site)
                st.session_state["flash"] = (f"Đã tạo {len(new_lines)} dòng ngân sách theo định biên cho {selected_dept} "
                                             f"({format_vnd(needs['propose_value'].sum() if not needs.empty else 0)}). "
                                             "Kiểm tra phân kỳ ở tab 'Lập & Nhập liệu' (mặc định 100% tháng đầu năm ngân sách).")
                st.rerun()
