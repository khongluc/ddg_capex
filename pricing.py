"""
Cập nhật đơn giá danh mục CNTT từ file báo giá (Excel / CSV).

Luồng: read_quote_file -> plan_price_update (xem trước, không ghi gì) -> apply_catalog_prices + reprice_lines.
Dòng ngân sách chỉ đổi giá khi đang dùng đúng giá danh mục cũ (không phải giá người lập sửa tay),
trừ khi chọn include_manual; site đã nộp/duyệt không bị đổi.
"""
import io
import re
import datetime
import unicodedata
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd

from master_data import find_catalog_item

# Tên cột chấp nhận trong file báo giá (so khớp không phân biệt hoa/thường, dấu cách)
COL_CODE = ("mã", "mã danh mục", "mã hạng mục", "code", "catalog_code")
COL_NAME = ("tên", "tên hạng mục", "tên hạng mục chuẩn", "hạng mục", "name", "item_name")
COL_PRICE = ("giá mới", "đơn giá mới", "đơn giá", "giá", "price", "new_price")
COL_VENDOR = ("nhà cung cấp", "ncc", "vendor", "supplier")
COL_DATE = ("ngày báo giá", "ngày", "quote_date", "date")
COL_NOTE = ("ghi chú", "note")


def _norm(v) -> str:
    return " ".join(unicodedata.normalize("NFC", str(v or "")).lower().split())


def _num(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "").removesuffix("đ").removesuffix("VNĐ").removesuffix("vnđ")
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):  # 27.000.000 / 27,000,000 -> 27000000
        s = s.replace(".", "").replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _pick(columns: List[str], names: Tuple[str, ...]) -> Optional[str]:
    by_norm = {_norm(c): c for c in columns}
    for n in names:  # ưu tiên theo thứ tự (vd. "giá mới" trước "đơn giá")
        if n in by_norm:
            return by_norm[n]
    return None


def template_frame(master: Dict[str, Any]) -> pd.DataFrame:
    """Mẫu báo giá: danh mục hiện tại + cột Giá mới để trống."""
    return pd.DataFrame([{
        "Mã": it.get("code", ""), "Tên hạng mục": it.get("name", ""), "ĐVT": it.get("unit", ""),
        "Giá hiện tại": it.get("price", 0), "Giá mới": None, "Nhà cung cấp": it.get("vendor", ""),
        "Ngày báo giá": None, "Ghi chú": "",
    } for it in master.get("standard_items", [])])


def template_bytes(master: Dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        template_frame(master).to_excel(xw, sheet_name="Báo giá", index=False)
        ws = xw.sheets["Báo giá"]
        for col, width in zip("ABCDEFGH", (12, 48, 12, 16, 16, 24, 14, 30)):
            ws.column_dimensions[col].width = width
    return buf.getvalue()


def read_quote_file(content: bytes, filename: str) -> pd.DataFrame:
    """Đọc file báo giá -> DataFrame [code, name, price, vendor, quote_date, note] (chuẩn hóa tên cột)."""
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content), dtype=str, encoding="utf-8-sig")
    else:
        df = pd.read_excel(io.BytesIO(content), dtype=object)
    cols = [str(c) for c in df.columns]
    df.columns = cols
    c_code, c_name, c_price = _pick(cols, COL_CODE), _pick(cols, COL_NAME), _pick(cols, COL_PRICE)
    if not c_price:
        raise ValueError("Không tìm thấy cột giá (đặt tên cột 'Giá mới' hoặc 'Đơn giá').")
    if not c_code and not c_name:
        raise ValueError("Không tìm thấy cột 'Mã' hoặc 'Tên hạng mục' để khớp danh mục.")
    c_vendor, c_date, c_note = _pick(cols, COL_VENDOR), _pick(cols, COL_DATE), _pick(cols, COL_NOTE)

    def _date(v):
        if v is None or (isinstance(v, float) and v != v) or str(v).strip() == "":
            return ""
        if isinstance(v, (datetime.date, datetime.datetime, pd.Timestamp)):
            return pd.Timestamp(v).strftime("%Y-%m-%d")
        try:
            return pd.to_datetime(str(v), dayfirst=True).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return str(v).strip()

    out = pd.DataFrame({
        "code": df[c_code].fillna("").astype(str).str.strip() if c_code else "",
        "name": df[c_name].fillna("").astype(str).str.strip() if c_name else "",
        "price": df[c_price].map(_num),
        "vendor": df[c_vendor].fillna("").astype(str).str.strip() if c_vendor else "",
        "quote_date": df[c_date].map(_date) if c_date else "",
        "note": df[c_note].fillna("").astype(str).str.strip() if c_note else "",
    })
    out["row"] = range(2, len(out) + 2)  # số dòng trong file (dòng 1 = tiêu đề)
    out["price"] = out["price"].astype(object).where(out["price"].notna(), None)
    return out[(out["code"] != "") | (out["name"] != "") | out["price"].notna()].reset_index(drop=True)


def match_quotes(quotes: pd.DataFrame, master: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Khớp từng dòng báo giá với danh mục. Trả về (thay đổi giá, vấn đề). Bỏ qua dòng không có giá / giá không đổi."""
    by_code = {it.get("code"): it for it in master.get("standard_items", []) if it.get("code")}
    changes, issues, seen = [], [], {}
    for q in quotes.to_dict("records"):
        item = by_code.get(q["code"]) if q["code"] else None
        if item is None and q["name"]:
            item = find_catalog_item(q["name"], master)
        label = q["code"] or q["name"]
        if item is None:
            issues.append(f"Dòng {q['row']}: '{label}' không có trong danh mục")
            continue
        if q["price"] is None or pd.isna(q["price"]):
            continue  # chưa điền giá mới -> không đổi
        if q["price"] <= 0:
            issues.append(f"Dòng {q['row']}: giá của '{label}' phải lớn hơn 0")
            continue
        code = item["code"]
        if code in seen:
            issues.append(f"Dòng {q['row']}: '{label}' trùng với dòng {seen[code]} - lấy dòng sau")
            changes = [c for c in changes if c["code"] != code]
        seen[code] = q["row"]
        old = float(item.get("price") or 0)
        new = float(round(q["price"]))
        if new == old and not q["vendor"] and not q["quote_date"]:
            continue
        changes.append({"code": code, "name": item["name"], "unit": item.get("unit", ""), "old_price": old,
                        "new_price": new, "pct": (new - old) / old if old else None,
                        "vendor": q["vendor"], "quote_date": q["quote_date"], "note": q["note"]})
    return changes, issues


def line_impact(changes: List[Dict[str, Any]], lines_by_site: Dict[str, List[Dict[str, Any]]],
                editable_sites: set, include_manual: bool = False) -> pd.DataFrame:
    """Các dòng ngân sách chịu ảnh hưởng: mỗi dòng 1 hàng, cột action = 'đổi' / lý do giữ nguyên."""
    ch = {c["code"]: c for c in changes if c["new_price"] != c["old_price"]}
    rows = []
    for site, lines in lines_by_site.items():
        for i, l in enumerate(lines):
            c = ch.get(l.get("catalog_code"))
            if not c:
                continue
            price = float(l.get("unit_price") or 0)
            manual = abs(price - c["old_price"]) > 0.5
            if site not in editable_sites:
                action = "Giữ: site đã nộp/duyệt"
            elif manual and not include_manual:
                action = "Giữ: giá đã sửa tay"
            else:
                action = "Đổi"
            qty = float(l.get("quantity") or 0)
            rows.append({"site": site, "idx": i, "dept": l.get("dept_proposing", ""), "code": c["code"], "name": c["name"],
                         "invest_type": l.get("invest_type", ""), "quantity": qty, "old_unit_price": price,
                         "new_unit_price": c["new_price"] if action == "Đổi" else price,
                         "old_total": qty * price, "new_total": qty * (c["new_price"] if action == "Đổi" else price),
                         "action": action})
    return pd.DataFrame(rows, columns=["site", "idx", "dept", "code", "name", "invest_type", "quantity", "old_unit_price",
                                       "new_unit_price", "old_total", "new_total", "action"])


def apply_catalog_prices(master: Dict[str, Any], changes: List[Dict[str, Any]], today: str = None) -> int:
    """Ghi giá mới (+ nhà cung cấp, ngày báo giá) vào danh mục. Trả về số hạng mục đổi giá."""
    today = today or datetime.date.today().strftime("%Y-%m-%d")
    ch = {c["code"]: c for c in changes}
    n = 0
    for it in master.get("standard_items", []):
        c = ch.get(it.get("code"))
        if not c:
            continue
        if float(it.get("price") or 0) != c["new_price"]:
            n += 1
        it["price"] = int(c["new_price"])
        if c.get("vendor"):
            it["vendor"] = c["vendor"]
        it["price_date"] = c.get("quote_date") or today
    return n


def reprice_lines(lines: List[Dict[str, Any]], impact_site: pd.DataFrame) -> List[Dict[str, Any]]:
    """Bản sao các dòng của 1 site với đơn giá mới cho những dòng action = 'Đổi' (chưa tính lại thành tiền/phân kỳ)."""
    out = [dict(l) for l in lines]
    for r in impact_site[impact_site["action"] == "Đổi"].to_dict("records"):
        out[int(r["idx"])]["unit_price"] = float(r["new_unit_price"])
    return out
