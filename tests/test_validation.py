import unittest
import pandas as pd

from master_data import DEFAULT_MONTHS
from validators import (
    validate_budget_rows,
    SEV_CRITICAL,
    SEV_WARNING,
    ValidationReport
)


class TestValidationEngine(unittest.TestCase):

    def setUp(self):
        self.months = DEFAULT_MONTHS  # 12 tháng: T10..T12 2025, T1..T9 2026

    def test_empty_dataframe(self):
        rep = validate_budget_rows(pd.DataFrame(), self.months)
        self.assertFalse(rep.is_valid)
        self.assertEqual(rep.critical_count, 1)
        self.assertEqual(rep.issues[0].code, "CRIT_EMPTY")
        self.assertIn("Phòng ban chưa có dòng ngân sách nào", rep.summary_messages)

    def test_valid_row(self):
        row = {
            "item_code": "NM-01-001",
            "item_name": "Laptop Dell Latitude",
            "catalog_code": "IT01-004",
            "unit": "Máy",
            "quantity": 5,
            "unit_price": 25_000_000,
            "total_budget": 125_000_000,
            "need_type": "Định biên",
            "need_reason": "Theo định biên phòng ban",
            "capex_type": "CCDC",  # < 30tr -> CCDC chuẩn
            "handover_date": "2025-10-31",
            f"pct_{self.months[0]}": 1.0,
            "pct_valid": True
        }
        df = pd.DataFrame([row])
        rep = validate_budget_rows(df, self.months)
        self.assertTrue(rep.is_valid)
        self.assertEqual(rep.critical_count, 0)
        self.assertEqual(rep.warning_count, 0)
        self.assertEqual(len(rep.invalid_item_codes), 0)

    def test_zero_or_negative_qty_and_price(self):
        # Qty = 0
        r1 = {
            "item_code": "IT-01",
            "item_name": "Bàn phím cơ",
            "quantity": 0,
            "unit_price": 1_200_000,
            f"pct_{self.months[0]}": 1.0,
        }
        # Price = 0
        r2 = {
            "item_code": "IT-02",
            "item_name": "Chuột không dây",
            "quantity": 2,
            "unit_price": 0,
            f"pct_{self.months[0]}": 1.0,
        }
        df = pd.DataFrame([r1, r2])
        rep = validate_budget_rows(df, self.months)
        self.assertFalse(rep.is_valid)
        self.assertEqual(rep.critical_count, 1)                     # SL = 0 chặn nộp
        codes = [iss.code for iss in rep.issues if iss.severity == SEV_CRITICAL]
        self.assertEqual(codes, ["CRIT_QTY_PRICE"])
        self.assertIn("IT-01", rep.critical_item_codes)
        # Đơn giá 0 chỉ cảnh báo (phần mềm miễn phí trong bộ trang bị chuẩn, tư vấn chưa báo giá) - không chặn nộp
        self.assertIn("IT-02", rep.warning_item_codes)
        self.assertNotIn("IT-02", rep.critical_item_codes)
        self.assertIn("WARN_ZERO_PRICE", [iss.code for iss in rep.issues])

    def test_phasing_not_100_percent(self):
        # Tổng tỷ lệ phân kỳ chỉ đạt 80% (0.8)
        r = {
            "item_code": "IT-03",
            "item_name": "Màn hình 27 inch",
            "quantity": 2,
            "unit_price": 5_000_000,
            f"pct_{self.months[0]}": 0.5,
            f"pct_{self.months[1]}": 0.3,
            # Thiếu 0.2
        }
        df = pd.DataFrame([r])
        rep = validate_budget_rows(df, self.months)
        self.assertFalse(rep.is_valid)
        self.assertIn("IT-03", rep.critical_item_codes)
        has_phasing_err = any(iss.code == "CRIT_PHASING" for iss in rep.issues)
        self.assertTrue(has_phasing_err)

    def test_missing_need_reason_for_new_need(self):
        r_new = {
            "item_code": "IT-04",
            "item_name": "Máy in màu đa năng",
            "quantity": 1,
            "unit_price": 15_000_000,
            "need_type": "Phát sinh mới",
            "need_reason": "",  # Để trống lý do
            f"pct_{self.months[0]}": 1.0,
        }
        df = pd.DataFrame([r_new])
        rep = validate_budget_rows(df, self.months)
        self.assertFalse(rep.is_valid)
        has_reason_err = any(iss.code == "CRIT_NEED_REASON" for iss in rep.issues)
        self.assertTrue(has_reason_err)

    def test_handover_date_before_first_purchase_month(self):
        # Mua vào T12 2025 (tháng thứ 3), nhưng ngày bàn giao lại ghi 2025-10-15 (T10 2025)
        r = {
            "item_code": "IT-05",
            "item_name": "Server lưu trữ NAS",
            "quantity": 1,
            "unit_price": 80_000_000,
            "need_type": "Định biên",
            "handover_date": "2025-10-15",
            f"pct_{self.months[2]}": 1.0,  # T12 2025
        }
        df = pd.DataFrame([r])
        rep = validate_budget_rows(df, self.months)
        self.assertFalse(rep.is_valid)
        has_date_err = any(iss.code == "CRIT_HANDOVER_DATE" for iss in rep.issues)
        self.assertTrue(has_date_err)

    def test_duplicate_items_generates_warning_only(self):
        # 2 dòng cùng tên thiết bị trong cùng 1 phòng ban
        r1 = {
            "item_code": "IT-06A",
            "item_name": "Màn hình Dell 24 inch",
            "catalog_code": "IT01-010",
            "quantity": 2,
            "unit_price": 3_500_000,
            "need_type": "Định biên",
            f"pct_{self.months[0]}": 1.0,
        }
        r2 = {
            "item_code": "IT-06B",
            "item_name": "Màn hình Dell 24 inch",
            "catalog_code": "IT01-010",
            "quantity": 1,
            "unit_price": 3_500_000,
            "need_type": "Định biên",
            f"pct_{self.months[1]}": 1.0,
        }
        df = pd.DataFrame([r1, r2])
        rep = validate_budget_rows(df, self.months)
        # Warning không làm is_valid thành False!
        self.assertTrue(rep.is_valid)
        self.assertGreater(rep.warning_count, 0)
        has_dup_warn = any(iss.code == "WARN_DUPLICATE" for iss in rep.issues)
        self.assertTrue(has_dup_warn)
        self.assertIn("IT-06A", rep.warning_item_codes)
        self.assertIn("IT-06B", rep.warning_item_codes)

    def test_capex_threshold_warning(self):
        # Đơn giá 20 triệu (< 30tr) nhưng chọn CAPEX
        r = {
            "item_code": "IT-07",
            "item_name": "iPad Pro",
            "catalog_code": "IT01-008",
            "quantity": 1,
            "unit_price": 20_000_000,
            "capex_type": "CAPEX",
            "need_type": "Định biên",
            f"pct_{self.months[0]}": 1.0,
        }
        df = pd.DataFrame([r])
        rep = validate_budget_rows(df, self.months)
        self.assertTrue(rep.is_valid)  # Vẫn cho nộp nhưng cảnh báo
        has_capex_warn = any(iss.code == "WARN_CAPEX_THRESHOLD" for iss in rep.issues)
        self.assertTrue(has_capex_warn)


if __name__ == "__main__":
    unittest.main()
