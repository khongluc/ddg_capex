"""Danh mục: hạng mục bảo trì hằng năm cho phần mềm bản quyền vĩnh viễn; bản online (danh mục trong CSDL) nhận đợt bổ sung 1 lần."""
import copy
import unittest

import master_data as md
from capex_engine import calculate_row
from tests import fixtures as fx


class MaintenanceItemsTest(unittest.TestCase):
    def setUp(self):
        self.m = fx.master()
        self.items = {it["code"]: it for it in self.m["standard_items"]}

    def test_every_perpetual_software_has_one_maintenance_item(self):
        perpetual = [it for it in self.items.values() if it["kind"] == md.KIND_SW_PERPETUAL]
        maint = [it for it in self.items.values() if it.get("maintenance_of")]
        self.assertGreaterEqual(len(perpetual), 20)
        self.assertEqual(sorted(it["maintenance_of"] for it in maint), sorted(it["code"] for it in perpetual))
        for it in maint:
            lic = self.items[it["maintenance_of"]]
            self.assertEqual(it["group"], lic["group"])
            self.assertEqual(it["kind"], md.KIND_SW_SUBSCRIPTION)
            self.assertTrue(it["unit"].endswith("/năm"))
            self.assertEqual(it["price"], int(round(float(lic.get("price") or 0) * 0.2, -3)))
            self.assertNotIn("bản quyền vĩnh viễn", it["name"])
        self.assertFalse([it for it in self.items.values() if it["kind"] == md.KIND_SW_SUBSCRIPTION and it.get("maintenance_of") is None
                          and it["name"].startswith("Bảo trì, cập nhật")])
        self.assertEqual(len({it["code"] for it in self.m["standard_items"]}), len(self.m["standard_items"]))

    def test_license_type_software_now_perpetual(self):
        for code in ("IT10-007", "IT10-008", "IT10-010"):  # SAP2000, ETABS, IDEA StatiCa
            self.assertEqual(self.items[code]["kind"], md.KIND_SW_PERPETUAL)

    def test_maintenance_line_is_opex_renewal(self):
        it = next(i for i in self.items.values() if i.get("maintenance_of") == fx.ZWCAD)
        row = {"quantity": 10, "unit_price": it["price"], f"pct_{fx.MONTHS[0]}": 1}
        md.apply_it_catalog(row, self.m, item=it)
        r = calculate_row(row, months=fx.MONTHS, year_code="A27", master=self.m)
        self.assertEqual((r["capex_type"], r["invest_type"]), ("OPEX", "Gia hạn, bảo trì"))
        self.assertEqual(md.find_catalog_item("Bảo trì ZWCAD", self.m)["code"], it["code"])

    def test_online_catalog_receives_seed_once(self):
        """Danh mục online (đợt 2, chưa có bảo trì, SAP2000 còn là thuê bao) nhận 20 hạng mục + đổi loại, chỉ 1 lần."""
        online = copy.deepcopy(self.m)
        online["catalog_seed"] = 2
        online["standard_items"] = [it for it in online["standard_items"] if not it.get("maintenance_of")]
        for it in online["standard_items"]:
            if it["code"] in ("IT10-007", "IT10-008", "IT10-010"):
                it["kind"] = md.KIND_SW_SUBSCRIPTION
        online["standard_items"].append({"code": "IT10-047", "group": "IT10", "name": "Hạng mục admin tự thêm", "kind": "service", "price": 1})
        self.assertTrue(md._merge_catalog_seed(online))
        got = {it["code"]: it for it in online["standard_items"]}
        self.assertEqual(sum(1 for it in got.values() if it.get("maintenance_of")), 20)
        self.assertEqual(got["IT10-007"]["kind"], md.KIND_SW_PERPETUAL)
        self.assertEqual(got["IT10-047"]["name"], "Hạng mục admin tự thêm")  # mã bị chiếm -> bảo trì nhận mã khác
        self.assertEqual(len(got), len(online["standard_items"]))
        self.assertEqual(online["catalog_seed"], 3)
        self.assertFalse(md._merge_catalog_seed(online))  # lần sau không chạy lại


if __name__ == "__main__":
    unittest.main()
