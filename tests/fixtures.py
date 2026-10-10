"""Dữ liệu mẫu cho kiểm thử: dòng ngân sách tạo từ danh mục thật (master_data.json), phòng ban / số lượng giả định."""
import copy
from typing import List, Dict, Any

from master_data import load_master_data, fiscal_months, apply_it_catalog
from capex_engine import calculate_row, assign_item_seqs

YEAR = "2027"
MONTHS = fiscal_months(YEAR)
SITE = "BDA"
SITE_NAME = "VP Bạch Đằng"
KD, KT, IT = "PHÒNG KD 10", "PHÒNG KẾ TOÁN", "PHÒNG CNTT"
LAPTOP, MONITOR, PRINTER, M365, ZWCAD = "IT01-004", "IT01-010", "IT02-001", "IT09-007", "IT10-014"

_MASTER = None


def master() -> Dict[str, Any]:
    global _MASTER
    if _MASTER is None:
        _MASTER = load_master_data()
    return copy.deepcopy(_MASTER)


def item(code: str) -> Dict[str, Any]:
    return next(it for it in master()["standard_items"] if it["code"] == code)


# (phòng ban, mã danh mục, hình thức, số lượng, phân kỳ theo tháng (chỉ số tháng -> số lượng), loại nhu cầu, định biên?)
SPEC = [
    (KD, LAPTOP, "Mua mới", 21, {0: 7, 1: 7, 2: 2, 3: 4, 4: 1}, "Định biên", True),
    (KD, MONITOR, "Mua mới", 21, {0: 21}, "Định biên", True),
    (KD, ZWCAD, "Mua mới", 12, {0: 5, 1: 3, 2: 1, 3: 2, 4: 1}, "Định biên", True),
    (KD, M365, "Gia hạn, bảo trì", 10, {0: 10}, "Định biên", True),
    (KT, LAPTOP, "Mua mới", 2, {0: 2}, "Định biên", True),
    (KT, M365, "Gia hạn, bảo trì", 12, {0: 12}, "Định biên", True),
    (KT, PRINTER, "Mua mới", 1, {3: 1}, "Phát sinh mới", False),
    (IT, LAPTOP, "Nâng cấp, thay thế", 5, {6: 5}, "Phát sinh mới", False),
]


def make_lines(spec=None, m=None) -> List[Dict[str, Any]]:
    """Dòng ngân sách đã tính (thành tiền, phân kỳ, mã hạng mục cố định) như khi app lưu 1 site."""
    m = m or master()
    rows = []
    for i, (dept, code, inv, qty, phase, need, auto) in enumerate(spec or SPEC):
        r = {"entity": "DDC", "location": SITE_NAME, "dept_proposing": dept, "dept_using": dept, "quantity": qty,
             "unit_price": item(code)["price"], "need_type": need, "need_reason": "Căn cứ thử" if need != "Định biên" else f"Định biên: {qty}",
             "auto_quota": auto, "stt": i + 1}
        apply_it_catalog(r, m, item=item(code), invest_type=inv)
        for j, mth in enumerate(MONTHS):
            r[f"pct_{mth}"] = phase.get(j, 0) / qty
        rows.append(calculate_row(r, months=MONTHS, year_code="A27", master=m))
    assign_item_seqs(rows, {})
    return rows
