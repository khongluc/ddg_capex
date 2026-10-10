"""
smart_advisor.py
Module Phân tích Thông minh, Kiểm định Rủi ro, Kịch bản Cắt giảm,
Đóng gói Mua sắm và Báo cáo Điều hành 1 Trang cho Hệ thống CapEx DDC.
"""
from typing import Dict, List, Any, Tuple, Optional
import pandas as pd
import numpy as np
import datetime
import html as _html

# ---------------------------------------------------------------------
# 1. 4 TRỤ CỘT CHIẾN LƯỢC SỐ HÓA DDC (DIGITAL STRATEGY PILLARS)
# ---------------------------------------------------------------------
PILLAR_PRODUCTION = "factory"        # Sản xuất & Vận hành Nhà máy
PILLAR_ENGINEERING = "engineering"    # Thiết kế & Kỹ thuật Kết cấu thép
PILLAR_INFRA_SECURITY = "security"   # An ninh mạng & Hạ tầng Số Cốt lõi
PILLAR_GOVERNANCE = "governance"     # Quản trị Doanh nghiệp & Môi trường làm việc số

PILLAR_META = {
    PILLAR_PRODUCTION: {
        "name": "Sản xuất & Vận hành Nhà máy",
        "icon": "🏭",
        "desc": "Camera an ninh xưởng, chấm công, MES, máy tính hiện trường & quản lý sản xuất",
        "groups": ["IT06"],
        "color": "#0284C7"
    },
    PILLAR_ENGINEERING: {
        "name": "Thiết kế & Kỹ thuật Kết cấu thép",
        "icon": "📐",
        "desc": "Bản quyền Tekla Structures, AutoCAD, BIM, Robot Structural, máy trạm đồ họa",
        "groups": ["IT10"],
        "color": "#D97706"
    },
    PILLAR_INFRA_SECURITY: {
        "name": "An ninh mạng & Hạ tầng Số Cốt lõi",
        "icon": "🛡️",
        "desc": "Máy chủ Server, lưu trữ SAN, Firewall, hệ thống mạng Wifi/LAN & Data Center",
        "groups": ["IT03", "IT04", "IT05", "IT08"],
        "color": "#DC2626"
    },
    PILLAR_GOVERNANCE: {
        "name": "Quản trị & Môi trường Làm việc Số",
        "icon": "💼",
        "desc": "Laptop, PC văn phòng, máy in, ERP, Office 365, Cloud & đường truyền viễn thông",
        "groups": ["IT01", "IT02", "IT07", "IT09", "IT11", "IT12", "IT13", "IT14", "IT15"],
        "color": "#16A34A"
    }
}


def classify_pillar(row: Dict[str, Any]) -> str:
    """Xác định dòng ngân sách thuộc trụ cột chiến lược số hóa nào."""
    grp = str(row.get("it_group") or row.get("catalog_group") or "")[:4].upper()
    name = str(row.get("item_name") or "").lower()
    
    # Ưu tiên theo tên hạng mục đặc thù
    if any(k in name for k in ["tekla", "bim", "autocad", "revit", "máy trạm", "workstation", "đồ họa"]):
        return PILLAR_ENGINEERING
    if any(k in name for k in ["camera", "chấm công", "nhà xưởng", "sản xuất", "xưởng"]):
        return PILLAR_PRODUCTION
    if any(k in name for k in ["firewall", "tường lửa", "server", "máy chủ", "backup", "switch", "ups", "an ninh"]):
        return PILLAR_INFRA_SECURITY
        
    for p_key, meta in PILLAR_META.items():
        if grp in meta["groups"]:
            return p_key
    return PILLAR_GOVERNANCE


def digital_strategy_breakdown(df: pd.DataFrame) -> Dict[str, Any]:
    """Phân bổ ngân sách theo 4 Trụ cột Chiến lược Số hóa."""
    if df is None or df.empty:
        return {"summary": [], "total": 0.0, "pie_data": pd.DataFrame()}
        
    d = df.copy()
    d["pillar"] = d.apply(lambda r: classify_pillar(r.to_dict()), axis=1)
    d["total_budget"] = pd.to_numeric(d.get("total_budget", 0), errors="coerce").fillna(0.0)
    
    total = float(d["total_budget"].sum())
    summary = []
    
    for p_key, meta in PILLAR_META.items():
        part = d[d["pillar"] == p_key]
        val = float(part["total_budget"].sum())
        pct = (val / total * 100.0) if total > 0 else 0.0
        n_items = len(part)
        summary.append({
            "key": p_key,
            "name": meta["name"],
            "icon": meta["icon"],
            "desc": meta["desc"],
            "budget": val,
            "pct": pct,
            "items_count": n_items,
            "color": meta["color"]
        })
        
    pie_df = pd.DataFrame([{
        "Trụ cột": f"{m['icon']} {m['name']}",
        "Ngân sách (VNĐ)": m["budget"],
        "Tỷ trọng (%)": m["pct"]
    } for m in summary if m["budget"] > 0])
    
    return {"summary": summary, "total": total, "pie_data": pie_df}


# ---------------------------------------------------------------------
# 2. KIỂM ĐỊNH RỦI RO & ĐIỂM SỨC KHỎE NGÂN SÁCH (SMART AUDIT & HEALTH SCORE)
# ---------------------------------------------------------------------
SEV_CRITICAL = "CRITICAL"  # Đỏ - Cần xử lý trước khi duyệt
SEV_WARNING = "WARNING"    # Vàng - Lưu ý cần giải trình
SEV_INFO = "INFO"          # Xanh - Khuyến nghị tối ưu

def audit_budget(df: pd.DataFrame, master: Dict[str, Any], months: List[str]) -> Dict[str, Any]:
    """
    Rà soát toàn diện hồ sơ ngân sách và tính Điểm Sức Khỏe (Health Score 0-100).
    Kiểm tra 5 tiêu chí:
    1. Phân kỳ dòng tiền 100%
    2. Căn cứ giải trình các dòng phát sinh mới / dùng chung
    3. Biên độ đơn giá so với giá chuẩn danh mục
    4. Tuân thủ phân loại kế toán (TSCĐ >= 30tr, dịch vụ -> OPEX)
    5. Cảnh báo dồn ứ áp lực dòng tiền theo tháng / quý
    """
    if df is None or df.empty:
        return {
            "score": 100,
            "status_label": "Chưa có dữ liệu",
            "status_color": "#64748B",
            "issues": [],
            "metrics": {"total_items": 0, "critical": 0, "warning": 0, "info": 0}
        }

    issues: List[Dict[str, Any]] = []
    score = 100
    
    # 1. Kiểm tra phân kỳ tỷ lệ
    if "pct_valid" in df.columns:
        invalid_pct = df[~df["pct_valid"].fillna(False).astype(bool)]
        if not invalid_pct.empty:
            count = len(invalid_pct)
            deduct = min(30, count * 10)
            score -= deduct
            issues.append({
                "severity": SEV_CRITICAL,
                "title": f"Có {count} hạng mục tổng phân kỳ 12 tháng khác 100%",
                "desc": "Tổng tỷ lệ phân kỳ của các tháng chưa đạt 100%, gây sai lệch dòng tiền giải ngân.",
                "action": "Chuyển sang Tab Nhập liệu, kiểm tra các dòng bị báo đỏ ở cột Phân kỳ.",
                "count": count
            })

    # 2. Kiểm tra căn cứ lý do phát sinh mới & hạ tầng dùng chung
    need_types = df.get("need_type", pd.Series("", index=df.index)).fillna("")
    need_reasons = df.get("need_reason", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    
    # Phát sinh mới hoặc Hạ tầng dùng chung cần lý do
    missing_reason_mask = need_types.isin(["Phát sinh mới", "Hạ tầng dùng chung"]) & (need_reasons == "")
    missing_reasons = df[missing_reason_mask]
    if not missing_reasons.empty:
        count = len(missing_reasons)
        deduct = min(20, count * 5)
        score -= deduct
        issues.append({
            "severity": SEV_CRITICAL,
            "title": f"Có {count} hạng mục 'Phát sinh mới' / 'Dùng chung' chưa ghi lý do",
            "desc": "Theo quy chế tài chính DDC, các khoản ngoài định biên chuẩn bắt buộc phải có căn cứ thẩm định.",
            "action": "Bổ sung cột 'Lý do phát sinh / căn cứ trang bị' trước khi nộp duyệt.",
            "count": count
        })

    # 3. Kiểm tra biên độ giá so với danh mục chuẩn
    catalog_items = {it.get("name", "").strip().lower(): float(it.get("price", 0)) for it in master.get("standard_items", [])}
    price_high_count = 0
    price_low_count = 0
    
    for _, r in df.iterrows():
        name = str(r.get("item_name", "")).strip().lower()
        price = float(r.get("unit_price", 0) or 0)
        ref_price = catalog_items.get(name, 0.0)
        if ref_price > 0 and price > 0:
            if price > ref_price * 1.25:
                price_high_count += 1
            elif price < ref_price * 0.75:
                price_low_count += 1
                
    if price_high_count > 0:
        deduct = min(15, price_high_count * 3)
        score -= deduct
        issues.append({
            "severity": SEV_WARNING,
            "title": f"Có {price_high_count} hạng mục đơn giá cao hơn 25% so với danh mục chuẩn",
            "desc": "Đơn giá dự toán vượt biên độ tham chiếu của tập đoàn, cần kiểm tra cấu hình hoặc đính kèm báo giá.",
            "action": "Rà soát lại đơn giá hoặc giải trình lý do chênh lệch (cấu hình cao cấp / biến động thị trường).",
            "count": price_high_count
        })

    # 4. Kiểm tra phân loại kế toán (TSCĐ dưới 30 triệu)
    capex_types = df.get("capex_type", pd.Series("", index=df.index)).fillna("")
    unit_prices = pd.to_numeric(df.get("unit_price", 0), errors="coerce").fillna(0.0)
    
    misclass_tscd = df[(capex_types == "CAPEX") & (unit_prices < 30_000_000) & (unit_prices > 0)]
    if not misclass_tscd.empty:
        count = len(misclass_tscd)
        deduct = min(15, count * 3)
        score -= deduct
        issues.append({
            "severity": SEV_WARNING,
            "title": f"Có {count} hạng mục đơn giá < 30 triệu đang phân loại là TSCĐ (CAPEX)",
            "desc": "Theo TT45/2013/TT-BTC, tài sản có nguyên giá dưới 30 triệu đồng phải hạch toán là Công cụ dụng cụ (CCDC).",
            "action": "Chuyển phân loại sang CCDC để phản ánh đúng chuẩn mực kế toán tài chính.",
            "count": count
        })

    # 5. Kiểm tra áp lực dồn ứ dòng tiền
    val_cols = [f"val_{m}" for m in months if f"val_{m}" in df.columns]
    tot_budget = float(df.get("total_budget", pd.Series(0)).sum())
    
    if val_cols and tot_budget > 0:
        m_sums = [float(df[c].sum()) for c in val_cols]
        max_month_val = max(m_sums) if m_sums else 0
        max_month_idx = m_sums.index(max_month_val) if m_sums else 0
        max_month_pct = (max_month_val / tot_budget * 100)
        
        if max_month_pct > 35.0:
            score -= 10
            month_name = months[max_month_idx]
            issues.append({
                "severity": SEV_WARNING,
                "title": f"Dòng tiền tập trung quá lớn vào {month_name} ({max_month_pct:.1f}% cả năm)",
                "desc": "Tháng này chiếm trên 35% tổng vốn đầu tư, có thể gây căng thẳng thanh khoản hoặc tắc nghẽn giải ngân.",
                "action": f"Cân nhắc giãn tiến độ giải ngân của {month_name} sang các tháng lân cận.",
                "count": 1
            })

    score = max(0, min(100, score))
    
    if score >= 90:
        s_lbl = "Xuất sắc (Sẵn sàng phê duyệt)"
        s_col = "#059669"
    elif score >= 75:
        s_lbl = "Khá (Cần hoàn thiện một số lưu ý)"
        s_col = "#D97706"
    else:
        s_lbl = "Cần chỉnh sửa (Nhiều rủi ro / sai sót)"
        s_col = "#DC2626"

    crit_cnt = sum(1 for x in issues if x["severity"] == SEV_CRITICAL)
    warn_cnt = sum(1 for x in issues if x["severity"] == SEV_WARNING)
    info_cnt = sum(1 for x in issues if x["severity"] == SEV_INFO)

    return {
        "score": score,
        "status_label": s_lbl,
        "status_color": s_col,
        "issues": issues,
        "metrics": {
            "total_items": len(df),
            "critical": crit_cnt,
            "warning": warn_cnt,
            "info": info_cnt
        }
    }


# ---------------------------------------------------------------------
# 3. KỊCH BẢN CẮT GIẢM & TỐI ƯU HÓA NGÂN SÁCH (WHAT-IF SCENARIOS)
# ---------------------------------------------------------------------
def simulate_budget_scenario(df: pd.DataFrame, cut_target_pct: float, strategy: str, months: List[str]) -> Dict[str, Any]:
    """
    Mô phỏng kịch bản cắt giảm hoặc điều chỉnh ngân sách.
    Strategy:
    - 'protect_core': Bảo vệ 100% hạng mục lõi (Phần mềm kỹ thuật Tekla/BIM, Bảo mật, Server),
                      cắt giảm các hạng mục mua sắm văn phòng, tiện ích.
    - 'proportional': Cắt giảm đồng đều theo tỷ lệ trên toàn bộ các hạng mục.
    - 'defer_cashflow': Giữ nguyên quy mô nhưng dời giải ngân từ 6 tháng đầu năm sang 6 tháng cuối năm.
    """
    if df is None or df.empty:
        return {"original_total": 0.0, "new_total": 0.0, "savings": 0.0, "diff_df": pd.DataFrame()}

    orig_df = df.copy()
    orig_total = float(orig_df["total_budget"].sum())
    sim_df = orig_df.copy()
    
    if strategy == "protect_core":
        # Xác định nhóm lõi cần bảo vệ
        def is_protected(r):
            p = classify_pillar(r)
            return p in [PILLAR_ENGINEERING, PILLAR_INFRA_SECURITY]
            
        protected_mask = sim_df.apply(is_protected, axis=1)
        unprotected_total = float(sim_df.loc[~protected_mask, "total_budget"].sum())
        target_savings = orig_total * (cut_target_pct / 100.0)
        
        if unprotected_total > 0 and target_savings > 0:
            cut_rate_unprotected = min(0.60, target_savings / unprotected_total)
            sim_df.loc[~protected_mask, "total_budget"] *= (1.0 - cut_rate_unprotected)
            # Cập nhật các cột tháng tương ứng
            val_cols = [f"val_{m}" for m in months if f"val_{m}" in sim_df.columns]
            for vc in val_cols:
                sim_df.loc[~protected_mask, vc] *= (1.0 - cut_rate_unprotected)

    elif strategy == "proportional":
        rate = 1.0 - (cut_target_pct / 100.0)
        sim_df["total_budget"] *= rate
        val_cols = [f"val_{m}" for m in months if f"val_{m}" in sim_df.columns]
        for vc in val_cols:
            sim_df[vc] *= rate

    elif strategy == "defer_cashflow":
        # Giữ nguyên tổng tiền, dời 50% giải ngân 6 tháng đầu sang 6 tháng cuối
        first_6 = [f"val_{m}" for m in months[:6] if f"val_{m}" in sim_df.columns]
        last_6 = [f"val_{m}" for m in months[6:] if f"val_{m}" in sim_df.columns]
        if first_6 and last_6:
            shifted_pool = 0.0
            for col in first_6:
                half = sim_df[col] * 0.40
                sim_df[col] -= half
                shifted_pool += half.sum()
            add_per_m = shifted_pool / len(last_6)
            for col in last_6:
                sim_df[col] += add_per_m / len(sim_df)

    new_total = float(sim_df["total_budget"].sum())
    savings = orig_total - new_total
    
    # Bảng phân tích so sánh trước vs sau
    comp_rows = []
    divs = orig_df["division"].fillna("Chưa phân loại").unique() if "division" in orig_df.columns else ["Toàn bộ"]
    for div in divs:
        o_val = float(orig_df[orig_df["division"] == div]["total_budget"].sum()) if "division" in orig_df.columns else orig_total
        n_val = float(sim_df[sim_df["division"] == div]["total_budget"].sum()) if "division" in sim_df.columns else new_total
        diff = o_val - n_val
        comp_rows.append({
            "Khối / Đơn vị": div,
            "Hiện tại (VNĐ)": o_val,
            "Kịch bản mới (VNĐ)": n_val,
            "Tiết giảm (VNĐ)": diff,
            "Tỷ lệ giảm (%)": (diff / o_val * 100) if o_val > 0 else 0.0
        })
        
    comp_df = pd.DataFrame(comp_rows).sort_values(by="Hiện tại (VNĐ)", ascending=False)
    
    # So sánh dòng tiền 12 tháng
    val_cols = [f"val_{m}" for m in months if f"val_{m}" in orig_df.columns]
    m_orig = [float(orig_df[c].sum()) for c in val_cols]
    m_sim = [float(sim_df[c].sum()) for c in val_cols]
    
    cashflow_df = pd.DataFrame({
        "Tháng": months[:len(val_cols)],
        "Hiện tại (VNĐ)": m_orig,
        "Kịch bản (VNĐ)": m_sim,
        "Chênh lệch": [s - o for o, s in zip(m_orig, m_sim)]
    })

    return {
        "original_total": orig_total,
        "new_total": new_total,
        "savings": savings,
        "savings_pct": (savings / orig_total * 100) if orig_total > 0 else 0.0,
        "comparison_df": comp_df,
        "cashflow_df": cashflow_df
    }


# ---------------------------------------------------------------------
# 4. ĐÓNG GÓI GÓI THẦU MUA SẮM TẬP TRUNG (PROCUREMENT PACKAGING)
# ---------------------------------------------------------------------
PACKAGE_DEFS = [
    {
        "id": "PKG-ENDUSER",
        "name": "Gói 1: Thiết bị Đầu cuối & Tin học Văn phòng",
        "icon": "💻",
        "desc": "Máy tính để bàn, Laptop, Màn hình, Máy in & Phụ kiện",
        "groups": ["IT01", "IT02", "IT13"],
        "target_rebate": "5% - 8%",
        "lead_time_days": 30
    },
    {
        "id": "PKG-SOFTWARE",
        "name": "Gói 2: Bản quyền Phần mềm Thiết kế & Hệ thống",
        "icon": "💿",
        "desc": "Tekla Structures, Autodesk AEC/BIM, Microsoft Office 365, ERP",
        "groups": ["IT09", "IT10", "IT11"],
        "target_rebate": "8% - 12%",
        "lead_time_days": 45
    },
    {
        "id": "PKG-INFRA",
        "name": "Gói 3: Hạ tầng Máy chủ, Lưu trữ & Mạng Doanh nghiệp",
        "icon": "🌐",
        "desc": "Server Dell/HP, Lưu trữ SAN/NAS, Switch Cisco, Tường lửa Firewall, UPS",
        "groups": ["IT03", "IT04", "IT05", "IT08"],
        "target_rebate": "7% - 10%",
        "lead_time_days": 60
    },
    {
        "id": "PKG-AUDIOVISUAL",
        "name": "Gói 4: Thiết bị Phòng họp & An ninh Giám sát Nhà máy",
        "icon": "🎥",
        "desc": "Hệ thống họp trực tuyến Polycom/Yealink, Camera xưởng, Kiểm soát ra vào",
        "groups": ["IT06", "IT07"],
        "target_rebate": "5% - 7%",
        "lead_time_days": 30
    },
    {
        "id": "PKG-SERVICES",
        "name": "Gói 5: Dịch vụ Cloud, Đường truyền Viễn thông & Tư vấn",
        "icon": "☁️",
        "desc": "Kênh truyền Internet Leased Line, Thuê chỗ đặt Server, Tư vấn ISO 27001",
        "groups": ["IT12", "IT14", "IT15"],
        "target_rebate": "3% - 5%",
        "lead_time_days": 20
    }
]


def generate_procurement_packages(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Gom toàn bộ nhu cầu trên toàn hệ thống thành các gói thầu lớn."""
    if df is None or df.empty:
        return []

    d = df.copy()
    d["total_budget"] = pd.to_numeric(d.get("total_budget", 0), errors="coerce").fillna(0.0)
    d["quantity"] = pd.to_numeric(d.get("quantity", 0), errors="coerce").fillna(0)
    
    results = []
    
    for pkg in PACKAGE_DEFS:
        # Lọc các dòng thuộc nhóm
        mask = d.apply(lambda r: any(str(r.get("it_group") or r.get("catalog_group") or "").startswith(g) for g in pkg["groups"]), axis=1)
        part = d[mask]
        
        if not part.empty:
            tot_val = float(part["total_budget"].sum())
            tot_qty = int(part["quantity"].sum())
            item_names = part["item_name"].dropna().unique().tolist()
            depts = part["dept_proposing"].dropna().unique().tolist() if "dept_proposing" in part.columns else []
            
            # Ước lượng tiết kiệm số lượng lớn (Volume Discount trung bình 6%)
            est_savings = tot_val * 0.06
            
            results.append({
                "id": pkg["id"],
                "name": pkg["name"],
                "icon": pkg["icon"],
                "desc": pkg["desc"],
                "target_rebate": pkg["target_rebate"],
                "lead_time_days": pkg["lead_time_days"],
                "total_budget": tot_val,
                "total_qty": tot_qty,
                "items_count": len(part),
                "depts_count": len(depts),
                "est_savings": est_savings,
                "top_items": item_names[:4],
                "rows": part
            })

    return results


# ---------------------------------------------------------------------
# 5. BÁO CÁO TÓM TẮT ĐIỀU HÀNH 1 TRANG (EXECUTIVE 1-PAGER BRIEFING)
# ---------------------------------------------------------------------
def render_executive_briefing_html(
    df: pd.DataFrame,
    master: Dict[str, Any],
    meta: Dict[str, Any],
    months: List[str],
    cio_notes: str = ""
) -> str:
    """Tạo mã HTML hoàn chỉnh cho Báo cáo Tóm tắt Điều hành 1 Trang (chuẩn in ấn A4)."""
    if df is None or df.empty:
        return "<p>Chưa có dữ liệu để lập báo cáo điều hành.</p>"

    year = meta.get("budget_year", "2026")
    site_lbl = meta.get("selected_site", "Toàn tập đoàn")
    plan_date = meta.get("date", datetime.date.today().strftime("%Y-%m-%d"))
    creator = meta.get("creator_name", "Phòng CNTT & CĐS")
    
    tot_budget = float(df["total_budget"].sum()) if "total_budget" in df.columns else 0.0
    tot_items = len(df)
    tot_qty = int(df["quantity"].sum()) if "quantity" in df.columns else 0
    
    ct = df.get("capex_type", pd.Series(index=df.index, dtype=object)).fillna("Chưa phân loại")
    tot_capex = float(df.loc[ct == "CAPEX", "total_budget"].sum())
    tot_ccdc = float(df.loc[ct == "CCDC", "total_budget"].sum())
    tot_opex = float(df.loc[ct == "OPEX", "total_budget"].sum())

    # Top 5 dự án đầu tư lớn nhất
    top5 = df.sort_values(by="total_budget", ascending=False).head(5) if "total_budget" in df.columns else pd.DataFrame()
    
    # 4 Quý
    quarters = {
        "Q1": months[0:3],
        "Q2": months[3:6],
        "Q3": months[6:9],
        "Q4": months[9:12]
    }
    q_vals = {}
    for q_lbl, ms in quarters.items():
        cols = [f"val_{m}" for m in ms if f"val_{m}" in df.columns]
        q_vals[q_lbl] = float(df[cols].sum().sum()) if cols else 0.0

    # Phân bổ theo trụ cột
    strat = digital_strategy_breakdown(df)

    def _fmt(val):
        return f"{val:,.0f} VNĐ".replace(",", ".")
    def _bil(val):
        return f"{val / 1e9:.2f} tỷ".replace(".", ",")

    top5_rows_html = ""
    for i, (_, r) in enumerate(top5.iterrows(), 1):
        top5_rows_html += f"""
        <tr>
            <td style="padding:6px 8px;border-bottom:1px solid #E2E8F0;text-align:center;">{i}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #E2E8F0;font-weight:600;">{_html.escape(str(r.get('item_name', '')))}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #E2E8F0;">{_html.escape(str(r.get('location', '')))}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #E2E8F0;text-align:center;">{int(r.get('quantity', 1))}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #E2E8F0;text-align:right;font-weight:700;color:#0F2C59;">{_fmt(r.get('total_budget', 0))}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #E2E8F0;text-align:center;"><span style="background:#EEF2F6;padding:2px 6px;border-radius:4px;font-size:11px;">{r.get('capex_type', '')}</span></td>
        </tr>
        """

    pillars_html = ""
    for p in strat["summary"]:
        pillars_html += f"""
        <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:10px;margin-bottom:8px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-weight:700;color:#0F2C59;font-size:12.5px;">{p['icon']} {p['name']}</span>
                <span style="font-weight:700;color:#1E40AF;font-size:13px;">{_bil(p['budget'])} ({p['pct']:.1f}%)</span>
            </div>
            <div style="font-size:11.5px;color:#64748B;margin-top:3px;">{p['desc']} ({p['items_count']} hạng mục)</div>
        </div>
        """

    default_note = cio_notes or (
        "1. Ngân sách năm nay ưu tiên duy trì và mở rộng năng lực thiết kế kết cấu thép Tekla/BIM, đáp ứng các dự án quốc tế trọng điểm của Tập đoàn.<br>"
        "2. Đề xuất Ban Giám đốc phê duyệt triển khai mua sắm tập trung 5 gói thầu nhằm đạt mức chiết khấu thương mại kỳ vọng 5% - 8%.<br>"
        "3. Dòng tiền được cân đối giải ngân theo 4 quý, tránh áp lực thanh khoản dồn vào cuối năm."
    )

    html_out = f"""
    <div style="font-family:'Inter',sans-serif;color:#1E293B;background:#FFFFFF;border:1px solid #CBD5E1;border-radius:12px;padding:24px;box-shadow:0 4px 16px rgba(0,0,0,0.06);max-width:960px;margin:auto;">
        <!-- Header -->
        <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #0F2C59;padding-bottom:14px;margin-bottom:18px;">
            <div>
                <div style="font-size:11px;font-weight:700;color:#64748B;letter-spacing:0.05em;text-transform:uppercase;">TẬP ĐOÀN CƠ KHÍ XÂY DỰNG ĐẠI DŨNG (DDC)</div>
                <div style="font-size:20px;font-weight:800;color:#0F2C59;margin-top:2px;">BÁO CÁO TỔNG QUAN ĐIỀU HÀNH NGÂN SÁCH CAPEX & CNTT {year}</div>
                <div style="font-size:12px;color:#475569;margin-top:2px;">Phạm vi: <b>{site_lbl}</b> · Ngày lập: {plan_date} · Người lập: {creator}</div>
            </div>
            <div style="text-align:right;">
                <span style="background:#EFF6FF;color:#1D4ED8;border:1px solid #BFDBFE;padding:4px 12px;border-radius:999px;font-size:12px;font-weight:700;">EXECUTIVE BRIEFING</span>
            </div>
        </div>

        <!-- 4 Top Cards -->
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px;">
            <div style="background:#F0F7FF;border:1px solid #BFDBFE;border-radius:10px;padding:12px;">
                <div style="font-size:11px;font-weight:700;color:#1E40AF;text-transform:uppercase;">TỔNG NGÂN SÁCH</div>
                <div style="font-size:22px;font-weight:800;color:#0F2C59;margin-top:2px;">{_bil(tot_budget)}</div>
                <div style="font-size:11.5px;color:#475569;">{_fmt(tot_budget)}</div>
            </div>
            <div style="background:#ECFDF5;border:1px solid #A7F3D0;border-radius:10px;padding:12px;">
                <div style="font-size:11px;font-weight:700;color:#047857;text-transform:uppercase;">TSCĐ (CAPEX)</div>
                <div style="font-size:22px;font-weight:800;color:#047857;margin-top:2px;">{_bil(tot_capex)}</div>
                <div style="font-size:11.5px;color:#475569;">Tỷ trọng: {(tot_capex/tot_budget*100 if tot_budget else 0):.1f}%</div>
            </div>
            <div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:10px;padding:12px;">
                <div style="font-size:11px;font-weight:700;color:#B45309;text-transform:uppercase;">CCDC & VẬT TƯ</div>
                <div style="font-size:22px;font-weight:800;color:#B45309;margin-top:2px;">{_bil(tot_ccdc)}</div>
                <div style="font-size:11.5px;color:#475569;">Tỷ trọng: {(tot_ccdc/tot_budget*100 if tot_budget else 0):.1f}%</div>
            </div>
            <div style="background:#FAF5FF;border:1px solid #E9D5FF;border-radius:10px;padding:12px;">
                <div style="font-size:11px;font-weight:700;color:#6D28D9;text-transform:uppercase;">DỊCH VỤ / OPEX</div>
                <div style="font-size:22px;font-weight:800;color:#6D28D9;margin-top:2px;">{_bil(tot_opex)}</div>
                <div style="font-size:11.5px;color:#475569;">Tỷ trọng: {(tot_opex/tot_budget*100 if tot_budget else 0):.1f}%</div>
            </div>
        </div>

        <!-- 2 Columns: Cashflow Quarters + Strategy Pillars -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:18px;">
            <!-- Column 1: Quarters -->
            <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;padding:14px;">
                <div style="font-size:13px;font-weight:700;color:#0F2C59;margin-bottom:10px;">📅 Phân kỳ Giải ngân theo 4 Quý</div>
                <table style="width:100%;border-collapse:collapse;font-size:12.5px;">
                    <tr style="border-bottom:1px solid #E2E8F0;">
                        <th style="padding:6px;text-align:left;color:#64748B;">Quý</th>
                        <th style="padding:6px;text-align:right;color:#64748B;">Số tiền</th>
                        <th style="padding:6px;text-align:right;color:#64748B;">Tỷ lệ</th>
                    </tr>
                    <tr><td style="padding:6px;font-weight:600;">Q1 (T10 - T12)</td><td style="padding:6px;text-align:right;">{_bil(q_vals['Q1'])}</td><td style="padding:6px;text-align:right;font-weight:700;color:#1E40AF;">{(q_vals['Q1']/tot_budget*100 if tot_budget else 0):.1f}%</td></tr>
                    <tr><td style="padding:6px;font-weight:600;">Q2 (T01 - T03)</td><td style="padding:6px;text-align:right;">{_bil(q_vals['Q2'])}</td><td style="padding:6px;text-align:right;font-weight:700;color:#1E40AF;">{(q_vals['Q2']/tot_budget*100 if tot_budget else 0):.1f}%</td></tr>
                    <tr><td style="padding:6px;font-weight:600;">Q3 (T04 - T06)</td><td style="padding:6px;text-align:right;">{_bil(q_vals['Q3'])}</td><td style="padding:6px;text-align:right;font-weight:700;color:#1E40AF;">{(q_vals['Q3']/tot_budget*100 if tot_budget else 0):.1f}%</td></tr>
                    <tr><td style="padding:6px;font-weight:600;">Q4 (T07 - T09)</td><td style="padding:6px;text-align:right;">{_bil(q_vals['Q4'])}</td><td style="padding:6px;text-align:right;font-weight:700;color:#1E40AF;">{(q_vals['Q4']/tot_budget*100 if tot_budget else 0):.1f}%</td></tr>
                </table>
            </div>

            <!-- Column 2: Pillars -->
            <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;padding:14px;">
                <div style="font-size:13px;font-weight:700;color:#0F2C59;margin-bottom:10px;">🚀 Cơ cấu theo 4 Trụ cột Chiến lược Số hóa</div>
                {pillars_html}
            </div>
        </div>

        <!-- Top 5 Projects Table -->
        <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;padding:14px;margin-bottom:18px;">
            <div style="font-size:13px;font-weight:700;color:#0F2C59;margin-bottom:10px;">🏆 Top 5 Hạng mục Đầu tư Lớn nhất</div>
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <thead>
                    <tr style="background:#F8FAFC;border-bottom:2px solid #CBD5E1;text-align:left;">
                        <th style="padding:6px 8px;width:40px;text-align:center;">STT</th>
                        <th style="padding:6px 8px;">Tên Hạng mục</th>
                        <th style="padding:6px 8px;">Vị trí / Nhà máy</th>
                        <th style="padding:6px 8px;text-align:center;">SL</th>
                        <th style="padding:6px 8px;text-align:right;">Ngân sách</th>
                        <th style="padding:6px 8px;text-align:center;">Loại</th>
                    </tr>
                </thead>
                <tbody>
                    {top5_rows_html}
                </tbody>
            </table>
        </div>

        <!-- CIO Strategic Recommendations -->
        <div style="background:#F8FAFC;border-left:4px solid #1E40AF;border-radius:6px;padding:12px 16px;">
            <div style="font-size:13px;font-weight:700;color:#0F2C59;margin-bottom:4px;">💡 Kết luận & Đề xuất của Giám đốc CNTT (CIO Recommendations)</div>
            <div style="font-size:12px;color:#334155;line-height:1.6;">
                {default_note}
            </div>
        </div>
    </div>
    """
    return html_out
