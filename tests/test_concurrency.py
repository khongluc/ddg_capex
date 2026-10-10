"""Nhiều người cùng lưu 1 site: gộp theo Mã hạng mục, không ghi đè thay đổi của nhau."""
import copy
import threading
import time
import unittest

import db
import workflow as wf
from capex_engine import assign_item_seqs
from tests import fixtures as fx


def edited(rows, code, **changes):
    return [{**r, **changes} if r["item_code"] == code else dict(r) for r in rows]


class MergeRowsTest(unittest.TestCase):
    def setUp(self):
        self.base = fx.make_lines()
        self.a, self.b, self.c = (r["item_code"] for r in self.base[:3])

    def test_two_people_edit_different_rows_both_kept(self):
        current = edited(self.base, self.b, quantity=99)          # người B đã lưu: sửa dòng b
        mine = edited(self.base, self.a, quantity=50)             # người A (xem bản cũ) sửa dòng a
        out, conflicts = wf.merge_site_rows(self.base, mine, current)
        q = {r["item_code"]: r["quantity"] for r in out}
        self.assertEqual((q[self.a], q[self.b]), (50, 99))
        self.assertEqual(conflicts, [])
        self.assertEqual([r["item_code"] for r in out], [r["item_code"] for r in self.base])  # giữ thứ tự

    def test_same_row_conflict_keeps_theirs_and_reports(self):
        current = edited(self.base, self.a, quantity=99)
        mine = edited(self.base, self.a, quantity=50)
        out, conflicts = wf.merge_site_rows(self.base, mine, current)
        self.assertEqual(next(r for r in out if r["item_code"] == self.a)["quantity"], 99)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("người khác vừa sửa", conflicts[0])

    def test_untouched_rows_follow_current_including_other_deletes(self):
        current = [r for r in self.base if r["item_code"] != self.c]       # B xóa dòng c
        current = edited(current, self.b, need_reason="B sửa lý do")       # và sửa dòng b
        out, conflicts = wf.merge_site_rows(self.base, copy.deepcopy(self.base), current)  # A lưu mà không đổi gì
        codes = [r["item_code"] for r in out]
        self.assertNotIn(self.c, codes)
        self.assertEqual(next(r for r in out if r["item_code"] == self.b)["need_reason"], "B sửa lý do")
        self.assertEqual(conflicts, [])

    def test_delete_vs_edit_and_edit_vs_delete(self):
        current = edited(self.base, self.a, quantity=99)                    # B sửa a
        mine = [r for r in self.base if r["item_code"] != self.a]           # A xóa a
        out, conflicts = wf.merge_site_rows(self.base, mine, current)
        self.assertIn(self.a, [r["item_code"] for r in out])
        self.assertIn("không xóa", conflicts[0])
        current = [r for r in self.base if r["item_code"] != self.a]        # B xóa a
        mine = edited(self.base, self.a, quantity=50)                       # A sửa a
        out, conflicts = wf.merge_site_rows(self.base, mine, current)
        self.assertNotIn(self.a, [r["item_code"] for r in out])
        self.assertIn("vừa xóa", conflicts[0])

    def test_additions_from_both_sides_and_own_delete(self):
        theirs = {**self.base[0], "item_code": "A01A27BDA04-05-901", "item_seq": 901, "item_name": "B thêm"}
        current = self.base + [theirs]
        mine = [r for r in self.base if r["item_code"] != self.c] + [{"item_name": "A thêm", "quantity": 1, "dept_proposing": fx.KD}]
        out, conflicts = wf.merge_site_rows(self.base, mine, current)
        names = [r["item_name"] for r in out]
        self.assertIn("B thêm", names)
        self.assertEqual(names[-1], "A thêm")
        self.assertNotIn(self.c, [r.get("item_code") for r in out])
        self.assertEqual(conflicts, [])

    def test_dept_scope_does_not_touch_other_departments(self):
        base_kt = [r for r in self.base if r["dept_proposing"] == fx.KT]   # phòng ban chỉ thấy phòng mình
        mine = edited(base_kt, base_kt[0]["item_code"], quantity=7)
        out, _ = wf.merge_site_rows(base_kt, mine, self.base)
        self.assertEqual(len(out), len(self.base))
        self.assertEqual([r["item_code"] for r in out], [r["item_code"] for r in self.base])


class LockedSaveTest(unittest.TestCase):
    """Giao dịch có khóa trên CSDL SQLite tạm: hai lượt lưu chồng nhau không mất dữ liệu, không trùng mã."""
    YEAR, SITE = "2099", "TST"

    def setUp(self):
        db.init_db()
        db.replace_lines(self.YEAR, self.SITE, fx.make_lines(), actor="setup@icost.test")
        with db.connect() as conn:
            conn.execute("DELETE FROM app_settings WHERE key = ?", (f"item_seq|{self.YEAR}|{self.SITE}",))
        self.base = [{k: v for k, v in r.items() if k != "site_code"} for r in db.load_lines(self.YEAR, [self.SITE])]

    def save(self, new_rows, delay=0.0):
        def _merge(current, counters):
            if delay:
                time.sleep(delay)  # giữ khóa lâu để lượt lưu kia phải chờ
            rows, _ = wf.merge_site_rows(self.base, new_rows, current)
            return rows, assign_item_seqs(rows, counters)
        return db.merge_site_lines(self.YEAR, self.SITE, _merge, actor="tester@icost.test")

    def test_concurrent_saves_both_survive_with_unique_codes(self):
        a_code, b_code = self.base[0]["item_code"], self.base[1]["item_code"]
        mine_a = edited(self.base, a_code, quantity=50) + [{**{k: v for k, v in self.base[0].items() if k not in ("item_seq", "item_code")}, "item_name": "Thêm của A"}]
        mine_b = edited(self.base, b_code, quantity=99) + [{**{k: v for k, v in self.base[0].items() if k not in ("item_seq", "item_code")}, "item_name": "Thêm của B"}]
        t = threading.Thread(target=self.save, args=(mine_a, 0.6))
        t.start()
        time.sleep(0.15)  # B lưu trong lúc A đang giữ khóa
        self.save(mine_b)
        t.join()
        rows = db.load_lines(self.YEAR, [self.SITE])
        q = {r["item_code"]: r["quantity"] for r in rows}
        self.assertEqual((q[a_code], q[b_code]), (50, 99))
        names = [r["item_name"] for r in rows]
        self.assertIn("Thêm của A", names)
        self.assertIn("Thêm của B", names)
        codes = [r["item_code"] for r in rows]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(rows), len(self.base) + 2)


if __name__ == "__main__":
    unittest.main()
