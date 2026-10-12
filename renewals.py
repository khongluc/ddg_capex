"""Nhắc gia hạn: hạng mục định kỳ (thuê bao phần mềm, dịch vụ theo năm / tháng, gia hạn - bảo trì) có trong ngân sách
năm trước nhưng năm đang lập chưa có hoặc ít hơn - tránh quên phí gia hạn khi lập ngân sách năm mới.
So khớp theo site + mã danh mục (không có mã: theo tên chuẩn hóa); không phân biệt phòng ban (license hay chuyển phòng)."""
from typing import Any, Dict, Optional

import pandas as pd

from capex_engine import clean_number
from master_data import KIND_SW_SUBSCRIPTION, _norm

RENEW_INVEST = "Gia hạn, bảo trì"
STATUS_MISSING = "Chưa có"
STATUS_LESS = "Ít hơn năm trước"
COLUMNS = ["site_code", "catalog_code", "item_name", "unit", "depts", "prev_qty", "prev_amount",
           "cur_qty", "missing_qty", "est_amount", "status"]


def _txt(v: Any) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def is_recurring(line: Dict[str, Any], item: Optional[Dict[str, Any]] = None) -> bool:
    """Hạng mục phải trả lại mỗi năm: thuê bao phần mềm, ĐVT theo năm / tháng (dịch vụ thuê, đường truyền, cloud),
    hoặc dòng hình thức "Gia hạn, bảo trì". Dịch vụ 1 lần (tư vấn, đào tạo - ĐVT Gói / Lần / Khóa) không tính."""
    item = item or {}
    kind = _txt(line.get("item_kind")) or _txt(item.get("kind"))
    unit = (_txt(line.get("unit")) or _txt(item.get("unit"))).lower()
    return (kind == KIND_SW_SUBSCRIPTION or "/năm" in unit or unit == "tháng" or unit.endswith("/tháng")
            or _txt(line.get("invest_type")) == RENEW_INVEST)


def _key(line: Dict[str, Any]) -> tuple:
    code = _txt(line.get("catalog_code"))
    return _txt(line.get("site_code")), code or "#" + _norm(line.get("item_name"))


def renewal_gaps(prev: Optional[pd.DataFrame], cur: Optional[pd.DataFrame], master: Dict[str, Any]) -> pd.DataFrame:
    """Bảng nhắc gia hạn (tiền ước tính = SL thiếu × đơn giá bình quân năm trước), sắp theo tiền giảm dần."""
    if prev is None or prev.empty:
        return pd.DataFrame(columns=COLUMNS)
    by_code = {it.get("code"): it for it in master.get("standard_items", [])}
    cur_qty: Dict[tuple, float] = {}
    for line in ([] if cur is None or cur.empty else cur.to_dict("records")):
        k = _key(line)
        cur_qty[k] = cur_qty.get(k, 0.0) + clean_number(line.get("quantity"), 0.0)

    agg: Dict[tuple, Dict[str, Any]] = {}
    for line in prev.to_dict("records"):
        if not is_recurring(line, by_code.get(_txt(line.get("catalog_code")))):
            continue
        k = _key(line)
        a = agg.setdefault(k, {"site_code": k[0], "catalog_code": _txt(line.get("catalog_code")),
                               "item_name": _txt(line.get("item_name")), "unit": _txt(line.get("unit")),
                               "depts": [], "prev_qty": 0.0, "prev_amount": 0.0})
        a["prev_qty"] += clean_number(line.get("quantity"), 0.0)
        a["prev_amount"] += clean_number(line.get("total_budget"), 0.0)
        dept = _txt(line.get("dept_proposing"))
        if dept and dept not in a["depts"]:
            a["depts"].append(dept)

    out = []
    for k, a in agg.items():
        now = cur_qty.get(k, 0.0)
        missing = a["prev_qty"] - now
        if a["prev_qty"] <= 0 or missing <= 1e-9:
            continue
        out.append({**a, "depts": ", ".join(a["depts"]), "cur_qty": now, "missing_qty": missing,
                    "est_amount": round(missing * a["prev_amount"] / a["prev_qty"]),
                    "status": STATUS_MISSING if now <= 0 else STATUS_LESS})
    df = pd.DataFrame(out, columns=COLUMNS)
    return df.sort_values("est_amount", ascending=False, kind="stable").reset_index(drop=True)
