"""Nạp chứng từ giải ngân hàng loạt từ file Excel / CSV (xuất từ ERP)."""
import io
import unittest

import pandas as pd

import db
import execution as ex

CODE, CODE2 = "A01A27BDA01-04-001", "A01A27BDA09-07-002"
SUMM = pd.DataFrame([
    {"site_code": "BDA", "item_code": CODE, "dept": "P.KD", "item_name": "Laptop", "budget": 200_000_000,
     "requested": 0.0, "contracted": 0.0, "paid": 0.0, "flag": ""},
    {"site_code": "BDA", "item_code": CODE2, "dept": "P.KT", "item_name": "M365", "budget": 30_000_000,
     "requested": 0.0, "contracted": 0.0, "paid": 0.0, "flag": ""},
])


def raw(*rows):
    cols = ["Mã hạng mục", "Loại chứng từ", "Số chứng từ", "Ngày chứng từ", "Số tiền (chưa VAT)", "Nhà cung cấp", "Ghi chú"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


class ParseAmountDateTest(unittest.TestCase):
    def test_amount_formats(self):
        for v, want in ((1234000, 1234000), ("1.234.000", 1234000), ("1,234,000", 1234000), ("1 234 000 đ", 1234000),
                        ("1234000.5", 1234000.5), ("12.500", 12500), ("", 0), (None, 0), ("abc", 0)):
            self.assertEqual(ex.parse_amount(v), want, v)

    def test_dates(self):
        self.assertEqual(ex.parse_doc_date("15/11/2026"), "2026-11-15")
        self.assertEqual(ex.parse_doc_date("2026-11-15"), "2026-11-15")
        self.assertEqual(ex.parse_doc_date(pd.Timestamp("2026-12-01")), "2026-12-01")
        self.assertEqual(ex.parse_doc_date("ngày mai"), "")


class ParseImportTest(unittest.TestCase):
    def test_statuses(self):
        ledger = [{"item_code": CODE2, "kind": db.EXEC_PAYMENT, "doc_no": "UNC-1", "amount": 10_000_000}]
        out = ex.parse_import(raw(
            (CODE, "Hợp đồng / PO", "PO-1", "15/11/2026", "150.000.000", "ABC", ""),     # hợp lệ
            (CODE, "PO", "PO-2", "16/11/2026", 80_000_000, "ABC", ""),                    # lũy kế 230tr > 200tr -> vượt
            (CODE, "PO", "PO-1", "15/11/2026", 150_000_000, "ABC", ""),                   # trùng dòng trên
            (CODE2, "UNC", "UNC-1", "01/12/2026", "10,000,000", "", ""),                  # trùng sổ
            ("SAI-MA", "Thanh toán", "X", "01/12/2026", 1, "", ""),                       # mã không có
            (CODE2, "Tạm ứng", "Y", "", 5, "", ""),                                       # loại không rõ
            (CODE2, "Đề nghị mua", "Z", "32/13/2026", 0, "", ""),                         # tiền 0 + ngày sai
            (None, None, None, None, None, None, None),                                  # dòng trống -> bỏ
        ), SUMM, ledger)
        self.assertEqual(out["status"].tolist(), [ex.IMPORT_STATUS_OK, ex.IMPORT_STATUS_OVER, ex.IMPORT_STATUS_DUP,
                                                  ex.IMPORT_STATUS_DUP, ex.IMPORT_STATUS_ERR, ex.IMPORT_STATUS_ERR,
                                                  ex.IMPORT_STATUS_ERR])
        first = out.iloc[0]
        self.assertEqual((first["kind"], first["amount"], first["doc_date"], first["site_code"], first["row"]),
                         (db.EXEC_CONTRACT, 150_000_000, "2026-11-15", "BDA", 2))
        self.assertIn("vượt", out.iloc[1]["message"])
        self.assertIn("Số tiền", out.iloc[6]["message"])
        self.assertIn("Ngày", out.iloc[6]["message"])

    def test_template_round_trip(self):
        tpl = pd.read_excel(io.BytesIO(ex.import_template()), sheet_name=0)
        out = ex.parse_import(tpl, SUMM, [])
        self.assertEqual(out["status"].tolist(), [ex.IMPORT_STATUS_OK, ex.IMPORT_STATUS_OK])
        self.assertEqual(out["kind"].tolist(), [db.EXEC_CONTRACT, db.EXEC_PAYMENT])

    def test_headers_without_accents(self):
        df = pd.DataFrame([{"ma hang muc": CODE, "loai": "thanh toan", "so tien": "1.000.000"}])
        self.assertEqual(ex.parse_import(df, SUMM, [])["status"].tolist(), [ex.IMPORT_STATUS_OK])


class AddExecManyTest(unittest.TestCase):
    YEAR = "2031"

    def test_writes_all_or_nothing(self):
        db.init_db()
        rows = [{"site_code": "BDA", "item_code": CODE, "kind": db.EXEC_CONTRACT, "amount": 100.0, "doc_no": "PO-9"},
                {"site_code": "BDA", "item_code": CODE, "kind": "khong_hop_le", "amount": 5.0}]
        with self.assertRaises(ValueError):
            db.add_exec_many(self.YEAR, rows, "t@test")
        self.assertEqual(db.load_exec(self.YEAR, ["BDA"]), [])
        self.assertEqual(db.add_exec_many(self.YEAR, rows[:1] * 2, "t@test", source="erp.xlsx"), 2)
        self.assertEqual(len(db.load_exec(self.YEAR, ["BDA"])), 2)


if __name__ == "__main__":
    unittest.main()
