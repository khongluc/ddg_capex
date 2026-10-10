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
                  "dept_proposing", "dept_using", "detail_work", "handover_date", "division", "review_note", "entity",
                  "asset_cat1", "asset_cat2", "cost_lv1", "cost_lv2", "supplier", "contract_date", "completion_date", "unit")


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


def _code(r: Dict[str, Any]):
    """Mã hạng mục cố định của dòng; None nếu dòng chưa được cấp số (dòng mới / đổi nhóm mã)."""
    seq = r.get("item_seq")
    if seq is None or (isinstance(seq, float) and math.isnan(seq)) or not r.get("item_code"):
        return None
    return r["item_code"]


def merge_site_rows(base: List[Dict[str, Any]], new: List[Dict[str, Any]], current: List[Dict[str, Any]]
                    ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Gộp thay đổi của 1 người vào bản đang có trong CSDL, theo Mã hạng mục (không ghi đè cả site).
    base = các dòng người đó đã xem (lúc tải trang), new = các dòng muốn lưu, current = các dòng hiện có trong CSDL.
    - Dòng người đó không đổi (new == base): giữ bản hiện có (kể cả khi người khác vừa sửa / xóa).
    - Dòng người đó sửa: ghi nếu người khác chưa sửa (current == base); người khác đã sửa / xóa -> giữ của họ, báo xung đột.
    - Dòng người đó xóa: xóa nếu người khác chưa sửa; đã sửa -> giữ, báo xung đột.
    - Dòng mới (chưa có mã): thêm cuối. Dòng người khác vừa thêm / dòng ngoài phạm vi người đó xem: giữ nguyên.
    Thứ tự dòng theo bản hiện có. Trả về (dòng để lưu, mô tả xung đột)."""
    b = {c: r for r in base if (c := _code(r))}
    cur = {c: r for r in current if (c := _code(r))}
    chosen, deleted, added, used, conflicts = {}, set(), [], set(), []

    def label(r):
        return f"{r.get('item_code')} ({r.get('item_name')}, {r.get('dept_proposing')})"

    for r in new:
        c = _code(r)
        if c is None:  # dòng mới
            added.append(r)
            continue
        if c in used:  # nhân bản trong cùng lần lưu -> cấp số mới
            added.append({**r, "item_seq": None})
            continue
        used.add(c)
        old, now = b.get(c), cur.get(c)
        if old is None:  # có mã nhưng ngoài bản đã xem
            if now is None:
                added.append(r)
            elif not _same(r, now):
                conflicts.append(f"{label(now)}: người khác vừa thêm / sửa")
            continue
        if _same(r, old):  # không đổi -> theo bản hiện có
            continue
        if now is None:
            conflicts.append(f"{label(r)}: người khác vừa xóa - không lưu thay đổi")
        elif _same(now, old):
            chosen[c] = r
        else:
            conflicts.append(f"{label(now)}: người khác vừa sửa - giữ bản của họ")
    for c, old in b.items():  # dòng đã xem mà lần lưu này không còn -> người này xóa
        if c in used or c not in cur:
            continue
        if _same(cur[c], old):
            deleted.add(c)
        else:
            conflicts.append(f"{label(cur[c])}: người khác vừa sửa - không xóa")
    out = []
    for r in current:
        c = _code(r)
        if c is None:
            if not any(_code(x) is None for x in base):  # dòng cũ chưa có mã: chỉ giữ nếu người này không xem chúng
                out.append(r)
        elif c not in deleted:
            out.append(chosen.get(c, r))
    return out + added, conflicts


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
