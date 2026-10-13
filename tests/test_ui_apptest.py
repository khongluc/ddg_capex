"""Kiểm thử giao diện (Streamlit AppTest): chạy app.py thật trong tiến trình kiểm thử với CSDL tạm và dữ liệu mẫu.
Mỗi lượt chạy Streamlit thực thi nội dung của mọi tab, nên 1 lượt / vai trò phủ toàn bộ giao diện: bắt lỗi NameError,
KeyError, sai cột... ở những tab ít khi mở tay. Đăng nhập được thay bằng người dùng giả (auth.require_login)."""
import os
import unittest

import db
import auth
from tests import fixtures as fx

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
PREV_YEAR = str(int(fx.YEAR) - 1)

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

USERS = {
    "admin": auth.CurrentUser(email="admin@test.local", name="Admin thử", role=db.ROLE_ADMIN),
    "site_it": auth.CurrentUser(email="it@test.local", name="IT site thử", role=db.ROLE_SITE_IT, sites=[fx.SITE]),
    "dept": auth.CurrentUser(email="kd@test.local", name="Phòng KD thử", role=db.ROLE_DEPT, sites=[fx.SITE],
                             depts=[(fx.SITE, fx.KD)]),
    "viewer": auth.CurrentUser(email="view@test.local", name="Người xem thử", role=db.ROLE_VIEWER),
}


@unittest.skipIf(AppTest is None, "Cần streamlit >= 1.28 (streamlit.testing)")
class AppUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls._orig_login = auth.require_login

    @classmethod
    def tearDownClass(cls):
        auth.require_login = cls._orig_login

    def setUp(self):
        db.replace_lines(fx.YEAR, fx.SITE, fx.make_lines(), actor="test")
        # năm trước có thêm thuê bao Phát sinh mới (không theo định biên) mà năm nay chưa có -> tab Nhắc gia hạn có dòng
        prev = fx.make_lines(fx.SPEC + [(fx.IT, fx.M365, "Gia hạn, bảo trì", 5, {0: 5}, "Phát sinh mới", False)])
        db.replace_lines(PREV_YEAR, fx.SITE, prev, actor="test")

    def start(self, role: str, site: str = fx.SITE) -> "AppTest":
        user = USERS[role]
        auth.require_login = lambda: user
        at = AppTest.from_file(APP, default_timeout=180)
        at.run()
        self.assertNoError(at, f"{role} - mở trang")
        box = next((s for s in at.selectbox if s.label == "Site lập ngân sách"), None)
        if box is not None and box.value != site:  # options là nhãn hiển thị, set_value nhận mã site
            box.set_value(site)
            at.run()
            self.assertNoError(at, f"{role} - chọn site {site}")
        return at

    def assertNoError(self, at, where: str):
        errs = [e.value for e in at.exception]
        self.assertEqual(errs, [], f"{where}: lỗi khi chạy trang")

    def test_every_tab_renders_for_each_role(self):
        for role in USERS:
            with self.subTest(role=role):
                at = self.start(role)
                self.assertTrue(at.tabs, f"{role}: không thấy tab nào")

    def open_popup(self, role: str, label_part: str) -> "AppTest":
        at = self.start(role)
        dept = next(s for s in at.selectbox if s.key == "sb_dept")
        if dept.value != fx.KD:
            dept.set_value(fx.KD)
            at.run()
        n_tabs = len(at.tabs)
        next(b for b in at.button if label_part in b.label).click()
        at.run()
        self.assertNoError(at, f"{role} - mở popup {label_part}")
        self.assertGreater(len(at.tabs) + len(at.radio), n_tabs, "popup không hiện nội dung")
        return at

    def test_checklist_popup_all_phasing_modes(self):
        """Popup checklist: mở được; mỗi tab trong popup chuyển đủ 3 cách phân kỳ (1 tháng / chia đều / tự nhập) không lỗi."""
        at = self.open_popup("admin", "Thêm hạng mục (gói chức danh")
        found = [r.key for r in at.radio if r.key in ("dlg_k_mode", "dlg_c_mode", "dlg_n_mode")]
        self.assertGreaterEqual(len(found), 2, f"popup thiếu ô chọn phân kỳ: {found}")
        for key in found:
            for mode in ("Chia đều nhiều tháng", "Tự nhập SL từng tháng", "1 tháng"):
                radio = next((r for r in at.radio if r.key == key), None)
                if radio is None:
                    break
                radio.set_value(mode)
                at.run()
                self.assertNoError(at, f"popup checklist {key} = {mode}")

    def test_review_popup_opens_for_dept_user(self):
        at = self.open_popup("dept", "Rà soát & sửa nhanh nhiều dòng")
        mode = next(r for r in at.radio if r.key == "dlg_adj_mode")
        for m in ("Chia đều nhiều tháng", "Tự nhập SL từng tháng"):
            mode.set_value(m)
            at.run()
            self.assertNoError(at, f"popup rà soát = {m}")

    def test_exec_tab_import_section_when_site_approved(self):
        """Site đã duyệt: tab Giải ngân hiện phần nạp chứng từ từ file, trang chạy không lỗi."""
        db.set_status(fx.YEAR, fx.SITE, db.STATUS_APPROVED, "test")
        try:
            at = self.start("admin")
            self.assertTrue(any(e.label.startswith("Nạp nhiều chứng từ từ file") for e in at.expander),
                            "không thấy phần nạp chứng từ")
        finally:
            db.set_status(fx.YEAR, fx.SITE, db.STATUS_DRAFT, "test")

    def test_all_sites_view(self):
        at = self.start("admin", site="__ALL__")
        self.assertNoError(at, "admin - tổng hợp tất cả site")

    def test_renewal_tab_lists_gaps(self):
        """Năm trước mỗi hạng mục nhiều hơn 3 -> các thuê bao (M365, ZWCAD...) hiện trong Nhắc gia hạn."""
        at = self.start("admin")
        m = next((x for x in at.metric if x.label == "Hạng mục cần xem lại"), None)
        self.assertIsNotNone(m, "không thấy bảng Nhắc gia hạn")
        self.assertGreaterEqual(int(m.value), 1)

    def test_infra_add_multi_items_multi_months(self):
        """Tab Hạ tầng: chọn 2 hạng mục, chia đều đầu mỗi quý, thêm -> 2 dòng hạ tầng mới trong CSDL."""
        at = self.start("admin")
        items = next(m for m in at.multiselect if m.label.startswith("(*) Hạng mục hạ tầng"))
        items.set_value(items.options[:2])
        at.run()
        mode = next(r for r in at.radio if r.key and r.key.startswith("infra_add_") and r.key.endswith("_mode"))
        mode.set_value("Chia đều nhiều tháng")
        at.run()
        next(t for t in at.text_input if t.label == "(*) Căn cứ / lý do").input("Thử nghiệm tự động")
        at.run()
        before = len([l for l in db.load_lines(fx.YEAR, [fx.SITE]) if l.get("need_type") == "Hạ tầng dùng chung"])
        next(b for b in at.button if b.label.startswith("➕ Thêm 2 hạng mục vào ngân sách hạ tầng")).click()
        at.run()
        self.assertNoError(at, "thêm hạ tầng")
        infra = [l for l in db.load_lines(fx.YEAR, [fx.SITE]) if l.get("need_type") == "Hạ tầng dùng chung"]
        self.assertEqual(len(infra), before + 2)
        new = [l for l in infra if l.get("need_reason") == "Thử nghiệm tự động"]
        self.assertEqual(len(new), 2)
        for l in new:
            self.assertAlmostEqual(sum(float(l.get(f"pct_{m}") or 0) for m in fx.MONTHS), 1.0)


if __name__ == "__main__":
    unittest.main()
