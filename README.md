# HỆ THỐNG QUẢN LÝ & TÍNH TOÁN NGÂN SÁCH ĐẦU TƯ CAPEX KHỐI CNTT
**TẬP ĐOÀN ĐẠI DŨNG (DDC) — I-COST PLATFORM**

---

## 🌟 Giới thiệu Tổng quan

**I-Cost** là nền tảng quản trị và lập ngân sách đầu tư Công nghệ Thông tin (IT CapEx & OpEx) toàn diện được thiết kế chuyên biệt cho Tập đoàn Đại Dũng. Hệ thống số hóa quy trình thu thập nhu cầu đầu tư, thẩm định danh mục CNTT, tự động hóa phân kỳ dòng tiền, tính toán khấu hao và đối soát thực hiện ngân sách.

Hệ thống đồng bộ 100% với biểu mẫu tài chính kế toán **`2. Form file nhập liệu CAPEX 2026.xlsx`** của Tập đoàn.

---

## 🚀 Khởi chạy Nhanh (Quick Start)

### Cách 1: Khởi chạy 1-Click (Khuyên dùng trên Windows)
- Nhấp đúp chuột vào file **`run_app.bat`** tại thư mục dự án `d:\DATA\dev\I_Cost`.
- Trình duyệt sẽ tự động mở tại địa chỉ: **`http://localhost:8501`**.

### Cách 2: Khởi chạy qua PowerShell / Command Prompt
```powershell
python -m streamlit run app.py
```

---

## 📁 Cấu trúc Thư mục Chuẩn Hóa (Standard Project Structure)

Hệ thống được tổ chức theo tiêu chuẩn kiến trúc phần mềm doanh nghiệp:

```
d:\DATA\dev\I_Cost/
├── .streamlit/               # Cấu hình theme Corporate Navy & server Streamlit
├── data/                     # Cơ sở dữ liệu SQLite & dữ liệu hoạt động
│   ├── icost.db              # Database chính
│   ├── backups/              # Các bản sao lưu database (.db, .zip)
│   └── archive/              # Dữ liệu dump và scratch lưu trữ
├── docs/                     # Tài liệu kỹ thuật dự án
│   ├── ARCHITECTURE.md       # Chi tiết kiến trúc phân tầng & modules
│   └── DEPLOY_STREAMLIT_CLOUD.md # Hướng dẫn triển khai Streamlit Cloud
├── templates/                # Biểu mẫu Excel kế toán & định biên nhân sự mẫu
├── tests/                    # Bộ 29+ test cases tự động (Python unittest)
├── app.py                    # Presentation Layer: 11 Tabs giao diện Streamlit
├── auth.py                   # Xác thực & phân quyền 4 vai trò (RBAC)
├── capex_engine.py           # Core Engine: Khấu hao, phân kỳ, hạch toán TSCĐ/CCDC
├── master_data.py            # Master Catalog: 13 nhóm CNTT & 112 hạng mục chuẩn
├── smart_advisor.py          # AI Rule Engine & Cố vấn tối ưu ngân sách
├── quota.py                  # Module phân tích định biên nhân sự & tự động dự toán
├── pricing.py                # Quản lý đơn giá & lịch sử báo giá nhà cung cấp
├── workflow.py               # Luồng phê duyệt 4 cấp & cơ chế khóa phòng ban
├── execution.py              # Theo dõi thực hiện ngân sách & đối soát PO/Hóa đơn
├── versions.py               # Quản lý phiên bản ngân sách & so sánh chênh lệch
├── reports.py                # Xuất báo cáo tài chính & biểu mẫu Excel DDC
├── requirements.txt          # Thư viện phụ thuộc
└── run_app.bat               # File thực thi 1-click
```

> 📖 **Xem chi tiết tài liệu kiến trúc hệ thống tại:** [docs/ARCHITECTURE.md](file:///d:/DATA/dev/I_Cost/docs/ARCHITECTURE.md)

---

## 🏢 Các Phân hệ Chức năng Chính (11 Tabs)

1. **📊 Tổng quan**: KPI tổng hợp, cơ cấu CAPEX / CCDC / OPEX, phân kỳ theo tháng/quý và phân bổ theo Khối.
2. **📝 Lập CapEx**:
   - **Multi-Item Batch Picker**: Chọn nhanh nhiều thiết bị trong nhóm CNTT, nhập số lượng và đẩy vào phòng ban chỉ trong 10 giây.
   - **Single Item Detailed Form**: Nhập chi tiết thiết bị đặc thù, nhà cung cấp, cấu hình và phân kỳ tùy chỉnh.
3. **👥 Định biên**: Phân tích bảng định biên nhân sự, tự động phát hiện số lượng vị trí để đề xuất bộ trang bị chuẩn (PC/Laptop, bản quyền).
4. **🏗️ Hạ tầng**: Lập dự toán hạ tầng CNTT dùng chung toàn site (Phòng Server, Core Switch, Firewall, Camera, UPS...).
5. **💿 Phần mềm**: Quản lý danh mục & phân bổ đầu tư bản quyền phần mềm (Office 365, Tekla, AutoCAD, ERP, E-Office...).
6. **📁 Nhập / Xuất**: Xuất file Excel chuẩn biểu mẫu tài chính DDC, nhập liệu từ sheet biểu mẫu và tải template mẫu.
7. **🎯 Kịch bản**: Mô phỏng kịch bản cắt giảm ngân sách (What-If) và gom gói thầu mua sắm tập trung tiết kiệm chi phí.
8. **💳 Giải ngân**: Đối soát kế hoạch ngân sách với PO thực tế ký kết, nghiệm thu và hóa đơn tài chính.
9. **🗂️ Phiên bản**: Lưu snapshot các kỳ ngân sách (V1, V2, Approved) và phân tích biến động chênh lệch.
10. **📈 Thẩm định**: Dự phóng khấu hao TSCĐ (theo TT 45/2013/TT-BTC) và thẩm định hiệu quả đầu tư dự án (NPV / IRR / ROI).
11. **⚙️ Danh mục**: Quản lý 13 nhóm CNTT với 112 hạng mục chuẩn, đơn giá trần/sàn, đơn vị tính và nhà máy/site.

---

## 💻 Danh mục Thiết bị & Bản quyền CNTT Chuẩn Hóa (13 Nhóm)

- **IT01. Thiết bị người dùng cuối**: PC văn phòng, PC thiết kế CAD/BIM, Laptop Core i5/i7, Màn hình 24"/27"...
- **IT02. Máy in, scan & thiết bị VP số**: Máy in laser A4/A3, Máy scan 2 mặt số hóa, Photocopy đa năng...
- **IT03. Máy chủ & lưu trữ**: Server Dell PowerEdge/HP ProLiant, Hệ thống lưu trữ NAS Synology, SAN, Enterprise HDD...
- **IT04. Hạ tầng mạng LAN/WAN/Wifi**: Core Switch Layer 3, Access Switch PoE, Access Point Wifi 6 doanh nghiệp...
- **IT05. An ninh mạng & bảo mật**: Firewall Cisco Meraki, Fortigate, Bản quyền quản trị bảo mật...
- **IT06. Camera, kiểm soát & chấm công**: Camera AI thông minh, Máy chấm công khuôn mặt, Hệ thống Access Control...
- **IT07. Phòng họp & thiết bị nghe nhìn**: Thiết bị họp trực tuyến All-in-one, Smart TV 65"/85", Âm thanh hội nghị...
- **IT08. Phòng server & nguồn điện dự phòng**: Bộ lưu điện Online UPS 3KVA-10KVA, Tủ Rack 42U/12U, Sàn nâng kỹ thuật...
- **IT09. Phần mềm hệ thống & văn phòng**: Windows Server, SQL Server Enterprise, Microsoft 365 (Business/Enterprise), Power BI...
- **IT10. Phần mềm kỹ thuật – thiết kế**: Tekla Structures, Trimble Connect, AutoCAD, Revit, SAP2000, ETABS, IDEA StatiCa...
- **IT11. Phần mềm quản trị doanh nghiệp**: Hệ thống ERP, Phần mềm Văn phòng số E-Office / BPM...
- **IT12. Dịch vụ CNTT, Cloud & đường truyền**: Dịch vụ Cloud Viettel, Backup Cloud Wasabi, License VMware, Internet Leased-line...
- **IT13. Linh kiện, vật tư & ngoại vi**: Nâng cấp RAM/SSD, VGA rời, Bộ phím chuột công thái học, USB Token...

---

## 🧪 Kiểm thử Tự động (Automated Test Suite)

Chạy bộ kiểm thử tự động trực tiếp bằng công cụ `unittest` có sẵn trong Python:

```bash
python -m unittest
```

- Toàn bộ **29+ test cases** được thực thi độc lập trong môi trường SQLite in-memory, đảm bảo tính toàn vẹn 100% của dữ liệu sản xuất.
- Bao gồm kiểm tra: Thuật toán phân kỳ, quy tắc khấu hao theo Thông tư 45, khóa phê duyệt phòng ban, so sánh phiên bản, và đối soát thực hiện PO.
