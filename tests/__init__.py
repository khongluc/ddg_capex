"""Kiểm thử tự động. Chạy từ thư mục dự án:  python -m unittest discover -s tests -v

CSDL kiểm thử là file SQLite tạm (biến ICOST_DB_PATH đặt trước khi nạp module db) - không đụng data/icost.db.
Dữ liệu ngân sách được tạo bằng tests/fixtures.py từ danh mục master_data.json, không dùng dữ liệu thật.
"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="icost_test_")
os.environ["ICOST_DB_PATH"] = os.path.join(_TMP, "icost_test.db")
os.environ.pop("ICOST_DATABASE_URL", None)
os.environ.pop("DATABASE_URL", None)
