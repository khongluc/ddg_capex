import copy
import io
import unittest

import pandas as pd

import db
import pricing
import quota as qt
import workflow as wf
from capex_engine import calculate_row
from tests import fixtures as fx


class QuotaLinesTest(unittest.TestCase):
    def needs(self, add, weights=None, renew=0):
        it = fx.item(fx.ZWCAD)
        return pd.DataFrame([{"catalog_code": it["code"], "price": it["price"], "basis": "thử", "add_weights": weights,
                              "add_qty": add, "renew_qty": renew, "replace_qty": 0}])

    def test_integer_split_and_surplus_in_first_month(self):
        # 12 license: tuyển thêm 2/1/0/1 người ở T11-T2, 8 người hiện có chưa có phần mềm -> mua ngay T10
        lines = qt.build_quota_lines(self.needs(12, [0, 2, 1, 0, 1]), fx.KD, [], fx.MONTHS, fx.master(), {"entity": "DDC"})
        self.assertEqual(len(lines), 1)
        r = calculate_row(lines[0], months=fx.MONTHS, year_code="A27", master=fx.master())
        units = [round(r[f"val_{m}"] / r["unit_price"], 6) for m in fx.MONTHS[:5]]
        self.assertEqual(units, [8, 2, 1, 0, 1])
        self.assertEqual(r["total_val"], r["total_budget"])

    def test_regenerate_keeps_code_and_phasing(self):
        old = [l for l in fx.make_lines() if l["catalog_code"] == fx.ZWCAD]
        new = qt.build_quota_lines(self.needs(12, [1, 1, 1, 1, 1]), fx.KD, old, fx.MONTHS, fx.master(), {"entity": "DDC"})
        self.assertEqual((new[0]["item_seq"], new[0]["item_code_base"]), (old[0]["item_seq"], old[0]["item_code_base"]))
        self.assertEqual({k: v for k, v in new[0].items() if k.startswith("pct_")}, {k: v for k, v in old[0].items() if k.startswith("pct_")})


class LockedDeptTest(unittest.TestCase):
    def setUp(self):
        self.stored = fx.make_lines()
        self.locked = {wf.dept_key(fx.KT)}
        self.kt = sorted(r["item_code"] for r in self.stored if r["dept_proposing"] == fx.KT)

    def test_no_change_keeps_order_without_warning(self):
        out, ign = wf.keep_locked_rows(copy.deepcopy(self.stored), self.stored, self.locked)
        self.assertEqual([r["item_code"] for r in out], [r["item_code"] for r in self.stored])
        self.assertEqual(ign, set())

    def test_edits_deletes_adds_in_locked_dept_are_ignored(self):
        new = copy.deepcopy(self.stored)
        i = next(k for k, r in enumerate(new) if r["dept_proposing"] == fx.KT)
        new[i]["quantity"] = 99
        del new[next(k for k, r in enumerate(new) if r["dept_proposing"] == fx.KT and k != i)]
        new.append({"item_code": "NEW-1", "dept_proposing": fx.KT, "quantity": 1})
        j = next(k for k, r in enumerate(new) if r["dept_proposing"] == fx.KD)
        new[j]["quantity"] = 77
        out, ign = wf.keep_locked_rows(new, self.stored, self.locked)
        kt_out = [r for r in out if r["dept_proposing"] == fx.KT]
        self.assertEqual(sorted(r["item_code"] for r in kt_out), self.kt)
        for r in kt_out:
            self.assertEqual(r, next(s for s in self.stored if s["item_code"] == r["item_code"]))
        self.assertEqual(next(r for r in out if r["item_code"] == new[j]["item_code"])["quantity"], 77)
        self.assertEqual(ign, {fx.KT})

    def test_moving_rows_across_lock_and_clearing_site(self):
        new = copy.deepcopy(self.stored)
        a = next(k for k, r in enumerate(new) if r["dept_proposing"] == fx.KT)
        new[a]["dept_proposing"] = fx.KD
        out, _ = wf.keep_locked_rows(new, self.stored, self.locked)
        self.assertEqual(next(r for r in out if r["item_code"] == new[a]["item_code"])["dept_proposing"], fx.KT)
        out, ign = wf.keep_locked_rows([], self.stored, self.locked)
        self.assertEqual(sorted(r["item_code"] for r in out), self.kt)

    def test_overview_pending_and_problems(self):
        df = pd.DataFrame(self.stored)
        ov = wf.dept_overview(df, {wf.dept_key(fx.KT): {"status": db.STATUS_APPROVED, "dept": fx.KT}})
        self.assertEqual(len(ov), 3)
        self.assertAlmostEqual(ov["Tổng ngân sách"].sum(), df["total_budget"].sum())
        self.assertNotIn(fx.KT, wf.pending_depts(ov))
        self.assertEqual(wf.dept_problems(df[df["dept_proposing"] == fx.KT]), [])
        bad = df[df["dept_proposing"] == fx.KT].copy()
        bad.loc[bad.index[0], "pct_valid"] = False
        bad.loc[bad.index[-1], "need_reason"] = ""  # dòng Phát sinh mới thiếu lý do
        self.assertEqual(len(wf.dept_problems(bad)), 2)


class PricingTest(unittest.TestCase):
    def test_template_roundtrip_and_impact(self):
        m = fx.master()
        tpl = pricing.template_frame(m)
        tpl.loc[tpl["Mã"] == fx.ZWCAD, ["Giá mới", "Nhà cung cấp", "Ngày báo giá"]] = [25_500_000, "NCC A", "15/10/2026"]
        buf = io.BytesIO()
        tpl.to_excel(buf, index=False)
        changes, issues = pricing.match_quotes(pricing.read_quote_file(buf.getvalue(), "q.xlsx"), m)
        self.assertEqual([(c["code"], c["new_price"], c["quote_date"]) for c in changes], [(fx.ZWCAD, 25_500_000, "2026-10-15")])
        self.assertEqual(issues, [])
        lines = fx.make_lines()
        imp = pricing.line_impact(changes, {"BDA": lines, "TCO": copy.deepcopy(lines)}, {"BDA"},
                                  locked_depts={"BDA": set()})
        self.assertEqual(set(imp[imp["site"] == "BDA"]["action"]), {"Đổi"})
        self.assertEqual(set(imp[imp["site"] == "TCO"]["action"]), {"Giữ: site đã nộp/duyệt"})
        locked = pricing.line_impact(changes, {"BDA": lines}, {"BDA"}, locked_depts={"BDA": {wf.dept_key(fx.KD)}})
        self.assertEqual(set(locked["action"]), {"Giữ: phòng ban đã nộp/duyệt"})
        out = pricing.reprice_lines(lines, imp[imp["site"] == "BDA"])
        self.assertEqual(next(r for r in out if r["catalog_code"] == fx.ZWCAD)["unit_price"], 25_500_000)
        self.assertEqual(next(r for r in lines if r["catalog_code"] == fx.ZWCAD)["unit_price"], fx.item(fx.ZWCAD)["price"])
        self.assertEqual(pricing.apply_catalog_prices(m, changes, today="2026-10-10"), 1)

    def test_csv_names_numbers_and_errors(self):
        csv = ("Tên hạng mục,Đơn giá\nzwCAD,\"26.000.000\"\nKhông có thật,1000\nZWCAD,0\n").encode("utf-8-sig")
        changes, issues = pricing.match_quotes(pricing.read_quote_file(csv, "q.csv"), fx.master())
        self.assertEqual({c["code"]: c["new_price"] for c in changes}, {fx.ZWCAD: 26_000_000})
        self.assertEqual(len(issues), 2)
        self.assertEqual(pricing._num("27,000,000"), 27e6)
        self.assertEqual(pricing._num("27000000.0"), 27e6)
        self.assertIsNone(pricing._num(""))

    def test_manual_price_kept_unless_included(self):
        lines = fx.make_lines()
        k = next(i for i, l in enumerate(lines) if l["catalog_code"] == fx.LAPTOP)
        lines[k]["unit_price"] = 20_000_000
        ch = [{"code": fx.LAPTOP, "name": "x", "old_price": fx.item(fx.LAPTOP)["price"], "new_price": 19_000_000}]
        imp = pricing.line_impact(ch, {"BDA": lines}, {"BDA"})
        self.assertEqual(imp[imp["idx"] == k]["action"].iloc[0], "Giữ: giá đã sửa tay")
        imp2 = pricing.line_impact(ch, {"BDA": lines}, {"BDA"}, include_manual=True)
        self.assertEqual(imp2[imp2["idx"] == k]["action"].iloc[0], "Đổi")


if __name__ == "__main__":
    unittest.main()
