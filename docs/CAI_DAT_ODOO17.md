# Cài bộ module DMAG lên Odoo 17 CE đang chạy

Thư mục `odoo17/` chứa bản dành cho **Odoo 17.0 Community**. Bản này đã cài thử trên Odoo 17 gốc và qua 35/35 bài test tự động.
Thư mục `odoo19/` là bản cho Odoo 19, dùng khi nâng cấp. Hai bản có cùng chức năng.

## 1. Ứng dụng Odoo cần có (tự cài theo phụ thuộc)

CRM, Sales (sale_management, sale_crm), Contacts, Invoicing/Accounting, Project, Calendar, UTM, **eLearning (website_slides)**.

> eLearning kéo theo app **Website**. Nếu DMAG chưa muốn bật Website, hãy báo lại: có thể tách phần ghi danh khoá học
> thành module tuỳ chọn để `dmag_delivery` không phụ thuộc eLearning.

## 2. Các bước cài (làm trên bản sao trước, không làm thẳng trên production)

1. **Sao lưu** database production và filestore.
2. Khôi phục bản sao vào máy **staging** có cùng mã nguồn Odoo 17 và các module BizApps.
3. Lấy mã:
   ```bash
   git clone <repo> /opt/dmag && git -C /opt/dmag checkout claude/tender-dirac-cc9hv2
   ```
4. Thêm `/opt/dmag/odoo17` vào `addons_path` trong file cấu hình Odoo, rồi khởi động lại dịch vụ.
5. Vào Ứng dụng → **Cập nhật danh sách ứng dụng**. Cài **DMAG Lead 360°** (`dmag_lead_hub`); module này tự cài 6 module còn lại.
   Muốn cài từng phần thì đi theo thứ tự `dmag_crm` → `dmag_dda` → `dmag_delivery` / `dmag_commission` / `dmag_contract` → `dmag_omnichannel` → `dmag_lead_hub`.
   Dòng lệnh tương đương:
   ```bash
   odoo-bin -c /etc/odoo.conf -d <db_staging> -i dmag_lead_hub --stop-after-init
   ```
   Không dùng `--with-demo` trên DB thật.
6. Kiểm tra trên staging theo checklist ở mục 4, rồi mới làm lại các bước 4–5 trên production (sau khi sao lưu).

## 3. Cấu hình sau khi cài

| Việc | Ở đâu |
|---|---|
| Gán nhóm **DMAG / Nhân viên** hoặc **DMAG / Quản lý** cho người dùng | Thiết lập → Người dùng |
| Rà ngưỡng phân khúc PK1–PK5 và 10 trụ cột DDA | DMAG CRM → Cấu hình |
| Nhập chỉ tiêu suất triển khai theo quý | DMAG CRM → Cấu hình → Suất triển khai theo quý |
| Tạo danh mục module × hình thức (sản phẩm dịch vụ, tab DMAG) | DMAG CRM → Cấu hình → Danh mục module |
| Tạo chính sách hoa hồng và gán cho từng người | DMAG CRM → Cấu hình / Hoa hồng |
| Tạo kết nối Facebook / Zalo OA / Stringee, rồi dán URL webhook sang từng nền tảng | DMAG CRM → Cấu hình → Kết nối kênh (xem `docs/KIEN_TRUC_DA_KENH.md`) |
| Nhập Stringee user ID hoặc số nhận cuộc gọi cho từng nhân viên | Hồ sơ người dùng → tab Tổng đài Stringee |
| Các giai đoạn CRM chuẩn của Odoo (New, Qualified…) dùng chung mọi pipeline nên sẽ hiện cả trong pipeline DMAG. Muốn ẩn thì gán chúng cho đội cũ. | CRM → Cấu hình → Giai đoạn |

## 4. Checklist kiểm tra trên staging

- [ ] Form lead, form liên hệ, form đơn bán **của BizApps** vẫn mở bình thường. Module DMAG chỉ thêm tab, nút và trường có tiền tố `dmag_`, không sửa trường gốc.
- [ ] Pipeline và lead cũ vẫn đúng giai đoạn. DMAG chỉ thêm 4 đội P1–P4 cùng giai đoạn riêng của các đội đó.
- [ ] Tạo thử một phòng khám, một cơ hội P1, đi qua các cổng giai đoạn; chấm DDA, kê đơn, tạo báo giá, hợp đồng, xuất hoá đơn đợt 1, ghi nhận thanh toán; kiểm tra dòng hoa hồng và tab Hồ sơ 360° trên lead.
- [ ] Gửi thử một tin Facebook/Zalo tới Page/OA và gọi thử hotline; xem "Nhật ký webhook" và dòng thời gian của lead.
- [ ] Hoá đơn Viettel: hoá đơn đợt sinh từ hợp đồng là hoá đơn Odoo chuẩn, nên phải đi qua đúng luồng phát hành HĐĐT Viettel mà BizApps đã cài.

## 5. Gỡ bỏ / quay lui

Nếu có sự cố trên production: khôi phục bản sao lưu ở bước 1. Gỡ module qua Ứng dụng → Gỡ cài đặt cũng được, nhưng sẽ xoá dữ liệu DMAG (DDA, hợp đồng, hội thoại…), nên chỉ làm trên staging.

## 6. Khác biệt kỹ thuật giữa bản 17 và 19 (cho đội phát triển)

| Odoo 19 | Odoo 17 |
|---|---|
| `<list>`, `<chatter/>`, kanban `t-name="card"` | `<tree>`, khối `oe_chatter`, `kanban-box` + `t-if` |
| `models.Constraint` | `_sql_constraints` |
| `res.groups.privilege`, `user_ids` | `ir.module.category`, `users` |
| `crm.stage.team_ids`, `crm.lead.won_status` | `crm.stage.team_id`; thắng = `stage_id.is_won`, đang mở = `active` và chưa thắng |
| `sale.order.line.product_uom_id` | `product_uom` |
| `project.task.is_closed` | `state in CLOSED_STATES` |
| Cron không cần `numbercall` | `numbercall = -1` |
| Trường dùng trong `invisible/readonly` tự được thêm vào view | Phải khai báo trong view; script `tools/odoo17_declare_modifier_fields.py` tự thêm |
