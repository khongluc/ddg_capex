"""CSS giao diện (bảng màu Corporate Navy, tab dạng capsule, thẻ chỉ số...) - nạp 1 lần mỗi lượt chạy."""
import streamlit as st

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

    /* Main Executive Header Banner */
    .main-header {
        background: linear-gradient(135deg, #0A192F 0%, #0F2C59 55%, #173B75 100%);
        padding: 16px 22px;
        border-radius: 14px;
        color: white;
        margin-bottom: 14px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        box-shadow: 0 10px 25px -5px rgba(15, 44, 89, 0.22), 0 8px 10px -6px rgba(15, 44, 89, 0.1);
        position: relative;
        overflow: hidden;
    }

    .main-header::before {
        content: "";
        position: absolute;
        top: -60px;
        right: -60px;
        width: 240px;
        height: 240px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(59, 130, 246, 0.25) 0%, rgba(59, 130, 246, 0) 70%);
        pointer-events: none;
    }

    .header-top-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 12px;
    }

    .header-brand-title {
        display: flex;
        align-items: center;
        gap: 14px;
    }

    .brand-icon-box {
        width: 40px;
        height: 40px;
        border-radius: 10px;
        background: rgba(255, 255, 255, 0.12);
        backdrop-filter: blur(8px);
        border: 1px solid rgba(255, 255, 255, 0.2);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 22px;
    }

    .header-title-text h1 {
        color: #FFFFFF !important;
        font-size: 20px !important;
        font-weight: 800 !important;
        letter-spacing: -0.01em;
        margin: 0 !important;
        padding: 0 !important;
        line-height: 1.25 !important;
    }

    .header-title-text .sub-corp {
        color: #93C5FD;
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-top: 2px;
    }

    .header-meta-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 10px;
        padding-top: 10px;
        border-top: 1px solid rgba(255, 255, 255, 0.12);
    }

    .meta-chip {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(4px);
        border: 1px solid rgba(255, 255, 255, 0.15);
        color: #E2E8F0;
        padding: 4px 11px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 500;
        display: inline-flex;
        align-items: center;
        gap: 5px;
    }

    .meta-chip strong {
        color: #FFFFFF;
    }

    .header-status-pill {
        padding: 6px 14px;
        border-radius: 999px;
        font-size: 12.5px;
        font-weight: 700;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        backdrop-filter: blur(6px);
    }
    .status-pill-draft { background: rgba(59, 130, 246, 0.25); color: #93C5FD; border: 1px solid rgba(59, 130, 246, 0.45); }
    .status-pill-submitted { background: rgba(245, 158, 11, 0.25); color: #FCD34D; border: 1px solid rgba(245, 158, 11, 0.45); }
    .status-pill-approved { background: rgba(16, 185, 129, 0.25); color: #6EE7B7; border: 1px solid rgba(16, 185, 129, 0.45); }
    .status-pill-returned { background: rgba(239, 68, 68, 0.25); color: #FCA5A5; border: 1px solid rgba(239, 68, 68, 0.45); }
    .status-pill-all { background: rgba(255, 255, 255, 0.18); color: #FFFFFF; border: 1px solid rgba(255, 255, 255, 0.35); }

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
        flex-wrap: wrap !important;
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
