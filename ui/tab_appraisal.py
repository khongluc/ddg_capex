"""Thẩm định: dự phóng khấu hao TSCĐ, hiệu quả đầu tư (NPV / IRR / ROI)."""
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from capex_engine import calculate_depreciation_schedule, calculate_project_financials


def render(ctx):
    """Nội dung tab - ctx: giá trị dùng chung của lượt chạy (app.app_context())."""
    budget_year, df_curr, fmt_num, format_vnd = ctx.budget_year, ctx.df_curr, ctx.fmt_num, ctx.format_vnd
    months, plot_chart = ctx.months, ctx.plot_chart

    st.markdown("### Phân tích Khấu hao TSCĐ & Đánh giá Hiệu quả Dự án")

    sub_tab1, sub_tab2 = st.tabs(["Dự phóng Khấu hao TSCĐ", "Thẩm định Hiệu quả Đầu tư (NPV / IRR / ROI)"])

    with sub_tab1:
        st.markdown("#### Dự phóng Khấu hao TSCĐ & Phân bổ CCDC (đường thẳng, Thông tư 45/2013/TT-BTC)")
        st.caption("Chỉ tính TSCĐ (khấu hao) và CCDC (phân bổ dần TK 242) theo thời gian sử dụng của từng nhóm CNTT; "
                   "phần mềm thuê bao, dịch vụ (OPEX) là chi phí trả trước trong năm nên không khấu hao. "
                   "Bắt đầu từ tháng giải ngân đầu tiên; Năm 1 = năm ngân sách (T10 – T9), chỉ tính số tháng còn lại.")

        if df_curr.empty:
            st.info("Chưa có dữ liệu để tính khấu hao.")
        else:
            dep_years = st.slider("Số năm dự phóng khấu hao:", min_value=3, max_value=10, value=5)
            dep_df = calculate_depreciation_schedule(df_curr, num_years=dep_years, months=months)
            if dep_df.empty:
                st.info("Phạm vi đang chọn không có TSCĐ / CCDC cần khấu hao, phân bổ.")

            if not dep_df.empty:
                tot_annual_dep = dep_df["annual_depreciation"].sum()

                d1, d2, d3 = st.columns(3)
                with d1:
                    st.metric(f"Khấu hao & phân bổ năm {budget_year}", format_vnd(dep_df["Năm 1"].sum()))
                with d2:
                    st.metric("Mức đầy đủ / năm (từ năm 2)", format_vnd(tot_annual_dep))
                with d3:
                    base_dep = dep_df["total_budget"].sum()
                    st.metric("Nguyên giá TSCĐ + CCDC", format_vnd(base_dep),
                              f"{fmt_num(tot_annual_dep / base_dep * 100 if base_dep else 0, 1)}%/năm", delta_color="off")

                # Depreciation bar chart by year
                dep_summary_by_year = [dep_df[f"Năm {y}"].sum() / 1e9 for y in range(1, dep_years + 1)]
                fig_dep = px.bar(
                    x=[f"Năm {y}" for y in range(1, dep_years + 1)],
                    y=dep_summary_by_year,
                    labels={"x": "Năm tài chính", "y": "Chi phí Khấu hao (Tỷ VNĐ)"},
                    title="Khấu hao TSCĐ & phân bổ CCDC theo năm tài chính (Tỷ VNĐ)",
                    color_discrete_sequence=["#0F2C59"]
                )
                fig_dep.update_layout(margin=dict(t=30, b=10, l=10, r=10), height=300)
                plot_chart(fig_dep, use_container_width=True)

                # Dataframe of depreciation
                disp_dep = dep_df.copy()
                disp_dep["total_budget"] = disp_dep["total_budget"].apply(format_vnd)
                disp_dep["annual_depreciation"] = disp_dep["annual_depreciation"].apply(format_vnd)
                disp_dep["monthly_depreciation"] = disp_dep["monthly_depreciation"].apply(format_vnd)
                for y in range(1, dep_years + 1):
                    disp_dep[f"Năm {y}"] = disp_dep[f"Năm {y}"].apply(format_vnd)

                disp_dep.columns = ["Tên Tài sản", "Pháp nhân", "Loại", "Nguyên giá", "Số năm KH / PB", "Bắt đầu", "KH năm (đầy đủ)",
                                    "KH tháng"] + [f"Năm {y}" for y in range(1, dep_years + 1)]
                st.dataframe(disp_dep, use_container_width=True, hide_index=True)

    with sub_tab2:
        st.markdown("#### Công cụ Thẩm định Hiệu quả Tài chính Dự án CAPEX")
        st.caption("Đánh giá các chỉ số tài chính: Net Present Value (NPV), Internal Rate of Return (IRR), Thời gian hoàn vốn (Payback Period).")

        total_capex_proj = df_curr["total_budget"].sum() if not df_curr.empty else 10_000_000_000.0

        tc1, tc2 = st.columns(2)
        with tc1:
            in_capex = st.number_input("Tổng vốn đầu tư ban đầu CapEx (VNĐ):", min_value=0.0, value=float(total_capex_proj), step=100_000_000.0, format="%.0f")
            in_savings = st.number_input("Doanh thu tăng thêm / Tiết kiệm chi phí hàng năm (VNĐ):", min_value=0.0, value=float(total_capex_proj * 0.35), step=50_000_000.0, format="%.0f")
            in_opex = st.number_input("Chi phí vận hành tăng thêm hàng năm OpEx (VNĐ):", min_value=0.0, value=float(total_capex_proj * 0.05), step=10_000_000.0, format="%.0f")

        with tc2:
            in_years = st.number_input("Vòng đời dự án đánh giá (Số năm):", min_value=1, max_value=20, value=5, step=1)
            in_discount = st.slider("Tỷ suất chiết khấu (WACC %):", min_value=1.0, max_value=25.0, value=10.0, step=0.5) / 100.0

            fin_result = calculate_project_financials(
                initial_capex=in_capex,
                annual_savings=in_savings,
                opex_annual=in_opex,
                life_years=in_years,
                discount_rate=in_discount
            )

            st.markdown("##### Kết quả Thẩm định")
            res_npv = fin_result["npv"]
            res_irr = fin_result["irr"]
            res_pb = fin_result["payback_years"]
            res_roi = fin_result["roi_pct"]

            if res_npv > 0 and res_irr > (in_discount * 100):
                st.success(f"**DỰ ÁN KHẢ THI CAO** (NPV > 0 và IRR > WACC {in_discount*100:.1f}%)")
            else:
                st.error("**DỰ ÁN CẦN XEM XÉT LẠI** (Hiệu quả chưa đạt tỷ suất kỳ vọng)")

        rc1, rc2, rc3, rc4 = st.columns(4)
        with rc1:
            st.metric("NPV (Hiện giá thuần)", format_vnd(res_npv))
        with rc2:
            st.metric("IRR (Suất sinh lời nội bộ)", f"{res_irr:.1f}%")
        with rc3:
            st.metric("Thời gian Hoàn vốn", f"{res_pb} năm")
        with rc4:
            st.metric("Tỷ suất ROI", f"{res_roi:.1f}%")

        # Cash flow projection chart
        cfs = fin_result["cash_flows"]
        fig_cf = go.Figure()
        fig_cf.add_trace(go.Bar(
            x=[f"Năm {i}" for i in range(len(cfs))],
            y=[cf / 1e9 for cf in cfs],
            marker_color=["#EF4444" if cf < 0 else "#10B981" for cf in cfs],
            name="Dòng tiền ròng (Tỷ VNĐ)",
            hovertemplate="Năm: %{x}<br>Dòng tiền: %{y:,.2f} tỷ VNĐ"
        ))
        fig_cf.update_layout(
            title="Dòng tiền Dự án theo các Năm (Tỷ VNĐ)",
            yaxis_title="Tỷ VNĐ",
            height=280,
            margin=dict(t=35, b=10, l=10, r=10)
        )
        plot_chart(fig_cf, use_container_width=True)
