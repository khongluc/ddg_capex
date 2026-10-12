"""Hàm trong app.py (lọc theo hạng mục, lưu bảng đang lọc). app.py chạy Streamlit khi nạp, nên chỉ tách đúng các hàm cần thử."""
import ast
import contextlib
import os
import unittest

import pandas as pd

from tests import fixtures as fx

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
WANTED_FUNCS = {"dept_key", "dept_mask", "filter_values", "save_view", "_commit_checklist_items", "phasing_picker"}
WANTED_NAMES = {"ITEM_FILTERS", "FILTER_BLANK", "PHASE_ONE"}


def load_app_funcs(**globals_):
    tree = ast.parse(open(APP, encoding="utf-8").read())
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name in WANTED_FUNCS)
            or (isinstance(n, ast.Assign) and any(getattr(x, "id", "") in WANTED_NAMES
                                                  for t in n.targets for x in ([t] + list(getattr(t, "elts", [])))))]
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


class _Rerun(Exception):
    pass


class PopupCommitTest(unittest.TestCase):
    """Popup thêm hạng mục: hạng mục trong danh mục / ngoài danh mục được phân loại & hạch toán đúng."""

    def setUp(self):
        import types
        import quota as qt
        from master_data import apply_it_catalog, classify_item, find_catalog_item, division_of
        from capex_engine import calculate_row
        self.saved = {}
        st = types.SimpleNamespace(session_state={}, rerun=lambda: (_ for _ in ()).throw(_Rerun()))
        db = types.SimpleNamespace(load_lines=lambda year, sites: [])
        self.ns = load_app_funcs(
            st=st, db=db, qt=qt, master=fx.master(), months=fx.MONTHS, year_code="A27", budget_year=fx.YEAR,
            SITE_NAME={fx.SITE: fx.SITE_NAME}, apply_it_catalog=apply_it_catalog, classify_item=classify_item,
            find_catalog_item=find_catalog_item, division_of=division_of, calculate_row=calculate_row,
            format_vnd=lambda v: f"{v:,.0f}", save_site=lambda df, site: self.saved.update(df=df, site=site))
        self.st = st

    def commit(self, rows, need="Phát sinh mới", reason="Dự án mới"):
        with self.assertRaises(_Rerun):
            self.ns["_commit_checklist_items"](pd.DataFrame(rows), fx.KD, fx.SITE, fx.MONTHS[2], need, reason)
        return self.saved["df"].to_dict("records")

    def test_off_catalog_items_classified_by_group_and_kind(self):
        out = self.commit([
            {"Mã": "", "Tên thiết bị / Hạng mục": "Máy đo laser Leica DISTO", "Nhóm": "IT13. x", "Loại": None,
             "Hình thức": "Mua mới", "ĐVT": "Cái", "Số lượng": 2, "Đơn giá (VNĐ)": 12_000_000, "Ghi chú": "đo hiện trường"},
            {"Mã": "", "Tên thiết bị / Hạng mục": "Phần mềm dự toán GXD", "Nhóm": "IT10. x", "Loại": "software_perpetual",
             "Hình thức": "Mua mới", "ĐVT": "License", "Số lượng": 1, "Đơn giá (VNĐ)": 45_000_000, "Ghi chú": ""},
            {"Mã": "", "Tên thiết bị / Hạng mục": "Thuê bao bản đồ số", "Nhóm": "IT12. x", "Loại": "software_subscription",
             "Hình thức": "Gia hạn, bảo trì", "ĐVT": "Năm", "Số lượng": 1, "Đơn giá (VNĐ)": 8_000_000, "Ghi chú": ""},
        ])
        a, b, c = out
        for r in out:
            self.assertEqual((r["it_group"], r["catalog_code"], r["dept_proposing"], r["need_type"]), ("(Ngoài danh mục)", "", fx.KD, "Phát sinh mới"))
            self.assertEqual(r["need_reason"], "Dự án mới")
            self.assertEqual(r[f"val_{fx.MONTHS[2]}"], r["total_budget"])
        self.assertEqual((a["capex_type"], a["unit"], a["total_budget"]), ("CCDC", "Cái", 24_000_000))   # thiết bị < 30 tr
        self.assertEqual(b["capex_type"], "CAPEX")                                                          # bản quyền vĩnh viễn >= 30 tr
        self.assertTrue(b["asset_cat1"].startswith("E"))
        self.assertEqual((c["capex_type"], c["invest_type"]), ("OPEX", "Gia hạn, bảo trì"))                 # thuê bao
        self.assertEqual(self.st.session_state["pending_dept"], fx.KD)

    def test_name_in_catalog_uses_catalog(self):
        out = self.commit([{"Mã": "", "Tên thiết bị / Hạng mục": "zwCAD", "Nhóm": "IT13. x", "Loại": None, "Hình thức": "Mua mới",
                            "ĐVT": "", "Số lượng": 3, "Đơn giá (VNĐ)": 27_000_000, "Ghi chú": ""}])
        self.assertEqual((out[0]["catalog_code"], out[0]["item_name"]), (fx.ZWCAD, "ZWCAD"))


    def test_one_item_split_over_months(self):
        """1 hạng mục SL nhiều, chia nhiều tháng (SL nguyên từng tháng) -> 1 dòng, giá trị tháng = SL tháng × đơn giá."""
        from capex_engine import even_units, phase_presets
        quarters = phase_presets(fx.MONTHS)["Đầu mỗi quý"]
        units = even_units(10, fx.MONTHS, quarters)
        self.assertEqual([units[fx.MONTHS.index(m)] for m in quarters], [3, 3, 2, 2])
        manual = [0] * len(fx.MONTHS)
        manual[1], manual[5] = 4, 1   # tự nhập: SL = tổng các tháng (5), bỏ qua cột Số lượng cũ
        out = self.commit([
            {"Mã": "", "Tên thiết bị / Hạng mục": "zwCAD", "Số lượng": 10, "Đơn giá (VNĐ)": 27_000_000, "_units": units},
            {"Mã": "", "Tên thiết bị / Hạng mục": "zwCAD", "Số lượng": 1, "Đơn giá (VNĐ)": 27_000_000, "_units": manual},
        ])
        a, b = out
        self.assertEqual(a["quantity"], 10)
        self.assertEqual([a[f"val_{m}"] for m in quarters], [81_000_000, 81_000_000, 54_000_000, 54_000_000])
        self.assertAlmostEqual(sum(a[f"pct_{m}"] for m in fx.MONTHS), 1.0)
        self.assertEqual(a["handover_date"], fx_last_day(quarters[-1]))
        self.assertEqual((b["quantity"], b["total_budget"]), (5, 135_000_000))
        self.assertEqual((b[f"val_{fx.MONTHS[1]}"], b[f"val_{fx.MONTHS[5]}"]), (108_000_000, 27_000_000))

    def test_even_units_edge_cases(self):
        from capex_engine import even_units
        self.assertEqual(sum(even_units(2, fx.MONTHS, fx.MONTHS[:4])), 2)        # SL < số tháng: dồn tháng sớm
        self.assertEqual(even_units(2, fx.MONTHS, fx.MONTHS[:4])[:2], [1, 1])
        self.assertIsNone(even_units(2.5, fx.MONTHS, fx.MONTHS[:2]))             # SL lẻ -> chia theo tỷ lệ
        self.assertIsNone(even_units(5, fx.MONTHS, []))


class _FakeSt:
    """Streamlit giả cho phasing_picker: radio / selectbox / multiselect trả giá trị cho trước, data_editor trả bảng đã sửa."""
    def __init__(self, mode, pick=None, chosen=None, edit=None):
        self.mode, self.pick, self.chosen, self.edit = mode, pick, chosen, edit
        self.column_config = types_ns(TextColumn=lambda *a, **k: None, NumberColumn=lambda *a, **k: None)

    def radio(self, *a, **k): return self.mode
    def selectbox(self, label, options, **k): return self.pick if self.pick is not None else options[k.get("index", 0)]
    def multiselect(self, label, options, default=None, **k): return self.chosen if self.chosen is not None else default
    def columns(self, spec): return [contextlib.nullcontext() for _ in spec]
    def dataframe(self, *a, **k): pass
    def caption(self, *a, **k): pass

    def data_editor(self, df, **k):
        df = df.copy()
        for (row, col), v in (self.edit or {}).items():
            df.loc[row, col] = v
        return df


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


class PhasingPickerTest(unittest.TestCase):
    def run_picker(self, fake, rows):
        from capex_engine import even_units, phase_presets
        ns = load_app_funcs(st=fake, months=fx.MONTHS, even_units=even_units, phase_presets=phase_presets)
        return ns, ns["phasing_picker"](pd.DataFrame(rows), "k")

    ROWS = [{"Tên thiết bị / Hạng mục": "Laptop", "Số lượng": 10, "Đơn giá (VNĐ)": 20_000_000},
            {"Tên thiết bị / Hạng mục": "Màn hình", "Số lượng": 3, "Đơn giá (VNĐ)": 4_000_000}]

    def test_one_month(self):
        ns, (out, err) = self.run_picker(_FakeSt("1 tháng", pick=fx.MONTHS[4]), self.ROWS)
        self.assertIsNone(err)
        self.assertEqual(out["_units"][0][4], 10)
        self.assertEqual(sum(out["_units"][0]), 10)

    def test_even_quarters_default(self):
        ns, (out, err) = self.run_picker(_FakeSt("Chia đều nhiều tháng"), self.ROWS)   # mẫu mặc định: đầu mỗi quý
        self.assertIsNone(err)
        q = [0, 3, 6, 9]
        self.assertEqual([out["_units"][0][i] for i in q], [3, 3, 2, 2])
        self.assertEqual([out["_units"][1][i] for i in q], [1, 1, 1, 0])
        self.assertEqual(out["Số lượng"].tolist(), [10, 3])

    def test_even_no_month_is_error(self):
        _, (out, err) = self.run_picker(_FakeSt("Chia đều nhiều tháng", chosen=[]), self.ROWS)
        self.assertTrue(err)

    def test_manual_grid_sets_quantity(self):
        edit = {(0, fx.MONTHS[0]): 6, (0, fx.MONTHS[2]): 6, (1, fx.MONTHS[0]): 0}
        _, (out, err) = self.run_picker(_FakeSt("Tự nhập SL từng tháng", edit=edit), self.ROWS)
        self.assertIn("Màn hình", err)                                        # dòng 2 không còn tháng nào
        edit[(1, fx.MONTHS[11])] = 2
        _, (out, err) = self.run_picker(_FakeSt("Tự nhập SL từng tháng", edit=edit), self.ROWS)
        self.assertIsNone(err)
        self.assertEqual(out["Số lượng"].tolist(), [12, 2])
        self.assertEqual(out["_units"][1][11], 2)

def fx_last_day(month_label):
    from capex_engine import default_handover_date
    return default_handover_date({f"pct_{month_label}": 1}, fx.MONTHS)

if __name__ == "__main__":
    unittest.main()
