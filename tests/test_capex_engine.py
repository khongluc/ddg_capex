import copy
import unittest

from capex_engine import calculate_row, snap_units, split_units, default_handover_date, assign_item_seqs
from master_data import division_of
from tests import fixtures as fx


def calc(row):
    return calculate_row(dict(row), months=fx.MONTHS, year_code="A27", master=fx.master())


class PhasingTest(unittest.TestCase):
    def test_split_units_largest_remainder(self):
        self.assertEqual(split_units(21, [7, 7, 2, 4, 1]), [7, 7, 2, 4, 1])
        self.assertEqual(split_units(21, [0.33, 0.33, 0.10, 0.19, 0.05]), [7, 7, 2, 4, 1])
        self.assertEqual(split_units(10, [1, 1, 1]), [4, 3, 3])
        self.assertIsNone(split_units(2.5, [1, 1]))
        self.assertIsNone(split_units(5, [0, 0]))

    def test_snap_near_integer_only(self):
        self.assertEqual(snap_units([0.3334, 0.3333, 0.0952, 0.1905, 0.0476], 21), [7, 7, 2, 4, 1])
        self.assertIsNone(snap_units([0.5, 0.5], 3))  # chia lẻ thật -> giữ tỷ lệ

    def test_month_values_are_whole_units(self):
        r = calc({"quantity": 21, "unit_price": 18e6, **{f"pct_{m}": p for m, p in zip(fx.MONTHS, [0.3334, 0.3333, 0.0952, 0.1905, 0.0476])}})
        self.assertEqual([r[f"val_{m}"] for m in fx.MONTHS[:5]], [126e6, 126e6, 36e6, 72e6, 18e6])
        self.assertEqual(r["total_val"], r["total_budget"])
        self.assertTrue(r["pct_valid"])

    def test_manual_fraction_kept_but_quota_line_resplit(self):
        r = calc({"quantity": 3, "unit_price": 1e6, f"pct_{fx.MONTHS[0]}": 0.5, f"pct_{fx.MONTHS[1]}": 0.5})
        self.assertEqual(r[f"val_{fx.MONTHS[0]}"], 1.5e6)
        q = calc({"quantity": 1, "unit_price": 3.45e6, "auto_quota": True, f"pct_{fx.MONTHS[0]}": 0.5, f"pct_{fx.MONTHS[1]}": 0.5})
        self.assertEqual((q[f"val_{fx.MONTHS[0]}"], q[f"val_{fx.MONTHS[1]}"]), (3.45e6, 0))


class HandoverTest(unittest.TestCase):
    def test_default_and_follows_phasing(self):
        base = {"quantity": 21, "unit_price": 18e6, **{f"pct_{m}": p for m, p in zip(fx.MONTHS, [7/21, 7/21, 2/21, 4/21, 1/21])}}
        r = calc(base)
        self.assertEqual(r["handover_date"], "2027-02-28")
        r2 = calc({**r, f"pct_{fx.MONTHS[4]}": 0, f"pct_{fx.MONTHS[3]}": 5/21})
        self.assertEqual(r2["handover_date"], "2027-01-31")

    def test_manual_kept_and_cleared_returns_to_auto(self):
        r = calc({"quantity": 1, "unit_price": 1, f"pct_{fx.MONTHS[3]}": 1, "handover_date": "2027-03-15"})
        self.assertEqual((r["handover_date"], r["handover_auto"]), ("2027-03-15", ""))
        self.assertEqual(calc({**r, "handover_date": ""})["handover_date"], "2027-01-31")

    def test_edges(self):
        self.assertEqual(default_handover_date({f"pct_{fx.MONTHS[-1]}": 1}, fx.MONTHS), "2027-09-30")
        self.assertEqual(default_handover_date({"pct_T2 2028": 1}, ["T2 2028"]), "2028-02-29")
        self.assertEqual(calc({"quantity": 1, "unit_price": 1})["handover_date"], "")


class DivisionTest(unittest.TestCase):
    def test_lookup_and_fill(self):
        m = fx.master()
        self.assertNotEqual(division_of(fx.KD, m), "")
        self.assertEqual(division_of("  phòng kd   10 ", m), division_of(fx.KD, m))
        self.assertEqual(division_of("PHÒNG KHÔNG CÓ THẬT", m), "")
        self.assertEqual(calc({"quantity": 1, "unit_price": 1, "dept_proposing": fx.KT})["division"], division_of(fx.KT, m))
        self.assertEqual(calc({"quantity": 1, "unit_price": 1, "dept_proposing": fx.KT, "division": "KHỐI KHÁC"})["division"], "KHỐI KHÁC")


class ItemCodeTest(unittest.TestCase):
    def save(self, rows, counters):
        out = [calc({**{k: v for k, v in r.items() if v is not None}, "stt": i + 1}) for i, r in enumerate(rows)]
        return out, assign_item_seqs(out, counters)

    def test_stable_across_saves_deletes_and_reorders(self):
        rows, cnt = self.save(fx.make_lines(), {})
        codes = [r["item_code"] for r in rows]
        self.assertEqual(len(set(codes)), len(codes))
        again, cnt2 = self.save(rows, cnt)
        self.assertEqual([r["item_code"] for r in again], codes)
        self.assertEqual(cnt2, cnt)
        deleted = again[0]["item_code"]
        mod = list(reversed(again[1:])) + [{**{k: v for k, v in again[0].items() if k not in ("item_seq", "item_code_base", "item_code")}}]
        rows3, cnt3 = self.save(mod, cnt2)
        for r in rows3[:-1]:
            self.assertIn(r["item_code"], codes)
        self.assertNotEqual(rows3[-1]["item_code"], deleted)  # số đã xóa không cấp lại
        base = rows3[-1]["item_code_base"]
        self.assertEqual(rows3[-1]["item_code"], f"{base}-{cnt2[base] + 1:03d}")

    def test_duplicate_seq_gets_new_number(self):
        rows, cnt = self.save(fx.make_lines(), {})
        dup, _ = self.save(rows + [copy.deepcopy(rows[0])], cnt)
        self.assertEqual(len({r["item_code"] for r in dup}), len(dup))
        self.assertEqual(dup[0]["item_code"], rows[0]["item_code"])

    def test_change_asset_class_moves_code_group(self):
        rows, cnt = self.save(fx.make_lines(), {})
        m = fx.master()
        other = next(c["name"] for c in m["asset_cat1"] if c.get("code4") and c.get("code4") != rows[0]["item_code_base"].rsplit("-", 1)[-1])
        ch = copy.deepcopy(rows)
        ch[0]["asset_cat1"] = other
        out, _ = self.save(ch, cnt)
        self.assertNotEqual(out[0]["item_code_base"], rows[0]["item_code_base"])
        self.assertEqual([r["item_code"] for r in out[1:]], [r["item_code"] for r in rows[1:]])


if __name__ == "__main__":
    unittest.main()
