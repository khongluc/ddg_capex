"""
So sánh 2 phiên bản ngân sách (hoặc bản duyệt với hiện tại) theo Mã hạng mục cố định.
"""
from typing import List, Dict, Any

import pandas as pd

ADDED, REMOVED, CHANGED, SAME = "➕ Thêm", "➖ Bỏ", "✏️ Đổi", "Giữ nguyên"
_FIELDS = ("item_name", "dept_proposing", "invest_type", "quantity", "unit_price", "total_budget")


def _frame(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    d = pd.DataFrame(rows or [])
    for c in _FIELDS + ("item_code",):
        if c not in d.columns:
            d[c] = None
    d = d[d["item_code"].notna() & (d["item_code"] != "")]
    for c in ("quantity", "unit_price", "total_budget"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0)
    return d.drop_duplicates("item_code", keep="last").set_index("item_code")[list(_FIELDS)]


def diff(old_rows: List[Dict[str, Any]], new_rows: List[Dict[str, Any]], include_same: bool = False) -> pd.DataFrame:
    """1 dòng / mã hạng mục: trạng thái (Thêm / Bỏ / Đổi / Giữ nguyên), SL, đơn giá, thành tiền cũ - mới, chênh lệch, nội dung đổi."""
    a, b = _frame(old_rows), _frame(new_rows)
    codes = a.index.union(b.index)
    out = []
    for code in codes:
        x = a.loc[code] if code in a.index else None
        y = b.loc[code] if code in b.index else None
        if x is None:
            status, what = ADDED, ""
        elif y is None:
            status, what = REMOVED, ""
        else:
            ch = []
            if abs(x["quantity"] - y["quantity"]) > 1e-9:
                ch.append(f"SL {x['quantity']:g} → {y['quantity']:g}")
            if abs(x["unit_price"] - y["unit_price"]) > 0.5:
                ch.append(f"đơn giá {x['unit_price']:,.0f} → {y['unit_price']:,.0f}")
            if str(x["invest_type"] or "") != str(y["invest_type"] or ""):
                ch.append(f"hình thức {x['invest_type']} → {y['invest_type']}")
            if str(x["dept_proposing"] or "") != str(y["dept_proposing"] or ""):
                ch.append(f"phòng {x['dept_proposing']} → {y['dept_proposing']}")
            if str(x["item_name"] or "") != str(y["item_name"] or ""):
                ch.append("tên hạng mục")
            if abs(x["total_budget"] - y["total_budget"]) > 0.5 and not ch:
                ch.append("phân bổ / thành tiền")
            status, what = (CHANGED, "; ".join(ch)) if ch else (SAME, "")
        if status == SAME and not include_same:
            continue
        ref = y if y is not None else x
        out.append({"item_code": code, "status": status, "dept": ref["dept_proposing"], "item_name": ref["item_name"],
                    "qty_old": x["quantity"] if x is not None else 0.0, "qty_new": y["quantity"] if y is not None else 0.0,
                    "total_old": x["total_budget"] if x is not None else 0.0, "total_new": y["total_budget"] if y is not None else 0.0,
                    "what": what})
    df = pd.DataFrame(out, columns=["item_code", "status", "dept", "item_name", "qty_old", "qty_new", "total_old", "total_new", "what"])
    df["delta"] = df["total_new"] - df["total_old"]
    return df.sort_values("delta", key=lambda s: -s.abs()).reset_index(drop=True)


def by_dept(old_rows: List[Dict[str, Any]], new_rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """Tổng theo phòng ban: cũ, mới, chênh lệch (chỉ phòng có thay đổi), sắp theo chênh lệch tuyệt đối."""
    a, b = _frame(old_rows), _frame(new_rows)
    old = a.groupby(a["dept_proposing"].fillna(""))["total_budget"].sum()
    new = b.groupby(b["dept_proposing"].fillna(""))["total_budget"].sum()
    df = pd.DataFrame({"total_old": old, "total_new": new}).fillna(0.0)
    df["delta"] = df["total_new"] - df["total_old"]
    df = df[df["delta"].abs() > 0.5]
    df.index.name = "dept"
    return df.reset_index().sort_values("delta", key=lambda s: -s.abs()).reset_index(drop=True)


def summary(d: pd.DataFrame, old_rows: List[Dict[str, Any]], new_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    a, b = _frame(old_rows), _frame(new_rows)
    cnt = d["status"].value_counts() if not d.empty else {}
    return {"total_old": float(a["total_budget"].sum()), "total_new": float(b["total_budget"].sum()),
            "added": int(cnt.get(ADDED, 0)), "removed": int(cnt.get(REMOVED, 0)), "changed": int(cnt.get(CHANGED, 0))}
