"""
Core calculation engine, data model, import/export for CAPEX Web App
"""
import os
import io
import calendar
import datetime
import math
import numpy as np
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from typing import Dict, List, Tuple, Any, Optional

from master_data import (
    load_master_data,
    generate_project_code,
    generate_item_code,
    generate_budget_code,
    apply_it_catalog,
    accounting_class,
    it_kinds,
    DEFAULT_MONTHS
)

# Standard useful life (years) by asset category 1 (TT45/2013/TT-BTC)
USEFUL_LIFE_DEFAULTS = {
    "A. Nhà cửa, vật kiến trúc": 25,
    "B. Máy móc thiết bị": 8,
    "C. Phương tiện vận tải": 6,
    "D. Thiết bị, dụng cụ quản lý": 4,
    "E. Bản quyền, Phần mềm": 3
}

def clean_number(val, default=0.0):
    if val is None or pd.isna(val):
        return default
    try:
        if isinstance(val, (int, float)):
            return float(val)
        val_str = str(val).replace(',', '').replace(' ', '').replace('%', '')
        return float(val_str)
    except Exception:
        return default

def default_handover_date(row: Dict[str, Any], months: List[str]) -> str:
    """Ngày cuối của tháng giải ngân cuối cùng (nhãn tháng dạng 'T10 2026'), '' nếu chưa phân kỳ."""
    last = next((m for m in reversed(months) if clean_number(row.get(f"pct_{m}", 0.0), 0.0) > 0), None)
    try:
        mo, yr = last[1:].split()
        mo, yr = int(mo), int(yr)
    except (TypeError, ValueError, AttributeError):
        return ""
    return datetime.date(yr, mo, calendar.monthrange(yr, mo)[1]).strftime("%Y-%m-%d")


def _int_or_none(v) -> Optional[int]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f == f and f >= 1 else None


def assign_item_seqs(rows: List[Dict[str, Any]], counters: Dict[str, int]) -> Dict[str, int]:
    """Cấp số cố định cho Mã hạng mục ({mã công trình}-{mã loại TS}-{số}).
    Dòng đã có số giữ nguyên; dòng mới/đổi nhóm mã/trùng số nhận số kế tiếp của nhóm. Bộ đếm chỉ tăng nên
    số của dòng đã xóa không bị cấp lại. Trả về bộ đếm mới {base: số lớn nhất đã cấp}."""
    counters = dict(counters or {})
    used: Dict[str, set] = {}
    for r in rows:
        seq = _int_or_none(r.get("item_seq"))
        base = r.get("item_code_base")
        if seq is not None and base:
            counters[base] = max(counters.get(base, 0), seq)
    for r in rows:
        base = r.get("item_code_base")
        if not base:
            continue
        seq = _int_or_none(r.get("item_seq"))
        taken = used.setdefault(base, set())
        if seq is None or seq in taken:
            counters[base] = counters.get(base, 0) + 1
            seq = counters[base]
        taken.add(seq)
        r["item_seq"] = seq
        r["item_code"] = f"{base}-{seq:03d}"
    return counters


def split_units(qty: float, weights: List[float]) -> Optional[List[int]]:
    """Chia SL nguyên theo trọng số tháng (phần dư lớn nhất), tổng đúng bằng SL. None nếu SL không nguyên / không có trọng số."""
    total = sum(w for w in weights if w > 0)
    n = int(round(qty))
    if total <= 0 or n <= 0 or abs(qty - n) > 1e-9:
        return None
    exact = [max(w, 0.0) / total * n for w in weights]
    units = [int(math.floor(e)) for e in exact]
    for i in sorted(range(len(exact)), key=lambda i: (-(exact[i] - units[i]), i))[:n - sum(units)]:
        units[i] += 1
    return units


def snap_units(pcts: List[float], qty: float, tol: float = 0.05) -> Optional[List[int]]:
    """Số lượng nguyên theo tháng nếu tỷ lệ phân kỳ ứng với số lượng gần nguyên (vd. 33,34% × 21 máy = 7,0014 -> 7).
    Trả về None khi SL không nguyên hoặc phân kỳ có tháng lẻ thật (vd. 50/50 cho 3 máy) - khi đó giữ nguyên tỷ lệ."""
    if qty <= 0 or abs(qty - round(qty)) > 1e-9 or not any(pcts):
        return None
    raw = [p * qty for p in pcts]
    units = [int(round(u)) for u in raw]
    if any(abs(u - r) > tol for u, r in zip(units, raw)) or sum(units) != int(round(qty)):
        return None
    return units


def calculate_row(row: Dict[str, Any], months: List[str] = DEFAULT_MONTHS, year_code: str = "A26", master: Dict[str, Any] = None) -> Dict[str, Any]:
    """Calculate and standardize all values for a single CapEx row"""
    if master is None:
        master = load_master_data()
        
    qty = clean_number(row.get("quantity", 1), 1.0)
    price = clean_number(row.get("unit_price", 0), 0.0)
    total_budget = qty * price
    row["quantity"] = qty
    row["unit_price"] = price
    row["total_budget"] = total_budget

    # Monthly percentages and values
    pcts = []
    for m in months:
        p = clean_number(row.get(f"pct_{m}", 0.0), 0.0)
        # In case user entered 20 instead of 0.2
        if p > 1.0 and p <= 100.0:
            p = p / 100.0
        pcts.append(p)
    units = snap_units(pcts, qty)
    auto_q = row.get("auto_quota")
    if units is None and auto_q is not None and not (isinstance(auto_q, float) and math.isnan(auto_q)) and bool(auto_q):  # dòng định biên: luôn mua số lượng nguyên mỗi tháng
        units = split_units(qty, pcts)
    total_pct = 0.0
    for i, m in enumerate(months):
        if units is not None:  # phân kỳ theo số lượng nguyên: giá trị tháng = SL tháng × đơn giá
            row[f"pct_{m}"] = units[i] / qty
            row[f"val_{m}"] = units[i] * price
        else:
            row[f"pct_{m}"] = pcts[i]
            row[f"val_{m}"] = pcts[i] * total_budget
        total_pct += row[f"pct_{m}"]

    # Ngày bàn giao: trống -> ngày cuối tháng giải ngân cuối (tự cập nhật theo phân kỳ); người lập nhập tay thì giữ nguyên
    hd = str(row.get("handover_date") or "").strip()
    if hd in ("", "nan", "None") or hd == str(row.get("handover_auto") or ""):
        auto = default_handover_date(row, months)
        row["handover_date"], row["handover_auto"] = auto, auto
    else:
        row["handover_auto"] = ""

    row["total_pct"] = round(total_pct, 4)
    row["total_val"] = sum(row.get(f"val_{m}", 0.0) for m in months)
    row["pct_valid"] = abs(row["total_pct"] - 1.0) < 0.005 or (total_budget == 0 and row["total_pct"] == 0)

    # Codes
    stt = int(clean_number(row.get("stt", 1), 1))
    row["stt"] = stt
    entity = str(row.get("entity", "DDC"))
    site = str(row.get("location", "VP Bạch Đằng"))
    cat1 = str(row.get("asset_cat1", "B. Máy móc thiết bị"))
    cat2 = str(row.get("asset_cat2", "B1. MMTB: Mua mới"))
    cost_lv2 = str(row.get("cost_lv2", "04.01. Máy móc thiết bị đầu tư mới"))
    
    p_code = generate_project_code(entity, site, cat1, year_code, master)
    base = generate_item_code(p_code, cat1, 0, master).rsplit("-", 1)[0]
    b_code = generate_budget_code(cost_lv2)
    seq = _int_or_none(row.get("item_seq"))
    if seq is None or row.get("item_code_base") != base:
        # Chưa có số cố định (dòng mới) hoặc đổi pháp nhân/site/loại TS -> cấp số mới khi lưu (assign_item_seqs)
        row["item_seq"] = None
        seq = stt
    row["item_code_base"] = base

    row["project_code"] = p_code
    row["item_code"] = f"{base}-{seq:03d}"
    row["budget_code"] = b_code
    
    # Useful life for depreciation
    if "useful_life" not in row or clean_number(row.get("useful_life", 0)) <= 0:
        row["useful_life"] = USEFUL_LIFE_DEFAULTS.get(cat1, 5)

    # Phân loại kế toán theo loại hạng mục CNTT & đơn giá 1 đơn vị (TSCĐ >= 30 triệu)
    kind = row.get("item_kind")
    if isinstance(kind, str) and kind:
        row["accounting_class"], row["capex_type"] = accounting_class(kind, price, master)
        row["item_kind_label"] = it_kinds(master).get(kind, kind)

    return row

def load_capex_from_excel(file_source, sheet_name: Optional[str] = None, months: List[str] = DEFAULT_MONTHS,
                          year_code: str = "A26") -> Tuple[Dict[str, Any], pd.DataFrame]:
    """
    Parse existing CapEx Excel file and return metadata and normalized DataFrame.
    file_source can be a path or file-like object (BytesIO).
    """
    master = load_master_data()
    wb = openpyxl.load_workbook(file_source, data_only=True)
    
    # Pick sheet
    target_sheet = sheet_name
    if not target_sheet or target_sheet not in wb.sheetnames:
        for candidate in ["CA.01_CAPEX (2)", "CA.01_CAPEX"]:
            if candidate in wb.sheetnames:
                target_sheet = candidate
                break
        if not target_sheet:
            target_sheet = wb.sheetnames[0]
            
    ws = wb[target_sheet]
    
    # Read metadata
    metadata = {
        "sheet_name": target_sheet,
        "date": str(ws["C17"].value or datetime.date.today()),
        "proposing_dept": str(ws["C18"].value or ws["D18"].value or "Khối CNTT & Chuyển đổi số"),
        "creator_name": str(ws["C19"].value or ws["D19"].value or ""),
        "creator_email": str(ws["C20"].value or ws["D20"].value or "")
    }
    
    # Read rows from row 26
    rows = []

    for r in range(26, ws.max_row + 1):
        item_name = ws.cell(row=r, column=10).value
        qty = ws.cell(row=r, column=13).value
        price = ws.cell(row=r, column=14).value

        # Stop at the total row; below it is the example table ("Bảng ví dụ")
        marker = str(ws.cell(row=r, column=2).value or "").strip().lower()
        if marker.startswith("tổng cộng") or marker.startswith("bảng ví dụ"):
            break

        # If row has no name and no price, skip
        if not item_name and not price:
            continue
            
        stt = ws.cell(row=r, column=2).value or (len(rows) + 1)
        entity = ws.cell(row=r, column=3).value or "DDC"
        division = ws.cell(row=r, column=4).value or ""
        dept_prop = ws.cell(row=r, column=5).value or metadata["proposing_dept"]
        dept_using = ws.cell(row=r, column=6).value or dept_prop
        location = ws.cell(row=r, column=7).value or "VP Bạch Đằng"
        cat1 = ws.cell(row=r, column=8).value or "B. Máy móc thiết bị"
        cat2 = ws.cell(row=r, column=9).value or "B1. MMTB: Mua mới"
        detail_work = ws.cell(row=r, column=11).value or ""
        supplier = ws.cell(row=r, column=12).value or ""
        
        # Dates
        contract_date = ws.cell(row=r, column=16).value
        completion_date = ws.cell(row=r, column=17).value
        handover_date = ws.cell(row=r, column=18).value
        
        def format_date(d):
            if d is None:
                return ""
            if isinstance(d, (datetime.datetime, datetime.date)):
                return d.strftime("%Y-%m-%d")
            return str(d)

        row_dict = {
            "stt": stt,
            "entity": str(entity).strip(),
            "division": str(division).strip(),
            "dept_proposing": str(dept_prop).strip(),
            "dept_using": str(dept_using).strip(),
            "location": str(location).strip(),
            "asset_cat1": str(cat1).strip(),
            "asset_cat2": str(cat2).strip(),
            "item_name": str(item_name or "").strip(),
            "detail_work": str(detail_work or "").strip(),
            "supplier": str(supplier or "").strip(),
            "quantity": clean_number(qty, 1.0),
            "unit_price": clean_number(price, 0.0),
            "contract_date": format_date(contract_date),
            "completion_date": format_date(completion_date),
            "handover_date": format_date(handover_date),
            "cost_lv1": str(ws.cell(row=r, column=45).value or "04. Chi phí MMTB").strip(),
            "cost_lv2": str(ws.cell(row=r, column=46).value or "04.01. Máy móc thiết bị đầu tư mới").strip()
        }
        
        # Gán nhóm CNTT / loại tài sản / loại chi phí theo danh mục CNTT
        apply_it_catalog(row_dict, master)

        # Monthly %
        # Cols 19 to 30
        for i, m in enumerate(months):
            p = ws.cell(row=r, column=19 + i).value
            row_dict[f"pct_{m}"] = clean_number(p, 0.0)
            
        # Calculate full row
        calculated_row = calculate_row(row_dict, months=months, year_code=year_code, master=master)
        rows.append(calculated_row)
        
    wb.close()
    df = pd.DataFrame(rows)
    return metadata, df

def export_capex_to_excel(df: pd.DataFrame, metadata: Dict[str, Any], months: List[str] = DEFAULT_MONTHS) -> bytes:
    """
    Generate standard Excel workbook matching CA.01_CAPEX format with all formulas and styles.
    Returns bytes buffer for direct download.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CA.01_CAPEX"
    
    # Setup styles
    font_title = Font(name="Calibri", size=14, bold=True, color="1F4E79")
    font_bold = Font(name="Calibri", size=10, bold=True)
    font_regular = Font(name="Calibri", size=10)
    font_header = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    font_sub_header = Font(name="Calibri", size=9, bold=True, color="FFFFFF")
    
    fill_header_main = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid") # Dark Blue
    fill_header_pct = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")  # Blue
    fill_header_val = PatternFill(start_color="337AB7", end_color="337AB7", fill_type="solid")  # Accent Blue
    fill_header_code = PatternFill(start_color="548235", end_color="548235", fill_type="solid") # Greenish
    fill_total_row = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    
    border_thin = Border(
        left=Side(style='thin', color='BFBFBF'),
        right=Side(style='thin', color='BFBFBF'),
        top=Side(style='thin', color='BFBFBF'),
        bottom=Side(style='thin', color='BFBFBF')
    )
    border_double_bottom = Border(
        left=Side(style='thin', color='BFBFBF'),
        right=Side(style='thin', color='BFBFBF'),
        top=Side(style='thin', color='BFBFBF'),
        bottom=Side(style='double', color='000000')
    )
    
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    # Header info rows
    ws.merge_cells("C15:N15")
    ws["C15"] = f"TỔNG HỢP NGÂN SÁCH ĐẦU TƯ {metadata.get('budget_year', '2026')} CỦA CÁC KHỐI/PHÒNG/BAN"
    ws["C15"].font = font_title
    ws["C15"].alignment = Alignment(horizontal="left", vertical="center")
    
    ws["B17"] = "Ngày:"
    ws["B17"].font = font_bold
    ws["C17"] = metadata.get("date", datetime.date.today().strftime("%Y-%m-%d"))
    
    ws["B18"] = "Phòng ban:"
    ws["B18"].font = font_bold
    ws["C18"] = metadata.get("proposing_dept", "")
    
    ws["B19"] = "Họ và tên:"
    ws["B19"].font = font_bold
    ws["C19"] = metadata.get("creator_name", "")
    
    ws["B20"] = "Email:"
    ws["B20"].font = font_bold
    ws["C20"] = metadata.get("creator_email", "")

    # Table Top Headers (Row 24)
    # Col 2-15: Thông tin ngân sách đầu tư
    ws.merge_cells("B24:O24")
    ws["B24"] = "Thông tin ngân sách đầu tư"
    ws["B24"].fill = fill_header_main
    ws["B24"].font = font_header
    ws["B24"].alignment = align_center

    # Col 16-18: Dates
    ws["P24"] = "Ngày dự kiến ký hợp đồng"
    ws["P24"].fill = fill_header_main
    ws["P24"].font = font_header
    ws["P24"].alignment = align_center

    ws["Q24"] = "Ngày dự kiến hoàn thành"
    ws["Q24"].fill = fill_header_main
    ws["Q24"].font = font_header
    ws["Q24"].alignment = align_center

    ws["R24"] = "Ngày bàn giao, sử dụng"
    ws["R24"].fill = fill_header_main
    ws["R24"].font = font_header
    ws["R24"].alignment = align_center

    # Col 19-31: Phân kỳ theo tỷ lệ (%)
    ws.merge_cells("S24:AE24")
    ws["S24"] = "Phân kỳ đầu tư theo tỷ lệ (%)"
    ws["S24"].fill = fill_header_pct
    ws["S24"].font = font_header
    ws["S24"].alignment = align_center

    # Col 32-44: Phân kỳ theo giá trị
    ws.merge_cells("AF24:AR24")
    ws["AF24"] = "Phân kỳ đầu tư theo giá trị (VNĐ)"
    ws["AF24"].fill = fill_header_val
    ws["AF24"].font = font_header
    ws["AF24"].alignment = align_center

    # Col 45-49: Phân loại & Mã hóa
    ws.merge_cells("AS24:BC24")
    ws["AS24"] = "Phân loại kế toán & Mã hóa"
    ws["AS24"].fill = fill_header_code
    ws["AS24"].font = font_header
    ws["AS24"].alignment = align_center

    # Table Column Headers (Row 25)
    headers_r25 = [
        (2, "(!)STT", fill_header_main),
        (3, "(*)Pháp nhân", fill_header_main),
        (4, "Khối", fill_header_main),
        (5, "Phòng ban đề xuất", fill_header_main),
        (6, "(*)Phòng ban sử dụng", fill_header_main),
        (7, "(*)Vị trí", fill_header_main),
        (8, "(*)Loại tài sản cấp 1", fill_header_main),
        (9, "Loại tài sản cấp 2", fill_header_main),
        (10, "(*)Tên hạng mục / Tài sản", fill_header_main),
        (11, "Công việc chi tiết", fill_header_main),
        (12, "Nhà cung cấp", fill_header_main),
        (13, "(*)Số lượng", fill_header_main),
        (14, "(*)Đơn giá (VNĐ)", fill_header_main),
        (15, "(!)Tổng ngân sách (VNĐ)", fill_header_main),
        (16, "Ký HĐ", fill_header_main),
        (17, "Hoàn thành", fill_header_main),
        (18, "Bàn giao", fill_header_main),
    ]

    for col_idx, text, fill_c in headers_r25:
        cell = ws.cell(row=25, column=col_idx, value=text)
        cell.fill = fill_c
        cell.font = font_sub_header
        cell.alignment = align_center
        cell.border = border_thin

    # % Month headers (Col 19-30) + Total (Col 31)
    for i, m in enumerate(months):
        c = ws.cell(row=25, column=19 + i, value=m)
        c.fill = fill_header_pct
        c.font = font_sub_header
        c.alignment = align_center
        c.border = border_thin
    c_tot_pct = ws.cell(row=25, column=31, value="Tổng (%)")
    c_tot_pct.fill = fill_header_pct
    c_tot_pct.font = font_sub_header
    c_tot_pct.alignment = align_center
    c_tot_pct.border = border_thin

    # VND Month headers (Col 32-43) + Total (Col 44)
    for i, m in enumerate(months):
        c = ws.cell(row=25, column=32 + i, value=m)
        c.fill = fill_header_val
        c.font = font_sub_header
        c.alignment = align_center
        c.border = border_thin
    c_tot_val = ws.cell(row=25, column=44, value="Tổng giải ngân")
    c_tot_val.fill = fill_header_val
    c_tot_val.font = font_sub_header
    c_tot_val.alignment = align_center
    c_tot_val.border = border_thin

    # Code headers (Col 45-49)
    code_headers = [
        (45, "Loại chi phí cấp 1"),
        (46, "Loại chi phí cấp 2"),
        (47, "Mã công trình"),
        (48, "Mã hạng mục"),
        (49, "Mã ngân sách"),
        (50, "Nhóm CNTT"),
        (51, "Mã danh mục CNTT"),
        (52, "ĐVT"),
        (53, "Phân loại kế toán"),
        (54, "Loại nhu cầu"),
        (55, "Lý do phát sinh / căn cứ")
    ]
    for col_idx, text in code_headers:
        c = ws.cell(row=25, column=col_idx, value=text)
        c.fill = fill_header_code
        c.font = font_sub_header
        c.alignment = align_center
        c.border = border_thin

    # Populate Data Rows
    current_row = 26
    for idx, row in df.iterrows():
        r = current_row
        
        ws.cell(row=r, column=2, value=row.get("stt", idx + 1)).alignment = align_center
        ws.cell(row=r, column=3, value=row.get("entity", "")).alignment = align_center
        ws.cell(row=r, column=4, value=row.get("division", "")).alignment = align_left
        ws.cell(row=r, column=5, value=row.get("dept_proposing", "")).alignment = align_left
        ws.cell(row=r, column=6, value=row.get("dept_using", "")).alignment = align_left
        ws.cell(row=r, column=7, value=row.get("location", "")).alignment = align_center
        ws.cell(row=r, column=8, value=row.get("asset_cat1", "")).alignment = align_left
        ws.cell(row=r, column=9, value=row.get("asset_cat2", "")).alignment = align_left
        ws.cell(row=r, column=10, value=row.get("item_name", "")).alignment = align_left
        ws.cell(row=r, column=11, value=row.get("detail_work", "")).alignment = align_left
        ws.cell(row=r, column=12, value=row.get("supplier", "")).alignment = align_left
        
        c_qty = ws.cell(row=r, column=13, value=clean_number(row.get("quantity", 1)))
        c_qty.number_format = '#,##0'
        c_qty.alignment = align_right
        
        c_price = ws.cell(row=r, column=14, value=clean_number(row.get("unit_price", 0)))
        c_price.number_format = '#,##0'
        c_price.alignment = align_right
        
        # Formula for total budget: =M{r}*N{r}
        c_tot = ws.cell(row=r, column=15, value=f"=M{r}*N{r}")
        c_tot.number_format = '#,##0'
        c_tot.font = font_bold
        c_tot.alignment = align_right

        ws.cell(row=r, column=16, value=str(row.get("contract_date", ""))).alignment = align_center
        ws.cell(row=r, column=17, value=str(row.get("completion_date", ""))).alignment = align_center
        ws.cell(row=r, column=18, value=str(row.get("handover_date", ""))).alignment = align_center

        # Monthly percentages
        for i, m in enumerate(months):
            p = clean_number(row.get(f"pct_{m}", 0.0))
            cp = ws.cell(row=r, column=19 + i, value=p)
            cp.number_format = '0.0%'
            cp.alignment = align_right

        # Total % formula: =SUM(S{r}:AD{r})
        c_sum_pct = ws.cell(row=r, column=31, value=f"=SUM(S{r}:AD{r})")
        c_sum_pct.number_format = '0.0%'
        c_sum_pct.font = font_bold
        c_sum_pct.alignment = align_right

        # Monthly VND: =S{r}*$O{r}
        for i, m in enumerate(months):
            col_letter_pct = get_column_letter(19 + i)
            cv = ws.cell(row=r, column=32 + i, value=f"={col_letter_pct}{r}*$O{r}")
            cv.number_format = '#,##0'
            cv.alignment = align_right

        # Total VND formula: =SUM(AF{r}:AQ{r})
        c_sum_val = ws.cell(row=r, column=44, value=f"=SUM(AF{r}:AQ{r})")
        c_sum_val.number_format = '#,##0'
        c_sum_val.font = font_bold
        c_sum_val.alignment = align_right

        ws.cell(row=r, column=45, value=row.get("cost_lv1", "")).alignment = align_left
        ws.cell(row=r, column=46, value=row.get("cost_lv2", "")).alignment = align_left
        ws.cell(row=r, column=47, value=row.get("project_code", "")).alignment = align_center
        ws.cell(row=r, column=48, value=row.get("item_code", "")).alignment = align_center
        ws.cell(row=r, column=49, value=row.get("budget_code", "")).alignment = align_center
        for col_c, key in ((50, "it_group"), (51, "catalog_code"), (52, "unit"), (53, "accounting_class"),
                           (54, "need_type"), (55, "need_reason")):
            v = row.get(key, "")
            ws.cell(row=r, column=col_c, value="" if v is None or (isinstance(v, float) and np.isnan(v)) else v).alignment = align_left

        for col_c in range(2, 56):
            cell = ws.cell(row=r, column=col_c)
            cell.border = border_thin
            if not cell.font or cell.font == Font():
                cell.font = font_regular

        current_row += 1

    # Chống chèn công thức (CSV/Excel injection): chữ người dùng nhập bắt đầu bằng = + - @ luôn lưu dạng chữ,
    # chỉ các cột công thức do hệ thống tạo (O, AE..AR) giữ công thức
    for ref in ("C15", "C17", "C18", "C19", "C20"):  # ô tiêu đề lấy từ dữ liệu người dùng (vd. tên phòng ban)
        if isinstance(ws[ref].value, str) and ws[ref].value[:1] in ("=", "+", "-", "@", chr(9), chr(13)):
            ws[ref].data_type = "s"
    text_cols = set(range(3, 13)) | {16, 17, 18} | set(range(45, 56))
    for r_idx in range(26, current_row):
        for c_idx in text_cols:
            cell = ws.cell(row=r_idx, column=c_idx)
            if isinstance(cell.value, str) and cell.value[:1] in ("=", "+", "-", "@", chr(9), chr(13)):
                cell.data_type = "s"

    # Total Summary Row at bottom
    if len(df) > 0:
        tot_r = current_row
        ws.cell(row=tot_r, column=2, value="TỔNG CỘNG").font = font_bold
        ws.merge_cells(f"B{tot_r}:L{tot_r}")
        ws.cell(row=tot_r, column=2).alignment = align_center
        
        # Sum quantity
        c_qtot = ws.cell(row=tot_r, column=13, value=f"=SUM(M26:M{tot_r-1})")
        c_qtot.font = font_bold
        c_qtot.number_format = '#,##0'
        c_qtot.alignment = align_right
        
        # Sum total budget
        c_btot = ws.cell(row=tot_r, column=15, value=f"=SUM(O26:O{tot_r-1})")
        c_btot.font = font_bold
        c_btot.number_format = '#,##0'
        c_btot.alignment = align_right

        # Monthly VND sums
        for i, m in enumerate(months):
            col_letter_val = get_column_letter(32 + i)
            c_mv_tot = ws.cell(row=tot_r, column=32 + i, value=f"=SUM({col_letter_val}26:{col_letter_val}{tot_r-1})")
            c_mv_tot.font = font_bold
            c_mv_tot.number_format = '#,##0'
            c_mv_tot.alignment = align_right

        # Grand total disbursement
        c_grand = ws.cell(row=tot_r, column=44, value=f"=SUM(AR26:AR{tot_r-1})")
        c_grand.font = font_bold
        c_grand.number_format = '#,##0'
        c_grand.alignment = align_right

        for c_idx in range(2, 56):
            c_cell = ws.cell(row=tot_r, column=c_idx)
            c_cell.fill = fill_total_row
            c_cell.border = border_double_bottom

        # Dự phòng phát sinh (% trên tổng hạng mục) và tổng CAPEX thường niên gồm dự phòng
        cont_pct = clean_number(metadata.get("contingency_pct", 0), 0.0)
        if cont_pct > 0:
            cont_r, grand_r = tot_r + 1, tot_r + 2
            ws.cell(row=cont_r, column=2, value=f"DỰ PHÒNG PHÁT SINH ({cont_pct * 100:g}%)").font = font_bold
            ws.merge_cells(f"B{cont_r}:L{cont_r}")
            ws.cell(row=cont_r, column=2).alignment = align_center
            c_cont = ws.cell(row=cont_r, column=15, value=f"=ROUND(O{tot_r}*{cont_pct},0)")
            ws.cell(row=grand_r, column=2, value="TỔNG CAPEX THƯỜNG NIÊN (GỒM DỰ PHÒNG)").font = font_bold
            ws.merge_cells(f"B{grand_r}:L{grand_r}")
            ws.cell(row=grand_r, column=2).alignment = align_center
            c_grand2 = ws.cell(row=grand_r, column=15, value=f"=O{tot_r}+O{cont_r}")
            for c in (c_cont, c_grand2):
                c.font = font_bold
                c.number_format = '#,##0'
                c.alignment = align_right
            for rr in (cont_r, grand_r):
                for c_idx in range(2, 56):
                    ws.cell(row=rr, column=c_idx).fill = fill_total_row

    # Set column widths
    column_widths = {
        2: 6,   # STT
        3: 10,  # Pháp nhân
        4: 22,  # Khối
        5: 25,  # PB đề xuất
        6: 25,  # PB sử dụng
        7: 15,  # Vị trí
        8: 22,  # Cat 1
        9: 22,  # Cat 2
        10: 30, # Tên tài sản
        11: 25, # Chi tiết
        12: 18, # NCC
        13: 10, # Qty
        14: 16, # Price
        15: 18, # Total
        16: 12, # Date 1
        17: 12, # Date 2
        18: 12, # Date 3
    }
    for c_idx, w in column_widths.items():
        ws.column_dimensions[get_column_letter(c_idx)].width = w
    for c_idx in range(19, 31):
        ws.column_dimensions[get_column_letter(c_idx)].width = 10
    ws.column_dimensions[get_column_letter(31)].width = 11
    for c_idx in range(32, 44):
        ws.column_dimensions[get_column_letter(c_idx)].width = 15
    ws.column_dimensions[get_column_letter(44)].width = 16
    for c_idx in range(45, 54):
        ws.column_dimensions[get_column_letter(c_idx)].width = 20
    ws.column_dimensions[get_column_letter(53)].width = 40
    ws.column_dimensions[get_column_letter(54)].width = 14
    ws.column_dimensions[get_column_letter(55)].width = 45

    # Also include Category sheet for reference
    ws_cat = wb.create_sheet("Category")
    master = load_master_data()
    ws_cat["A1"] = "CODE 1"
    ws_cat["B1"] = "Pháp nhân"
    for idx_e, ent in enumerate(master.get("entities", [])):
        ws_cat.cell(row=idx_e+2, column=1, value=ent.get("code", ""))
        ws_cat.cell(row=idx_e+2, column=2, value=ent.get("name", ""))

    ws_cat["C1"] = "CODE 2"
    ws_cat["D1"] = "Sites"
    for idx_s, st in enumerate(master.get("sites", [])):
        ws_cat.cell(row=idx_s+2, column=3, value=st.get("code", ""))
        ws_cat.cell(row=idx_s+2, column=4, value=st.get("name", ""))

    ws_cat["E1"] = "Loại tài sản cấp 1"
    ws_cat["F1"] = "CODE 3"
    ws_cat["G1"] = "CODE 4"
    for idx_c, cat in enumerate(master.get("asset_cat1", [])):
        ws_cat.cell(row=idx_c+2, column=5, value=cat.get("name", ""))
        ws_cat.cell(row=idx_c+2, column=6, value=cat.get("code3", ""))
        ws_cat.cell(row=idx_c+2, column=7, value=cat.get("code4", ""))

    ws_cat["U1"] = "Tên hạng mục chính / Tài sản"
    ws_cat["V1"] = "Giá tham chiếu"
    ws_cat["W1"] = "Mã danh mục CNTT"
    ws_cat["X1"] = "Nhóm CNTT"
    ws_cat["Y1"] = "ĐVT"
    for idx_it, it in enumerate(master.get("standard_items", [])):
        ws_cat.cell(row=idx_it+2, column=21, value=it.get("name", ""))
        ws_cat.cell(row=idx_it+2, column=22, value=it.get("price", 0))
        ws_cat.cell(row=idx_it+2, column=23, value=it.get("code", ""))
        ws_cat.cell(row=idx_it+2, column=24, value=it.get("group", ""))
        ws_cat.cell(row=idx_it+2, column=25, value=it.get("unit", ""))

    out_stream = io.BytesIO()
    wb.save(out_stream)
    out_stream.seek(0)
    return out_stream.getvalue()

def calculate_depreciation_schedule(df: pd.DataFrame, num_years: int = 5, months: List[str] = None) -> pd.DataFrame:
    """
    Khấu hao / phân bổ đường thẳng theo năm tài chính (T10 - T9):
      - TSCĐ (capex_type CAPEX): khấu hao theo thời gian sử dụng của nhóm (useful_life, năm)
      - CCDC: phân bổ dần (TK 242) theo thời gian phân bổ
      - Thuê bao / dịch vụ (OPEX): chi phí trả trước ngắn hạn, KHÔNG khấu hao -> bỏ qua
    Bắt đầu từ tháng giải ngân đầu tiên (phân kỳ > 0); năm 1 = năm ngân sách, chỉ tính số tháng còn lại.
    """
    months = months or DEFAULT_MONTHS
    dep_rows = []
    for idx, row in df.iterrows():
        total = clean_number(row.get("total_budget", 0))
        kind = str(row.get("capex_type") or "")
        if total <= 0 or kind not in ("CAPEX", "CCDC"):
            continue
        useful_life = clean_number(row.get("useful_life", 0), 0.0)
        if useful_life <= 0:
            useful_life = 5.0 if kind == "CAPEX" else 3.0
        life_m = max(1, int(round(useful_life * 12)))
        start = next((i for i, m in enumerate(months) if clean_number(row.get(f"pct_{m}", 0)) > 0), 0)
        monthly_dep = total / life_m
        row_dep = {
            "item_name": row.get("item_name", f"Hạng mục {idx+1}"),
            "entity": row.get("entity", ""),
            "dep_type": "TSCĐ - khấu hao" if kind == "CAPEX" else "CCDC - phân bổ",
            "total_budget": total,
            "useful_life": round(useful_life, 2),
            "start_month": months[start] if start < len(months) else "",
            "annual_depreciation": monthly_dep * 12,
            "monthly_depreciation": monthly_dep,
        }
        for y in range(1, num_years + 1):
            y0, y1 = 12 * (y - 1), 12 * y
            overlap = max(0, min(y1, start + life_m) - max(y0, start))
            row_dep[f"Năm {y}"] = monthly_dep * overlap
        dep_rows.append(row_dep)
    return pd.DataFrame(dep_rows)

def calculate_project_financials(initial_capex: float, annual_savings: float, opex_annual: float, life_years: int = 5, discount_rate: float = 0.10) -> Dict[str, Any]:
    """
    Calculate financial appraisal indicators: NPV, IRR, Payback Period, ROI.
    """
    if initial_capex <= 0:
        return {"npv": 0, "irr": 0, "payback": 0, "roi": 0}
        
    net_annual_cash_flow = annual_savings - opex_annual
    cash_flows = [-initial_capex] + [net_annual_cash_flow] * int(life_years)
    
    # NPV
    npv_val = np.npv(discount_rate, cash_flows) if hasattr(np, 'npv') else 0.0
    if not hasattr(np, 'npv'):
        npv_val = sum(cf / ((1 + discount_rate) ** t) for t, cf in enumerate(cash_flows))
        
    # IRR
    try:
        import numpy_financial as npf
        irr_val = npf.irr(cash_flows)
    except Exception:
        # Simple binary search or numpy irr fallback
        irr_val = (net_annual_cash_flow / initial_capex) if initial_capex > 0 else 0
        
    # Payback
    payback_years = (initial_capex / net_annual_cash_flow) if net_annual_cash_flow > 0 else 999.0
    # Simple ROI
    total_net_return = (net_annual_cash_flow * life_years) - initial_capex
    roi_pct = (total_net_return / initial_capex) * 100 if initial_capex > 0 else 0
    
    return {
        "npv": float(npv_val),
        "irr": float(irr_val) * 100 if irr_val is not None and not np.isnan(irr_val) else 0.0,
        "payback_years": round(payback_years, 1),
        "roi_pct": round(roi_pct, 1),
        "cash_flows": cash_flows
    }
