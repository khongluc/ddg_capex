"""
Đọc file định biên nhân sự của Khối QTNNL (vd. "Tổng hợp định biên 2027 toàn Tập đoàn - Gửi CNTT.xlsx")
-> gán site theo "Nơi làm việc", gán bộ trang bị tiêu chuẩn theo vị trí / cấp bậc
-> gộp theo (site, phòng ban, bộ trang bị): nhân sự hiện có, định biên, nhân sự theo 12 tháng.
Không lưu họ tên / mã nhân viên.
"""
import datetime
import json
import math
import re
import unicodedata
from typing import Any, Dict, List, Tuple

import openpyxl
import pandas as pd

# Nơi làm việc -> mã site (so khớp chuỗi con, không phân biệt hoa thường; theo thứ tự)
DEFAULT_SITE_RULES: List[Tuple[str, str]] = [
    ("bạch đằng", "BDA"),
    ("an hạ", "AHA"), ("ahc", "AHA"),
    ("long an", "LAN"),
    ("bình chánh", "BCH"),
    ("nghi sơn", "NSO"),
    ("miền trung", "QNG"),
    ("vũng tàu", "VTA"),
    ("ba son", "BSO"),
    ("dự án", "TCO"), ("công trường", "TCO"), ("sân bay", "TCO"), ("hangar", "TCO"), ("apec", "TCO"),
    ("adamas", "TCO"), ("jefferson", "TCO"), ("kim long", "TCO"), ("qatar", "TCO"), ("mascot", "TCO"),
    ("nhà máy", "AHA"),
]
SITE_ASSUMED = {"ahc": "Giả định AHC = Nhà máy An Hạ", "nhà máy": "Giả định 'Nhà máy' (không ghi tên) = An Hạ",
                "": "Không ghi nơi làm việc - gán VP Bạch Đằng"}

LEADER_WORDS = ["tổng giám đốc", "giám đốc", "gđ dự án", "quản lý", "trưởng bộ phận", "phó bộ phận",
                "chánh văn phòng", "chỉ huy trưởng", "trợ lý tổng giám đốc", "trợ lý phó tổng giám đốc"]

# Quy tắc gán bộ trang bị: (mã bộ, lý do, hàm kiểm tra) - theo thứ tự, quy tắc đầu tiên khớp được dùng
KIT_RULES = [
    ("KIT06", "Cột Thiết bị = laptop, Phần mềm có AutoCAD", lambda r: "laptop" in r["it_device"] and "acad" in r["software"]),
    ("KIT01", "Cột Thiết bị = laptop", lambda r: "laptop" in r["it_device"]),
    ("KIT08", "Cột Thiết bị = desktop, Phần mềm có AutoCAD", lambda r: "desktop" in r["it_device"] and "acad" in r["software"]),
    ("KIT07", "Cột Thiết bị = desktop", lambda r: "desktop" in r["it_device"]),
    ("KIT09", "Lái xe / phụ kho / công nhân",
     lambda r: re.search(r"tài xế|lái xe|phụ kho|công nhân|bảo vệ|tạp vụ|phục vụ", r["position"] + " " + r["level"]) is not None),
    ("KIT04", "Cấp quản lý", lambda r: any(w in r["level"] for w in LEADER_WORDS)),
    ("KIT03", "Kết cấu / Tekla / BIM / Shop drawing",
     lambda r: re.search(r"tekla|kết cấu|bim|shop|cutting plan|3d", r["position"]) is not None),
    ("KIT02", "Thiết kế / vẽ / biện pháp", lambda r: re.search(r"thiết kế|vẽ|biện pháp", r["position"]) is not None),
    ("KIT08", "Dự toán / khối lượng / QS / báo giá",
     lambda r: re.search(r"dự toán|khối lượng|\bqs\b|báo giá", r["position"]) is not None),
    ("KIT06", "Kỹ sư / giám sát / quản lý dự án",
     lambda r: re.search(r"kỹ sư|giám sát|qlda|quản lý dự án|điều phối dự án", r["position"]) is not None),
    ("KIT05", "Nhân viên tại nhà máy / công trường / kho",
     lambda r: (r["site"] != "BDA" and r["level"].startswith("nhân viên")) or "kho" in r["position"]),
    ("KIT01", "Mặc định: nhân viên văn phòng", lambda r: True),
]


def _txt(v) -> str:
    return unicodedata.normalize("NFC", " ".join(str(v).split()).strip()) if v is not None else ""


def _num(v):
    """Số hoặc None (ô trống / lỗi #REF!)."""
    if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
        return float(v)
    return None


def map_site(location: str, rules: List[Tuple[str, str]] = None) -> Tuple[str, str]:
    """-> (mã site, ghi chú giả định)."""
    loc = location.lower()
    if not loc:
        return "BDA", SITE_ASSUMED[""]
    for key, code in rules or DEFAULT_SITE_RULES:
        if key in loc:
            return code, SITE_ASSUMED.get(loc.strip(), "")
    return "BDA", f"Không nhận diện '{location}' - gán VP Bạch Đằng"


def assign_kit(r: Dict[str, Any], valid_kits: set) -> Tuple[str, str]:
    for code, reason, test in KIT_RULES:
        if code in valid_kits and test(r):
            return code, reason
    return "KIT01", "Mặc định"


def position_key(position: str, level: str) -> str:
    return f"{position.lower()} | {level.lower()}"


def read_roster(file_source, valid_kits: set, site_overrides: Dict[str, str] = None,
                kit_overrides: Dict[str, str] = None) -> Dict[str, Any]:
    """Đọc file định biên -> {positions: DataFrame, months: [...], fiscal_year, issues: [...]}."""
    wb = openpyxl.load_workbook(file_source, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    # Dòng tiêu đề: dòng có ô "Phòng" và "Định biên ..." (mặc định dòng 3)
    hdr_idx = next((i for i, r in enumerate(rows[:20]) if r and any(_txt(v) == "Phòng" for v in r)), 2)
    hdr = [_txt(v) if not isinstance(v, (datetime.date, datetime.datetime)) else v for v in rows[hdr_idx]]

    def col(name_start: str) -> int:
        for i, h in enumerate(hdr):
            if isinstance(h, str) and h.lower().startswith(unicodedata.normalize("NFC", name_start).lower()):
                return i
        raise ValueError(f"Không tìm thấy cột '{name_start}' trong file định biên")

    c = {"entity": col("Pháp nhân"), "division": col("Khối"), "dept": col("Phòng"), "unit": col("Bộ phận"),
         "position": col("Vị trí công việc"), "name": col("Họ và tên"), "location": col("Nơi làm việc"),
         "level": col("Cấp bậc"), "it_device": col("Thiết bị CNTT"), "software": col("Phần mềm"),
         "db_prev": col("Định biên 20"), "actual": col("Nhân sự thực tế"), "plan": None}
    plan_cols = [i for i, h in enumerate(hdr) if isinstance(h, str) and h.lower().startswith("định biên 20")]
    c["plan"] = plan_cols[-1] if plan_cols else None
    month_cols = [i for i, h in enumerate(hdr) if isinstance(h, (datetime.date, datetime.datetime))]
    months = [hdr[i] for i in month_cols]
    fiscal_year = months[-1].year if months else None

    overrides = {k.lower(): v for k, v in (site_overrides or {}).items()}
    positions, issues = [], []
    for ridx, r in enumerate(rows[hdr_idx + 2:], start=hdr_idx + 3):
        if not r or not any(v is not None for v in r[c["entity"]:c["level"] + 1]):
            continue
        dept = _txt(r[c["dept"]])
        if not dept:
            continue
        loc = _txt(r[c["location"]])
        site, site_note = (overrides[loc.lower()], "Theo điều chỉnh khi nhập") if loc.lower() in overrides else map_site(loc)
        series = [_num(r[i]) for i in month_cols]
        plan = _num(r[c["plan"]]) if c["plan"] is not None else None
        if plan is None:
            known = [v for v in series if v is not None]
            plan = known[-1] if known else 0.0
            if r[c["plan"]] is not None:
                issues.append(f"Dòng {ridx}: Định biên lỗi ({r[c['plan']]}) - lấy theo nhân sự tháng cuối = {plan:g}")
        actual = _num(r[c["actual"]]) or 0.0
        rec = {
            "entity": _txt(r[c["entity"]]), "division": _txt(r[c["division"]]), "dept": dept,
            "unit": _txt(r[c["unit"]]), "position": _txt(r[c["position"]]).lower(), "position_label": _txt(r[c["position"]]),
            "level": _txt(r[c["level"]]).lower(), "location": loc, "site": site, "site_note": site_note,
            "it_device": _txt(r[c["it_device"]]).lower(), "software": _txt(r[c["software"]]).lower(),
            "actual": actual, "plan": plan, "is_new": "tuyển" in _txt(r[c["name"]]).lower(),
            "months": [v if v is not None else 0.0 for v in series],
        }
        ov = (kit_overrides or {}).get(position_key(rec["position"], rec["level"]))
        if ov in valid_kits:
            rec["kit"], rec["kit_reason"] = ov, "Điều chỉnh theo vị trí"
        else:
            rec["kit"], rec["kit_reason"] = assign_kit(rec, valid_kits)
        positions.append(rec)
    return {"positions": pd.DataFrame(positions), "months": months, "fiscal_year": fiscal_year, "issues": issues}


def aggregate(positions: pd.DataFrame) -> List[Dict[str, Any]]:
    """Gộp theo (site, phòng ban, bộ trang bị) -> dòng dept_headcount."""
    out = []
    if positions.empty:
        return out
    for (site, dept, kit), g in positions.groupby(["site", "dept", "kit"], sort=True):
        months = [round(sum(vals), 4) for vals in zip(*g["months"].tolist())] if len(g) else []
        out.append({"site_code": site, "dept": dept, "kit_code": kit,
                    "hc_current": float(g["actual"].sum()), "hc_plan": float(g["plan"].sum()),
                    "hc_months": json.dumps(months)})
    return out


def estimate_inventory(headcount_rows: List[Dict[str, Any]], kits: List[Dict[str, Any]]) -> Dict[str, float]:
    """Thiết bị / bản quyền hiện có ƯỚC TÍNH = nhân sự hiện có × bộ trang bị (làm tròn lên)."""
    kit_map = {k["code"]: k for k in kits}
    acc: Dict[str, float] = {}
    for h in headcount_rows:
        kit = kit_map.get(h["kit_code"])
        if not kit:
            continue
        for ki in kit["items"]:
            acc[ki["catalog_code"]] = acc.get(ki["catalog_code"], 0.0) + h["hc_current"] * float(ki["qty_per_person"])
    return {k: float(math.ceil(round(v, 6))) for k, v in acc.items() if v > 0}
