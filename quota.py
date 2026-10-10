"""
Định biên thiết bị & phần mềm theo phòng ban:
  Định mức = Σ (nhân sự định biên của vị trí × số lượng/người trong bộ trang bị tiêu chuẩn), làm tròn lên
  Thiết bị / phần mềm vĩnh viễn: mua bổ sung = max(0, định mức - hiện có) ; thay thế = số khai báo cần thay
  Phần mềm thuê bao / dịch vụ:   gia hạn = min(hiện có, định mức) ; mua mới = max(0, định mức - hiện có)
"""
import json
import math
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd

from master_data import (
    KIND_SW_SUBSCRIPTION,
    KIND_SERVICE,
    apply_it_catalog,
)

NEED_QUOTA = "Định biên"
NEED_NEW = "Phát sinh mới"
NEED_INFRA = "Hạ tầng dùng chung"
NEED_TYPES = [NEED_QUOTA, NEED_NEW, NEED_INFRA]
NEED_WITH_REASON = (NEED_NEW, NEED_INFRA)  # bắt buộc ghi lý do / căn cứ

# Bộ trang bị tiêu chuẩn mặc định (Admin sửa ở tab Quản lý Danh mục) - số lượng tính trên 1 nhân sự
DEFAULT_STANDARD_KITS = [
    {"code": "KIT01", "name": "Nhân viên văn phòng", "items": [
        {"catalog_code": "IT01-004", "qty_per_person": 1},    # Laptop Core i5
        {"catalog_code": "IT01-010", "qty_per_person": 1},    # Màn hình 24"
        {"catalog_code": "IT09-007", "qty_per_person": 1},    # M365 Business Standard
        {"catalog_code": "IT05-006", "qty_per_person": 1},    # Kaspersky
        {"catalog_code": "IT02-001", "qty_per_person": 0.1},  # Máy in A4: 1 máy / 10 người
        {"catalog_code": "IT09-011", "qty_per_person": 1},    # PDF
    ]},
    {"code": "KIT02", "name": "Kỹ sư thiết kế (CAD)", "items": [
        {"catalog_code": "IT01-008", "qty_per_person": 1},    # Workstation
        {"catalog_code": "IT01-011", "qty_per_person": 2},    # 2 màn hình 27"
        {"catalog_code": "IT09-007", "qty_per_person": 1},
        {"catalog_code": "IT05-006", "qty_per_person": 1},
        {"catalog_code": "IT10-001", "qty_per_person": 1},    # AutoCAD
        {"catalog_code": "IT09-011", "qty_per_person": 1},    # PDF
    ]},
    {"code": "KIT03", "name": "Kỹ sư kết cấu / BIM (Tekla, Revit)", "items": [
        {"catalog_code": "IT01-009", "qty_per_person": 1},    # Workstation cao cấp
        {"catalog_code": "IT01-011", "qty_per_person": 2},
        {"catalog_code": "IT09-007", "qty_per_person": 1},
        {"catalog_code": "IT05-006", "qty_per_person": 1},
        {"catalog_code": "IT10-004", "qty_per_person": 1},    # Tekla Structures
        {"catalog_code": "IT09-011", "qty_per_person": 1},    # PDF
    ]},
    {"code": "KIT04", "name": "Cán bộ quản lý (Trưởng/Phó phòng)", "items": [
        {"catalog_code": "IT01-005", "qty_per_person": 1},    # Laptop Core i7
        {"catalog_code": "IT01-011", "qty_per_person": 1},
        {"catalog_code": "IT09-008", "qty_per_person": 1},    # M365 E3
        {"catalog_code": "IT05-006", "qty_per_person": 1},
        {"catalog_code": "IT09-011", "qty_per_person": 1},    # PDF
    ]},
    {"code": "KIT05", "name": "Nhân viên sản xuất / công trường (dùng chung)", "items": [
        {"catalog_code": "IT01-001", "qty_per_person": 0.2},  # 1 máy bàn dùng chung / 5 người
        {"catalog_code": "IT09-006", "qty_per_person": 1},    # M365 Business Basic (email)
        {"catalog_code": "IT05-006", "qty_per_person": 0.2},
    ]},
    {"code": "KIT06", "name": "Kỹ sư dự án / kinh doanh (laptop + AutoCAD)", "items": [
        {"catalog_code": "IT01-004", "qty_per_person": 1},
        {"catalog_code": "IT01-010", "qty_per_person": 1},
        {"catalog_code": "IT09-007", "qty_per_person": 1},
        {"catalog_code": "IT05-006", "qty_per_person": 1},
        {"catalog_code": "IT10-001", "qty_per_person": 1},
        {"catalog_code": "IT09-011", "qty_per_person": 1},    # PDF
    ]},
    {"code": "KIT07", "name": "Nhân viên văn phòng (máy bàn)", "items": [
        {"catalog_code": "IT01-002", "qty_per_person": 1},    # Máy bàn Core i5
        {"catalog_code": "IT01-010", "qty_per_person": 1},
        {"catalog_code": "IT09-007", "qty_per_person": 1},
        {"catalog_code": "IT05-006", "qty_per_person": 1},
        {"catalog_code": "IT02-001", "qty_per_person": 0.1},
        {"catalog_code": "IT09-011", "qty_per_person": 1},    # PDF
    ]},
    {"code": "KIT08", "name": "Dự toán / khối lượng / QS (máy bàn + AutoCAD)", "items": [
        {"catalog_code": "IT01-003", "qty_per_person": 1},    # Máy bàn Core i7
        {"catalog_code": "IT01-011", "qty_per_person": 2},
        {"catalog_code": "IT09-007", "qty_per_person": 1},
        {"catalog_code": "IT05-006", "qty_per_person": 1},
        {"catalog_code": "IT10-001", "qty_per_person": 1},
        {"catalog_code": "IT09-011", "qty_per_person": 1},    # PDF
    ]},
    {"code": "KIT09", "name": "Lái xe / phụ kho / công nhân (chỉ email)", "items": [
        {"catalog_code": "IT09-006", "qty_per_person": 1},    # M365 Business Basic
    ]},
]


def standard_kits(master: Dict[str, Any]) -> List[Dict[str, Any]]:
    return master.get("standard_kits") or DEFAULT_STANDARD_KITS


def catalog_by_code(master: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {it.get("code"): it for it in master.get("standard_items", []) if it.get("code")}


def parse_months(v) -> List[float]:
    """Chuỗi JSON / list nhân sự theo 12 tháng -> list số."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return []
    return [_num(x) for x in v] if isinstance(v, list) else []


def _num(v, default=0.0) -> float:
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_kit_items(v) -> Optional[List[Dict[str, Any]]]:
    """Trang bị phòng ban tự chọn cho 1 vị trí (JSON). None = dùng bộ trang bị tiêu chuẩn."""
    if v is None or (isinstance(v, float) and math.isnan(v)) or v == "":
        return None
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return None
    if not isinstance(v, list):
        return None
    out = []
    for x in v:
        if isinstance(x, dict) and x.get("catalog_code"):
            out.append({"catalog_code": str(x["catalog_code"]), "qty_per_person": _num(x.get("qty_per_person")),
                        "fixed_qty": _num(x.get("fixed_qty")), "note": str(x.get("note") or "")})
    return out


def kit_items_of(h: Dict[str, Any], kits: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Danh sách trang bị áp cho 1 dòng định biên: phòng ban tự chọn, không có thì theo bộ tiêu chuẩn."""
    custom = parse_kit_items(h.get("kit_items"))
    if custom is not None:
        return custom
    kit = kits.get(h.get("kit_code"))
    return list(kit["items"]) if kit else []


def compute_needs(headcount: List[Dict[str, Any]], inventory: List[Dict[str, Any]], master: Dict[str, Any]) -> pd.DataFrame:
    """Bảng nhu cầu theo hạng mục cho 1 phòng ban."""
    catalog = catalog_by_code(master)
    kits = {k["code"]: k for k in standard_kits(master)}
    norm_qty: Dict[str, float] = {}
    shared_only: Dict[str, bool] = {}  # chỉ có định mức lẻ < 1/người (vd. máy in 1/10 người) -> làm tròn gần nhất
    basis: Dict[str, List[str]] = {}
    month_need: Dict[str, List[float]] = {}  # nhu cầu tăng thêm theo tháng (nhân sự theo tháng) -> phân kỳ mua mới
    for h in headcount:
        kit = kits.get(h.get("kit_code"))
        plan = _num(h.get("hc_plan"))
        if not kit or plan <= 0:
            continue
        custom = parse_kit_items(h.get("kit_items")) is not None
        pos_name = kit["name"] + (" (tự chọn)" if custom else "")
        increments = []
        prev = _num(h.get("hc_current"))
        for v in parse_months(h.get("hc_months")):
            increments.append(max(0.0, v - prev))
            prev = max(prev, v)
        for ki in kit_items_of(h, kits):
            code = ki["catalog_code"]
            fixed = _num(ki.get("fixed_qty"))
            if fixed > 0:  # số lượng cố định cho cả vị trí (vd. 3 bản quyền Tekla cho 10 kỹ sư)
                norm_qty[code] = norm_qty.get(code, 0.0) + fixed
                shared_only[code] = False
                basis.setdefault(code, []).append(f"{fixed:g} cho {pos_name}")
                continue
            q = _num(ki.get("qty_per_person"))
            if q <= 0:
                continue
            norm_qty[code] = norm_qty.get(code, 0.0) + plan * q
            shared_only[code] = shared_only.get(code, True) and q < 1
            basis.setdefault(code, []).append(f"{plan:g} {pos_name} × {q:g}")
            if increments:
                acc = month_need.setdefault(code, [0.0] * len(increments))
                for i, d in enumerate(increments[:len(acc)]):
                    acc[i] += d * q

    inv = {r["catalog_code"]: r for r in inventory}
    rows = []
    for code in list(dict.fromkeys(list(norm_qty) + list(inv))):
        item = catalog.get(code)
        if not item:
            continue
        r = inv.get(code, {})
        raw_q = round(norm_qty.get(code, 0.0), 6)
        # Thiết bị dùng chung: làm tròn gần nhất (0,3 máy in -> 0, dùng chung với phòng khác); còn lại làm tròn lên
        dinh_muc = int(math.floor(raw_q + 0.5)) if shared_only.get(code) else math.ceil(raw_q)
        override = r.get("quota_override")
        quota = int(_num(override)) if override is not None and not (isinstance(override, float) and math.isnan(override)) else dinh_muc
        current = _num(r.get("current_qty"))
        replace = _num(r.get("replace_qty"))
        kind = item.get("kind")
        if kind in (KIND_SW_SUBSCRIPTION, KIND_SERVICE):
            renew, add, replace = min(current, quota), max(0.0, quota - current), 0.0
        else:
            renew, add = 0.0, max(0.0, quota - current)
        price = _num(item.get("price"))
        rows.append({
            "catalog_code": code, "item_name": item["name"], "group": item.get("group"), "kind": kind,
            "unit": item.get("unit", ""), "price": price,
            "dinh_muc": dinh_muc, "quota_override": override, "quota": quota,
            "current_qty": current, "replace_qty": replace,
            "add_qty": add, "renew_qty": renew, "propose_qty": add + renew + replace,
            "propose_value": (add + renew + replace) * price,
            "basis": "; ".join(basis.get(code, [])) or "Khai báo trực tiếp",
            "note": r.get("note") or "",
            "add_weights": month_need.get(code),
        })
    return pd.DataFrame(rows, columns=[
        "catalog_code", "item_name", "group", "kind", "unit", "price", "dinh_muc", "quota_override", "quota",
        "current_qty", "replace_qty", "add_qty", "renew_qty", "propose_qty", "propose_value", "basis", "note", "add_weights"])


def build_quota_lines(needs: pd.DataFrame, dept: str, old_lines: List[Dict[str, Any]], months: List[str],
                      master: Dict[str, Any], defaults: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Sinh các dòng ngân sách loại 'Định biên' (giữ phân kỳ/ngày đã chỉnh của dòng cũ cùng hạng mục & hình thức)."""
    catalog = catalog_by_code(master)
    previous = {(l.get("catalog_code"), l.get("invest_type")): l for l in old_lines}
    lines = []
    for _, n in needs.iterrows():
        item = catalog.get(n["catalog_code"])
        parts: List[Tuple[str, float, str]] = []
        if n["add_qty"] > 0:
            parts.append(("Mua mới", n["add_qty"], "Bổ sung theo định biên"))
        if n["renew_qty"] > 0:
            parts.append(("Gia hạn, bảo trì", n["renew_qty"], "Gia hạn theo định biên"))
        if n["replace_qty"] > 0:
            parts.append(("Nâng cấp, thay thế", n["replace_qty"], "Thay thế thiết bị cũ / hết khấu hao"))
        for invest_type, qty, detail in parts:
            row = dict(defaults)
            row.update({"item_name": item["name"], "detail_work": detail, "quantity": qty,
                        "unit_price": n["price"], "dept_proposing": dept, "dept_using": dept,
                        "need_type": NEED_QUOTA, "need_reason": f"Định biên: {n['basis']}", "auto_quota": True})
            apply_it_catalog(row, master, item=item, invest_type=invest_type)
            prev = previous.get((item.get("code"), invest_type))
            if prev:
                for k, v in prev.items():
                    if k.startswith("pct_") or k in ("contract_date", "completion_date", "handover_date", "supplier", "entity"):
                        row[k] = v
            else:
                weights = n.get("add_weights") if invest_type == "Mua mới" else None
                total = sum(weights) if isinstance(weights, list) else 0
                for i, m in enumerate(months):
                    if total > 0:
                        row[f"pct_{m}"] = round(weights[i] / total, 4) if i < len(weights) else 0.0
                    else:
                        row[f"pct_{m}"] = 1.0 if i == 0 else 0.0
                if total > 0:  # làm tròn để tổng đúng 100%
                    first = next(m for i, m in enumerate(months) if i < len(weights) and weights[i] > 0)
                    row[f"pct_{first}"] = round(row[f"pct_{first}"] + 1.0 - sum(row[f"pct_{m}"] for m in months), 4)
            lines.append(row)
    return lines
