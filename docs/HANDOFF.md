# BẢNG BÀN GIAO CLAUDE 🤝 ANTIGRAVITY

Kênh trao đổi chung giữa hai agent (không nhắn trực tiếp được cho nhau). Quy trình chi tiết: [COLLABORATION.md](COLLABORATION.md).

**Mỗi lượt làm việc:**
1. **Bắt đầu:** đọc file này + `git status` + `git log --oneline -5`. Nếu file mình định sửa đang có trong "Đang làm" của agent kia → không sửa, ghi câu hỏi vào "Hỏi / Nhắn".
2. **Nhận việc:** chuyển dòng việc sang "Đang làm", ghi tên agent + các file sẽ sửa.
3. **Kết thúc:** `python -m unittest` xanh → commit → chuyển việc sang "Đã xong" (kèm mã commit) → ghi lại điều agent kia cần biết vào "Nhật ký".
4. Không để thay đổi chưa commit khi bàn giao, trừ khi ghi rõ ở "Đang làm".

---

## Đang làm
| Agent | Việc | File đang sửa | Từ ngày |
| :--- | :--- | :--- | :--- |
| _(trống)_ | | | |

## Việc chờ (người dùng giao, chưa ai nhận)
- _(trống - người dùng thêm vào đây hoặc giao trực tiếp cho một agent)_

## Hỏi / Nhắn
- _(trống)_

## Đã xong
| Ngày | Agent | Việc | Commit |
| :--- | :--- | :--- | :--- |
| 2026-10-12 | Claude | Phân kỳ nhiều tháng khi thêm hạng mục (popup + tab Chọn nhanh), chọn nhiều nhóm CNTT | `eb6fbcf` |
| 2026-10-12 | Antigravity + Claude | Tài liệu phối hợp CLAUDE.md / AGENTS.md / COLLABORATION.md | `6e2e3fe` |

## Nhật ký (mới nhất ở trên)
- **2026-10-12 · Claude → Antigravity:**
  - Phân kỳ thêm hạng mục nằm ở `phasing_picker()` (app.py) + `even_units()` / `phase_presets()` (capex_engine.py). Mọi đường thêm hạng mục từ danh mục / popup lưu qua `_commit_checklist_items()`; cột `_units` = SL nguyên từng tháng. Sửa giao diện popup thì giữ các tên này (test trích bằng `ast.parse`).
  - Ổ C: còn ~0,7 GB, D: ~2 GB - chạy Streamlit / test có thể lỗi do đầy ổ.
  - Claude không ghi được vào `data/icost.db` (bị chặn quyền): việc cần sửa CSDL sản xuất → Claude viết script dry-run / `--apply` để người dùng chạy.
