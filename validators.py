"""
Module kiểm tra tính hợp lệ & cảnh báo trước khi nộp ngân sách (Pre-submission Validation Engine).
Phân tầng:
- Critical (Lỗi nghiêm trọng): Chặn nút nộp ngân sách (phòng ban & site).
- Warning (Cảnh báo lưu ý): Nhắc nhở rà soát nhưng không chặn nộp.
"""
import calendar
import datetime
import math
from typing import Dict, List, Any, Set, Optional
from dataclasses import dataclass, field

import pandas as pd

from master_data import DEFAULT_MONTHS, TSCD_THRESHOLD
from capex_engine import clean_number
import quota as qt


SEV_CRITICAL = "CRITICAL"
SEV_WARNING = "WARNING"


@dataclass
class ValidationIssue:
    severity: str             # SEV_CRITICAL hoặc SEV_WARNING
    code: str                 # Mã lỗi (vd: CRIT_QTY_PRICE, WARN_DUPLICATE)
    title: str                # Tóm tắt lỗi
    message: str              # Diễn giải chi tiết
    item_code: str = ""       # Mã hạng mục bị vi phạm
    item_name: str = ""       # Tên hạng mục bị vi phạm
    row_index: Optional[int] = None
    action: str = ""          # Hướng xử lý đề xuất


@dataclass
class ValidationReport:
    is_valid: bool = True     # True nếu không có lỗi CRITICAL
    critical_count: int = 0
    warning_count: int = 0
    issues: List[ValidationIssue] = field(default_factory=list)
    critical_item_codes: Set[str] = field(default_factory=set)
    warning_item_codes: Set[str] = field(default_factory=set)
    invalid_item_codes: Set[str] = field(default_factory=set)

    @property
    def critical_messages(self) -> List[str]:
        return [iss.message for iss in self.issues if iss.severity == SEV_CRITICAL]

    @property
    def warning_messages(self) -> List[str]:
        return [iss.message for iss in self.issues if iss.severity == SEV_WARNING]

    @property
    def summary_messages(self) -> List[str]:
        """Tóm tắt lỗi critical gom nhóm theo từng loại kiểm tra (cho wf.dept_problems & thông báo)."""
        crit_issues = [iss for iss in self.issues if iss.severity == SEV_CRITICAL]
        if not crit_issues:
            return []
        from collections import defaultdict
        grouped = defaultdict(list)
        for iss in crit_issues:
            grouped[iss.code].append(iss)
        summaries = []
        for code, items in grouped.items():
            if code == "CRIT_EMPTY":
                summaries.append("Phòng ban chưa có dòng ngân sách nào")
            elif code == "CRIT_QTY_PRICE":
                summaries.append(f"{len(items)} dòng có số lượng <= 0")
            elif code == "CRIT_PHASING":
                summaries.append(f"{len(items)} dòng có tổng phân kỳ khác 100%")
            elif code == "CRIT_NEED_REASON":
                summaries.append(f"{len(items)} dòng 'Phát sinh mới' / 'Hạ tầng dùng chung' chưa ghi lý do / căn cứ")
            elif code == "CRIT_HANDOVER_DATE":
                summaries.append(f"{len(items)} dòng có ngày bàn giao trước tháng giải ngân")
            else:
                summaries.append(f"{len(items)} dòng vi phạm {code}")
        return summaries


def _parse_month_year(m_str: str) -> Optional[datetime.date]:
    """Phân tích nhãn tháng dạng 'T10 2025' thành ngày đầu tháng."""
    try:
        parts = str(m_str).strip().split()
        if len(parts) == 2 and parts[0].startswith("T"):
            mo = int(parts[0][1:])
            yr = int(parts[1])
            return datetime.date(yr, mo, 1)
    except (ValueError, TypeError, IndexError):
        pass
    return None


def _parse_date(d_str: Any) -> Optional[datetime.date]:
    """Phân tích chuỗi ngày YYYY-MM-DD hoặc DD/MM/YYYY."""
    if not d_str or pd.isna(d_str):
        return None
    s = str(d_str).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def validate_budget_rows(
    df: Optional[pd.DataFrame],
    months: Optional[List[str]] = None,
    master: Optional[Dict[str, Any]] = None
) -> ValidationReport:
    """
    Rà soát toàn diện các dòng ngân sách của một phòng ban hoặc site trước khi nộp.
    
    Quy tắc Critical (Chặn nộp):
    1. Phòng ban trống (không có dòng ngân sách).
    2. Số lượng <= 0.
    3. Tổng tỷ lệ phân kỳ 12 tháng khác 100% (dung sai 0.001).
    4. Căn cứ / lý do phát sinh mới hoặc hạ tầng dùng chung để trống.
    5. Ngày bàn giao tài sản nằm trước tháng giải ngân đầu tiên có phân kỳ.
    
    Quy tắc Warning (Cảnh báo nhắc nhở):
    0. Đơn giá = 0 (phần mềm miễn phí, hạng mục tư vấn chưa báo giá... - không chặn nộp, luật nộp trước đây cũng không chặn).
    1. Chưa có mã danh mục chuẩn CNTT (catalog_code trống).
    2. Trùng lặp hạng mục trong cùng một phòng ban đề xuất.
    3. Đơn giá lệch > 25% so với giá chuẩn trong Master Data.
    4. Phân loại kế toán chưa chuẩn (đơn giá < 30 triệu nhưng chọn TSCĐ).
    """
    if months is None:
        months = DEFAULT_MONTHS

    report = ValidationReport()

    if df is None or df.empty:
        issue = ValidationIssue(
            severity=SEV_CRITICAL,
            code="CRIT_EMPTY",
            title="Chưa có dữ liệu ngân sách",
            message="Phòng ban chưa có bất kỳ dòng ngân sách nào được lập",
            action="Thêm hạng mục trang bị bằng popup Checklist hoặc form nhập liệu"
        )
        report.is_valid = False
        report.critical_count = 1
        report.issues.append(issue)
        return report

    # Bảng chuẩn giá từ Master Data để đối chiếu
    cat_prices = {}
    if master and "standard_items" in master:
        for it in master["standard_items"]:
            code = str(it.get("code") or "").strip().lower()
            name = str(it.get("name") or "").strip().lower()
            p = clean_number(it.get("price"), 0.0)
            if code:
                cat_prices[code] = p
            if name:
                cat_prices[name] = p

    # Tập hợp kiểm tra trùng lặp trong cùng phòng ban
    seen_items: Dict[str, List[str]] = {}  # {key: [item_code1, item_code2]}

    for idx, r in df.iterrows():
        it_code = str(r.get("item_code") or "").strip()
        it_name = str(r.get("item_name") or "").strip()
        qty = clean_number(r.get("quantity"), 0.0)
        price = clean_number(r.get("unit_price"), 0.0)
        need_type = str(r.get("need_type") or "").strip()
        need_reason = str(r.get("need_reason") or "").strip()
        cat_code = str(r.get("catalog_code") or "").strip()
        handover_str = r.get("handover_date")
        capex_type = str(r.get("capex_type") or "").strip()
        label_code = it_code or f"Dòng #{idx + 1}"

        # --- 1. CRITICAL: Số lượng <= 0; WARNING: Đơn giá = 0 ---
        # Đơn giá 0 chỉ cảnh báo: danh mục có hạng mục giá 0 thật (vd. phần mềm đọc PDF miễn phí trong bộ trang bị chuẩn,
        # tư vấn chưa báo giá) - chặn nộp làm phần lớn phòng ban không nộp được.
        if qty <= 0:
            report.issues.append(ValidationIssue(
                severity=SEV_CRITICAL,
                code="CRIT_QTY_PRICE",
                title="Số lượng không hợp lệ",
                message=f"{label_code} ({it_name}): Số lượng ({qty}) phải > 0",
                item_code=it_code,
                item_name=it_name,
                row_index=idx,
                action="Nhập lại số lượng > 0 hoặc xóa dòng"
            ))
            report.critical_item_codes.add(it_code)
        if price <= 0:
            report.issues.append(ValidationIssue(
                severity=SEV_WARNING,
                code="WARN_ZERO_PRICE",
                title="Chưa có đơn giá",
                message=f"{label_code} ({it_name}): Đơn giá = 0 - kiểm tra lại nếu không phải hạng mục miễn phí",
                item_code=it_code,
                item_name=it_name,
                row_index=idx,
                action="Nhập đơn giá theo báo giá, hoặc bỏ qua nếu hạng mục miễn phí"
            ))
            report.warning_item_codes.add(it_code)

        # --- 2. CRITICAL: Tổng tỷ lệ phân kỳ != 100% ---
        pcts = [clean_number(r.get(f"pct_{m}"), 0.0) for m in months]
        sum_pct = sum(pcts)
        pct_valid_col = r.get("pct_valid")
        
        is_pct_bad = False
        if pct_valid_col is not None and not pd.isna(pct_valid_col):
            if not bool(pct_valid_col):
                is_pct_bad = True
        elif abs(sum_pct - 1.0) > 0.001 and qty > 0:
            is_pct_bad = True

        if is_pct_bad:
            report.issues.append(ValidationIssue(
                severity=SEV_CRITICAL,
                code="CRIT_PHASING",
                title="Tổng phân kỳ 12 tháng khác 100%",
                message=f"{label_code} ({it_name}): Tổng tỷ lệ phân kỳ hiện là {sum_pct * 100:.1f}%, phải đủ 100%",
                item_code=it_code,
                item_name=it_name,
                row_index=idx,
                action="Điều chỉnh lại tỷ lệ phân kỳ 12 tháng sao cho tổng đúng 100%"
            ))
            report.critical_item_codes.add(it_code)

        # --- 3. CRITICAL: Lý do phát sinh mới / hạ tầng dùng chung trống ---
        if need_type in qt.NEED_WITH_REASON and not need_reason:
            report.issues.append(ValidationIssue(
                severity=SEV_CRITICAL,
                code="CRIT_NEED_REASON",
                title="Thiếu căn cứ / lý do thẩm định",
                message=f"{label_code} ({it_name}): Thuộc diện '{need_type}' bắt buộc phải ghi rõ lý do / căn cứ",
                item_code=it_code,
                item_name=it_name,
                row_index=idx,
                action="Điền thông tin vào cột 'Căn cứ / lý do phát sinh'"
            ))
            report.critical_item_codes.add(it_code)

        # --- 4. CRITICAL: Ngày bàn giao trước tháng giải ngân đầu tiên ---
        handover_dt = _parse_date(handover_str)
        if handover_dt:
            # Tìm tháng đầu tiên có giải ngân
            first_mo_idx = next((i for i, p in enumerate(pcts) if p > 0), None)
            if first_mo_idx is not None:
                first_mo_dt = _parse_month_year(months[first_mo_idx])
                if first_mo_dt and handover_dt < first_mo_dt:
                    report.issues.append(ValidationIssue(
                        severity=SEV_CRITICAL,
                        code="CRIT_HANDOVER_DATE",
                        title="Ngày bàn giao trước tháng giải ngân",
                        message=f"{label_code} ({it_name}): Ngày bàn giao ({handover_dt.strftime('%d/%m/%Y')}) trước tháng mua đầu tiên ({months[first_mo_idx]})",
                        item_code=it_code,
                        item_name=it_name,
                        row_index=idx,
                        action="Chỉnh lại ngày bàn giao bằng hoặc sau tháng giải ngân mua sắm"
                    ))
                    report.critical_item_codes.add(it_code)

        # --- 5. WARNING: Thiếu mã danh mục chuẩn CNTT ---
        if not cat_code:
            report.issues.append(ValidationIssue(
                severity=SEV_WARNING,
                code="WARN_NO_CATALOG",
                title="Hạng mục chưa gán mã danh mục chuẩn",
                message=f"{label_code} ({it_name}): Chưa có mã danh mục CNTT tập đoàn",
                item_code=it_code,
                item_name=it_name,
                row_index=idx,
                action="Bấm 'Chuẩn hóa & Tính lại' hoặc chọn từ danh mục chuẩn để áp đúng mã và đơn giá tham chiếu"
            ))
            report.warning_item_codes.add(it_code)

        # --- 6. WARNING: Trùng lặp hạng mục trong cùng một phòng ban ---
        dedup_key = cat_code.lower() if cat_code else it_name.lower().strip()
        if dedup_key and qty > 0:
            seen_items.setdefault(dedup_key, []).append(label_code)

        # --- 7. WARNING: Đơn giá lệch lớn (>25%) so với giá chuẩn ---
        ref_p = cat_prices.get(cat_code.lower()) or cat_prices.get(it_name.lower())
        if ref_p and ref_p > 0 and price > 0:
            diff_ratio = abs(price - ref_p) / ref_p
            if diff_ratio > 0.25:
                direction = "cao hơn" if price > ref_p else "thấp hơn"
                report.issues.append(ValidationIssue(
                    severity=SEV_WARNING,
                    code="WARN_PRICE_DEVIATION",
                    title="Đơn giá lệch lớn so với danh mục chuẩn",
                    message=f"{label_code} ({it_name}): Đơn giá {price:,.0f} VNĐ {direction} {diff_ratio * 100:.0f}% so với giá chuẩn ({ref_p:,.0f} VNĐ)",
                    item_code=it_code,
                    item_name=it_name,
                    row_index=idx,
                    action="Kiểm tra lại cấu hình hoặc ghi chú giải trình lý do biến động giá"
                ))
                report.warning_item_codes.add(it_code)

        # --- 8. WARNING: Phân loại kế toán chưa chuẩn (nguyên giá < 30 triệu là TSCĐ) ---
        if capex_type == "CAPEX" and 0 < price < TSCD_THRESHOLD:
            report.issues.append(ValidationIssue(
                severity=SEV_WARNING,
                code="WARN_CAPEX_THRESHOLD",
                title="Đơn giá < 30 triệu nhưng phân loại là TSCĐ",
                message=f"{label_code} ({it_name}): Đơn giá {price:,.0f} VNĐ < 30 triệu đồng (ngưỡng TSCĐ theo TT45)",
                item_code=it_code,
                item_name=it_name,
                row_index=idx,
                action="Chuyển sang CCDC để hạch toán chi phí phân bổ đúng Thông tư 45/2013/TT-BTC"
            ))
            report.warning_item_codes.add(it_code)

    # Xử lý các hạng mục bị trùng lặp
    for k, codes in seen_items.items():
        if len(codes) > 1:
            report.issues.append(ValidationIssue(
                severity=SEV_WARNING,
                code="WARN_DUPLICATE",
                title="Hạng mục bị khai báo trùng lặp",
                message=f"Có {len(codes)} dòng cùng khai báo hạng mục '{k.upper()}': {', '.join(codes)}",
                action="Gom chung thành 1 dòng với số lượng tổng hoặc phân biệt rõ bằng chi tiết công việc"
            ))
            for c in codes:
                report.warning_item_codes.add(c)

    # Tổng kết
    report.critical_count = sum(1 for iss in report.issues if iss.severity == SEV_CRITICAL)
    report.warning_count = sum(1 for iss in report.issues if iss.severity == SEV_WARNING)
    report.is_valid = (report.critical_count == 0)
    report.invalid_item_codes = report.critical_item_codes | report.warning_item_codes

    return report
