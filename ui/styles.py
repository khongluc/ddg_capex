"""CSS giao diện (bảng màu Corporate Navy, tab dạng capsule, thẻ chỉ số...) - nạp 1 lần mỗi lượt chạy."""
import streamlit as st

# Bộ màu biểu đồ dùng chung: navy -> xanh -> xanh ngọc -> vàng đất -> xám (đậm trước, nhạt sau)
CHART_COLORS = ["#0F2C59", "#2563EB", "#0EA5A4", "#D97706", "#64748B", "#93C5FD", "#7C3AED", "#DC2626",
                "#16A34A", "#CBD5E1"]

CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* Ẩn thanh công cụ của Streamlit / Streamlit Cloud (Fork, GitHub, menu ⋮, Deploy) - không gợi ý mã nguồn */
    [data-testid="stToolbar"], [data-testid="stToolbarActions"], [data-testid="stMainMenu"],
    [data-testid="stAppDeployButton"], .stDeployButton, #MainMenu,
    [data-testid="stDecoration"] { display: none !important; visibility: hidden !important; }
    a[href*="github.com"] { display: none !important; }

    /* Bỏ dải trắng phía trên trang, luôn hiện nút thu / mở thanh bên */
    [data-testid="stHeader"] { background: transparent !important; }
    [data-testid="stMainBlockContainer"], .block-container { padding-top: 2.4rem !important; padding-bottom: 3rem !important; }
    [data-testid="stSidebarCollapseButton"] { display: flex !important; }
    [data-testid="stSidebarUserContent"] { padding-top: 0.5rem !important; }

    html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        -webkit-font-smoothing: antialiased;
    }

    [data-testid="stAppViewContainer"] {
        background-color: #F8FAFC !important;
    }

    /* Tùy chỉnh thanh cuộn hiện đại */
    ::-webkit-scrollbar {
        width: 6px;
        height: 6px;
    }
    ::-webkit-scrollbar-track {
        background: transparent;
    }
    ::-webkit-scrollbar-thumb {
        background: #CBD5E1;
        border-radius: 999px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #94A3B8;
    }

    /* Sidebar Custom Styling */
    [data-testid="stSidebar"] {
        background: #FFFFFF !important;
        border-right: 1px solid #E2E8F0 !important;
        box-shadow: 2px 0 12px rgba(15, 23, 42, 0.03) !important;
    }

    .user-profile-card {
        background: linear-gradient(135deg, #F8FAFC 0%, #F1F5F9 100%);
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 12px 14px;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    }

    .user-avatar-circle {
        width: 38px;
        height: 38px;
        border-radius: 50%;
        background: linear-gradient(135deg, #1E40AF 0%, #3B82F6 100%);
        color: #FFFFFF;
        font-weight: 700;
        font-size: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 2px 6px rgba(37, 99, 235, 0.25);
        flex-shrink: 0;
    }

    .user-info-text {
        flex-grow: 1;
        overflow: hidden;
    }

    .user-name {
        font-weight: 700;
        font-size: 13.5px;
        color: #0F2C59;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .user-email {
        font-size: 11.5px;
        color: #64748B;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .role-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        margin-top: 4px;
    }
    .role-badge-admin { background: #EEF2FF; color: #4F46E5; border: 1px solid #C7D2FE; }
    .role-badge-it { background: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE; }
    .role-badge-dept { background: #FEF3C7; color: #B45309; border: 1px solid #FDE68A; }
    .role-badge-viewer { background: #F1F5F9; color: #475569; border: 1px solid #E2E8F0; }

    /* Đầu trang: thẻ sáng, viền nhấn navy bên trái */
    .main-header {
        background: #FFFFFF;
        padding: 14px 20px;
        border-radius: 12px;
        color: #0F172A;
        margin-bottom: 12px;
        border: 1px solid #E2E8F0;
        border-left: 4px solid #1E40AF;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
    }
    .header-top-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
    .header-brand-title { display: flex; align-items: center; gap: 14px; }
    .header-title-text h1 {
        color: #0F2C59 !important;
        font-size: 19px !important;
        font-weight: 750 !important;
        letter-spacing: -0.01em;
        margin: 0 !important;
        padding: 0 !important;
        line-height: 1.3 !important;
    }
    .header-title-text .sub-corp { color: #64748B; font-size: 12px; font-weight: 500; margin-top: 2px; }
    .header-meta-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .meta-chip {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        color: #64748B;
        padding: 3px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 500;
    }
    .meta-chip strong { color: #0F172A; font-weight: 600; }
    .header-status-pill {
        padding: 5px 12px;
        border-radius: 999px;
        font-size: 12.5px;
        font-weight: 650;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .header-status-pill::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
    .status-pill-draft { background: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE; }
    .status-pill-submitted { background: #FFFBEB; color: #B45309; border: 1px solid #FDE68A; }
    .status-pill-approved { background: #ECFDF5; color: #047857; border: 1px solid #A7F3D0; }
    .status-pill-returned { background: #FEF2F2; color: #B91C1C; border: 1px solid #FECACA; }
    .status-pill-all { background: #F1F5F9; color: #334155; border: 1px solid #E2E8F0; }

    /* Tiêu đề mục: gọn, cùng 1 màu */
    [data-testid="stMarkdownContainer"] h3 { font-size: 1.25rem !important; font-weight: 700 !important; color: #0F172A !important; }
    [data-testid="stMarkdownContainer"] h4 { font-size: 1.05rem !important; font-weight: 650 !important; color: #0F2C59 !important; }
    [data-testid="stMarkdownContainer"] h5 { font-size: 0.95rem !important; font-weight: 650 !important; color: #334155 !important; }

    /* Executive KPI Cards */
    .kpi-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 16px 18px;
        min-height: 150px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;
    }

    .kpi-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 10px 24px -4px rgba(15, 44, 89, 0.08), 0 4px 6px -2px rgba(15, 44, 89, 0.03);
        border-color: #CBD5E1;
    }

    .kpi-card-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 8px;
        margin-bottom: 10px;
    }

    .kpi-title {
        color: #64748B;
        font-size: 11.5px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        line-height: 1.35;
        margin: 0;
        min-width: 0;
    }

    .kpi-icon-badge {
        width: 34px;
        height: 34px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 17px;
        flex-shrink: 0;
    }
    .kpi-icon-blue { background: #EFF6FF; color: #1D4ED8; border: 1px solid #DBEAFE; }
    .kpi-icon-emerald { background: #ECFDF5; color: #047857; border: 1px solid #A7F3D0; }
    .kpi-icon-amber { background: #FFFBEB; color: #B45309; border: 1px solid #FDE68A; }
    .kpi-icon-purple { background: #FAF5FF; color: #6D28D9; border: 1px solid #E9D5FF; }

    .kpi-value {
        color: #0F172A;
        font-size: 26px;
        font-weight: 800;
        letter-spacing: -0.02em;
        line-height: 1.15;
        margin-bottom: 6px;
    }

    .kpi-unit {
        font-size: 14px;
        font-weight: 600;
        color: #475569;
    }

    .kpi-sub {
        font-size: 12px;
        color: #64748B;
        font-weight: 500;
    }

    .kpi-pill {
        display: inline-block;
        max-width: 100%;
        overflow-wrap: anywhere;
        line-height: 1.4;
        padding: 2px 8px;
        border-radius: 6px;
        font-size: 11.5px;
        font-weight: 600;
    }
    .kpi-pill-blue { background: #F0F7FF; color: #1E40AF; }
    .kpi-pill-emerald { background: #ECFDF5; color: #047857; }
    .kpi-pill-amber { background: #FFFBEB; color: #B45309; }
    .kpi-pill-purple { background: #F5F3FF; color: #6D28D9; }

    .badge-code {
        background: #EFF6FF;
        color: #1D4ED8;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
        font-family: monospace;
    }

    /* Segmented Capsule Pill Tabs */
    .stTabs [data-baseweb="tab-list"] {
        background: #EEF2F6 !important;
        padding: 4px !important;
        border-radius: 12px !important;
        gap: 4px !important;
        border-bottom: none !important;
        box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.04) !important;
        margin-bottom: 16px !important;
        flex-wrap: nowrap !important;
        overflow-x: auto !important;
        scrollbar-width: thin;
    }
    .stTabs [data-baseweb="tab-highlight"] { display: none !important; }

    .stTabs [data-baseweb="tab"] {
        height: 36px !important;
        padding: 0 10px !important;
        font-size: 13px !important;
        font-weight: 600 !important;
        color: #475569 !important;
        border-radius: 8px !important;
        border: none !important;
        background: transparent !important;
        white-space: nowrap !important;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }

    .stTabs [data-baseweb="tab"]:hover {
        color: #0F2C59 !important;
        background: rgba(255, 255, 255, 0.75) !important;
    }

    .stTabs [aria-selected="true"] {
        background: #FFFFFF !important;
        color: #1E40AF !important;
        box-shadow: 0 2px 6px rgba(15, 44, 89, 0.12), 0 1px 2px rgba(0, 0, 0, 0.04) !important;
        font-weight: 700 !important;
    }

    .stTabs [data-baseweb="tab-border"] {
        display: none !important;
    }

    /* Toast Notification Styling */
    [data-testid="stToast"] {
        background: #FFFFFF !important;
        border: 1px solid #CBD5E1 !important;
        border-left: 4px solid #1E40AF !important;
        border-radius: 10px !important;
        box-shadow: 0 10px 25px -5px rgba(15, 44, 89, 0.15), 0 8px 10px -6px rgba(15, 44, 89, 0.08) !important;
        font-weight: 500 !important;
        color: #0F172A !important;
    }

    /* Modern Primary & Secondary Buttons */
    .stButton > button[kind="primary"], [data-testid="baseButton-primary"] {
        background: linear-gradient(135deg, #1E40AF 0%, #2563EB 100%) !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        padding: 8px 18px !important;
        box-shadow: 0 2px 6px rgba(37, 99, 235, 0.25) !important;
        transition: all 0.2s ease !important;
    }

    .stButton > button[kind="primary"]:hover, [data-testid="baseButton-primary"]:hover {
        background: linear-gradient(135deg, #1E3A8A 0%, #1D4ED8 100%) !important;
        box-shadow: 0 4px 14px rgba(37, 99, 235, 0.38) !important;
        transform: translateY(-1px);
    }

    .stButton > button[kind="secondary"], [data-testid="baseButton-secondary"] {
        background: #FFFFFF !important;
        color: #1E293B !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        padding: 8px 18px !important;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03) !important;
        transition: all 0.2s ease !important;
    }

    .stButton > button[kind="secondary"]:hover, [data-testid="baseButton-secondary"]:hover {
        border-color: #94A3B8 !important;
        background: #F8FAFC !important;
        color: #0F172A !important;
    }

    /* Auto Metric Card Styling */
    [data-testid="stMetric"] {
        background: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 12px !important;
        padding: 14px 18px !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03) !important;
        transition: all 0.2s ease !important;
    }
    [data-testid="stMetric"]:hover {
        border-color: #CBD5E1 !important;
        box-shadow: 0 4px 12px rgba(15, 44, 89, 0.06) !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 11.5px !important;
        font-weight: 700 !important;
        color: #64748B !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 20px !important;
        font-weight: 800 !important;
        color: #0F2C59 !important;
        letter-spacing: -0.01em !important;
    }

    /* Expanders & DataFrames */
    [data-testid="stExpander"] {
        background: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 12px !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02) !important;
        margin-bottom: 12px !important;
    }

    [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
        border: 1px solid #E2E8F0 !important;
        border-radius: 10px !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02) !important;
        background: #FFFFFF !important;
    }
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)
