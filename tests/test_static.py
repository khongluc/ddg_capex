"""Kiểm tra tĩnh: tên dùng mà chưa định nghĩa (vd. xóa nhầm 1 hằng số làm app lỗi NameError khi mở).
app.py chạy Streamlit khi nạp nên các kiểm thử khác không bắt được loại lỗi này. Cần pyflakes (pip install pyflakes)."""
import glob
import os
import unittest

try:
    from pyflakes import api as _pyflakes_api, reporter as _pyflakes_reporter
except ImportError:  # pragma: no cover
    _pyflakes_api = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Collect:
    def __init__(self):
        self.messages = []

    def unexpectedError(self, filename, msg):
        self.messages.append(f"{filename}: {msg}")

    def syntaxError(self, filename, msg, lineno, offset, text):
        self.messages.append(f"{filename}:{lineno}: {msg}")

    def flake(self, message):
        if "undefined name" in str(message) or "used before assignment" in str(message):
            self.messages.append(str(message))


@unittest.skipIf(_pyflakes_api is None, "cần pyflakes: pip install pyflakes")
class UndefinedNamesTest(unittest.TestCase):
    def test_no_undefined_names(self):
        rep = _Collect()
        for path in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
            with open(path, encoding="utf-8") as f:
                _pyflakes_api.check(f.read(), path, rep)
        self.assertEqual(rep.messages, [], "\n".join(rep.messages))


if __name__ == "__main__":
    unittest.main()
