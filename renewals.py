"""Nhắc gia hạn: hạng mục định kỳ (thuê bao phần mềm, dịch vụ theo năm / tháng, gia hạn - bảo trì) có trong ngân sách
năm trước nhưng năm đang lập chưa có hoặc ít hơn - tránh quên phí gia hạn khi lập ngân sách năm mới.
So khớp theo site + mã danh mục (không có mã: theo tên chuẩn hóa); không phân biệt phòng ban (license hay chuyển phòng)."""
from typing import Any, Dict, Optional

import pandas as pd

from capex_engine import clean_number
from master_data import KIND_SW_SUBSCRIPTION, _norm, apply_it_catalog

RENEW_INVEST = "Gia hạn, bảo trì"
STATUS_MISSING = "Chưa có"
STATUS_LESS = "Ít hơn năm trước"
STATUS_WAIT_QUOTA = "Chờ sinh từ Định biên"  # dòng định biên năm trước, site chưa sinh định biên năm nay
NEED_QUOTA = "Định biên"
COLUMNS = ["site_code", "catalog_code", "item_name", "unit", "depts", "prev_qty", "prev_amount",
           "cur_qty", "missing_qty", "est_amount", "status", "entity", "need_type", "invest_type"]
NEED_INFRA = "Hạ tầng dùng chung"
NEED_NEW = "Phát sinh mới"


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


def is_quota_line(line: Dict[str, Any]) -> bool:
    """Dòng sinh từ Định biên: SL theo số người năm đó, không so với năm trước."""
    auto = line.get("auto_quota")
    return _txt(line.get("need_type")) == NEED_QUOTA or (auto is True or str(auto).lower() == "true")


def _key(line: Dict[str, Any]) -> tuple:
    code = _txt(line.get("catalog_code"))
    return _txt(line.get("site_code")), code or "#" + _norm(line.get("item_name")), is_quota_line(line)


def renewal_gaps(prev: Optional[pd.DataFrame], cur: Optional[pd.DataFrame], master: Dict[str, Any]) -> pd.DataFrame:
    """Bảng nhắc gia hạn (tiền ước tính = SL thiếu × đơn giá bình quân năm trước), sắp theo tiền giảm dần.
    Dòng định biên tách riêng: site năm nay đã sinh định biên -> bỏ qua (SL theo số người, giảm là do nhân sự);
    chưa sinh -> trạng thái "Chờ sinh từ Định biên" (sinh ở tab Định biên, không thêm tay ở đây)."""
    if prev is None or prev.empty:
        return pd.DataFrame(columns=COLUMNS)
    by_code = {it.get("code"): it for it in master.get("standard_items", [])}
    cur_qty: Dict[tuple, float] = {}
    quota_sites = set()  # site năm nay đã có dòng định biên
    for line in ([] if cur is None or cur.empty else cur.to_dict("records")):
        k = _key(line)
        cur_qty[k] = cur_qty.get(k, 0.0) + clean_number(line.get("quantity"), 0.0)
        if k[2]:
            quota_sites.add(k[0])

    agg: Dict[tuple, Dict[str, Any]] = {}
    for line in prev.to_dict("records"):
        if not is_recurring(line, by_code.get(_txt(line.get("catalog_code")))):
            continue
        k = _key(line)
        a = agg.setdefault(k, {"site_code": k[0], "catalog_code": _txt(line.get("catalog_code")),
                               "item_name": _txt(line.get("item_name")), "unit": _txt(line.get("unit")),
                               "depts": [], "prev_qty": 0.0, "prev_amount": 0.0, "entity": _txt(line.get("entity")),
                               "need_type": _txt(line.get("need_type")), "invest_type": _txt(line.get("invest_type"))})
        a["prev_qty"] += clean_number(line.get("quantity"), 0.0)
        a["prev_amount"] += clean_number(line.get("total_budget"), 0.0)
        dept = _txt(line.get("dept_proposing"))
        if dept and dept not in a["depts"]:
            a["depts"].append(dept)

    out = []
    for k, a in agg.items():
        site, _, quota = k
        if quota and site in quota_sites:
            continue
        now = cur_qty.get(k, 0.0)
        missing = a["prev_qty"] - now
        if a["prev_qty"] <= 0 or missing <= 1e-9:
            continue
        status = STATUS_WAIT_QUOTA if quota else (STATUS_MISSING if now <= 0 else STATUS_LESS)
        out.append({**a, "depts": ", ".join(a["depts"]), "cur_qty": now, "missing_qty": missing,
                    "est_amount": round(missing * a["prev_amount"] / a["prev_qty"]), "status": status})
    df = pd.DataFrame(out, columns=COLUMNS)
    return df.sort_values("est_amount", ascending=False, kind="stable").reset_index(drop=True)


def renewal_line(gap: Dict[str, Any], qty: float, units: Optional[list], months: list, master: Dict[str, Any],
                 prev_year: Any, location: str) -> Dict[str, Any]:
    """Dòng ngân sách gia hạn cho 1 hạng mục trong bảng nhắc (chưa tính - gọi calculate_row sau).
    Đơn giá: giá danh mục hiện hành, không có thì bình quân năm trước. Phòng ban: phòng đầu tiên năm trước.
    Nhu cầu: hạ tầng dùng chung giữ nguyên, còn lại "Phát sinh mới" (dòng định biên do tab Định biên tự sinh)."""
    by_code = {it.get("code"): it for it in master.get("standard_items", [])}
    item = by_code.get(gap.get("catalog_code")) if gap.get("catalog_code") else None
    prev_price = clean_number(gap.get("prev_amount"), 0.0) / clean_number(gap.get("prev_qty"), 1.0) if gap.get("prev_qty") else 0.0
    price = clean_number((item or {}).get("price"), 0.0) or prev_price
    dept = (_txt(gap.get("depts")).split(", ") or [""])[0]
    infra = gap.get("need_type") == NEED_INFRA
    row = {"entity": gap.get("entity") or "DDC", "location": location, "item_name": gap.get("item_name"),
           "unit": gap.get("unit"), "quantity": float(qty), "unit_price": float(price),
           "dept_proposing": dept, "dept_using": "Dùng chung toàn site" if infra else dept,
           "need_type": NEED_INFRA if infra else NEED_NEW,
           "need_reason": f"Gia hạn từ ngân sách {prev_year}", "detail_work": f"Gia hạn ({prev_year})",
           "catalog_code": gap.get("catalog_code") or ""}
    invest = RENEW_INVEST  # năm trước có thể là "Mua mới" (năm đầu) - năm nay là gia hạn
    if item:
        apply_it_catalog(row, master, item=item, invest_type=invest)
    row["unit_price"], row["invest_type"] = float(price), invest
    units = units if units and len(units) == len(months) and sum(units) > 0 else None
    for i, m in enumerate(months):
        row[f"pct_{m}"] = units[i] / sum(units) if units else (1.0 if i == 0 else 0.0)
    return row
