"""Nhật ký thao tác: lọc theo người / loại thao tác / ngày / chữ trong chi tiết."""
import datetime
import unittest

import db


class QueryAuditTest(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db.connect() as conn:
            conn.execute("DELETE FROM audit_log")
            rows = [("2026-10-01T08:00:00", "a@x.vn", "login", "dev"),
                    ("2026-10-05T09:30:00", "b@x.vn", "add_exec", "2027/BDA/A01-001: Hợp đồng / PO PO-1 100,000"),
                    ("2026-10-05T23:59:59", "a@x.vn", "save_lines", "2027/AHA: 12 dòng"),
                    ("2026-10-09T10:00:00", "b@x.vn", "add_exec_many", "2027: nạp 3 chứng từ từ erp.xlsx")]
            conn.executemany("INSERT INTO audit_log(ts, email, action, detail) VALUES (?,?,?,?)", rows)

    def test_filters(self):
        q = db.query_audit
        self.assertEqual(len(q()), 4)
        self.assertEqual({r["email"] for r in q(emails=["a@x.vn"])}, {"a@x.vn"})
        self.assertEqual([r["action"] for r in q(actions=["add_exec", "add_exec_many"])], ["add_exec_many", "add_exec"])
        self.assertEqual(len(q(date_from="2026-10-05", date_to="2026-10-05")), 2)      # cả dòng 23:59:59
        self.assertEqual([r["action"] for r in q(text="PO-1")], ["add_exec"])
        self.assertEqual([r["action"] for r in q(text="ERP")], ["add_exec_many"])       # không phân biệt hoa thường
        self.assertEqual(len(q(emails=["b@x.vn"], date_to="2026-10-06")), 1)
        self.assertEqual(len(q(limit=1)), 1)

    def test_text_is_parameter_not_sql(self):
        self.assertEqual(db.query_audit(text="' OR 1=1 --"), [])

    def test_values(self):
        self.assertEqual(db.audit_values("email"), ["a@x.vn", "b@x.vn"])
        self.assertIn("login", db.audit_values("action"))
        with self.assertRaises(ValueError):
            db.audit_values("detail; DROP TABLE audit_log")


if __name__ == "__main__":
    unittest.main()
