"""
Theo dõi thực hiện ngân sách theo Mã hạng mục (cố định): đề nghị mua -> hợp đồng / PO -> thanh toán.
Còn lại = Ngân sách - max(Hợp đồng, Đề nghị) (đề nghị chưa ký hợp đồng cũng giữ chỗ ngân sách).
"""
import datetime
import io
import unicodedata
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



# ---------------------------------------------------------------- Nạp chứng từ hàng loạt (file Excel / CSV xuất từ ERP)
IMPORT_STATUS_OK, IMPORT_STATUS_OVER = "Hợp lệ", "Vượt ngân sách / hợp đồng"
IMPORT_STATUS_DUP, IMPORT_STATUS_ERR = "Trùng (đã có trong sổ)", "Lỗi"
_IMPORT_HEADERS = {  # cột chuẩn -> tên cột chấp nhận (so sau khi bỏ dấu, chữ thường, gộp khoảng trắng)
    "item_code": ("ma hang muc", "item code", "item_code", "ma ngan sach hang muc"),
    "kind": ("loai chung tu", "loai", "kind"),
    "doc_no": ("so chung tu", "so ct", "doc no", "doc_no", "so hd", "so po"),
    "doc_date": ("ngay chung tu", "ngay ct", "ngay", "doc date", "doc_date"),
    "amount": ("so tien (chua vat)", "so tien", "gia tri", "amount"),
    "vendor": ("nha cung cap", "ncc", "vendor"),
    "note": ("ghi chu", "note"),
}
_KIND_ALIASES = {
    db.EXEC_REQUEST: ("de nghi mua", "de nghi", "pr", "request", db.EXEC_REQUEST),
    db.EXEC_CONTRACT: ("hop dong / po", "hop dong/po", "hop dong", "hd", "po", "contract", db.EXEC_CONTRACT),
    db.EXEC_PAYMENT: ("thanh toan", "unc", "tt", "payment", db.EXEC_PAYMENT),
}


def _plain(text: Any) -> str:
    """Chuỗi để so khớp: bỏ dấu tiếng Việt, chữ thường, gộp khoảng trắng."""
    s = unicodedata.normalize("NFD", str(text or "")).replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


def _cell(v: Any) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def parse_amount(val: Any) -> float:
    """Số tiền từ file ERP: 1234000 / '1.234.000' / '1,234,000' / '1 234 000 đ' / '1234000.5'. Không đọc được -> 0."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = "".join(c for c in str(val) if c.isdigit() or c in ".,-")
    if not s:
        return 0.0
    if s.count(".") > 1 or (s.count(".") == 1 and "," not in s and len(s.split(".")[1]) == 3):
        s = s.replace(".", "").replace(",", ".")  # dấu chấm ngăn nghìn (kiểu Việt Nam)
    else:
        s = s.replace(",", "")  # dấu phẩy ngăn nghìn
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_doc_date(val: Any) -> str:
    """Ngày chứng từ -> 'YYYY-MM-DD'; trống hoặc không đọc được -> ''."""
    if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)) and not pd.isna(val):
        return pd.Timestamp(val).strftime("%Y-%m-%d")
    s = _cell(val)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y"):
        try:
            return datetime.datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def import_template() -> bytes:
    """File mẫu nạp chứng từ (.xlsx): sheet dữ liệu có 2 dòng ví dụ + sheet hướng dẫn."""
    sample = pd.DataFrame([
        {"Mã hạng mục": "A01A27BDA01-04-001", "Loại chứng từ": "Hợp đồng / PO", "Số chứng từ": "PO-2026-0123",
         "Ngày chứng từ": "15/11/2026", "Số tiền (chưa VAT)": 125_000_000, "Nhà cung cấp": "Công ty ABC", "Ghi chú": ""},
        {"Mã hạng mục": "A01A27BDA01-04-001", "Loại chứng từ": "Thanh toán", "Số chứng từ": "UNC-0456",
         "Ngày chứng từ": "20/12/2026", "Số tiền (chưa VAT)": 62_500_000, "Nhà cung cấp": "Công ty ABC", "Ghi chú": "Đợt 1"},
    ])
    guide = pd.DataFrame({
        "Cột": ["Mã hạng mục", "Loại chứng từ", "Số chứng từ", "Ngày chứng từ", "Số tiền (chưa VAT)", "Nhà cung cấp", "Ghi chú"],
        "Bắt buộc": ["Có", "Có", "Nên có (để phát hiện trùng)", "Nên có", "Có", "Không", "Không"],
        "Cách ghi": ["Đúng Mã hạng mục trong ngân sách đã duyệt (cột Mã hạng mục ở tab Giải ngân)",
                     "Đề nghị mua / Hợp đồng / PO / Thanh toán (hoặc PR, PO, HĐ, UNC, TT)",
                     "Số ĐN / HĐ / PO / UNC", "dd/mm/yyyy hoặc yyyy-mm-dd",
                     "Số, chưa VAT; nhận cả 1.234.000 hoặc 1,234,000", "", ""]})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        sample.to_excel(w, sheet_name="Chứng từ", index=False)
        guide.to_excel(w, sheet_name="Hướng dẫn", index=False)
    return buf.getvalue()


def parse_import(raw: pd.DataFrame, summ: pd.DataFrame, exec_rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """File chứng từ -> bảng xem trước, mỗi dòng 1 trạng thái: Hợp lệ / Vượt ngân sách / Trùng / Lỗi (kèm lý do).
    Mã hạng mục phải có trong ngân sách đang xem (summ, trừ dòng đã xóa). Vượt tính lũy kế cả các dòng trên trong file.
    Trùng = cùng mã + loại + số chứng từ + số tiền đã có trong sổ hoặc ở dòng trên của file."""
    cols = ["row", "item_code", "item_name", "site_code", "kind", "kind_label", "doc_no", "doc_date", "amount", "vendor", "note",
            "status", "message"]
    if raw is None or raw.empty:
        return pd.DataFrame(columns=cols)
    head = {_plain(c): c for c in raw.columns}
    src = {k: next((head[a] for a in aliases if a in head), None) for k, aliases in _IMPORT_HEADERS.items()}
    kinds = {a: k for k, aliases in _KIND_ALIASES.items() for a in aliases}
    budget = {} if summ is None else {r["item_code"]: dict(r) for r in summ.to_dict("records") if r.get("flag") != FLAG_NO_LINE}
    seen = {(r["item_code"], r["kind"], _cell(r.get("doc_no")), round(float(r.get("amount") or 0))) for r in exec_rows or []}
    out = []
    for i, r in enumerate(raw.to_dict("records"), start=2):  # dòng 1 trong Excel là tiêu đề
        def get(k):
            return r.get(src[k]) if src[k] else None
        code, raw_kind, raw_date = _cell(get("item_code")), _cell(get("kind")), get("doc_date")
        kind = kinds.get(_plain(raw_kind))
        amount = parse_amount(get("amount"))
        line = budget.get(code, {})
        rec = {"row": i, "item_code": code, "item_name": line.get("item_name", ""), "site_code": line.get("site_code", ""),
               "kind": kind or "", "kind_label": db.EXEC_LABELS.get(kind, raw_kind), "doc_no": _cell(get("doc_no")),
               "doc_date": parse_doc_date(raw_date), "amount": amount, "vendor": _cell(get("vendor")), "note": _cell(get("note"))}
        if not any(_cell(v) for v in r.values()):
            continue  # dòng trống
        errs = []
        if not code:
            errs.append("thiếu Mã hạng mục")
        elif code not in budget:
            errs.append("Mã hạng mục không có trong ngân sách đang xem")
        if not kind:
            errs.append(f"Loại chứng từ không rõ: '{raw_kind}'")
        if amount <= 0:
            errs.append("Số tiền phải > 0")
        if _cell(raw_date) and not rec["doc_date"]:
            errs.append(f"Ngày chứng từ không đọc được: '{_cell(raw_date)}'")
        if errs:
            out.append({**rec, "status": IMPORT_STATUS_ERR, "message": "; ".join(errs)})
            continue
        key = (code, kind, rec["doc_no"], round(amount))
        if key in seen:
            out.append({**rec, "status": IMPORT_STATUS_DUP, "message": "đã có chứng từ cùng mã, loại, số, số tiền - bỏ qua"})
            continue
        seen.add(key)
        warn = check_new(budget[code], kind, amount)
        col = {db.EXEC_REQUEST: "requested", db.EXEC_CONTRACT: "contracted", db.EXEC_PAYMENT: "paid"}[kind]
        budget[code][col] = budget[code].get(col, 0.0) + amount  # lũy kế cho các dòng sau trong file
        out.append({**rec, "status": IMPORT_STATUS_OVER if warn else IMPORT_STATUS_OK, "message": warn})
    return pd.DataFrame(out, columns=cols)
