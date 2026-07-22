# Tuần 4 — Matching Engine + ràng buộc pin/trạm sạc + A/B testing

> Kết quả chạy `python -m ml.train_week4` (Cost Model + Matching Engine demo) và `python -m ml.ab_testing --multi-seed` (A/B test 10 seed) trên dữ liệu/simulator đã có từ Tuần 2-3. Code: `ml/cost_model.py`, `ml/matching_engine.py`, `ml/ab_testing.py`, và phần mở rộng trong `simulator/engine.py`.

## Trạng thái

| Deliverable Tuần 4 | Trạng thái |
|---|---|
| Cost Prediction Model, MAE trên tập test | ✅ Xong |
| Matching Engine 2 chế độ (Hungarian + ride-pooling) | ✅ Xong — demo trên batch thực tế |
| Ràng buộc pin/trạm sạc | ✅ Có trong Matching Engine (phạt pin thấp) + đã có sẵn trong simulator từ Tuần 1-2 |
| A/B testing 3 kịch bản trên simulator, đo 4 KPI | ✅ Xong — chạy thật trên simulator, không phải chỉ demo |
| OpenTelemetry tracing | ❌ Chưa làm — nợ Platform/Infra Track |
| Log Cost Prediction Model vào MLflow | ❌ Chưa làm — MLflow chưa setup (nợ từ Tuần 2) |

**Thay thế:** `LightGBM/XGBoost` → `HistGradientBoostingRegressor` (lý do giống Tuần 3 — lỗi cài đặt). `OpenRouteService` (routing thật) không có API key trong môi trường này → Cost Prediction Model train trên **dataset route-cost giả lập có seed**, đúng như `report.md` đã ghi rõ ý định ("khi train dùng route cost giả lập có seed"), không phải một sự thay thế ngoài kế hoạch.

## 1. Cost Prediction Model

Dataset: 40.000 chuyến giả lập (origin/destination zone ngẫu nhiên theo `base_demand_weight`, giờ/thứ/thời tiết ngẫu nhiên). Nhãn `duration_minutes` sinh từ quãng đường × hệ số tắc đường theo giờ × hệ số thời tiết, **kết hợp phi tuyến tính** (`(traffic_factor × weather_multiplier) ^ 1.3`) đúng yêu cầu report.md — mưa giờ cao điểm tệ hơn hẳn tổng of 2 hiệu ứng cộng lại.

| | MAE (test) |
|---|---:|
| Baseline tuyến tính thuần (chỉ quãng đường/tốc độ cố định) | 9,53 phút |
| **Cost Prediction Model (HistGradientBoostingRegressor)** | **4,61 phút** |

Model học được đúng hiệu ứng phi tuyến giờ cao điểm × thời tiết mà công thức tuyến tính cố định (`w1×distance+w2×wait+w3×battery`) không thể nắm bắt — giảm gần 52% sai số so với baseline.

## 2. Matching Engine

### Cơ chế chọn chế độ

`should_use_pooling(weather, hour, system_deficit)` — bật ride-pooling khi mưa **hoặc** giờ cao điểm (7-9h, 17-19h) **hoặc** deficit hệ thống vượt ngưỡng, đúng điều kiện report.md. Test: 18h + mưa → `True`; 13h + nắng → `False`.

### Chế độ 1-1 (Hungarian Algorithm)

Batch 40 request thật (lấy từ `drivers_final.json`, 209 tài xế idle) → **40/40 ghép được**, chi phí dự đoán trung bình 5,61 phút/chuyến. Ràng buộc pin: tài xế pin thấp bị phạt chi phí nặng cho cuốc xa (>10 phút dự đoán) thay vì cấm hẳn — vẫn nhận được cuốc ngắn gần đó.

### Chế độ ride-pooling (insertion heuristic)

Cùng 40 request, kịch bản 18h + mưa → **40/40 được phục vụ nhưng chỉ dùng 27 tài xế** (thay vì 40 nếu ghép 1-1), trong đó **9 tài xế phục vụ từ 2 khách trở lên** trong cùng chuyến. Đúng cơ chế insertion: mỗi request thử chèn vào tuyến tài xế gần đó tại mọi vị trí hợp lệ (giữ đúng thứ tự đón trước-trả sau, không vượt `vehicle_capacity=4`, detour ≤ 20% so với đi riêng), chọn phương án tăng chi phí ít nhất; không chèn được thì mới cấp tài xế mới.

**Lưu ý hiệu năng:** bản đầu tiên gọi Cost Prediction Model riêng cho từng cặp tài xế-khách/mỗi vị trí chèn → hàng chục nghìn lệnh gọi `model.predict()`, bị timeout. Sửa bằng cách áp dụng đúng gợi ý cache của report.md ("gọi theo cặp zone-to-zone... cache kết quả"): tính trước bảng chi phí cho toàn bộ 30×30 cặp zone trong **1 lệnh gọi batch**, sau đó chỉ tra bảng — nhanh tức thì.

## 3. A/B Testing — chạy thật trên simulator, không chỉ demo

Khác với Tuần 3 (demo Repositioning Suggester trên 1 snapshot tĩnh), Tuần 4 **nối thẳng Repositioning Suggester vào vòng lặp chính của simulator** (`simulator/engine.py`, method mới `_reposition_drivers` + trạng thái tài xế `incoming` mà `supply_tracker.py` đã có sẵn field chờ từ Tuần 2 nhưng chưa ai dùng tới) — đây là lý do 3 scenario code (`A_PASSIVE`/`B_REPOSITION_NO_RESERVE`/`C_REPOSITION_SOFT_RESERVE`) đã có sẵn trong `simulation_config.json` từ đầu dự án. Mặc định `scenario="A_PASSIVE"` giữ **nguyên hành vi cũ** — đã xác nhận lại 56 ngày dữ liệu Tuần 2 ra đúng số cũ (374.269 request...) sau khi sửa code.

Chạy 7 ngày × 3 kịch bản × **10 seed** (đã cấu hình sẵn trong `experiments.ab_test_seeds`) để tránh kết luận sai do nhiễu ngẫu nhiên:

| KPI | A_PASSIVE | B_NO_RESERVE | C_SOFT_RESERVE |
|---|---:|---:|---:|
| Thời gian chờ khách TB (giây) | 8,86 | **6,45** | 6,59 |
| Tỷ lệ hủy cuốc (%) | 4,05% | **2,58%** | 2,65% |
| Deadhead/tài xế (m) | 228.467 | 246.486 | **242.728** |
| Độ lệch chuẩn tỷ lệ cung/cầu | 5,45 | 4,34 | **4,50** |
| Số lượt điều xe/7 ngày | 0 | 6.680 | **5.955** (-11%) |

*(Số liệu đầy đủ + độ lệch chuẩn giữa các seed: `data/ab_test_multiseed/ab_test_summary_multi_seed.csv`)*

### Nhận định trung thực

**Có repositioning (B hoặc C) tốt hơn hẳn không có (A):** giảm ~27% thời gian chờ, ~36% tỷ lệ hủy cuốc, giảm mất cân bằng cung/cầu — chứng minh rõ giá trị của Repositioning Suggester nói chung, nhất quán qua cả 10 seed (không phải may rủi).

**Nhưng B vs C — kết quả không ủng hộ tuyệt đối cơ chế chống herding như kỳ vọng ban đầu:** B (không chống herding) có wait/cancellation **nhỉnh hơn một chút** so với C (6,45s/2,58% vs 6,59s/2,65%), ngược lại C có deadhead thấp hơn (242.728m vs 246.486m) và **dùng ít lượt điều xe hơn 11%** (5.955 vs 6.680) để đạt kết quả tương đương. Đây là đánh đổi thật, không phải "C thắng tuyệt đối":

- **Chống herding (C) hiệu quả hơn** — đạt kết quả khách hàng gần tương đương B nhưng tốn ít tài nguyên hơn (ít điều xe hơn, ít deadhead hơn).
- **B có thêm một "lớp đệm" tự nhiên** — vì không trừ số xe đang di chuyển ra khỏi deficit, hệ thống vô tình gửi dư thêm tài xế mỗi tick, tạo dư thừa giúp chống lại sai số dự báo demand ngẫu nhiên — nhưng phải trả giá bằng lượt điều xe và deadhead nhiều hơn.

Nói cách khác: cơ chế chống herding **đúng như thiết kế** (giảm số lượt điều xe dư thừa — đúng mục đích chống "dồn xe"), nhưng lợi ích đó thể hiện rõ nhất ở **hiệu quả vận hành** (ít deadhead, ít lượt điều xe hơn cho cùng kết quả), chứ không phải luôn luôn cho KPI khách hàng tốt hơn tuyệt đối trong mọi phép đo. Đây là kết quả trung thực từ 10 lần chạy, không phải cố ép cho khớp giả thuyết ban đầu.

**Giới hạn của phép so sánh:** vì `_reposition_drivers` tiêu tốn thêm số lần gọi RNG so với `A_PASSIVE`, dòng demand thực tế giữa 3 kịch bản không hoàn toàn giống hệt nhau dù cùng seed (generated_requests lệch nhau ~1%) — đã giảm thiểu ảnh hưởng bằng cách lấy trung bình 10 seed thay vì 1, nhưng đây vẫn là giới hạn cần nêu rõ, không phải một thí nghiệm có kiểm soát tuyệt đối.

## Việc còn thiếu trước khi coi Tuần 4 hoàn thành

- [ ] OpenTelemetry tracing (Platform/Infra Track) — chưa làm.
- [ ] Log Cost Prediction Model vào MLflow — chặn bởi việc MLflow chưa setup từ Tuần 2.
- [ ] Matching Engine (Hungarian/ride-pooling) mới chạy demo trên 1 batch tĩnh, **chưa nối vào vòng lặp multi-day của simulator** như Repositioning Suggester đã làm — nếu muốn đo ảnh hưởng của chế độ matching lên KPI dài hạn (thay vì chỉ ảnh hưởng của repositioning) thì cần làm thêm.
