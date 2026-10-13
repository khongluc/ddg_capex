"""Nhắc gia hạn: hạng mục định kỳ năm trước mà năm đang lập chưa có / ít hơn."""
import unittest

import pandas as pd

from capex_engine import calculate_row, even_units
from renewals import STATUS_LESS, STATUS_MISSING, is_recurring, renewal_gaps, renewal_line
from tests import fixtures as fx

MASTER = {"standard_items": [
    {"code": "IT09-001", "name": "Microsoft 365 Business Standard", "unit": "User/năm", "kind": "software_subscription"},
    {"code": "IT12-005", "name": "Đường truyền Internet", "unit": "Tháng", "kind": "service"},
    {"code": "IT14-001", "name": "Tư vấn chuyển đổi số", "unit": "Gói", "kind": "service"},
    {"code": "IT01-001", "name": "Laptop", "unit": "Cái", "kind": "hardware"},
    {"code": "IT10-001", "name": "Bảo trì, cập nhật Tekla (hằng năm)", "unit": "License", "kind": "software_perpetual"},
]}


def line(code, qty, price, site="AHA", dept="P.KẾ TOÁN", **kw):
    it = next(i for i in MASTER["standard_items"] if i["code"] == code)
    return {"site_code": site, "catalog_code": code, "item_name": it["name"], "unit": it["unit"], "item_kind": it["kind"],
            "quantity": qty, "unit_price": price, "total_budget": qty * price, "dept_proposing": dept, **kw}


class IsRecurringTest(unittest.TestCase):
    def test_kinds(self):
        self.assertTrue(is_recurring(line("IT09-001", 1, 1)))                     # thuê bao phần mềm
        self.assertTrue(is_recurring(line("IT12-005", 12, 1)))                    # dịch vụ theo tháng
        self.assertFalse(is_recurring(line("IT14-001", 1, 1)))                    # tư vấn 1 lần
        self.assertFalse(is_recurring(line("IT01-001", 1, 1)))                    # phần cứng
        self.assertTrue(is_recurring(line("IT10-001", 1, 1, invest_type="Gia hạn, bảo trì")))

    def test_falls_back_to_catalog(self):
        self.assertTrue(is_recurring({"catalog_code": "IT09-001"}, MASTER["standard_items"][0]))


class RenewalGapsTest(unittest.TestCase):
    def test_missing_less_and_covered(self):
        prev = pd.DataFrame([
            line("IT09-001", 20, 3_000_000),                                     # năm nay chỉ 15 -> thiếu 5
            line("IT09-001", 5, 3_000_000, dept="P.NHÂN SỰ"),                   # cùng site + mã: gộp 25
            line("IT12-005", 12, 2_000_000),                                     # năm nay chưa có
            line("IT12-005", 12, 2_000_000, site="LAN"),                         # site khác đã có đủ
            line("IT14-001", 1, 500_000_000),                                    # tư vấn 1 lần: không nhắc
            line("IT01-001", 10, 20_000_000),                                    # phần cứng: không nhắc
        ])
        cur = pd.DataFrame([
            line("IT09-001", 15, 3_200_000, dept="P.CNTT"),                     # phòng khác vẫn tính
            line("IT12-005", 12, 2_000_000, site="LAN"),
        ])
        out = renewal_gaps(prev, cur, MASTER)
        self.assertEqual(out["catalog_code"].tolist(), ["IT09-001", "IT12-005"])  # tiền giảm dần: 30tr > 24tr
        m365, net = out.iloc[0], out.iloc[1]
        self.assertEqual((m365["prev_qty"], m365["cur_qty"], m365["missing_qty"]), (25, 15, 10))
        self.assertEqual((m365["est_amount"], m365["status"]), (30_000_000, STATUS_LESS))
        self.assertEqual(m365["depts"], "P.KẾ TOÁN, P.NHÂN SỰ")
        self.assertEqual((net["site_code"], net["status"], net["est_amount"]), ("AHA", STATUS_MISSING, 24_000_000))

    def test_no_catalog_code_matches_by_name(self):
        prev = pd.DataFrame([{"site_code": "AHA", "catalog_code": "", "item_name": "Gia hạn tên miền ddc.vn",
                              "unit": "Tên miền/năm", "quantity": 1, "total_budget": 1_000_000}])
        cur = pd.DataFrame([{"site_code": "AHA", "catalog_code": "", "item_name": "gia hạn tên miền  DDC.VN", "quantity": 1}])
        self.assertTrue(renewal_gaps(prev, cur, MASTER).empty)
        self.assertEqual(len(renewal_gaps(prev, pd.DataFrame(), MASTER)), 1)

    def test_empty(self):
        self.assertTrue(renewal_gaps(pd.DataFrame(), None, MASTER).empty)
        self.assertTrue(renewal_gaps(None, None, MASTER).empty)


class RenewalLineTest(unittest.TestCase):
    GAP = {"site_code": "AHA", "catalog_code": "", "item_name": "Gia hạn tên miền ddc.vn", "unit": "Tên miền/năm",
           "depts": "P.CNTT, P.HÀNH CHÍNH", "prev_qty": 2, "prev_amount": 2_000_000, "entity": "DDC",
           "need_type": "Định biên", "invest_type": "Mua mới"}

    def test_line_from_previous_year(self):
        units = even_units(4, fx.MONTHS, [fx.MONTHS[0], fx.MONTHS[6]])
        row = calculate_row(renewal_line(self.GAP, 4, units, fx.MONTHS, MASTER, 2026, "VP Bạch Đằng"), months=fx.MONTHS, master={})
        self.assertEqual((row["quantity"], row["unit_price"], row["total_budget"]), (4, 1_000_000, 4_000_000))  # giá bình quân năm trước
        self.assertEqual((row["dept_proposing"], row["need_type"], row["invest_type"]), ("P.CNTT", "Phát sinh mới", "Gia hạn, bảo trì"))
        self.assertEqual((row[f"val_{fx.MONTHS[0]}"], row[f"val_{fx.MONTHS[6]}"]), (2_000_000, 2_000_000))
        self.assertIn("2026", row["need_reason"])

    def test_infra_kept_and_catalog_price(self):
        master = {"standard_items": [{"code": "IT12-005", "name": "Đường truyền Internet", "unit": "Tháng", "kind": "service",
                                      "price": 3_000_000, "group": "IT12"}], "it_groups": []}
        gap = {**self.GAP, "catalog_code": "IT12-005", "item_name": "Đường truyền Internet", "need_type": "Hạ tầng dùng chung"}
        row = renewal_line(gap, 12, None, fx.MONTHS, master, 2026, "VP")
        self.assertEqual((row["unit_price"], row["need_type"], row["dept_using"]), (3_000_000, "Hạ tầng dùng chung", "Dùng chung toàn site"))
        self.assertEqual(row[f"pct_{fx.MONTHS[0]}"], 1.0)                       # chưa phân kỳ -> tháng đầu


if __name__ == "__main__":
    unittest.main()
