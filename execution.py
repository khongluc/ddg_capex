"""
Theo dõi thực hiện ngân sách theo Mã hạng mục (cố định): đề nghị mua -> hợp đồng / PO -> thanh toán.
Còn lại = Ngân sách - max(Hợp đồng, Đề nghị) (đề nghị chưa ký hợp đồng cũng giữ chỗ ngân sách).
"""
import datetime
from typing import List, Dict, Any

import pandas as pd

import db

FLAG_OVER = "⚠️ Vượt ngân sách"
FLAG_PAY_OVER = "⚠️ Thanh toán vượt hợp đồng"
FLAG_NO_LINE = "⚠️ Mã không còn trong ngân sách"


def _exec_frame(exec_rows) -> pd.DataFrame:
    e = pd.DataFrame(exec_rows or [], columns=["id", "site_code", "item_code", "kind", "doc_no", "doc_date", "amount", "vendor", "note",
                                                "created_by", "created_at"])
    e["amount"] = pd.to_numeric(e["amount"], errors="coerce").fillna(0.0)
    return e


def summarize(lines: pd.DataFrame, exec_rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """1 dòng / mã hạng mục: ngân sách, đề nghị, hợp đồng, thanh toán, còn lại, % giải ngân, cảnh báo.
    Chứng từ của mã không còn trong ngân sách (dòng đã xóa) vẫn hiện, ngân sách = 0, có cảnh báo."""
    cols = ["site_code", "item_code", "dept", "item_name", "budget", "requested", "contracted", "paid", "remaining", "paid_pct", "flag"]
    e = _exec_frame(exec_rows)
    l = lines.copy() if lines is not None and not lines.empty else pd.DataFrame(columns=["site_code", "item_code", "dept_proposing", "item_name", "total_budget"])
    if "site_code" not in l.columns:
        l["site_code"] = ""
    base = pd.DataFrame({"site_code": l["site_code"], "item_code": l["item_code"], "dept": l.get("dept_proposing", ""),
                         "item_name": l.get("item_name", ""), "budget": pd.to_numeric(l.get("total_budget", 0), errors="coerce").fillna(0.0)})
    base = base.groupby(["site_code", "item_code"], as_index=False).agg(dept=("dept", "first"), item_name=("item_name", "first"),
                                                                        budget=("budget", "sum"))
    if not e.empty:  # Mã hạng mục đã gồm mã site -> ghép theo mã
        pv = e.pivot_table(index="item_code", columns="kind", values="amount", aggfunc="sum", fill_value=0.0).reset_index()
        site_of = e.groupby("item_code")["site_code"].first()
        out = base.merge(pv, on="item_code", how="outer")
        out["site_code"] = out["site_code"].where(out["site_code"].fillna("") != "", out["item_code"].map(site_of)).fillna("")
    else:
        out = base.copy()
    for k, c in ((db.EXEC_REQUEST, "requested"), (db.EXEC_CONTRACT, "contracted"), (db.EXEC_PAYMENT, "paid")):
        out[c] = pd.to_numeric(out[k], errors="coerce").fillna(0.0) if k in out.columns else 0.0
    out["budget"] = out["budget"].fillna(0.0)
    missing = out["dept"].isna() & out["item_name"].isna()
    out["dept"] = out["dept"].fillna("")
    out["item_name"] = out["item_name"].fillna("(dòng đã xóa)")
    out["remaining"] = out["budget"] - out[["requested", "contracted"]].max(axis=1)
    out["paid_pct"] = (out["paid"] / out["budget"]).where(out["budget"] > 0)

    def flag(r, miss):
        if miss:
            return FLAG_NO_LINE
        if max(r["requested"], r["contracted"], r["paid"]) > r["budget"] + 0.5:
            return FLAG_OVER
        if r["contracted"] > 0 and r["paid"] > r["contracted"] + 0.5:
            return FLAG_PAY_OVER
        return ""
    out["flag"] = [flag(r, m) for r, m in zip(out.to_dict("records"), missing)]
    return out[cols].sort_values(["flag", "remaining"], key=lambda s: (s == "") if s.name == "flag" else s).reset_index(drop=True)


def totals(summary: pd.DataFrame) -> Dict[str, float]:
    t = {c: float(summary[c].sum()) if not summary.empty else 0.0 for c in ("budget", "requested", "contracted", "paid", "remaining")}
    t["paid_pct"] = t["paid"] / t["budget"] if t["budget"] else 0.0
    t["n_flag"] = int((summary["flag"] != "").sum()) if not summary.empty else 0
    return t


def month_label(date_str: str) -> str:
    """'2027-02-15' -> 'T2 2027' (nhãn tháng phân kỳ)."""
    try:
        d = datetime.date.fromisoformat(str(date_str)[:10])
    except ValueError:
        return ""
    return f"T{d.month} {d.year}"


def plan_vs_actual(lines: pd.DataFrame, exec_rows: List[Dict[str, Any]], months: List[str]) -> pd.DataFrame:
    """Theo tháng của năm ngân sách: kế hoạch giải ngân (phân kỳ) và thực thanh toán; lũy kế cả hai."""
    plan = [float(pd.to_numeric(lines.get(f"val_{m}", 0), errors="coerce").fillna(0).sum()) if lines is not None and not lines.empty else 0.0
            for m in months]
    e = _exec_frame(exec_rows)
    pay = e[e["kind"] == db.EXEC_PAYMENT].assign(m=lambda x: x["doc_date"].map(month_label))
    by_m = pay.groupby("m")["amount"].sum()
    actual = [float(by_m.get(m, 0.0)) for m in months]
    outside = float(pay.loc[~pay["m"].isin(months), "amount"].sum())
    df = pd.DataFrame({"Tháng": months, "Kế hoạch": plan, "Thực chi": actual})
    df["Lũy kế kế hoạch"] = df["Kế hoạch"].cumsum()
    df["Lũy kế thực chi"] = df["Thực chi"].cumsum()
    df.attrs["outside"] = outside  # thanh toán có ngày ngoài năm ngân sách / không ghi ngày
    return df


def check_new(summary_row: Dict[str, Any], kind: str, amount: float) -> str:
    """Cảnh báo trước khi ghi 1 chứng từ (không chặn): vượt còn lại / thanh toán vượt hợp đồng."""
    if amount <= 0:
        return "Số tiền phải lớn hơn 0"
    budget = summary_row.get("budget", 0.0)
    if kind in (db.EXEC_REQUEST, db.EXEC_CONTRACT):
        col = "requested" if kind == db.EXEC_REQUEST else "contracted"
        after = summary_row.get(col, 0.0) + amount
        if after > budget + 0.5:
            return f"Sau khi ghi, {db.EXEC_LABELS[kind]} lũy kế {after:,.0f} vượt ngân sách {budget:,.0f}"
    if kind == db.EXEC_PAYMENT:
        after = summary_row.get("paid", 0.0) + amount
        limit = summary_row.get("contracted", 0.0) or budget
        if after > limit + 0.5:
            return f"Sau khi ghi, thanh toán lũy kế {after:,.0f} vượt {'hợp đồng' if summary_row.get('contracted') else 'ngân sách'} {limit:,.0f}"
    return ""
