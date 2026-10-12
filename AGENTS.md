# AGENTS.md — HƯỚNG DẪN DỰ ÁN CHO ANTIGRAVITY & CODING AGENTS
**Dự án: I-Cost — Hệ Thống Quản Lý & Lập Ngân Sách Đầu Tư CNTT (Tập đoàn Đại Dũng - DDC)**

Tài liệu này xác định các quy ước lập trình, cấu trúc thư mục, quy tắc giao diện và giao thức phối hợp làm việc song song giữa **Antigravity** và **Claude**.

---

## 1. Nguyên Tắc Cốt Lõi & Lệnh Thực Thi (Core Guidelines)

* **Ngôn ngữ**: Python 3.11+, Streamlit 1.45+, SQLite / PostgreSQL, OpenPyXL, Plotly.
* **Lệnh kiểm thử tự động**:
  ```bash
  python -m unittest
  ```
  *(Toàn bộ test cases phải PASS trước khi kết thúc bất kỳ lượt làm việc nào)*.
* **Lệnh khởi chạy mặc định của Antigravity**:
  ```bash
  python -m streamlit run app.py --server.port 8501 --server.headless true
  ```
* **Kiểm tra cú pháp**:
  ```bash
  python -m compileall -q .
  ```

---

## 2. Quy Chuẩn Giao Diện (Design System & UI Standards)

1. **Hệ màu nhận diện Doanh nghiệp (Corporate Navy)**:
   - Primary Color: `#1E40AF` (Royal Blue)
   - Header & Dark accents: `#0A192F`, `#0F2C59`
   - Backgrounds: `#F8FAFC` (Canvas), `#EEF2F6` (Neutral cards)
   - Text: `#0F172A` (Slate 900), `#475569` (Slate 600)
   - Typography: Font chuẩn `Inter, sans-serif`
2. **Quy tắc Thành phần Giao diện (Components)**:
   - **Thanh điều hướng**: 11 tabs dạng Segmented Capsule Pills thu gọn trên 1 dòng duy nhất (`📊 Tổng quan`, `📝 Lập CapEx`, `👥 Định biên`, `🏗️ Hạ tầng`, `💿 Phần mềm`, `📁 Nhập / Xuất`, `🎯 Kịch bản`, `💳 Giải ngân`, `🗂️ Phiên bản`, `📈 Thẩm định`, `⚙️ Danh mục`).
   - **Thông báo**: Sử dụng `st.toast(..., icon="✅")` cho các hành động nhanh thay vì thanh alert cồng kềnh đẩy layout.
   - **Cửa sổ Popup tương tác**: Sử dụng `@st.dialog(..., width="large")` cho các tác vụ chọn hàng loạt (Batch Picker) và rà soát (Batch Adjust).
   - **An toàn HTML Output**: Mọi dữ liệu do người dùng nhập khi render vào HTML phải bọc qua `html.escape()`.

---

## 3. Ranh Giới Module & Phân Tầng Nghiệp Vụ

| Module | Trách nhiệm | Ranh giới |
| :--- | :--- | :--- |
| **`app.py`** | Giao diện Streamlit, Điều hướng, Dialogs, Filter Bar | Không nhúng logic khấu hao hay SQL thô; gọi qua service modules |
| **`capex_engine.py`** | Thuật toán phân kỳ, Khấu hao TT45, Phân loại TSCĐ/CCDC | Không phụ thuộc `streamlit` |
| **`db.py`** | Kết nối CSDL, Schema, Prepared Statements, Audit Log | Đảm bảo 100% Parameterized queries |
| **`quota.py`** | Định biên nhân sự, Kits tiêu chuẩn (`DEFAULT_STANDARD_KITS`) | Độc lập giao diện |
| **`smart_advisor.py`** | Quy tắc khám sức khỏe ngân sách (/100 điểm), tư vấn chi phí | Phân tích read-only |
| **`workflow.py`** | Trạng thái nộp/duyệt, cơ chế giữ dòng khóa (`keep_locked_rows`) | Không sửa trực tiếp CSDL |

---

## 4. Giao Thức Phối Hợp Đa Agent (Antigravity 🤝 Claude)

0. **Bảng bàn giao [docs/HANDOFF.md](docs/HANDOFF.md)**: đọc đầu mỗi lượt (ai đang sửa file nào, việc chờ, lời nhắn); nhận việc thì ghi vào "Đang làm"; xong thì commit, ghi "Đã xong" + "Nhật ký" cho agent kia.
1. **Đồng bộ hóa Tài liệu Hướng dẫn**:
   - `AGENTS.md` (dành cho Antigravity) và `CLAUDE.md` (dành cho Claude) luôn được duy trì cùng 1 phiên bản nghiệp vụ và ràng buộc kỹ thuật.
2. **Tránh Xung Đột Cổng Mạng (Port Isolation)**:
   - Antigravity phục vụ người dùng chính trên cổng **`8501`**.
   - Claude chạy các tác vụ thử nghiệm trên cổng **`8502 – 8504`** (xem cấu hình `.claude/launch.json`).
3. **An Toàn Mã Nguồn & Git**:
   - Trước khi thực hiện chỉnh sửa lớn, kiểm tra `git status` và `git diff`.
   - Giữ nguyên các hàm / biến mà `tests/test_app_helpers.py` trích xuất từ `app.py` bằng `ast.parse`: `dept_key`, `dept_mask`, `filter_values`, `save_view`, `_commit_checklist_items`, `phasing_picker` và các biến `ITEM_FILTERS`, `FILTER_BLANK`, `PHASE_ONE` (xem `WANTED_FUNCS` / `WANTED_NAMES` trong file test).
   - Tổng tỷ lệ phân kỳ (cột `pct_<tháng>`, năm ngân sách T10 → T9) của mỗi dòng phải bằng 1.0.
   - Xem thêm chi tiết tại [docs/COLLABORATION.md](file:///d:/DATA/dev/I_Cost/docs/COLLABORATION.md).

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
