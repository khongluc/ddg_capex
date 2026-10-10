"""Hàm trong app.py (lọc theo hạng mục, lưu bảng đang lọc). app.py chạy Streamlit khi nạp, nên chỉ tách đúng các hàm cần thử."""
import ast
import os
import unittest

import pandas as pd

from tests import fixtures as fx

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
WANTED_FUNCS = {"dept_key", "dept_mask", "filter_values", "save_view"}
WANTED_NAMES = {"ITEM_FILTERS", "FILTER_BLANK"}


def load_app_funcs(**globals_):
    tree = ast.parse(open(APP, encoding="utf-8").read())
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name in WANTED_FUNCS)
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in WANTED_NAMES for t in n.targets))]
    ns = {"pd": pd, "ALL_DEPTS": "(Tất cả phòng ban)", **globals_}
    exec(compile(ast.Module(keep, []), APP, "exec"), ns)
    return ns


class FilteredSaveTest(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        df_site = pd.DataFrame(fx.make_lines())
        df_site["_order"] = range(len(df_site))
        self.ns = load_app_funcs(save_site=lambda df, code: self.saved.update(df=df, code=code),
                                 df_site=df_site, selected_dept=fx.KD, selected_site=fx.SITE)
        self.df_site = df_site
        self.df_curr = df_site[self.ns["dept_mask"](df_site, fx.KD)].reset_index(drop=True)

    def test_filter_values_and_blank(self):
        v = self.ns["filter_values"](self.df_curr, "_item_label")
        self.assertTrue(v.str.contains(" · ").all())
        self.assertEqual(self.ns["filter_values"](pd.DataFrame({"x": [None, ""]}), "it_group").tolist(),
                         [self.ns["FILTER_BLANK"]] * 2)

    def test_edit_while_filtered_keeps_hidden_rows(self):
        mask = self.ns["filter_values"](self.df_curr, "capex_type").isin(["CCDC"])
        grid = self.df_curr[mask]
        self.assertTrue(0 < len(grid) < len(self.df_curr))
        edited = grid.copy()
        edited.iloc[0, edited.columns.get_loc("quantity")] = 99
        edited = pd.concat([edited.iloc[:1], pd.DataFrame([{"item_name": "Dòng thêm", "quantity": 1}])])  # xóa các dòng còn lại + thêm 1
        self.ns["save_view"](pd.concat([self.df_curr[~mask], edited], ignore_index=True))  # đúng biểu thức trong app.py
        out = self.saved["df"]
        kd = out[out["dept_proposing"] == fx.KD]
        for o in self.df_curr[~mask]["_order"]:
            self.assertIn(o, set(kd["_order"]))  # dòng bị ẩn còn nguyên
        self.assertEqual(kd.loc[kd["item_code"] == grid.iloc[0]["item_code"], "quantity"].iloc[0], 99)
        self.assertEqual(len(kd), len(self.df_curr) - len(grid) + 2)
        other_before = self.df_site[self.df_site["dept_proposing"] != fx.KD]["item_code"].tolist()
        self.assertEqual(out[out["dept_proposing"] != fx.KD]["item_code"].tolist(), other_before)
        self.assertEqual(out.iloc[-1]["item_name"], "Dòng thêm")  # dòng mới ở cuối


if __name__ == "__main__":
    unittest.main()
