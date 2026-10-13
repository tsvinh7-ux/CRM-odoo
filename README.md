# DMAG CRM B2B trên Odoo (demo)

Bộ module Odoo cho mô hình **DMAG – Nền tảng Vận hành & Tăng trưởng Nha khoa**:
một hồ sơ phòng khám → chẩn đoán (DISC + phân khúc + Fast-Check → DDA → Radar) →
đơn kê lộ trình module × hình thức → triển khai được giám sát tự động → hoa hồng theo thực thu.

> **Trạng thái:** bản demo chạy được trên **Odoo 19.0 Community**. Đã có 21 bài test tự động.
> Danh mục module, giá, ngưỡng điểm và chính sách hoa hồng trong dữ liệu mẫu đều là **giả định**,
> chờ DMAG chốt rồi thay.

## Các module

| Module | Chức năng chính |
|---|---|
| `dmag_crm` | Hồ sơ phòng khám 360° (quy mô, phân khúc PK1–PK5, chặng G0–G5, vòng đời, Account Owner, hội đồng mua + DISC, đồng ý nhận thông tin). Chuẩn hoá SĐT và chặn tạo trùng phòng khám. Pipeline P1 Chẩn đoán / P2 Lộ trình / P3 EDU / P4 TECH. **Cổng giai đoạn** (trường bắt buộc để chuyển giai đoạn). **Suất triển khai theo quý** (chỉ đếm và cảnh báo; quản lý bấm duyệt khi vượt). |
| `dmag_dda` | 10 trụ cột DDA (T1 là điểm liệt). Phiếu chấm tự chấm / Genba. Hội đồng phán quyết → cập nhật PK, chặng, cờ đỏ T1 vào hồ sơ phòng khám. **Radar 4 lớp** (xem trên form và in PDF). **Đơn kê lộ trình**: tự gợi ý module × hình thức từ khoảng thiếu, kẹp theo phân khúc, chặn khi có cờ đỏ T1 → tạo báo giá. Báo giá cọc DDA. |
| `dmag_delivery` | Khi xác nhận đơn bán có module, hệ thống tự sinh **lộ trình triển khai**. Tự học / Học có hướng dẫn: ghi danh khoá eLearning, có buổi nhóm. Kèm 1:1: gói buổi, lịch và biên bản. Thực địa: Project gồm kickoff + Sprint. **Pulse Xanh/Vàng/Đỏ** chạy hằng ngày (trễ hạn, nợ quá hạn, im lặng, chậm tiến độ) và chỉ giao việc khi có cờ. Nhắc và tạo **DDA lần 2** ở mốc ngày 90. |
| `dmag_commission` | Chính sách hoa hồng gán theo **từng người** (có thể ghi đè tỷ lệ riêng). **Chỉ tính khi tiền đã về và đối soát vào hoá đơn**, trên số chưa VAT. Chia người chốt / người chăm lead / Account Owner. Huỷ đối soát thì tự trừ lại. Bảng kê tháng có hệ số theo % mục tiêu thực thu, đi qua xác nhận → duyệt → **đẩy sang lương** hạng mục `HOA_HONG`. |

Thứ tự phụ thuộc: `dmag_crm` → `dmag_dda` → (`dmag_delivery`, `dmag_commission`).

## Chạy demo

```bash
# Odoo 19.0 + PostgreSQL. Thêm thư mục addons của repo này vào addons_path.
odoo-bin -c odoo.conf -d dmag_demo -i dmag_delivery,dmag_commission --with-demo --load-language=vi_VN
```

Dữ liệu mẫu gồm:
- 3 phòng khám giả định: PK3, PK1 có cờ đỏ T1, và một phòng khám mới.
- 2 hồ sơ DDA đã phán quyết, 1 đơn kê lộ trình.
- 1 lộ trình triển khai đủ 3 hình thức (kèm 1:1, học có hướng dẫn, thực địa).
- 1 khoản thu cọc DDA đã sinh hoa hồng và bảng kê tháng.

Muốn dùng sơ đồ tài khoản và tiền tệ Việt Nam, cài `base`, đặt quốc gia công ty là Việt Nam với tiền tệ VND **trước** khi cài các module trên.

## Chạy test

```bash
odoo-bin -c odoo.conf -d dmag_test -i dmag_delivery,dmag_commission --with-demo \
  --test-enable --test-tags /dmag_crm,/dmag_dda,/dmag_delivery,/dmag_commission --stop-after-init
```

## Ảnh màn hình

Xem thư mục `docs/screenshots/`.

## Chưa có trong demo (bước tiếp)

- Tích hợp Stringee (`dmag_stringee`), Zalo OA/ZNS, Facebook Lead Ads / Ladipage, webhook ngân hàng SePay/Casso + VietQR, HĐĐT Viettel.
- Nối hoa hồng vào module lương thật: điểm nối là `_dmag_payroll_input_vals()`.
- Cổng khách hàng "DMAG Hub", dashboard ban điều hành, theme nhận diện DMAG.
- Pay-to-work (khoá quyền truy cập khi quá hạn thanh toán), AI (nháp Radar, tóm tắt cuộc gọi).
- Nhập dữ liệu từ các Google Sheets hiện tại.
