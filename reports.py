"""
Báo cáo tổng hợp theo Khối: bảng Khối (so sánh năm trước) và file Excel Khối -> Phòng ban -> Hạng mục.
Khối lấy từ cột division của dòng ngân sách; trống -> theo bảng phòng ban -> khối (dept_divisions).
"""
import io
from typing import Dict, Any, Optional

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from master_data import division_of

NO_DIVISION = "(Chưa có khối)"
NO_DEPT = "(Chưa ghi phòng ban)"
TYPES = ("CAPEX", "CCDC", "OPEX")
TYPE_LABEL = {"CAPEX": "TSCĐ (CAPEX)", "CCDC": "CCDC", "OPEX": "OPEX"}


def _key(v) -> str:
    return " ".join(str(v or "").upper().split())


def with_division(df: pd.DataFrame, master: Dict[str, Any]) -> pd.DataFrame:
    """Thêm cột khoi / dept / ctype đã chuẩn hóa (không đổi df gốc)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["khoi", "dept", "ctype", "total_budget"])
    d = df.copy()
    dept = d["dept_proposing"].fillna("").astype(str).str.strip() if "dept_proposing" in d.columns else pd.Series("", index=d.index)
    div = d["division"].fillna("").astype(str).str.strip() if "division" in d.columns else pd.Series("", index=d.index)
    div = div.where(~div.isin(["", "nan", "None"]), dept.map(lambda x: division_of(x, master)))
    d["khoi"] = div.map(lambda v: _key(v) or NO_DIVISION)
    d["dept"] = dept.where(dept != "", NO_DEPT)
    ct = d["capex_type"] if "capex_type" in d.columns else pd.Series("", index=d.index)
    d["ctype"] = ct.where(ct.isin(TYPES), "Chưa phân loại")
    d["total_budget"] = pd.to_numeric(d.get("total_budget", 0), errors="coerce").fillna(0.0)
    return d


def summary_by_division(df: pd.DataFrame, prev_df: Optional[pd.DataFrame], master: Dict[str, Any]) -> pd.DataFrame:
    """1 dòng / Khối: số phòng, số dòng, tiền theo CAPEX/CCDC/OPEX, tổng, tỷ trọng, năm trước, chênh lệch. Sắp theo tổng."""
    d = with_division(df, master)
    cols = ["Khối", "Số phòng", "Số dòng", *[TYPE_LABEL[t] for t in TYPES], "Chưa phân loại", "Tổng", "Tỷ trọng",
            "Năm trước", "Chênh lệch", "% so năm trước"]
    if d.empty:
        return pd.DataFrame(columns=cols)
    g = d.groupby("khoi")
    out = pd.DataFrame({"Số phòng": g["dept"].nunique(), "Số dòng": g.size(), "Tổng": g["total_budget"].sum()})
    pv = d.pivot_table(index="khoi", columns="ctype", values="total_budget", aggfunc="sum", fill_value=0.0)
    for t in (*TYPES, "Chưa phân loại"):
        out[TYPE_LABEL.get(t, t)] = pv[t] if t in pv.columns else 0.0
    total = out["Tổng"].sum()
    out["Tỷ trọng"] = out["Tổng"] / total if total else 0.0
    p = with_division(prev_df, master)
    prev = p.groupby("khoi")["total_budget"].sum() if not p.empty else pd.Series(dtype=float)
    out = out.reindex(out.index.union(prev.index), fill_value=0.0)
    out["Năm trước"] = prev.reindex(out.index).fillna(0.0)
    out["Chênh lệch"] = out["Tổng"] - out["Năm trước"]
    out["% so năm trước"] = (out["Chênh lệch"] / out["Năm trước"]).where(out["Năm trước"] > 0)
    out[["Số phòng", "Số dòng"]] = out[["Số phòng", "Số dòng"]].astype(int)
    out = out.sort_values(["Tổng", "Năm trước"], ascending=False)
    out.index.name = "Khối"
    return out.reset_index()[cols]


# ---------------------------------------------------------------- Excel
_THIN = Side(style="thin", color="CBD5E1")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEAD = PatternFill("solid", fgColor="1E3A5F")
_FILL_K = PatternFill("solid", fgColor="DBEAFE")
_FILL_P = PatternFill("solid", fgColor="F1F5F9")
_MONEY = '#,##0'


def _header(ws, row: int, titles, widths):
    for i, (t, w) in enumerate(zip(titles, widths), 1):
        c = ws.cell(row=row, column=i, value=t)
        c.font, c.fill, c.border = Font(bold=True, color="FFFFFF"), _HEAD, _BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[row].height = 30
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _title(ws, title: str, sub: str):
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14, color="1E3A5F")
    ws["A2"] = sub
    ws["A2"].font = Font(italic=True, color="64748B")


def report_xlsx(df: pd.DataFrame, prev_df: Optional[pd.DataFrame], master: Dict[str, Any], meta: Dict[str, Any]) -> bytes:
    year, scope = meta.get("budget_year", ""), meta.get("scope", "")
    prev_year = str(int(year) - 1) if str(year).isdigit() else "năm trước"
    sub = f"Phạm vi: {scope} · Đơn vị: VNĐ, chưa VAT, chưa gồm dự phòng · Lập ngày {meta.get('date', '')}"
    wb = Workbook()

    # Sheet 1: theo Khối
    ws = wb.active
    ws.title = "Theo Khối"
    _title(ws, f"TỔNG HỢP NGÂN SÁCH CNTT {year} THEO KHỐI", sub)
    s = summary_by_division(df, prev_df, master)
    titles = ["Khối", "Số phòng", "Số dòng", "TSCĐ (CAPEX)", "CCDC", "OPEX", "Chưa phân loại", f"Tổng {year}", "Tỷ trọng",
              f"Năm {prev_year}", "Chênh lệch", "% so năm trước"]
    _header(ws, 4, titles, [38, 10, 10, 18, 18, 18, 16, 20, 10, 18, 18, 12])
    keys = ["Khối", "Số phòng", "Số dòng", "TSCĐ (CAPEX)", "CCDC", "OPEX", "Chưa phân loại", "Tổng", "Tỷ trọng",
            "Năm trước", "Chênh lệch", "% so năm trước"]
    r = 5
    for rec in s.to_dict("records"):
        for i, k in enumerate(keys, 1):
            v = rec[k]
            c = ws.cell(row=r, column=i, value=None if (isinstance(v, float) and v != v) else v)
            c.border = _BORDER
            c.number_format = "0.0%" if k in ("Tỷ trọng", "% so năm trước") else (_MONEY if i > 1 else "@")
        r += 1
    if r > 5:  # dòng tổng bằng công thức
        ws.cell(row=r, column=1, value="TỔNG CỘNG")
        for i in range(2, len(keys) + 1):
            col = get_column_letter(i)
            if keys[i - 1] == "% so năm trước":
                val = f"=IF({get_column_letter(10)}{r}>0,{get_column_letter(11)}{r}/{get_column_letter(10)}{r},\"\")"
            elif keys[i - 1] == "Tỷ trọng":
                val = f"=SUM({col}5:{col}{r - 1})"
            else:
                val = f"=SUM({col}5:{col}{r - 1})"
            c = ws.cell(row=r, column=i, value=val)
            c.number_format = "0.0%" if keys[i - 1] in ("Tỷ trọng", "% so năm trước") else _MONEY
        for i in range(1, len(keys) + 1):
            ws.cell(row=r, column=i).font = Font(bold=True)
            ws.cell(row=r, column=i).fill = _FILL_K
            ws.cell(row=r, column=i).border = _BORDER
    ws.cell(row=r + 2, column=1, value="Số phòng ban của dòng TỔNG CỘNG là tổng theo từng khối.").font = Font(italic=True, color="64748B")

    # Sheet 2: Khối -> Phòng -> Hạng mục (gom theo mã danh mục + hình thức)
    ws2 = wb.create_sheet("Khối - Phòng - Hạng mục")
    _title(ws2, f"CHI TIẾT NGÂN SÁCH CNTT {year}: KHỐI → PHÒNG BAN → HẠNG MỤC", sub + " · Bấm dấu +/− bên trái để thu gọn")
    _header(ws2, 4, ["Khối / Phòng ban / Hạng mục", "Mã danh mục", "Hình thức", "Loại", "ĐVT", "Số lượng", "Đơn giá", "Thành tiền"],
            [56, 13, 18, 10, 10, 11, 16, 20])
    d = with_division(df, master)
    order = list(s["Khối"]) if not s.empty else []
    r = 5
    for khoi in order:
        dk = d[d["khoi"] == khoi]
        if dk.empty:
            continue
        rk = r
        ws2.cell(row=r, column=1, value=khoi)
        r += 1
        for dept, dp in sorted(dk.groupby("dept"), key=lambda x: -x[1]["total_budget"].sum()):
            rp = r
            ws2.cell(row=r, column=1, value=f"   {dept}")
            r += 1
            agg = (dp.assign(code=dp.get("catalog_code", pd.Series("", index=dp.index)).fillna(""),
                             inv=dp.get("invest_type", pd.Series("", index=dp.index)).fillna(""),
                             unit=dp.get("unit", pd.Series("", index=dp.index)).fillna(""),
                             price=pd.to_numeric(dp.get("unit_price", 0), errors="coerce").fillna(0.0),
                             qty=pd.to_numeric(dp.get("quantity", 0), errors="coerce").fillna(0.0))
                   .groupby(["item_name", "code", "inv", "ctype", "unit", "price"], dropna=False)
                   .agg(qty=("qty", "sum"), tot=("total_budget", "sum")).reset_index()
                   .sort_values("tot", ascending=False))
            first = r
            for it in agg.to_dict("records"):
                vals = [f"      {it['item_name']}", it["code"], it["inv"], it["ctype"], it["unit"], it["qty"], it["price"], it["tot"]]
                for i, v in enumerate(vals, 1):
                    c = ws2.cell(row=r, column=i, value=v)
                    c.border = _BORDER
                    if i >= 6:
                        c.number_format = _MONEY
                ws2.row_dimensions[r].outline_level = 2
                r += 1
            ws2.cell(row=rp, column=8, value=f"=SUM(H{first}:H{r - 1})")
            ws2.row_dimensions[rp].outline_level = 1
            for i in range(1, 9):
                c = ws2.cell(row=rp, column=i)
                c.font, c.fill, c.border = Font(bold=True), _FILL_P, _BORDER
                if i == 8:
                    c.number_format = _MONEY
        # tổng khối = tổng các dòng phòng ban của khối (cấp outline 1)
        dept_rows = [rr for rr in range(rk + 1, r) if ws2.row_dimensions[rr].outline_level == 1]
        ws2.cell(row=rk, column=8, value="=" + "+".join(f"H{rr}" for rr in dept_rows) if dept_rows else 0)
        for i in range(1, 9):
            c = ws2.cell(row=rk, column=i)
            c.font, c.fill, c.border = Font(bold=True, color="1E3A5F"), _FILL_K, _BORDER
            if i == 8:
                c.number_format = _MONEY
    if r > 5:
        khoi_rows = [rr for rr in range(5, r) if ws2.row_dimensions[rr].outline_level == 0]
        ws2.cell(row=r, column=1, value="TỔNG CỘNG")
        ws2.cell(row=r, column=8, value="=" + "+".join(f"H{rr}" for rr in khoi_rows))
        for i in range(1, 9):
            c = ws2.cell(row=r, column=i)
            c.font, c.fill, c.border = Font(bold=True), _FILL_K, _BORDER
            if i == 8:
                c.number_format = _MONEY
    ws2.sheet_properties.outlinePr.summaryBelow = False

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
