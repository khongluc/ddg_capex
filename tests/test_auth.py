"""Đăng nhập thử (dev_login) chỉ mở khi app lắng nghe trên localhost và người truy cập ở chính máy đó."""
import unittest
from types import SimpleNamespace
from unittest import mock

import auth


def ctx(host, ip):
    return SimpleNamespace(headers={"Host": host} if host is not None else {}, ip_address=ip)


class DevLoginGuardTest(unittest.TestCase):
    def allowed(self, address, providers=(), server_db=False):
        with mock.patch("streamlit.config.get_option", return_value=address), \
             mock.patch.object(auth.db, "using_server_db", return_value=server_db):
            return auth._dev_login_allowed(list(providers))

    def test_only_explicit_loopback_address(self):
        for addr in ("localhost", "127.0.0.1", "::1", "LOCALHOST "):
            self.assertTrue(self.allowed(addr), addr)
        # để trống (mặc định Streamlit = mọi card mạng) / 0.0.0.0 / IP LAN -> tắt đăng nhập thử
        for addr in (None, "", "0.0.0.0", "192.168.1.10", "::"):
            self.assertFalse(self.allowed(addr), addr)

    def test_off_with_providers_or_server_db(self):
        self.assertFalse(self.allowed("localhost", providers=["google"]))
        self.assertFalse(self.allowed("localhost", server_db=True))

    def test_local_request_needs_localhost_host_and_loopback_ip(self):
        cases = {
            ("localhost:8501", None): True,          # Streamlit trả ip None khi truy cập qua localhost
            ("127.0.0.1:8501", "127.0.0.1"): True,
            ("[::1]:8501", "::1"): True,
            ("localhost:8501", "192.168.1.20"): False,   # Host giả là localhost nhưng kết nối từ máy khác
            ("192.168.1.5:8501", None): False,
            ("app.example.com", None): False,
            (None, None): False,                     # không có header -> không coi là local
        }
        for (host, ip), expected in cases.items():
            with mock.patch.object(auth.st, "context", ctx(host, ip)):
                self.assertEqual(auth._is_local_request(), expected, (host, ip))

    def test_no_auto_admin_login(self):
        src = open(auth.__file__, encoding="utf-8").read()
        self.assertNotIn("@daidung.vn", src)                       # không ghi cứng email trong code
        self.assertNotIn('session_state["dev_login_email"] = default_admin', src)


if __name__ == "__main__":
    unittest.main()
