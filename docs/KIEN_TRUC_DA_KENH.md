# Đa kênh trong CRM DMAG: phương án kiến trúc

> Mục tiêu: chat Facebook Messenger, chat Zalo OA và cuộc gọi Stringee tự đổ vào lead CRM. Mỗi lead có một
> dòng thời gian chung (giống Bitrix24), gồm tin nhắn, cuộc gọi kèm ghi âm, email, ghi chú, việc cần làm
> và lịch sử thay đổi. Từ lead có nút và tab nối thẳng tới hợp đồng, hoá đơn, thanh toán, lộ trình triển khai và dự án.

## 1. Cài module thêm vào CRM Odoo hay tách app riêng?

| Phương án | Ưu điểm | Nhược điểm | Kết luận |
|---|---|---|---|
| **A. Module (addon) cài vào chính Odoo** | Một database, một lần đăng nhập. Lead, liên hệ, hoá đơn, chatter dùng chung, không phải đồng bộ hai chiều. Quyền truy cập và nhật ký dùng luôn của Odoo. Đội tinh gọn chỉ phải vận hành một hệ thống. Đúng chủ trương "100% Odoo". | Webhook đi thẳng vào Odoo. Nếu lưu lượng rất lớn (hàng chục nghìn tin mỗi giờ) thì cần thêm hàng đợi. | **Chọn** |
| B. App riêng (một omnichannel hub viết bằng Node/NestJS) rồi đồng bộ vào Odoo qua API | Chịu tải lớn, có chat realtime (đang gõ, đã xem) cho nhiều nhân viên cùng lúc | Thêm một hệ thống phải vận hành, bảo mật và sao lưu. Dữ liệu khách nằm hai nơi, phải đồng bộ hai chiều, dễ lệch. Tốn gấp 2–3 lần công. | Chưa cần ở quy mô hiện tại |
| C. Mua sẵn (Pancake, Bitrix24, module Viindoo `viin_zalo_crm` / `viin_stringee`) | Nhanh | Pancake và Bitrix24 là hệ thống ngoài Odoo, lại quay về phương án B. Module Viindoo chỉ phủ từng phần (gắn nguồn Zalo, gọi điện), phụ thuộc lịch nâng cấp của nhà cung cấp, giấy phép OPL. | Không chọn |

**Quyết định:** làm thành **các module cài vào Odoo**. Code đã chừa sẵn để tách được về sau:
- Toàn bộ việc gọi API của từng kênh nằm trong các hàm `_facebook_*`, `_zalo_*`, `_stringee_*` của model `dmag.channel.account` (lớp adapter).
- Mọi webhook đều được ghi vào `dmag.channel.event` (nhật ký sự kiện) trước khi xử lý. Bảng này vừa là hàng đợi, vừa là nhật ký kiểm toán, vừa dùng để thử lại khi lỗi.

Khi nào mới tách thành gateway riêng: khi lượng tin vượt khoảng 50 nghìn tin/ngày, hoặc khi DMA-TECH bán tính năng "CRM Recall đa kênh" cho nhiều phòng khám, mỗi phòng khám một database Odoo. Lúc đó chỉ thay lớp adapter, phần CRM giữ nguyên.

## 2. Odoo 17 hay phiên bản mới?

- Các module viết cho **Odoo 19.0 Community**: đã chạy thật và có 35 bài test tự động.
- Hệ thống đang chạy là **Odoo 17 CE** (BizApps tuỳ biến), và DMAG đã chốt sẽ sớm lên bản mới nhất. Khuyến nghị:
  1. **Go-live trên 19**: BizApps chuyển các module của họ lên 19 trên môi trường staging; module DMAG cài thẳng vào đó.
  2. Nếu buộc phải chạy trên 17 trước khi nâng cấp: tạo nhánh `17.0` port lại. Phần phải sửa đều mang tính cơ học:
     - `<list>` → `<tree>`; `<chatter/>` → khối `oe_chatter`.
     - `models.Constraint` → `_sql_constraints`.
     - Nhóm quyền dùng `category_id` thay cho `res.groups.privilege`.
     - Template kanban `card` → `kanban-box`.
     - `crm.stage.team_ids` → `team_id`; route `type='jsonrpc'` không dùng.

     Ước tính 2–3 ngày, tính cả chạy lại toàn bộ test trên 17.
- Odoo 20 đã ra, nhưng chưa nên dùng ngay: các module VN và OCA (HĐĐT Viettel, Zalo…) chưa có bản cho 20.

## 3. Các module đã làm

| Module | Vai trò |
|---|---|
| `dmag_omnichannel` | Kết nối Facebook / Zalo OA / Stringee, webhook, hộp thư đa kênh, cuộc gọi, ghép khách vào lead, ghi mọi tương tác vào dòng thời gian của lead |
| `dmag_contract` | Hợp đồng gắn lead, đơn bán và đơn kê; lịch thu nhiều đợt (40/40/20…); xuất hoá đơn từng đợt; theo dõi đã thu, công nợ, quá hạn; nhắc tự động |
| `dmag_lead_hub` | "Lead 360°": nút và tab nối tới phòng khám, đơn kê, báo giá/đơn bán, hợp đồng, hoá đơn, lộ trình, dự án, hội thoại, cuộc gọi, hoa hồng, kèm tóm tắt tài chính |

Các module này nằm trên `dmag_crm`, `dmag_dda`, `dmag_delivery` và `dmag_commission` đã có.

## 4. Luồng dữ liệu

```
Facebook Page ──webhook (chữ ký X-Hub-Signature-256)──┐
Zalo OA ───────webhook (X-ZEvent-Signature)───────────┼─► /dmag/webhook/... ─► dmag.channel.event (nhật ký, chống trùng, thử lại)
Stringee ──────event_url / answer_url─────────────────┘                          │
                                                                                 ▼
                                    Ghép khách: ID trên kênh → liên hệ → (SĐT trong tin nhắn / số gọi) → phòng khám
                                                                                 │
                                    Lead đang mở của phòng khám? ── có ──► gắn vào lead đó
                                                                  └─ không ─► tạo lead mới ở P1 (nguồn UTM: Facebook / Zalo OA / Hotline)
                                                                                 │
                                                                                 ▼
                         dmag.conversation / dmag.call ─► ghi vào chatter của lead (nhãn kênh, chiều ⬅/➡, thời lượng, link ghi âm)
                                                        ─► gọi nhỡ thì tự giao việc "Gọi lại"; tin chưa đọc hiện trên thẻ Kanban
```

- Lead đã có sẵn trong Odoo: lịch sử thay đổi giai đoạn, người phụ trách, doanh thu (tracking), email, ghi chú, hoạt động. Tin nhắn và cuộc gọi được ghi thêm vào **cùng chatter đó**, nên một dòng thời gian thể hiện toàn bộ tương tác.
- Muốn có nhật ký kiểm toán mọi trường (ai sửa gì, lúc nào, trên mọi model) thì cài thêm OCA `auditlog`.

## 5. Thiết lập từng kênh khi chạy thật

Webhook cần tên miền HTTPS công khai, ví dụ `https://dmagroup.vn`.

| Kênh | Việc cần làm |
|---|---|
| Facebook | Tạo Meta App, thêm sản phẩm Messenger, lấy **Page Access Token**. Đăng ký webhook (Callback URL = URL webhook trên form kết nối; Verify Token tự đặt) với các trường `messages` và `message_echoes`. Xin quyền `pages_messaging` (App Review). Nhập App Secret để Odoo kiểm chữ ký. |
| Zalo OA | Tạo ứng dụng trên Zalo for Developers và liên kết OA. Cấp quyền OA theo OAuth v4 để lấy **Refresh Token** (Odoo tự làm mới mỗi giờ). Khai báo Webhook URL và bật các sự kiện `user_send_*`, `oa_send_*`, `follow`. Nhập OA Secret Key để kiểm chữ ký. |
| Stringee | Tạo project, thuê số hotline, tạo API Key. Khai báo `event_url` = URL webhook và `answer_url` = cùng URL nhưng thay `/stringee/event/` bằng `/stringee/answer/`. Mỗi nhân viên nhập **Stringee user ID** (softphone) hoặc số điện thoại nhận cuộc gọi trong hồ sơ người dùng. Bật ghi âm cuộc gọi. |

## 6. Giới hạn cần biết

- **Cửa sổ nhắn tin:**
  - Facebook chỉ cho Page nhắn trong 24 giờ kể từ tin cuối của khách.
  - Zalo OA cho gửi tin tư vấn trong 48 giờ.
  - Quá hạn thì nút "Gửi" bị khoá; phải gọi điện hoặc gửi ZNS (tin mẫu trả phí, sẽ làm ở bước sau).
- **Zalo cá nhân** không có API chính thức, nên không đồng bộ. Khách cần nhắn qua Zalo OA.
- **Ghi âm** hiện trên dòng thời gian dạng link "▶ Nghe ghi âm", vì chatter của Odoo lọc thẻ `<audio>`. Có thể làm widget phát ngay trong trang ở bước sau.
- **Stringee:** tài liệu gốc không truy cập được từ môi trường phát triển. Tên các trường trong `event_url` được đọc theo nhiều biến thể (`call_id`/`callId`, `call_status`/`callStatus`…). Cần thử bằng một cuộc gọi thật, xem trong "Nhật ký webhook" rồi chỉnh nếu lệch.
- **Chữ ký webhook Zalo** dùng công thức `sha256(app_id + body + timestamp + OA secret)`; cần đối chiếu lại khi kết nối thật.

## 7. Bảo mật và dữ liệu cá nhân

- Mỗi URL webhook có mã bảo vệ riêng (`?token=`). Facebook và Zalo còn được kiểm chữ ký.
- Token và secret chỉ nhóm **Quản lý DMAG** đọc được. Nhân viên chỉ thấy hội thoại và cuộc gọi.
- Mọi payload gốc lưu ở "Nhật ký webhook" (chỉ quản lý xem được). Cần đặt thời hạn lưu theo Luật Bảo vệ dữ liệu cá nhân 2025.
