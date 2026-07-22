# Tuần 2 — Simulator & dữ liệu

## Trạng thái

Phần Business/AI đã triển khai simulator theo cấu hình 30 zone, 300 tài xế, tick 5 phút và forecast horizon 20 phút.

## Thành phần

- Driver generator phân bố xe theo demand weight và sinh pin ban đầu.
- Demand generator dùng Poisson, pattern giờ cao điểm, loại zone, cuối tuần, lễ và thời tiết.
- Event loop cập nhật busy/idle/charging, pin, matching và hủy request sau 10 phút.
- Zone Supply Tracker xuất đủ 30 zone mỗi tick, tách idle/incoming/outgoing.
- Acceptance generator sinh feature, xác suất ẩn và label Bernoulli có seed.
- CLI hỗ trợ run 1 ngày hoặc 56 ngày và ghi Parquet theo partition ngày.
- Validator kiểm tra schema, uniqueness, range và số zone mỗi tick.

## Kết quả run chuẩn

| Chỉ số | Giá trị |
|---|---:|
| Khoảng thời gian | 56 ngày từ 2026-01-05 |
| Seed | 20260717 |
| Demand events | 374.269 |
| Supply snapshots | 483.840 |
| Acceptance samples | 97.051 |
| Matched requests | 360.252 |
| Cancelled requests | 14.017 |
| Dung lượng output | Khoảng 9,11 MB |

Kết quả này là dữ liệu giả lập có kiểm soát, không phải dữ liệu vận hành GSM thật. `p_accept_ground_truth` chỉ dùng sanity check và không được đưa vào feature huấn luyện Acceptance Model.
