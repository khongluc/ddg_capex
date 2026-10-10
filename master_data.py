"""
Master data management and code generation for CAPEX Web App
Specialized for CNTT (Information Technology - IT Department)
"""
import json
import os
from typing import Dict, List, Any, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_DATA_FILE = os.environ.get("ICOST_MASTER_PATH", os.path.join(BASE_DIR, "master_data.json"))

# Default entities
DEFAULT_ENTITIES = [
    {"code": "A01", "name": "DDC"},
    {"code": "A04", "name": "DD2"},
    {"code": "A05", "name": "DD3"},
    {"code": "A02", "name": "DMT"},
    {"code": "A06", "name": "DNS"},
    {"code": "A07", "name": "DVT"}
]

# Default sites / locations
DEFAULT_SITES = [
    {"code": "AHA", "name": "NM An Hạ"},
    {"code": "LAN", "name": "NM Long An"},
    {"code": "BCH", "name": "NM Bình Chánh"},
    {"code": "QNG", "name": "NM Miền Trung"},
    {"code": "BSO", "name": "NX Ba Son"},
    {"code": "NSO", "name": "NM Nghi Sơn"},
    {"code": "VTA", "name": "NM Vũng Tàu"},
    {"code": "TCO", "name": "Thi công/Công Trường"},
    {"code": "BDA", "name": "VP Bạch Đằng"}
]

# Asset Category Level 1
DEFAULT_ASSET_CAT1 = [
    {"name": "A. Nhà cửa, vật kiến trúc", "code3": "01", "code4": "04"},
    {"name": "B. Máy móc thiết bị", "code3": "02", "code4": "03"},
    {"name": "C. Phương tiện vận tải", "code3": "03", "code4": "04"},
    {"name": "D. Thiết bị, dụng cụ quản lý", "code3": "04", "code4": "05"},
    {"name": "E. Bản quyền, Phần mềm", "code3": "05", "code4": "06"}
]

# Asset Category Level 2
DEFAULT_ASSET_CAT2 = [
    "A1. NCVK: Xây dựng mới",
    "A2. NCVK: Nâng cấp, mở rộng",
    "A3. NCVK: Bảo trì, bảo dưỡng",
    "B1. MMTB: Mua mới",
    "B2. MMTB: Nâng cấp",
    "B3. MMTB: Bảo trì, bảo dưỡng",
    "C1. PTVT: Mua mới",
    "C2. PTVT: Nâng cấp, đại tu",
    "D1. TBQL: Mua mới",
    "D2. TBQL: Thay thế, nâng cấp",
    "E1. PM: Bản quyền mới",
    "E2. PM: Gia hạn / Nâng cấp"
]

# Cost Categories Level 1 & 2
DEFAULT_COST_LV1 = [
    "01. Chi phí pháp lý",
    "02. Chi phí đất đai",
    "03. Chi phí xây dựng",
    "04. Chi phí MMTB",
    "05. Chi phí quản lý dự án",
    "06. Chi phí tư vấn đầu tư",
    "07. Chi phí khác"
]

DEFAULT_COST_LV2 = [
    "01.01. Chi phí lập báo cáo nghiên cứu khả thi",
    "01.02. Chi phí thẩm tra báo cáo nghiên cứu khả thi",
    "01.03. Chi phí khảo sát đo vẽ bản đồ hiện trạng",
    "01.04. Chi phí xin điều chỉnh quy hoạch, phê duyệt chủ trương",
    "02.01. Chi phí bồi thường, giải phóng mặt bằng",
    "02.02. Tiền thuê đất, sử dụng đất",
    "03.01. Chi phí phá dỡ công trình cũ",
    "03.02. Chi phí san lấp mặt bằng",
    "03.13. Chi phí nhà xưởng vật kiến trúc xây mới",
    "03.14. Chi phí cải tạo, sửa chữa lớn nhà xưởng",
    "04.01. Máy móc thiết bị đầu tư mới",
    "04.02. Máy móc thiết bị nâng cấp, cải tiến",
    "04.03. Thiết bị công nghệ thông tin, văn phòng",
    "04.04. Phương tiện vận tải mới",
    "05.01. Chi phí quản lý dự án nội bộ",
    "06.01. Chi phí thiết kế kỹ thuật, bản vẽ",
    "07.01. Chi phí dự phòng, khác"
]

DEFAULT_MONTHS = [
    "T10 2025", "T11 2025", "T12 2025",
    "T1 2026", "T2 2026", "T3 2026", "T4 2026",
    "T5 2026", "T6 2026", "T7 2026", "T8 2026", "T9 2026"
]

def fiscal_months(budget_year) -> List[str]:
    """12 tháng của năm ngân sách: T10 năm trước -> T9 năm ngân sách"""
    y = int(budget_year)
    return [f"T{m} {y - 1}" for m in (10, 11, 12)] + [f"T{m} {y}" for m in range(1, 10)]

# Loại hạng mục CNTT -> quyết định cách hạch toán
KIND_HARDWARE = "hardware"
KIND_COMPONENT = "component"
KIND_SW_PERPETUAL = "software_perpetual"
KIND_SW_SUBSCRIPTION = "software_subscription"
KIND_SERVICE = "service"

DEFAULT_IT_KINDS = {
    KIND_HARDWARE: "Phần cứng",
    KIND_COMPONENT: "Linh kiện / vật tư",
    KIND_SW_PERPETUAL: "Phần mềm bản quyền vĩnh viễn",
    KIND_SW_SUBSCRIPTION: "Phần mềm thuê bao (theo năm)",
    KIND_SERVICE: "Dịch vụ CNTT",
}

# Hình thức đầu tư -> loại tài sản cấp 2 theo nhóm tài sản cấp 1 (D: thiết bị quản lý, E: phần mềm)
INVEST_TYPES = ["Mua mới", "Nâng cấp, thay thế", "Gia hạn, bảo trì"]
_CAT2_BY_INVEST = {
    "D": {"Mua mới": "D1. TBQL: Mua mới", "Nâng cấp, thay thế": "D2. TBQL: Nâng cấp, thay thế",
          "Gia hạn, bảo trì": "D3. TBQL: Bảo trì, bảo dưỡng"},
    "E": {"Mua mới": "E1. BQPM: Mua mới", "Nâng cấp, thay thế": "E2. BQPM: Gia hạn, nâng cấp",
          "Gia hạn, bảo trì": "E2. BQPM: Gia hạn, nâng cấp"},
}

TSCD_THRESHOLD = 30_000_000  # Nguyên giá tối thiểu ghi nhận TSCĐ (TT45/2013/TT-BTC)


# Phạm vi hạng mục: trang bị theo người (ngân sách của từng phòng ban) / hạ tầng dùng chung (ngân sách của phòng phụ trách)
SCOPE_USER = "per_user"
SCOPE_SHARED = "shared"
SCOPE_LABELS = {SCOPE_USER: "Theo người – phòng ban", SCOPE_SHARED: "Hạ tầng dùng chung"}
DEFAULT_INFRA_OWNER = "PHÒNG CNTT"


def item_scope(item: Dict[str, Any], master: Dict[str, Any]) -> str:
    if item.get("scope") in SCOPE_LABELS:
        return item["scope"]
    group = next((g for g in it_groups(master) if g["code"] == item.get("group")), {})
    return group.get("scope") if group.get("scope") in SCOPE_LABELS else SCOPE_USER


def item_owner(item: Dict[str, Any], master: Dict[str, Any]) -> str:
    """Phòng ban đứng tên ngân sách cho hạng mục hạ tầng dùng chung."""
    group = next((g for g in it_groups(master) if g["code"] == item.get("group")), {})
    return item.get("owner") or group.get("owner") or master.get("infra_owner") or DEFAULT_INFRA_OWNER


def it_groups(master: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [g for g in master.get("it_groups", []) if isinstance(g, dict)]


def it_kinds(master: Dict[str, Any]) -> Dict[str, str]:
    return master.get("it_kinds", DEFAULT_IT_KINDS)


def _norm(name: Any) -> str:
    return " ".join(str(name or "").lower().split())


def find_catalog_item(name: str, master: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Tìm hạng mục trong danh mục CNTT theo tên chuẩn hoặc tên cũ (aliases)."""
    key = _norm(name)
    if not key:
        return None
    for it in master.get("standard_items", []):
        if _norm(it.get("name")) == key or key in (_norm(a) for a in it.get("aliases", [])):
            return it
    return None


def default_invest_type(kind: str) -> str:
    return "Gia hạn, bảo trì" if kind in (KIND_SW_SUBSCRIPTION, KIND_SERVICE) else "Mua mới"


def accounting_class(kind: str, unit_price: float, master: Dict[str, Any] = None) -> Tuple[str, str]:
    """Phân loại hạch toán theo loại hạng mục & đơn giá 1 đơn vị. Trả về (phân loại kế toán, CAPEX/CCDC/OPEX)."""
    threshold = float((master or {}).get("tscd_threshold", TSCD_THRESHOLD))
    if kind == KIND_SERVICE:
        return "Chi phí dịch vụ / trả trước ngắn hạn (TK 2421)", "OPEX"
    if kind == KIND_SW_SUBSCRIPTION:
        return "Chi phí trả trước - phần mềm thuê bao (TK 242)", "OPEX"
    if kind == KIND_SW_PERPETUAL:
        if unit_price >= threshold:
            return "TSCĐ vô hình - Chương trình phần mềm (TK 2135)", "CAPEX"
        return "CCDC dài hạn chờ phân bổ (TK 2422)", "CCDC"
    if kind in (KIND_HARDWARE, KIND_COMPONENT):
        if unit_price >= threshold:
            return "TSCĐ hữu hình - Máy móc, thiết bị thông tin, điện tử (TK 2114)", "CAPEX"
        return "CCDC dài hạn chờ phân bổ (TK 2422)", "CCDC"
    return "", ""


def classify_item(item: Dict[str, Any], master: Dict[str, Any], invest_type: str = None) -> Dict[str, Any]:
    """Nhóm CNTT, loại tài sản cấp 1/2, loại chi phí cấp 1/2, thời gian phân bổ của 1 hạng mục danh mục."""
    group = next((g for g in it_groups(master) if g["code"] == item.get("group")), None)
    if not group:
        return {}
    kind = item.get("kind") or group.get("kind")
    invest_type = invest_type or default_invest_type(kind)
    cat1 = group.get("asset_cat1", "D. Thiết bị, dụng cụ quản lý")
    cost_lv2 = group.get("cost_lv2", "04.03. Thiết bị quản lý - Thiết bị CNTT")
    # Bản quyền phần mềm luôn là nhóm E dù nằm trong nhóm thiết bị (vd. license tường lửa), và ngược lại
    if kind in (KIND_SW_PERPETUAL, KIND_SW_SUBSCRIPTION) and not cat1.startswith("E"):
        cat1, cost_lv2 = "E. Bản quyền, Phần mềm", "04.04. Thiết bị quản lý - Phần mềm/bản quyền"
    elif kind in (KIND_HARDWARE, KIND_COMPONENT) and not cat1.startswith("D"):
        cat1, cost_lv2 = "D. Thiết bị, dụng cụ quản lý", "04.03. Thiết bị quản lý - Thiết bị CNTT"
    if item.get("cost_lv2"):  # loại chi phí riêng của hạng mục (vd. đào tạo -> 07.03)
        cost_lv2 = item["cost_lv2"]
    cost_lv1 = next((c for c in master.get("cost_lv1", []) if c.startswith(cost_lv2[:3])), "04. Chi phí MMTB")
    months = int(item.get("useful_months") or group.get("useful_months") or 12)
    return {
        "it_group": f"{group['code']}. {group['name']}",
        "item_kind": kind,
        "invest_type": invest_type,
        "asset_cat1": cat1,
        "asset_cat2": _CAT2_BY_INVEST.get(cat1[:1], {}).get(invest_type),
        "cost_lv1": cost_lv1,
        "cost_lv2": cost_lv2,
        "useful_months": months,
    }


def apply_it_catalog(row: Dict[str, Any], master: Dict[str, Any], item: Dict[str, Any] = None,
                     invest_type: str = None) -> bool:
    """Gán nhóm CNTT, ĐVT, loại tài sản & loại chi phí cho dòng ngân sách theo danh mục. Trả về True nếu khớp."""
    item = item or find_catalog_item(row.get("item_name"), master)
    if not item:
        return False
    cls = classify_item(item, master, invest_type or row.get("invest_type"))
    if not cls:
        return False
    row["item_name"] = item["name"]
    row["catalog_code"] = item.get("code", "")
    row["unit"] = item.get("unit", "")
    row["useful_life"] = max(cls.pop("useful_months") / 12.0, 1.0)
    if not cls.get("asset_cat2"):
        cls.pop("asset_cat2")
    row.update(cls)
    return True


def build_it_catalog_view(master: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Bản phẳng của danh mục (khóa 'it_catalog') cho các hàm get_it_* : group là nhãn nhóm."""
    out = []
    for it in master.get("standard_items", []):
        cls = classify_item(it, master)
        if not cls:
            continue
        out.append({
            "code": it.get("code", ""), "name": it["name"], "group": cls["it_group"], "price": it.get("price", 0),
            "unit": it.get("unit", ""), "kind": cls["item_kind"],
            "asset_cat1": cls["asset_cat1"], "asset_cat2": cls.get("asset_cat2"),
            "cost_lv1": cls["cost_lv1"], "cost_lv2": cls["cost_lv2"],
            "useful_life": round(cls["useful_months"] / 12.0, 2),
        })
    return out

_DB_CACHE: Dict[str, Any] = {"value": None, "at": 0.0}
_DB_CACHE_TTL = 15  # giây - tránh đọc CSDL nhiều lần trong 1 lần chạy lại


def _merge_catalog_seed(data: Dict[str, Any]) -> bool:
    """Danh mục trong CSDL được admin sửa nên không ghi đè bằng file. Khi file master_data.json có đợt bổ sung mới
    (catalog_seed tăng), chỉ thêm các hạng mục của đợt đó chưa có trong CSDL và điền hãng còn trống - chạy 1 lần."""
    if not os.path.exists(MASTER_DATA_FILE):
        return False
    try:
        with open(MASTER_DATA_FILE, "r", encoding="utf-8") as f:
            file_data = json.load(f)
    except Exception:
        return False
    file_seed = int(file_data.get("catalog_seed") or 0)
    applied = int(data.get("catalog_seed") or 0)
    if file_seed <= applied:
        return False
    items = data.setdefault("standard_items", [])
    by_code = {it.get("code"): it for it in items}
    names = {str(it.get("name", "")).strip().lower() for it in items}
    for it in file_data.get("standard_items", []):
        cur = by_code.get(it.get("code"))
        if cur is not None and cur.get("name") == it.get("name"):
            if it.get("vendor") and not cur.get("vendor"):
                cur["vendor"] = it["vendor"]
            continue
        if int(it.get("seed") or 0) > applied and str(it.get("name", "")).strip().lower() not in names:
            new = dict(it)
            if cur is not None:  # mã đã bị hạng mục khác (admin tự thêm) dùng -> cấp mã kế tiếp trong nhóm
                n = 1
                while f"{new['group']}-{n:03d}" in by_code:
                    n += 1
                new["code"] = f"{new['group']}-{n:03d}"
            items.append(new)
            by_code[new["code"]] = new
            names.add(str(new.get("name", "")).strip().lower())
    order = {g.get("code"): i for i, g in enumerate(data.get("it_groups", []))}
    data["standard_items"] = sorted(items, key=lambda it: (order.get(it.get("group"), 99), str(it.get("code"))))
    data["catalog_seed"] = file_seed
    return True


def load_master_data() -> Dict[str, Any]:
    """Danh mục: lấy từ CSDL khi chạy PostgreSQL (đã lưu), không có thì lấy file master_data.json, cuối cùng là mặc định."""
    import time as _time
    import copy as _copy
    import db as _db
    if _db.using_server_db():
        if _DB_CACHE["value"] is not None and _time.time() - _DB_CACHE["at"] < _DB_CACHE_TTL:
            return _copy.deepcopy(_DB_CACHE["value"])
        raw = _db.get_setting("master_data")
        if raw:
            data = json.loads(raw)
            if _merge_catalog_seed(data):
                save_master_data(data)
            _DB_CACHE.update(value=data, at=_time.time())
            return _copy.deepcopy(data)
    if os.path.exists(MASTER_DATA_FILE):
        try:
            with open(MASTER_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data
        except Exception:
            pass
    return {
        "entities": DEFAULT_ENTITIES,
        "sites": DEFAULT_SITES,
        "asset_cat1": DEFAULT_ASSET_CAT1,
        "asset_cat2": DEFAULT_ASSET_CAT2,
        "cost_lv1": DEFAULT_COST_LV1,
        "cost_lv2": DEFAULT_COST_LV2,
        "divisions": ["Ban Kiểm Soát", "Khối Dịch Vụ Kinh Doanh", "Khối Sản Xuất", "Khối Dự Án", "Khối Tài Chính - Kế Toán", "Khối Hành Chính - Nhân Sự", "Khối CNTT & Chuyển đổi số"],
        "departments": ["Phòng CNTT & CĐS", "Phòng Kiểm toán Nội bộ", "PHÒNG CHIẾN LƯỢC & KẾ HOẠCH KINH DOANH", "Phòng Cơ điện", "Phòng Quản lý Thiết bị", "Phòng Kế toán", "Phòng Nhân sự"],
        "it_catalog": [],
        "it_groups": []
    }

def save_master_data(data: Dict[str, Any]):
    """Lưu danh mục: vào CSDL khi chạy PostgreSQL (không mất khi cập nhật code), ngược lại vào file JSON."""
    import db as _db
    if it_groups(data):
        data["it_catalog"] = build_it_catalog_view(data)
    if _db.using_server_db():
        _db.set_setting("master_data", json.dumps(data, ensure_ascii=False))
        _DB_CACHE.update(value=None, at=0.0)
        return
    with open(MASTER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def division_of(dept: Any, master: Dict[str, Any]) -> str:
    """Khối của phòng ban theo bảng 'dept_divisions' (lấy từ file định biên); không có -> ''."""
    key = " ".join(str(dept or "").lower().split())
    if not key:
        return ""
    for name, div in (master.get("dept_divisions") or {}).items():
        if " ".join(str(name).lower().split()) == key:
            return div or ""
    return ""

def get_it_catalog() -> List[Dict[str, Any]]:
    """Get full list of structured IT items"""
    m = load_master_data()
    return m.get("it_catalog", [])

def get_it_groups() -> List[str]:
    """Get list of IT Category Groups"""
    m = load_master_data()
    groups = [f"{g['code']}. {g['name']}" if isinstance(g, dict) else g for g in m.get("it_groups", [])]
    if not groups and m.get("it_catalog"):
        groups = sorted(list(set(it.get("group", "") for it in m.get("it_catalog", []))))
    return groups

def get_it_items_by_group(group_name: str) -> List[Dict[str, Any]]:
    """Filter IT items by group"""
    catalog = get_it_catalog()
    if not group_name or group_name == "Tất cả các nhóm":
        return catalog
    return [it for it in catalog if it.get("group") == group_name]

def get_it_item_details(item_name: str) -> Optional[Dict[str, Any]]:
    """Find details of a specific IT item by name"""
    catalog = get_it_catalog()
    for it in catalog:
        if it.get("name", "").strip().lower() == item_name.strip().lower():
            return it
    return None

def generate_project_code(entity_name: str, site_name: str, cat1_name: str, year_str: str = "A26", master: Dict[str, Any] = None) -> str:
    """Generate Mã công trình: {Entity_Code}{Year_Code}{Site_Code}{Cat1_Code}"""
    if master is None:
        master = load_master_data()
    
    ent_code = "A01"
    for ent in master.get("entities", []):
        if ent.get("name") == entity_name or ent.get("code") == entity_name:
            ent_code = ent.get("code", "A01")
            break
            
    site_code = "AHA"
    for st in master.get("sites", []):
        if st.get("name") == site_name or st.get("code") == site_name:
            site_code = st.get("code", "AHA")
            break
            
    cat1_code = "02"
    for c1 in master.get("asset_cat1", []):
        if c1.get("name") == cat1_name:
            cat1_code = c1.get("code3") or "02"
            break
            
    return f"{ent_code}{year_str}{site_code}{cat1_code}"

def generate_item_code(project_code: str, cat1_name: str, stt: int = 1, master: Dict[str, Any] = None) -> str:
    """Generate Mã hạng mục: {project_code}-{code4}-{stt:03d}"""
    if master is None:
        master = load_master_data()
        
    code4 = "03"
    for c1 in master.get("asset_cat1", []):
        if c1.get("name") == cat1_name:
            code4 = c1.get("code4") or "03"
            break
            
    return f"{project_code}-{code4}-{int(stt):03d}"

def generate_budget_code(cost_lv2_name: str) -> str:
    """Generate Mã ngân sách: A.01.{CostLv2Code}"""
    if not cost_lv2_name:
        return "A.01.04.01."
    parts = cost_lv2_name.strip().split()
    if parts:
        prefix = parts[0].strip()
        if not prefix.endswith("."):
            prefix += "."
        return f"A.01.{prefix}"
    return "A.01.04.01."
