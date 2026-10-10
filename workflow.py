"""
Nộp & duyệt ngân sách theo phòng ban: Phòng ban nộp -> IT site duyệt / trả lại -> IT site nộp site -> Admin duyệt site.
Dòng của phòng ban đã nộp / đã duyệt bị khóa: khi lưu site, các dòng đó luôn giữ đúng bản đã lưu.
"""
import math
from typing import Dict, List, Any, Set, Tuple, Callable

import pandas as pd

import db
import quota as qt

COMPARE_FIELDS = ("item_name", "catalog_code", "quantity", "unit_price", "invest_type", "need_type", "need_reason",
                  "dept_proposing", "dept_using", "detail_work", "handover_date", "division")


def dept_key(name) -> str:
    return " ".join(str(name or "").lower().split())


def _clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _same(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    keys = set(COMPARE_FIELDS) | {k for k in list(a) + list(b) if k.startswith("pct_")}
    for k in keys:
        x, y = _clean(a.get(k)), _clean(b.get(k))
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            if abs(float(x) - float(y)) > 1e-6:
                return False
        elif str(x).strip() != str(y).strip():
            return False
    return True


def keep_locked_rows(new_rows: List[Dict[str, Any]], stored: List[Dict[str, Any]], locked: Set[str]) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Ghép dòng sắp lưu với bản đã lưu: dòng của phòng ban bị khóa (locked = tên phòng chuẩn hóa) giữ nguyên bản đã lưu,
    đúng vị trí. Trả về (dòng để lưu, tên phòng ban có thay đổi bị bỏ qua)."""
    if not locked:
        return new_rows, set()
    by_code = {r.get("item_code"): r for r in stored if r.get("item_code")}
    stored_locked = [r for r in stored if dept_key(r.get("dept_proposing")) in locked]
    out, used, ignored = [], set(), set()
    for r in new_rows:
        code = r.get("item_code")
        old = by_code.get(code) if code else None
        new_locked = dept_key(r.get("dept_proposing")) in locked
        old_locked = old is not None and dept_key(old.get("dept_proposing")) in locked
        if not new_locked and not old_locked:
            out.append(r)
            continue
        if old is None:  # dòng mới thêm vào phòng bị khóa -> bỏ
            ignored.add(r.get("dept_proposing"))
            continue
        if code in used:  # trùng (dòng bị nhân bản) -> bỏ bản sau
            ignored.add(r.get("dept_proposing"))
            continue
        if not _same(r, old):
            ignored.add(old.get("dept_proposing") if old_locked else r.get("dept_proposing"))
        out.append(dict(old))  # giữ bản đã lưu (cả trường hợp chuyển dòng vào / ra phòng bị khóa)
        used.add(code)
    for r in stored_locked:  # dòng của phòng bị khóa đã bị xóa -> trả lại
        if r.get("item_code") not in used:
            out.append(dict(r))
            used.add(r.get("item_code"))
            ignored.add(r.get("dept_proposing"))
    return out, {d for d in ignored if d}


def dept_problems(rows: pd.DataFrame) -> List[str]:
    """Kiểm tra trước khi nộp / duyệt 1 phòng ban."""
    if rows is None or rows.empty:
        return ["Phòng ban chưa có dòng ngân sách nào"]
    msgs = []
    if "pct_valid" in rows.columns:
        n = int((~rows["pct_valid"].fillna(False).astype(bool)).sum())
        if n:
            msgs.append(f"{n} dòng có tổng phân kỳ khác 100%")
    if "need_type" in rows.columns:
        reason = rows["need_reason"] if "need_reason" in rows.columns else pd.Series("", index=rows.index)
        n = int((rows["need_type"].isin(qt.NEED_WITH_REASON) & (reason.fillna("").astype(str).str.strip() == "")).sum())
        if n:
            msgs.append(f"{n} dòng 'Phát sinh mới' / 'Hạ tầng dùng chung' chưa ghi lý do / căn cứ")
    return msgs


def dept_overview(lines: pd.DataFrame, statuses: Dict[str, Dict[str, Any]], canon: Callable[[str], str] = None) -> pd.DataFrame:
    """Tiến độ từng phòng ban có dòng ngân sách: số dòng, tổng, trạng thái, người/lúc cập nhật, ghi chú."""
    cols = ["Phòng ban", "Số dòng", "Tổng ngân sách", "Trạng thái", "status", "Cập nhật", "Ghi chú"]
    if lines is None or lines.empty or "dept_proposing" not in lines.columns:
        return pd.DataFrame(columns=cols)
    d = lines.assign(_k=lines["dept_proposing"].map(dept_key))
    rows = []
    for k, g in d.groupby("_k"):
        name = g["dept_proposing"].mode().iloc[0]
        stt = statuses.get(k) or {}
        status = stt.get("status", db.STATUS_DRAFT)
        rows.append({"Phòng ban": canon(name) if canon else name, "Số dòng": len(g),
                     "Tổng ngân sách": float(pd.to_numeric(g.get("total_budget", 0), errors="coerce").fillna(0).sum()),
                     "Trạng thái": db.DEPT_STATUS_LABELS.get(status, status), "status": status,
                     "Cập nhật": f"{stt.get('updated_by') or ''} {stt.get('updated_at') or ''}".strip(),
                     "Ghi chú": stt.get("note") or ""})
    order = {db.STATUS_SUBMITTED: 0, db.STATUS_RETURNED: 1, db.STATUS_DRAFT: 2, db.STATUS_APPROVED: 3}
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(["status", "Tổng ngân sách"], key=lambda s: s.map(order) if s.name == "status" else -s).reset_index(drop=True)


def pending_depts(overview: pd.DataFrame) -> List[str]:
    """Phòng ban có dòng mà chưa được duyệt (chặn nộp site)."""
    if overview.empty:
        return []
    return overview.loc[overview["status"] != db.STATUS_APPROVED, "Phòng ban"].tolist()
