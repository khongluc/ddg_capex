"""Kịch bản cắt giảm (What-If) và đóng gói mua sắm tập trung."""
import plotly.graph_objects as go
import streamlit as st

import smart_advisor as advisor


def render(ctx):
    """Nội dung tab - ctx: giá trị dùng chung của lượt chạy (app.app_context())."""
    MONEY_FMT, df_curr, format_vnd_short, months = ctx.MONEY_FMT, ctx.df_curr, ctx.format_vnd_short, ctx.months
    plot_chart = ctx.plot_chart

    st.markdown("### 🎯 Mô phỏng Kịch bản Cắt giảm & Đóng gói Gói thầu Mua sắm")
    st.caption("Công cụ phân tích cho Ban Lãnh đạo & Hội đồng Thẩm định: Thử nghiệm kịch bản cắt giảm/hoãn tiến độ What-If "
               "và tự động gom nhóm nhu cầu thành các Gói thầu Mua sắm Tập trung để đàm phán chiết khấu số lượng lớn (Volume Discount).")

    if df_curr.empty:
        st.info("💡 Chưa có dữ liệu CapEx để phân tích kịch bản. Vui lòng nạp hoặc nhập dữ liệu ở tab 'Lập & Nhập liệu CapEx'.")
    else:
        sc_tab1, sc_tab2 = st.tabs([
            "📉 Mô phỏng Kịch bản Cắt giảm & Tối ưu (What-If)",
            "📦 Đóng gói Gói thầu Mua sắm Tập trung (Procurement)"
        ])

        with sc_tab1:
            st.markdown("##### 📉 Mô phỏng Cắt giảm & Điều tiết Tiến độ Ngân sách")
            st.caption("Thử nghiệm tác động khi cắt giảm ngân sách theo các mục tiêu và chiến lược khác nhau.")

            w_col1, w_col2 = st.columns([1.2, 2.8])
            with w_col1:
                cut_pct = st.slider("Mục tiêu cắt giảm (%):", min_value=5, max_value=35, value=10, step=5, key="sc_cut_slider")
                strategy = st.radio(
                    "Chiến lược điều chỉnh:",
                    [
                        ("Bảo vệ cốt lõi (Bảo mật, Tekla/BIM, Server)", "protect_core"),
                        ("Cắt giảm đồng đều theo tỷ lệ", "proportional"),
                        ("Kéo giãn dòng tiền (Dời 40% sang 6 tháng cuối)", "defer_cashflow")
                    ],
                    format_func=lambda x: x[0],
                    key="sc_strat_radio"
                )[1]

            sim_res = advisor.simulate_budget_scenario(df_curr, cut_pct, strategy, months)

            with w_col2:
                sm1, sm2, sm3 = st.columns(3)
                sm1.metric("Ngân sách hiện tại", format_vnd_short(sim_res["original_total"]))
                sm2.metric("Ngân sách kịch bản", format_vnd_short(sim_res["new_total"]))
                sm3.metric("Số tiền tiết giảm", format_vnd_short(sim_res["savings"]),
                           f"-{sim_res['savings_pct']:.1f}%" if sim_res["savings"] > 0 else "0%", delta_color="normal")

            st.markdown("---")
            # Charts & Comparison Table
            sc_c1, sc_c2 = st.columns([1.3, 1.7])
            with sc_c1:
                st.markdown("###### 📅 So sánh Dòng tiền 12 Tháng")
                cf_df = sim_res["cashflow_df"]
                fig_cf = go.Figure()
                fig_cf.add_trace(go.Bar(
                    x=cf_df["Tháng"],
                    y=cf_df["Hiện tại (VNĐ)"] / 1e9,
                    name="Hiện tại (Tỷ VNĐ)",
                    marker_color="#0F2C59"
                ))
                fig_cf.add_trace(go.Bar(
                    x=cf_df["Tháng"],
                    y=cf_df["Kịch bản (VNĐ)"] / 1e9,
                    name="Kịch bản mới (Tỷ VNĐ)",
                    marker_color="#2563EB"
                ))
                fig_cf.update_layout(
                    barmode="group",
                    margin=dict(t=20, b=10, l=10, r=10),
                    height=320,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                plot_chart(fig_cf, use_container_width=True)

            with sc_c2:
                st.markdown("###### 🏛️ Chi tiết Tác động theo Khối / Đơn vị")
                comp_show = sim_res["comparison_df"]
                st.dataframe(
                    comp_show,
                    use_container_width=True,
                    hide_index=True,
                    height=320,
                    column_config={
                        "Hiện tại (VNĐ)": st.column_config.NumberColumn(format=MONEY_FMT),
                        "Kịch bản mới (VNĐ)": st.column_config.NumberColumn(format=MONEY_FMT),
                        "Tiết giảm (VNĐ)": st.column_config.NumberColumn(format=MONEY_FMT),
                        "Tỷ lệ giảm (%)": st.column_config.NumberColumn(format="%.1f%%")
                    }
                )

        with sc_tab2:
            st.markdown("##### 📦 Đóng gói Gói thầu Mua sắm Tập trung (Procurement Sourcing Plan)")
            st.caption("Tự động gom nhu cầu của toàn bộ các nhà máy và phòng ban thành các gói thầu lớn để đàm phán chiết khấu số lượng (Volume Discount).")

            pkgs = advisor.generate_procurement_packages(df_curr)
            if not pkgs:
                st.info("Chưa có hạng mục nào phù hợp để đóng gói thầu.")
            else:
                total_pkg_val = sum(p["total_budget"] for p in pkgs)
                total_est_save = sum(p["est_savings"] for p in pkgs)

                pk_k1, pk_k2, pk_k3 = st.columns(3)
                pk_k1.metric("Tổng giá trị các gói thầu", format_vnd_short(total_pkg_val))
                pk_k2.metric("Số gói thầu mua sắm", f"{len(pkgs)} gói")
                pk_k3.metric("Ước tính chiết khấu kỳ vọng", format_vnd_short(total_est_save), "Tiết kiệm 5% - 8%", delta_color="normal")

                st.markdown("---")
                for pkg in pkgs:
                    with st.expander(f"{pkg['icon']} **{pkg['name']}** — {format_vnd_short(pkg['total_budget'])} ({pkg['total_qty']} thiết bị/bản quyền)", expanded=False):
                        pc1, pc2, pc3 = st.columns([1.5, 1, 1])
                        with pc1:
                            st.write(f"**Mô tả:** {pkg['desc']}")
                            st.write(f"**Thiết bị tiêu biểu:** {', '.join(pkg['top_items'])}")
                        with pc2:
                            st.write(f"**Thời gian đặt hàng (Lead time):** ~{pkg['lead_time_days']} ngày")
                            st.write(f"**Chiết khấu mục tiêu:** {pkg['target_rebate']}")
                        with pc3:
                            st.metric("Tiết kiệm dự kiến", format_vnd_short(pkg["est_savings"]))

                        sub_df = pkg["rows"][["item_name", "location", "quantity", "unit_price", "total_budget", "capex_type"]].copy()
                        sub_df.columns = ["Tên thiết bị / Hạng mục", "Vị trí", "SL", "Đơn giá", "Thành tiền", "Loại"]
                        st.dataframe(
                            sub_df,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Đơn giá": st.column_config.NumberColumn(format=MONEY_FMT),
                                "Thành tiền": st.column_config.NumberColumn(format=MONEY_FMT)
                            }
                        )
