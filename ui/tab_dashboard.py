"""Tổng quan: chỉ số, biểu đồ, tổng hợp theo phòng ban / Khối, tiến độ duyệt."""
import datetime
import html as _html

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import ui.styles

import smart_advisor as advisor
import quota as qt
import reports


def _with_total(t: pd.DataFrame) -> pd.DataFrame:
    t = t.sort_values("Tổng ngân sách", ascending=False)
    t.loc["TỔNG CỘNG"] = t.sum(numeric_only=True)
    return t


@st.cache_data(max_entries=16)
def _cached_dashboard_pivots(df_dept: pd.DataFrame, quarters_items: tuple) -> tuple:
    quarters = dict(quarters_items)
    t1 = df_dept.groupby("dept").agg(
        **{"Số hạng mục": ("dept", "size"), "Tổng ngân sách": ("total_budget", "sum")},
        **{q: (q, "sum") for q in quarters}
    )
    t1["Tỷ trọng"] = t1["Tổng ngân sách"] / t1["Tổng ngân sách"].sum() if t1["Tổng ngân sách"].sum() else 0.0
    t1 = _with_total(t1)

    t2 = df_dept.pivot_table(index="dept", columns="it_group", values="total_budget", aggfunc="sum", fill_value=0)
    t2["Tổng ngân sách"] = t2.sum(axis=1)
    t2 = _with_total(t2)

    ct = df_dept.get("capex_type", pd.Series(index=df_dept.index, dtype=object)).fillna("Chưa phân loại")
    t3 = df_dept.assign(capex_type=ct).pivot_table(index="dept", columns="capex_type", values="total_budget",
                                                   aggfunc="sum", fill_value=0)
    t3["Tổng ngân sách"] = t3.sum(axis=1)
    t3 = _with_total(t3)

    kind_s = df_dept["item_kind"] if "item_kind" in df_dept.columns else pd.Series(index=df_dept.index, dtype=object)
    kind_grp = kind_s.map(lambda k: "Phần mềm" if str(k).startswith("software") else ("Dịch vụ" if k == "service" else
                                                                                       ("Thiết bị" if isinstance(k, str) and k else "Chưa phân loại")))
    need_s = df_dept["need_type"] if "need_type" in df_dept.columns else pd.Series(index=df_dept.index, dtype=object)
    t4 = df_dept.assign(col=need_s.fillna("Chưa phân loại") + " – " + kind_grp).pivot_table(
        index="dept", columns="col", values="total_budget", aggfunc="sum", fill_value=0)
    t4 = t4[sorted(t4.columns)]
    t4["Tổng ngân sách"] = t4.sum(axis=1)
    t4 = _with_total(t4)
    return t1, t2, t3, t4


def render(ctx):
    """Nội dung tab - ctx: giá trị dùng chung của lượt chạy (app.app_context())."""
    MONEY_FMT, budget_year, contingency_pct, current_user = ctx.MONEY_FMT, ctx.budget_year, ctx.contingency_pct, ctx.current_user
    dept_key, dept_list, df_curr, fmt_num = ctx.dept_key, ctx.dept_list, ctx.df_curr, ctx.fmt_num
    format_vnd, format_vnd_short, item_filter_widgets, master = ctx.format_vnd, ctx.format_vnd_short, ctx.item_filter_widgets, ctx.master
    months, plot_chart, prev_year_lines, selected_dept = ctx.months, ctx.plot_chart, ctx.prev_year_lines, ctx.selected_dept
    selected_site, site_label = ctx.selected_site, ctx.site_label

    if df_curr.empty:
        st.info("Chưa có dữ liệu CapEx. Bạn hãy chuyển sang tab **'Lập & Nhập liệu CapEx'** hoặc bấm nút **'Nạp dữ liệu mẫu'** ở thanh bên trái!")
    else:
        # Calculate summary metrics
        total_capex = df_curr["total_budget"].sum() if "total_budget" in df_curr.columns else 0.0
        total_items = len(df_curr)
        total_qty = df_curr["quantity"].sum() if "quantity" in df_curr.columns else 0
        num_entities = df_curr["entity"].nunique() if "entity" in df_curr.columns else 0

        # Top entity / cat1
        top_cat = df_curr.groupby("asset_cat1")["total_budget"].sum().idxmax() if "asset_cat1" in df_curr.columns and not df_curr.empty else "N/A"
        top_cat_val = df_curr.groupby("asset_cat1")["total_budget"].sum().max() if "asset_cat1" in df_curr.columns and not df_curr.empty else 0

        # KPI Row
        cont_pct = contingency_pct()
        cont_val = round(total_capex * cont_pct)
        entity_list = ", ".join(sorted(df_curr["entity"].dropna().astype(str).unique())) if "entity" in df_curr.columns else ""
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-card-header">
                    <span class="kpi-title">CAPEX thường niên {budget_year} (gồm dự phòng)</span>
                    <span class="kpi-icon-badge kpi-icon-blue">💰</span>
                </div>
                <div class="kpi-value">{fmt_num((total_capex + cont_val) / 1e9, 2)} <span class="kpi-unit">tỷ VNĐ</span></div>
                <div class="kpi-sub"><span class="kpi-pill kpi-pill-blue">Hạng mục: {fmt_num(total_capex)} + dự phòng {fmt_num(cont_pct * 100, 0)}%: {fmt_num(cont_val)} VNĐ</span></div>
            </div>
            """, unsafe_allow_html=True)

        with k2:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-card-header">
                    <span class="kpi-title">Tổng Hạng mục Đầu tư</span>
                    <span class="kpi-icon-badge kpi-icon-emerald">📦</span>
                </div>
                <div class="kpi-value">{total_items} <span class="kpi-unit">mục</span></div>
                <div class="kpi-sub"><span class="kpi-pill kpi-pill-emerald">Tổng số lượng: {fmt_num(total_qty)} cái/bộ</span></div>
            </div>
            """, unsafe_allow_html=True)

        with k3:
            pct_top = (top_cat_val / total_capex * 100) if total_capex > 0 else 0
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-card-header">
                    <span class="kpi-title">Nhóm Tỷ trọng Cao Nhất</span>
                    <span class="kpi-icon-badge kpi-icon-amber">📊</span>
                </div>
                <div class="kpi-value" style="font-size:16px;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;" title="{_html.escape(str(top_cat))}">{_html.escape(str(top_cat))}</div>
                <div class="kpi-sub"><span class="kpi-pill kpi-pill-amber">{fmt_num(top_cat_val / 1e9, 2)} tỷ VNĐ ({fmt_num(pct_top, 1)}%)</span></div>
            </div>
            """, unsafe_allow_html=True)

        with k4:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-card-header">
                    <span class="kpi-title">Phạm vi Pháp nhân</span>
                    <span class="kpi-icon-badge kpi-icon-purple">🏢</span>
                </div>
                <div class="kpi-value">{num_entities} <span class="kpi-unit">đơn vị</span></div>
                <div class="kpi-sub"><span class="kpi-pill kpi-pill-purple" title="{_html.escape(entity_list)}">{_html.escape(entity_list or 'Chưa có')}</span></div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

        # Filters Row
        with st.expander("Bộ lọc Phân tích Trực quan", expanded=False):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                filter_entity = st.multiselect("Lọc theo Pháp nhân", options=sorted(df_curr["entity"].dropna().unique().tolist()))
            with fc2:
                filter_cat1 = st.multiselect("Lọc theo Loại tài sản cấp 1", options=sorted(df_curr["asset_cat1"].dropna().unique().tolist()))
            with fc3:
                filter_site = st.multiselect("Lọc theo Vị trí / Nhà máy", options=sorted(df_curr["location"].dropna().unique().tolist()))
            dash_item_mask = item_filter_widgets(df_curr, f"dashflt_{budget_year}_{selected_site}_{dept_key(selected_dept)}")

        df_filtered = df_curr[dash_item_mask].copy()
        if filter_entity:
            df_filtered = df_filtered[df_filtered["entity"].isin(filter_entity)]
        if filter_cat1:
            df_filtered = df_filtered[df_filtered["asset_cat1"].isin(filter_cat1)]
        if filter_site:
            df_filtered = df_filtered[df_filtered["location"].isin(filter_site)]

        # CHARTS ROW 1: Entity & Asset Category
        c1, c2 = st.columns([1, 1])

        with c1:
            st.markdown("##### Phân bổ Ngân sách theo Pháp nhân")
            df_ent = df_filtered.groupby("entity")["total_budget"].sum().reset_index()
            fig_ent = px.pie(
                df_ent,
                names="entity",
                values="total_budget",
                hole=0.45,
                color_discrete_sequence=ui.styles.CHART_COLORS
            )
            fig_ent.update_traces(
                textposition='inside',
                textinfo='percent+label',
                hovertemplate="<b>%{label}</b><br>Ngân sách: %{value:,.0f} VNĐ<br>Tỷ lệ: %{percent}"
            )
            fig_ent.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=320)
            plot_chart(fig_ent, use_container_width=True)

        with c2:
            st.markdown("##### Phân bổ theo Loại Tài sản Cấp 1")
            df_cat = df_filtered.groupby("asset_cat1")["total_budget"].sum().reset_index().sort_values(by="total_budget", ascending=True)
            df_cat["budget_bil"] = df_cat["total_budget"] / 1e9
            fig_cat = px.bar(
                df_cat,
                x="budget_bil",
                y="asset_cat1",
                orientation='h',
                labels={"budget_bil": "Ngân sách (Tỷ VNĐ)", "asset_cat1": "Loại tài sản"},
                color="budget_bil",
                color_continuous_scale="Blues"
            )
            fig_cat.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=320, coloraxis_showscale=False)
            fig_cat.update_traces(hovertemplate="<b>%{y}</b><br>Ngân sách: %{x:,.2f} tỷ VNĐ")
            plot_chart(fig_cat, use_container_width=True)

        # CHARTS ROW 2: Monthly Disbursement Cash Flow & Site
        c3, c4 = st.columns([1.3, 1])

        with c3:
            st.markdown("##### Dòng tiền Giải ngân Phân kỳ 12 Tháng")
            val_cols = [f"val_{m}" for m in months if f"val_{m}" in df_filtered.columns]
            monthly_sums = [df_filtered[c].sum() / 1e9 for c in val_cols]
            cum_sums = np.cumsum(monthly_sums)

            fig_cash = go.Figure()
            fig_cash.add_trace(go.Bar(
                x=months,
                y=monthly_sums,
                name="Giải ngân tháng (Tỷ VNĐ)",
                marker_color="#1E4E8C",
                hovertemplate="Tháng: %{x}<br>Giải ngân: %{y:,.2f} tỷ VNĐ"
            ))
            fig_cash.add_trace(go.Scatter(
                x=months,
                y=cum_sums,
                name="Lũy kế giải ngân (Tỷ VNĐ)",
                mode="lines+markers",
                line=dict(color="#E11D48", width=3),
                marker=dict(size=6),
                yaxis="y2",
                hovertemplate="Lũy kế đến %{x}: %{y:,.2f} tỷ VNĐ"
            ))
            fig_cash.update_layout(
                margin=dict(t=20, b=20, l=20, r=20),
                height=340,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                yaxis=dict(title="Tháng (Tỷ VNĐ)"),
                yaxis2=dict(title="Lũy kế (Tỷ VNĐ)", overlaying="y", side="right")
            )
            plot_chart(fig_cash, use_container_width=True)

        with c4:
            st.markdown("##### Phân bổ theo Vị trí / Nhà máy")
            df_loc = df_filtered.groupby("location")["total_budget"].sum().reset_index().sort_values(by="total_budget", ascending=False)
            df_loc["budget_bil"] = df_loc["total_budget"] / 1e9
            fig_site = px.pie(
                df_loc,
                names="location",
                values="budget_bil",
                color_discrete_sequence=ui.styles.CHART_COLORS
            )
            fig_site.update_traces(
                textposition='inside',
                textinfo='percent+label',
                hovertemplate="<b>%{label}</b><br>Ngân sách: %{value:,.2f} tỷ VNĐ"
            )
            fig_site.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=340)
            plot_chart(fig_site, use_container_width=True)

        # CƠ CẤU: trang bị theo định biên / hạ tầng dùng chung / phát sinh mới
        if "need_type" in df_curr.columns and not df_curr.empty:
            st.markdown("##### Cơ cấu ngân sách CNTT")
            nt = df_curr["need_type"].fillna("Chưa phân loại")
            cc = st.columns(4)
            for col_box, (lbl, key) in zip(cc, [("Trang bị theo định biên", qt.NEED_QUOTA), ("Hạ tầng dùng chung", qt.NEED_INFRA),
                                                ("Phát sinh mới", qt.NEED_NEW), ("Chưa phân loại", "Chưa phân loại")]):
                col_box.metric(lbl, format_vnd_short(df_curr.loc[nt == key, "total_budget"].sum()) + " VNĐ")

        # TỔNG HỢP THEO PHÒNG BAN (theo phòng ban đang chọn; "Tất cả" = mọi phòng ban của site)
        if "dept_proposing" in df_curr.columns and not df_curr.empty:
            st.markdown("##### Tổng hợp Ngân sách theo Phòng ban")
            canon = {dept_key(d): d for d in dept_list}
            df_dept = df_curr.assign(
                dept=df_curr["dept_proposing"].map(lambda d: canon.get(dept_key(d), d) if str(d or "").strip() else "(Chưa ghi phòng ban)"),
                it_group=df_curr["it_group"].fillna("(Chưa phân nhóm)") if "it_group" in df_curr.columns else "(Chưa phân nhóm)")
            quarters = {"Q1 (T10-T12)": months[0:3], "Q2 (T1-T3)": months[3:6], "Q3 (T4-T6)": months[6:9], "Q4 (T7-T9)": months[9:12]}
            for q, ms in quarters.items():
                cols = [f"val_{m}" for m in ms if f"val_{m}" in df_dept.columns]
                df_dept[q] = df_dept[cols].sum(axis=1) if cols else 0.0
            d_tab1, d_tab2, d_tab3, d_tab4 = st.tabs(["Phòng ban × Quý giải ngân", "Phòng ban × Nhóm CNTT",
                                                      "Phòng ban × CAPEX/CCDC/OPEX", "Phòng ban × Định biên / Phát sinh"])
            money = st.column_config.NumberColumn(format=MONEY_FMT)

            t1, t2, t3, t4 = _cached_dashboard_pivots(df_dept, tuple(quarters.items()))

            with d_tab1:
                st.dataframe(t1, use_container_width=True,
                             column_config={**{c: money for c in ["Tổng ngân sách", *quarters]},
                                            "Tỷ trọng": st.column_config.ProgressColumn(format="%.1f%%", min_value=0.0, max_value=1.0)})
            with d_tab2:
                st.dataframe(t2, use_container_width=True, column_config={c: money for c in t2.columns})
            with d_tab3:
                st.dataframe(t3, use_container_width=True, column_config={c: money for c in t3.columns})
            with d_tab4:
                st.dataframe(t4, use_container_width=True, column_config={c: money for c in t4.columns})
                st.caption("Định biên: sinh từ định biên nhân sự × bộ trang bị tiêu chuẩn (tab 'Định biên & Nhu cầu'). "
                           "Phát sinh mới: nhu cầu ngoài định biên, có lý do. 'Chưa phân loại': dữ liệu cũ/nhập Excel.")
            st.caption("Bảng tổng hợp tính theo phòng ban đang chọn ở thanh bên trái (không áp bộ lọc biểu đồ).")

        # TỔNG HỢP THEO KHỐI (so sánh năm trước)
        div_tbl = reports.summary_by_division(df_curr, prev_year_lines(), master)
        if not div_tbl.empty:
            st.markdown("##### Tổng hợp Ngân sách theo Khối")
            prev_label = f"Năm {int(budget_year) - 1}"
            show = div_tbl.rename(columns={"Tổng": f"Tổng {budget_year}", "Năm trước": prev_label})
            st.dataframe(show, use_container_width=True, hide_index=True,
                         column_config={**{c: st.column_config.NumberColumn(format=MONEY_FMT) for c in
                                           ("TSCĐ (CAPEX)", "CCDC", "OPEX", "Chưa phân loại", f"Tổng {budget_year}", prev_label, "Chênh lệch")},
                                        "Tỷ trọng": st.column_config.ProgressColumn(format="%.1f%%", min_value=0.0, max_value=1.0),
                                        "% so năm trước": st.column_config.NumberColumn(format="percent")})
            st.caption("Khối theo phòng ban đề xuất (bảng phòng ban → khối từ file định biên). "
                       f"{prev_label}: cùng phạm vi site & phòng ban; khối chỉ có ở năm trước hiện tổng năm nay = 0. "
                       "Tải file chi tiết Khối → Phòng ban → Hạng mục ở tab Nhập / Xuất Excel.")

        # TOP 10 LARGEST CAPEX ITEMS
        # CHARTS ROW 3: Nhóm CNTT & phân loại hạch toán
        if "it_group" in df_filtered.columns:
            c5, c6 = st.columns([1.4, 1])
            with c5:
                st.markdown("##### Ngân sách theo Nhóm CNTT")
                df_grp = (df_filtered.assign(it_group=df_filtered["it_group"].fillna("(Chưa phân nhóm)"))
                          .groupby("it_group")["total_budget"].sum().reset_index().sort_values("total_budget"))
                df_grp["budget_bil"] = df_grp["total_budget"] / 1e9
                fig_grp = px.bar(df_grp, x="budget_bil", y="it_group", orientation="h",
                                 labels={"budget_bil": "Ngân sách (Tỷ VNĐ)", "it_group": "Nhóm CNTT"},
                                 color_discrete_sequence=["#1E4E8C"])
                fig_grp.update_traces(hovertemplate="<b>%{y}</b><br>Ngân sách: %{x:,.2f} tỷ VNĐ")
                fig_grp.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=360)
                plot_chart(fig_grp, use_container_width=True)
            with c6:
                st.markdown("##### Phân loại Hạch toán")
                df_acc = (df_filtered.assign(capex_type=df_filtered.get("capex_type", pd.Series(dtype=str)).fillna("Chưa phân loại"))
                          .groupby("capex_type")["total_budget"].sum().reset_index())
                fig_acc = px.pie(df_acc, names="capex_type", values="total_budget", hole=0.45,
                                 color="capex_type",
                                 color_discrete_map={"CAPEX": "#0F2C59", "CCDC": "#3B82F6", "OPEX": "#F59E0B", "Chưa phân loại": "#CBD5E1"})
                fig_acc.update_traces(textinfo="percent+label", hovertemplate="<b>%{label}</b><br>%{value:,.0f} VNĐ<br>%{percent}")
                fig_acc.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=360, showlegend=False)
                plot_chart(fig_acc, use_container_width=True)
                st.caption("CAPEX: TSCĐ (≥ 30tr/đơn vị) · CCDC: phân bổ dần TK 242 · OPEX: thuê bao, dịch vụ")

        st.markdown("##### Top 10 Hạng mục Ngân sách Đầu tư Lớn nhất")
        top_items = df_filtered.sort_values(by="total_budget", ascending=False).head(10)[
            ["stt", "item_name", "entity", "location", "asset_cat1", "quantity", "unit_price", "total_budget", "project_code"]
        ].copy()

        top_items["unit_price"] = top_items["unit_price"].apply(format_vnd)
        top_items["total_budget"] = top_items["total_budget"].apply(format_vnd)
        top_items.columns = ["STT", "Tên Hạng mục / Tài sản", "Pháp nhân", "Vị trí", "Loại TS", "SL", "Đơn giá", "Tổng ngân sách", "Mã công trình"]

        st.dataframe(top_items, use_container_width=True, hide_index=True)

        # -------------------------------------------------------------
        # PHÂN TÍCH CHIẾN LƯỢC SỐ HÓA & BÁO CÁO ĐIỀU HÀNH 1 TRANG
        # -------------------------------------------------------------
        st.markdown("---")
        exp_p1, exp_p2 = st.columns(2)

        with exp_p1:
            st.markdown("##### 4 Trụ cột Chiến lược Số hóa DDC")
            strat_res = advisor.digital_strategy_breakdown(df_filtered)
            if not strat_res["pie_data"].empty:
                fig_strat = px.pie(
                    strat_res["pie_data"],
                    names="Trụ cột",
                    values="Ngân sách (VNĐ)",
                    hole=0.45,
                    color_discrete_sequence=ui.styles.CHART_COLORS[1:]
                )
                fig_strat.update_traces(textinfo="percent+label", hovertemplate="<b>%{label}</b><br>%{value:,.0f} VNĐ<br>%{percent}")
                fig_strat.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=300, showlegend=False)
                plot_chart(fig_strat, use_container_width=True)
            for p in strat_res["summary"]:
                st.caption(f"{p['icon']} **{p['name']}**: {format_vnd_short(p['budget'])} ({p['pct']:.1f}%) — {p['desc']}")

        with exp_p2:
            st.markdown("##### Báo cáo Điều hành Tóm tắt 1 Trang (Executive Briefing)")
            st.caption("Báo cáo cô đọng chuẩn Ban Tổng Giám đốc & Hội đồng Quản trị: tóm tắt dự toán, 4 quý, Top 5 khoản đầu tư và kết luận của CIO.")
            with st.popover("Xem trước & In Báo cáo Điều hành (A4)", use_container_width=True):
                meta_report = {
                    "budget_year": budget_year,
                    "selected_site": site_label(selected_site),
                    "date": datetime.date.today().strftime("%d/%m/%Y"),
                    "creator_name": current_user.name
                }
                cio_custom_note = st.text_area(
                    "Ghi chú / Khuyến nghị của Giám đốc CNTT (CIO Notes):",
                    value=st.session_state.get("cio_custom_note", ""),
                    placeholder="Nhập khuyến nghị chiến lược trình Ban Tổng Giám Đốc...",
                    key="cio_note_input"
                )
                st.session_state["cio_custom_note"] = cio_custom_note
                briefing_html = advisor.render_executive_briefing_html(df_filtered, master, meta_report, months, cio_notes=cio_custom_note)
                st.components.v1.html(briefing_html, height=650, scrolling=True)
                st.download_button(
                    "⬇️ Tải file Báo cáo Điều hành (.html)",
                    data=briefing_html,
                    file_name=f"DDC_CapEx_{budget_year}_Executive_Briefing.html",
                    mime="text/html",
                    use_container_width=True
                )
