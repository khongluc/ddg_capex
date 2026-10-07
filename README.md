# HỆ THỐNG QUẢN LÝ & TÍNH TOÁN NGÂN SÁCH ĐẦU TƯ CAPEX KHỐI CNTT
**CÔNG TY CỔ PHẦN CƠ KHÍ XÂY DỰNG THƯƠNG MẠI ĐẠI DŨNG (DDC)**

---

## 🌟 Giới thiệu

Web App được xây dựng chuyên biệt để giải quyết bài toán **Lập kế hoạch, Phân loại, Tính toán chi phí, Phân kỳ giải ngân và Thẩm định Ngân sách Đầu tư CAPEX cho Khối / Phòng Công nghệ Thông tin (CNTT)** theo từng phòng ban và toàn công ty. 

Toàn bộ hệ thống được đồng bộ 100% với file biểu mẫu kế toán **`2. Form file nhập liệu CAPEX 2026.xlsx`** của Tập đoàn Đại Dũng.

---

## 🚀 Khởi chạy Web App

### Cách 1: Khởi chạy 1-Click (Khuyên dùng)
- Nhấp đúp chuột vào file **`run_app.bat`** tại thư mục dự án `d:\DATA\dev\I_Cost`.
- Trình duyệt sẽ tự động mở tại địa chỉ: **`http://localhost:8501`**.

### Cách 2: Khởi chạy bằng PowerShell / Terminal
```powershell
python -m streamlit run app.py
```

---

## 🏢 FORM LẬP NGÂN SÁCH THEO PHÒNG BAN TIỆN LỢI

Hệ thống đã nâng cấp toàn diện Tab **"📝 Lập & Nhập liệu CapEx"** thành trung tâm lập ngân sách theo phòng ban với 2 hình thức nhập liệu cực kỳ thuận tiện:

### 1. 🏢 Thẻ Thiết lập & Thống kê Phòng ban Mục tiêu
- **Bộ chọn phòng ban trực quan**: Chọn nhanh phòng ban cần lập (trong 64 phòng ban của DDC hoặc phòng ban mới).
- **Thẻ KPI phòng ban tức thì**:
  - Tên phòng ban & Vị trí / Site.
  - Số lượng hạng mục đã lập.
  - Tổng ngân sách đề xuất của riêng phòng ban.
  - Bóc tách theo chuẩn kế toán: **TSCĐ (CAPEX)** vs **CCDC dài hạn** vs **Chi phí (OPEX)**.
- **Nút xuất Excel riêng**: Tải riêng file Excel phiếu đề xuất của phòng ban đó để trình ký.

### 2. 🛒 Chế độ 1: Chọn Nhanh theo Danh mục CNTT (Multi-Item Batch Picker - Tiện lợi nhất)
- **Thao tác trong 10 giây**:
  1. Chọn **Nhóm CNTT** (vd: `IT01. Thiết bị người dùng cuối` - PC/Laptop, `IT09. Phần mềm M365`, `IT02. Máy in/Scan`...).
  2. Bảng các thiết bị của nhóm hiện ra với: Mã, Tên thiết bị chuẩn, Đơn giá tham chiếu DDC, Đơn vị tính, Phân loại kế toán.
  3. Người dùng chỉ cần gõ số lượng cần mua vào cột **"Số lượng cần mua"** (những món không mua để 0). Có thể nhập thêm ghi chú / đối tượng sử dụng.
  4. Chọn **Tháng đưa vào sử dụng** (vd: `T1 2026`).
  5. Chọn **Loại nhu cầu** (Định biên / Phát sinh mới).
  6. Bấm nút: **`➕ Thêm [X] mục vào [Tên Phòng Ban]`**.
- **Tự động hóa hoàn toàn**:
  - Tự động tính thành tiền: `Số lượng × Đơn giá`.
  - Tự động phân kỳ giải ngân 100% vào tháng sử dụng đã chọn.
  - Tự động sinh `Mã công trình`, `Mã hạng mục`, `Mã ngân sách`.
  - Tự động hạch toán TSCĐ (nguyên giá ≥ 30tr) hoặc CCDC/OPEX.
  - Tiết kiệm 95% thời gian so với việc nhập từng form đơn lẻ!

### 3. ✍️ Chế độ 2: Thêm Chi tiết 1 Hạng mục (Single Item Form)
- Dành cho các thiết bị cần cấu hình kỹ thuật riêng, nhà cung cấp riêng, hoặc phân kỳ giải ngân phức tạp.
- Tự động điền sẵn Phòng ban đề xuất, Pháp nhân, Site.
- Chọn thiết bị từ danh mục ➔ Tự động nhảy đơn giá chuẩn, loại tài sản, mã ngân sách.
- Nút phân kỳ giải ngân 1-click (100% vào tháng sử dụng hoặc chia đều 12 tháng).
- Bấm **`💾 Thêm hạng mục vào phòng ban`**.

---

## 💻 BỘ DANH MỤC CAPEX CNTT CHUẨN HOÁ (13 NHÓM - 112 HẠNG MỤC)

1. **IT01. Thiết bị người dùng cuối**: PC văn phòng i3/i5/i7, PC thiết kế CAD/BIM, Laptop i5/i7, Laptop VGA rời, Màn hình 24"/27", Tablet...
2. **IT02. Máy in, scan & thiết bị VP số**: Máy in A4/A3, Máy in màu laser, Máy Scaner số hóa tài liệu, Máy Photocopy đa năng...
3. **IT03. Máy chủ & lưu trữ**: Server Dell/HP, Hệ thống lưu trữ NAS, SAN, Ổ cứng Enterprise HDD chuyên dụng NAS...
4. **IT04. Hạ tầng mạng LAN/WAN/Wifi**: Core Switch, Access Switch, Wifi doanh nghiệp Indoor/Outdoor, ODF quang, Module quang, Cáp quang/đồng...
5. **IT05. An ninh mạng & bảo mật**: Firewall Meraki, Firewall Fortigate, License quản trị bảo mật Switch Meraki...
6. **IT06. Camera, kiểm soát & chấm công**: Camera an ninh, Đầu ghi hình, Camera AI nhận diện thông minh, Máy chấm công khuôn mặt, Access Control...
7. **IT07. Phòng họp & thiết bị nghe nhìn**: Phòng họp thông minh (Lầu 2, Lầu 7, Lầu 8), Thiết bị họp trực tuyến lớn/vừa, Smart TV 85"/65"/55", Máy chiếu, Âm thanh...
8. **IT08. Phòng server & nguồn điện dự phòng**: UPS chuyên dụng Server/Mạng, Tủ Rack 42U/12U/9U/6U, Sàn nâng kỹ thuật, Máy hút ẩm...
9. **IT09. Phần mềm hệ thống & văn phòng**: Windows Server, SQL Enterprise/Std, Microsoft 365 (Basic, Std, E3, E5), Power BI Pro, Kaspersky, Anydesk, SSL...
10. **IT10. Phần mềm kỹ thuật – thiết kế (DDC)**: Tekla Structures, Tekla Model Sharing, Trimble Connect, AutoCAD, Revit, Navisworks, SketchUp, SAP2000, ETABS, IDEA StatiCa, BIM, EnjiCAD, ZWCAD, Primavera P6...
11. **IT11. Phần mềm quản trị doanh nghiệp**: Dự án ERP, Hệ thống Văn phòng số E-Office / BPM...
12. **IT12. Dịch vụ CNTT, Cloud & đường truyền**: Dịch vụ Cloud Viettel (ERP/E-Office), Cloud Wasabi (Backup), License VMware, Leased-line...
13. **IT13. Linh kiện, vật tư & ngoại vi**: Nâng cấp RAM, SSD/HDD, Card VGA rời, Nguồn PC, Webcam, Chuột phím, USB...
