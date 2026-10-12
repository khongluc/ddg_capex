# CLAUDE.md — HƯỚNG DẪN DỰ ÁN CHO CLAUDE (CLAUDE CODE & DESKTOP)
**Dự án: I-Cost — Hệ Thống Lập & Quản Lý Ngân Sách Đầu Tư CNTT (Tập đoàn Đại Dũng - DDC)**

Tài liệu này cung cấp toàn bộ quy tắc nghiệp vụ, kiến trúc kỹ thuật, lệnh thực thi và nguyên tắc phối hợp đa Agent (Claude & Antigravity) để đảm bảo mọi thay đổi của Claude đều chính xác, an toàn và đồng bộ 100%.

---

## 1. Lệnh Khởi Chạy & Kiểm Thử Thường Dùng (Commands)

```bash
# 1. Chạy toàn bộ test cases tự động (BẮT BUỘC chạy trước & sau khi sửa code)
python -m unittest

# 2. Khởi chạy Web App Streamlit (Cổng độc lập cho Claude tránh xung đột cổng 8501)
python -m streamlit run app.py --server.port 8502 --server.headless true

# 3. Biên dịch kiểm tra lỗi cú pháp Python toàn bộ dự án
python -m compileall -q .

# 4. Kiểm tra trạng thái Git trước khi chỉnh sửa
git status
```

> ⚠️ **Quy tắc Kiểm thử**: Toàn bộ kiểm thử dùng SQLite tạm cách ly (`tests/__init__.py` đặt `ICOST_DB_PATH`). Tuyệt đối **không đọc/ghi đè** lên CSDL sản xuất tại `data/icost.db`.

---

## 2. Kiến Trúc Dự Án & Phân Định Trách Nhiệm File (Architecture)

```
d:\DATA\dev\I_Cost\
├── app.py                  # Presentation Layer: 11 Tabs Streamlit UI, Dialogs, Filter bar
├── auth.py                 # Xác thực OIDC (Google/UltraID), Dev Login Guard, RBAC 4 vai trò
├── capex_engine.py         # Core Calculation: Khấu hao TT45, Phân kỳ 12 tháng, Sinh mã kế toán
├── master_data.py          # Master Catalog: 16 Nhóm CNTT (IT01-IT16), ~255 hạng mục chuẩn
├── master_data.json        # Database JSON gốc cho danh mục hạng mục & 64 phòng ban
├── quota.py                # Phân tích định biên nhân sự, Kits chuẩn (KIT01-KIT05)
├── smart_advisor.py        # AI Rule Engine: Khám sức khỏe hồ sơ /100 điểm, tối ưu chi phí
├── pricing.py              # Đơn giá thị trường & lịch sử báo giá nhà cung cấp
├── workflow.py             # Luồng phê duyệt 4 cấp, khóa nộp/duyệt phòng ban
├── execution.py            # Đối soát ngân sách kế hoạch vs PO ký kết & Hóa đơn thực tế
├── versions.py             # Quản lý phiên bản ngân sách & phân tích sai lệch (variance diff)
├── reports.py              # Xuất biểu mẫu Excel chuẩn DDC và báo cáo theo Khối
├── data/icost.db           # SQLite Database sản xuất (bị .gitignore)
├── templates/              # Biểu mẫu Excel kế toán & bảng định biên mẫu
├── docs/                   # Tài liệu kiến trúc (ARCHITECTURE.md, DEPLOY_STREAMLIT_CLOUD.md)
└── tests/                  # Bộ test cases tự động (unittest)
```

---

## 3. Các Quy Tắc Nghiệp Vụ Cốt Lõi (Invariants - Không Được Vi Phạm)

1. **Chuẩn Kế Toán Thông tư 45/2013/TT-BTC**:
   - Nguyên giá $\ge 30.000.000$ VNĐ $\rightarrow$ **TSCĐ (CAPEX)**.
   - Nguyên giá $< 30.000.000$ VNĐ $\rightarrow$ **CCDC dài hạn**.
   - Dịch vụ, đường truyền, cloud hàng năm $\rightarrow$ **Chi phí (OPEX)**.
2. **Khóa Phòng Ban Khi Đã Nộp/Duyệt**:
   - Khi phòng ban ở trạng thái `STATUS_SUBMITTED` hoặc `STATUS_APPROVED`, người lập không được sửa/ghi đè. Hàm `save_site()` phải giữ nguyên các dòng đã khóa (`wf.keep_locked_rows`).
3. **Tính Đầy Đủ Phân Kỳ Dòng Tiền**:
   - Tổng tỷ lệ phân kỳ 12 tháng (cột `pct_<tháng>`, năm ngân sách T10 → T9, vd. `pct_T10 2026` ... `pct_T9 2027`) của mỗi dòng phải đạt **chính xác 100% (1.0)**.
4. **Tính Tương Thích với `tests/test_app_helpers.py`**:
   - File `test_app_helpers.py` sử dụng `ast.parse` để bóc tách trực tiếp các hàm: `dept_key`, `dept_mask`, `filter_values`, `save_view`, `_commit_checklist_items`, `phasing_picker` và các biến `ITEM_FILTERS`, `FILTER_BLANK`, `PHASE_ONE` (xem `WANTED_FUNCS` / `WANTED_NAMES` trong file test). **Không được đổi tên hoặc xóa các hàm/biến này trong `app.py`**.
5. **Đường Dẫn Động & Fallback Biểu Mẫu**:
   - Dùng hàm `resolve_template_path()` để tìm file mẫu trong `templates/` hoặc thư mục gốc.

---

## 4. Nguyên Tắc Phối Hợp Đa Agent (Claude 🤝 Antigravity)

0. **Bảng bàn giao [docs/HANDOFF.md](docs/HANDOFF.md)**: đọc đầu mỗi lượt (ai đang sửa file nào, việc chờ, lời nhắn); nhận việc thì ghi vào "Đang làm"; xong thì commit, ghi "Đã xong" + "Nhật ký" cho agent kia.
1. **Phân bổ Cổng Port Chạy Server**:
   - **8501**: Cổng mặc định cho Antigravity / Người dùng chạy qua `run_app.bat`.
   - **8502 – 8504**: Cổng dành riêng cho Claude (xem `.claude/launch.json`) để test độc lập, không gây lỗi xung đột cổng `Port 8501 already in use`.
2. **Git Awareness**:
   - Luôn chạy `git status` trước khi sửa file để biết Antigravity hay người dùng có đang sửa dở file nào không.
   - Viết commit rõ ràng, tách bạch thay đổi.
3. **Bảo Mật Dữ Liệu**:
   - Không commit `.streamlit/secrets.toml`, file `.db`, file `.xlsx`, `.zip`.
   - Tránh hardcode mật khẩu, token hay email thật vào mã nguồn.

---

## 5. Mức Tự Chủ — Tự Làm, Không Hỏi Lại

Người dùng đã giao: **agent tự chia việc và tự làm**. Mặc định là **làm luôn đến hết việc, báo kết quả sau** — không xin xác nhận từng bước, không hỏi "có muốn tôi tiếp tục không".

**Tự quyết, KHÔNG hỏi:**
- Cách làm, tên hàm / biến, bố cục giao diện (theo quy chuẩn ở trên).
- Sửa / thêm code, kiểm thử, tài liệu trong repo; chạy `python -m unittest`, `compileall`, chạy app ở cổng của mình.
- Commit khi kiểm thử xanh; push lên `origin/main` khi kiểm thử xanh.
- Nhận việc trong "Việc chờ" của [docs/HANDOFF.md](docs/HANDOFF.md) có ghi tên mình, cập nhật bảng.
- Yêu cầu chưa rõ: chọn cách hợp lý nhất, **ghi giả định** vào "Nhật ký" của HANDOFF và báo cáo cuối lượt — không dừng lại để hỏi.
- Gặp lỗi: tự tìm nguyên nhân và sửa; chỉ báo khi đã thử mà không được.

**Chỉ hỏi người dùng khi:**
- Ghi / xóa dữ liệu thật: `data/icost.db` hoặc CSDL online (PostgreSQL).
- Thao tác không khôi phục được: xóa file / dữ liệu ngoài phạm vi việc, `git push --force`, sửa lịch sử git.
- Đổi quy tắc nghiệp vụ (ngưỡng TT45, luồng nộp / duyệt, phân quyền) hoặc làm việc người dùng đã hoãn (khấu hao theo tháng bàn giao).
- File cần sửa đang trong "Đang làm" của agent kia → không hỏi người dùng: ghi "Hỏi / Nhắn" trong HANDOFF rồi làm việc khác trong lúc chờ.
