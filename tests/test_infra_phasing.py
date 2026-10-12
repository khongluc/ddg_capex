"""Hạ tầng dùng chung: bảng chỉ có 1 cột tháng - lưu lại không được làm mất phân kỳ nhiều tháng; hiện phân kỳ dạng chữ."""
import unittest

from capex_engine import calculate_row, current_units, even_units, phase_text, regrid_pcts
from tests import fixtures as fx

M = fx.MONTHS


class RegridPctsTest(unittest.TestCase):
    def test_same_first_month_keeps_multi_month(self):
        units = even_units(4, M, [M[0], M[3]])                      # 2 tháng: 2 + 2
        pcts = [u / 4 for u in units]
        self.assertEqual(regrid_pcts(pcts, M[0], M), pcts)

    def test_changed_month_moves_all(self):
        pcts = [u / 4 for u in even_units(4, M, [M[0], M[3]])]
        out = regrid_pcts(pcts, M[5], M)
        self.assertEqual(out[5], 1.0)
        self.assertEqual(sum(out), 1.0)

    def test_new_row_or_bad_data(self):
        for old in (None, [], [0.0] * len(M), [1.0]):              # dòng mới thêm trên bảng / dữ liệu hỏng
            out = regrid_pcts(old, M[2], M)
            self.assertEqual((out[2], sum(out)), (1.0, 1.0))

    def test_saved_row_keeps_values(self):
        """Dòng 3 tủ rack chia 2 tháng, lưu lại bảng với tháng đầu không đổi -> giá trị từng tháng giữ nguyên."""
        row = {"quantity": 3, "unit_price": 10_000_000, "item_name": "Tủ rack"}
        for m, pc in zip(M, regrid_pcts([u / 3 for u in even_units(3, M, [M[1], M[7]])], M[1], M)):
            row[f"pct_{m}"] = pc
        out = calculate_row(row, months=M, master={})
        self.assertEqual((out[f"val_{M[1]}"], out[f"val_{M[7]}"]), (20_000_000, 10_000_000))


class CurrentUnitsTest(unittest.TestCase):
    """Popup rà soát, "Tự nhập SL từng tháng": bảng điền sẵn SL nguyên theo phân kỳ đang có."""
    def test_from_whole_units(self):
        units = even_units(10, M, M[0::3])
        self.assertEqual(current_units([u / 10 for u in units], 10), units)

    def test_ratio_rounded_keeps_total(self):
        pcts = [0.5 if i in (0, 1) else 0.0 for i in range(len(M))]       # 50/50 cho 3 máy
        self.assertEqual(sum(current_units(pcts, 3)), 3)

    def test_empty_phasing_goes_to_first_month(self):
        u = current_units([0.0] * len(M), 4)
        self.assertEqual((u[0], sum(u)), (4, 4))


class PhaseTextTest(unittest.TestCase):
    def test_units(self):
        pcts = [u / 10 for u in even_units(10, M, M[0::3])]
        self.assertEqual(phase_text(pcts, 10, M), f"{M[0]}: 3 · {M[3]}: 3 · {M[6]}: 2 · {M[9]}: 2")

    def test_percent_when_not_whole(self):
        pcts = [0.5 if i in (0, 1) else 0.0 for i in range(len(M))]
        self.assertEqual(phase_text(pcts, 3, M), f"{M[0]}: 50% · {M[1]}: 50%")


if __name__ == "__main__":
    unittest.main()
