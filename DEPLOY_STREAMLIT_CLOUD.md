# Chạy thử miễn phí trên Streamlit Community Cloud

Mục đích: cho IT các site vào nhập ngân sách thử (UAT) nhanh, miễn phí. Khi chạy thật nên chuyển sang máy chủ Linux + Cloudflare Tunnel.

## Lưu ý quan trọng
- **Ổ đĩa không lưu bền**: dữ liệu (`data/icost.db`, danh mục) có thể mất khi app khởi động lại / ngủ / cập nhật code.
  → Admin vào **👥 Phân quyền & Tiến độ → 💾 Sao lưu / Khôi phục**, tải bản sao lưu cuối mỗi ngày; sau khi app khởi động lại thì khôi phục.
- File Excel (form CAPEX, file định biên) **không** được đưa lên GitHub vì có họ tên / mã nhân viên. Admin tải file lên qua giao diện app khi cần.
- **Không bật `dev_login`** trên cloud (ai cũng gõ được email admin). Phải cấu hình đăng nhập Google (hoặc UltraID) trước.

## Bước 1 – Đưa mã nguồn lên GitHub (kho riêng tư)
1. Tạo tài khoản / đăng nhập https://github.com, bấm **New repository** → tên `ddc-capex` → chọn **Private** → Create.
2. Trên máy, mở PowerShell tại `D:\DATA\dev\I_Cost` và chạy (thay `<tai-khoan>`):
   ```
   git remote add origin https://github.com/<tai-khoan>/ddc-capex.git
   git push -u origin main
   ```

## Bước 2 – Tạo app trên Streamlit Community Cloud
1. Vào https://share.streamlit.io → đăng nhập bằng GitHub → **Create app** → **Deploy a public app from GitHub**.
2. Repository: `<tai-khoan>/ddc-capex`, Branch: `main`, Main file path: `app.py`.
3. **App URL**: đặt tên, ví dụ `ddc-capex` → địa chỉ sẽ là `https://ddc-capex.streamlit.app`.
4. **Advanced settings** → Python 3.11 → ô **Secrets**: dán nội dung ở Bước 3 → **Deploy**.

## Bước 3 – Secrets (dán vào ô Secrets của Streamlit Cloud)
```toml
[icost]
admin_emails = ["luckv@daidung.vn"]
allowed_domains = ["daidung.vn"]
dev_login = false

[auth]
redirect_uri = "https://ddc-capex.streamlit.app/oauth2callback"
cookie_secret = "<chuỗi ngẫu nhiên: python -c \"import secrets; print(secrets.token_hex(32))\">"

[auth.google]
client_id = "<Client ID từ Google Cloud Console>"
client_secret = "<Client secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
client_kwargs = { scope = "openid email profile", prompt = "select_account" }
```
Trong Google Cloud Console → Credentials → OAuth client: thêm **Authorized redirect URI** `https://ddc-capex.streamlit.app/oauth2callback` (trùng tuyệt đối với `redirect_uri`).

## Bước 4 – Nạp dữ liệu ban đầu
1. Mở `https://ddc-capex.streamlit.app` → đăng nhập Google bằng tài khoản admin.
2. Nếu đã có dữ liệu trên máy: trên máy local vào tab Sao lưu → tải `.zip` → trên cloud vào tab Sao lưu → **Khôi phục**.
3. Hoặc nhập lại: chọn năm 2027 → tab **👥 Định biên & Nhu cầu** → Nhập file định biên → *Tải lên file khác* → **Áp định biên**.
4. Tab **👥 Phân quyền & Tiến độ**: thêm email IT từng site, vai trò *IT Site*, chọn site.

## Bước 5 – Cập nhật code sau này
`git add -A && git commit -m "..." && git push` → Streamlit Cloud tự cập nhật (nhớ **sao lưu trước** khi push).
