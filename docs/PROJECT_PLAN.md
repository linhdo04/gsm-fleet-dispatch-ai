# Kế hoạch 6 tuần: AI Điều Phối Đội Xe cho GSM (Xanh SM)

## Vấn đề cần giải quyết

Hãng gọi xe điện như Xanh SM phải điều phối hàng nghìn xe sao cho xe có mặt đúng nơi có nhu cầu, nhưng cung-cầu lệch theo giờ/khu vực khiến:

- **Nơi thiếu xe:** khách chờ lâu, hủy chuyến.
- **Nơi thừa xe:** tài xế chờ không, tốn pin.

**Bài toán: AI điều phối đội xe**, gồm các thành phần:

- Dự báo nhu cầu theo khu vực và thời điểm.
- Gợi ý tài xế di chuyển đến vùng sắp có nhu cầu cao _trước khi_ nhu cầu xảy ra.
- Tối ưu ghép chuyến và phân bổ xe.
- Cân nhắc trạng thái pin và trạm sạc.
- Giải thích gợi ý cho tài xế bằng ngôn ngữ tự nhiên.

**Mục tiêu:** Giảm thời gian chờ của khách và tăng thu nhập tài xế qua phân bổ thông minh.

## Team & phân chia vai trò (2 người)

| Track                    | Phạm vi công việc                                                                                                         |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| **Business/AI Track**    | Simulator, Forecast Engine, Repositioning Suggester (+ chống herding), Matching Engine, NLG Explainer, giao diện demo     |
| **Platform/Infra Track** | Docker/Docker Compose, CI/CD (GitHub Actions), OpenTelemetry tracing, Prometheus/Grafana, MLflow, DVC, structured logging |

## Kiến trúc tổng thể

```
[Simulator/Data] → [Forecast Engine] → [Repositioning Suggester + Supply Tracker]
                                              ↓
                                      [Matching Engine] → [NLG Explainer] → [Dashboard/Map UI]
```

**5 module chính:**

1. **Forecast Engine** — dự báo nhu cầu theo zone/thời điểm (ML: Prophet/XGBoost).
2. **Repositioning Suggester + Supply Tracker** — gợi ý tài xế di chuyển, có cơ chế chống dồn xe (herding); xếp hạng tài xế bằng **Acceptance Probability Model** (ML) thay vì chỉ theo khoảng cách.
3. **Matching Engine** — ghép tài xế-khách tối ưu (batch matching bằng Hungarian Algorithm), cost matrix được tính từ **Cost Prediction Model** (ML) thay vì công thức tuyến tính cố định; ràng buộc pin/trạm sạc.
4. **NLG Explainer** — sinh giải thích gợi ý bằng ngôn ngữ tự nhiên (dùng LLM API).
5. **CI/CD & Observability**
   - Containerize toàn bộ hệ thống (Backend & Frontend).
   - CI/CD tự động bằng GitHub Actions.
   - Thu thập metrics, logs, traces bằng OpenTelemetry.
   - Giám sát API, Forecast Engine và Matching Engine bằng Prometheus + Grafana.
   - Theo dõi chất lượng model.

**3 model ML trong project (để phân biệt rõ với phần thuật toán tối ưu/rule-based thuần túy):**

| Model                                                                    | Mục đích                                                                                                                                 | Dùng ở module           |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| **Demand Forecast Model** (Prophet/XGBoost)                              | Dự báo nhu cầu theo zone/thời điểm                                                                                                       | Forecast Engine         |
| **Acceptance Probability Model** (Logistic Regression/Gradient Boosting) | Dự đoán khả năng tài xế chấp nhận & hoàn thành tốt nếu được gợi ý đến 1 zone, dựa trên khoảng cách, pin, lịch sử chấp nhận gợi ý         | Repositioning Suggester |
| **Cost Prediction Model** (Gradient Boosting/LightGBM)                   | Dự đoán chi phí di chuyển thực tế (thời gian/quãng đường hiệu chỉnh theo traffic + thời tiết) để tạo cost matrix cho Hungarian Algorithm | Matching Engine         |

> **Lưu ý về khoảng cách:** dùng **routing thực tế qua OpenRouteService API** (quãng đường + thời gian di chuyển theo road network thật, không phải đường chim bay) làm input cho Cost Prediction Model. OpenRouteService có gói miễn phí (2.000 request/ngày), không cần tự host, phù hợp quy mô 6 tuần.

**Tech stack đề xuất:**

- Backend: Python (FastAPI)
- Forecast: Prophet hoặc XGBoost
- Acceptance Probability Model: scikit-learn (Logistic Regression) hoặc LightGBM
- Cost Prediction Model: LightGBM/XGBoost
- Matching: scipy (Hungarian Algorithm / `linear_sum_assignment`)
- Frontend: React + Leaflet (bản đồ)
- NLG: Claude/GPT API
- Data thời tiết: OpenWeatherMap API (thật); traffic/ngày lễ: rule-based/giả lập
- Routing: OpenRouteService API (miễn phí, 2.000 request/ngày) — tính quãng đường/thời gian theo road network thật, dùng làm feature cho Cost Prediction Model; nên cache kết quả theo cặp zone để tránh gọi lại API nhiều lần
- Containerization: Docker + Docker Compose
- CI/CD: GitHub Actions
- Monitoring: Prometheus + Grafana
- Telemetry: OpenTelemetry
- Logging: Structlog hoặc Python logging
- Model Registry: MLflow

---

## Tuần 1 — Thiết kế bài toán & kiến trúc hệ thống

**Mục tiêu:** Chốt đặc tả bài toán, kiến trúc, và cơ chế chống herding trước khi code.

**Business/AI Track:**

- Chia bản đồ Hà Nội thành lưới zone (20–30 zone, dùng H3/geohash hoặc lưới vuông đơn giản).
- Định nghĩa dữ liệu:
  - Driver: vị trí, % pin, trạng thái (`idle` / `incoming` / `busy` / `charging`)
  - Rider request: zone, thời điểm
  - Context: giờ, thời tiết, ngày lễ
- Định nghĩa công thức cốt lõi:
  - `predicted_supply[zone, t] = idle_drivers + incoming_drivers − outgoing_drivers`
  - `deficit[zone, t] = predicted_demand[zone, t] − predicted_supply[zone, t]`
- Thiết kế cơ chế **soft-reserve**: khi gợi ý 1 tài xế → zone X, cập nhật ngay `incoming_drivers[X] += 1` để lần tính kế tiếp không tiếp tục dồn thêm tài xế vào X.
- Chọn nguồn dữ liệu: thời tiết dùng API thật; traffic + ngày lễ dùng rule-based/giả lập (nêu rõ lý do đơn giản hóa có chủ đích).

**Platform/Infra Track:**

- Dựng khung repo (tách rõ backend/frontend/service).
- Viết Dockerfile cơ bản (backend + frontend, dù nội dung service còn rỗng).
- Setup CI pipeline (GitHub Actions) chạy được, dù chưa có nhiều để test/build.
- Thống nhất với Business/AI Track về interface/contract dữ liệu giữa các module.

**Deliverable:**

- Tài liệu đặc tả bài toán (problem statement)
- Sơ đồ kiến trúc hệ thống (5 module + data flow)
- Sơ đồ cơ chế chống herding
- Repo khởi tạo với Dockerfile cơ bản (backend + frontend) và pipeline CI rỗng (GitHub Actions chạy được)

---

## Tuần 2 — Simulator & dữ liệu

**Mục tiêu:** Có dữ liệu giả lập đủ thực tế để forecast học được pattern.

**Business/AI Track:**

- Xây simulator sinh dữ liệu có pattern thời gian:
  - Giờ cao điểm: 7–9h, 17–19h
  - Cuối tuần vs ngày thường
  - Ngày lễ VN (bảng lịch rule-based)
  - Thời tiết (gọi API thật hoặc chọn kịch bản: nắng/mưa)
- Sinh demand theo zone có seasonality + nhiễu ngẫu nhiên (Poisson process), cầu tăng đột biến ở zone đặc thù (sân bay, trung tâm) vào giờ lễ/mưa.
- Xây **Zone Supply Tracker**: module theo dõi số xe `idle` / `incoming` / `outgoing` theo từng zone ở mỗi tick thời gian.
- Sinh thêm dữ liệu giả lập **lịch sử chấp nhận gợi ý của tài xế** (mỗi lần simulator gợi ý tài xế → zone, gán nhãn "chấp nhận/từ chối" theo rule hợp lý: khoảng cách càng xa, pin càng thấp → xác suất chấp nhận càng giảm) — dùng làm tập train cho Acceptance Probability Model ở tuần 3.

**Platform/Infra Track:**

- Hoàn thiện Docker Compose cho toàn bộ stack (simulator + các service rỗng).
- CI pipeline build & chạy lint/test cơ bản mỗi lần push.
- Setup MLflow tracking server (sẵn sàng nhận log ở tuần 3).

**Deliverable:**

- Simulator chạy được, log ra trạng thái cung-cầu theo zone theo thời gian (dạng bảng/JSON theo tick)
- Docker Compose chạy được toàn bộ stack, CI pipeline hoạt động ổn định
- MLflow tracking server sẵn sàng

---

## Tuần 3 — Forecast Engine + Repositioning Suggester (có chống herding)

**Mục tiêu:** Dự báo được nhu cầu và sinh gợi ý điều xe mà không gây dồn xe quá tay.

**Business/AI Track:**

- Xây model dự báo demand theo zone:
  - Model: Prophet hoặc XGBoost
  - Feature: giờ, thứ trong tuần, thời tiết, ngày lễ, zone
  - Đánh giá: MAE/RMSE trên tập test giả lập
- Train **Acceptance Probability Model** (Logistic Regression/Gradient Boosting):
  - Feature: khoảng cách từ tài xế đến zone, % pin, giờ, lịch sử chấp nhận gợi ý trước đó của tài xế
  - Label: chấp nhận/từ chối (từ dữ liệu giả lập tuần 2)
  - Output: `p_accept(driver, zone)` — xác suất tài xế chấp nhận & di chuyển thành công đến zone
  - Đánh giá: accuracy/AUC trên tập test
- Xây thuật toán Repositioning Suggester (dùng `p_accept` để xếp hạng thay vì chỉ khoảng cách, có kiểm soát dồn xe):

```
for mỗi zone có deficit > 0 (ưu tiên deficit cao trước):
    so_can_goi_y = deficit[zone]
    chọn top-N tài xế idle có p_accept(driver, zone) cao nhất + đủ pin
    với mỗi tài xế được chọn:
        gợi ý di chuyển đến zone
        incoming_drivers[zone] += 1   # soft-reserve
        deficit[zone] = predicted_demand[zone] - predicted_supply[zone]  # tính lại ngay
        nếu deficit <= 0 → dừng, sang zone tiếp theo
```

- Cho phép bật/tắt cơ chế chống herding để so sánh sau này.

**Platform/Infra Track:**

- Tích hợp MLflow logging vào Forecast Engine ngay khi Business/AI Track code xong phần train model (làm việc chung, review nhau).
- Log model version + metrics (MAE/RMSE) vào MLflow.

**Deliverable:**

- Module Forecast + Suggester chạy end-to-end
- Biểu đồ dự báo vs thực tế (đánh giá độ chính xác)
- Acceptance Probability Model train xong, có accuracy/AUC trên tập test
- Model version + metrics (MAE/RMSE, accuracy/AUC) được log vào MLflow

---

## Tuần 4 — Matching Engine + ràng buộc pin/trạm sạc + A/B testing

**Mục tiêu:** Hoàn thiện luồng dispatch thực tế và chứng minh giá trị bằng số liệu.

**Business/AI Track:**

- Train **Cost Prediction Model** (LightGBM/XGBoost):
  - Feature: quãng đường/thời gian di chuyển thực tế từ OpenRouteService API (routing theo road network, không phải chim bay), giờ, zone, thời tiết, mức tắc đường (traffic factor)
  - Label: thời gian di chuyển thực tế (giả lập có nhiễu, phản ánh traffic/thời tiết ảnh hưởng phi tuyến tính)
  - Output: `predicted_cost(driver, rider)` — dùng thay cho công thức tuyến tính cố định `w1×distance + w2×wait + w3×battery`
  - Đánh giá: MAE trên tập test
- Xây Matching Engine: batch matching bằng Hungarian Algorithm (`scipy.optimize.linear_sum_assignment`), cost matrix được điền bằng `predicted_cost` từ model trên (không phải công thức tay), cộng thêm battery penalty như ràng buộc.
- Gọi OpenRouteService theo cặp **zone-to-zone** (centroid mỗi zone) thay vì theo từng cặp tài xế-khách riêng lẻ, rồi cache kết quả (20–30 zone → tối đa ~900 cặp, chỉ cần gọi 1 lần và refresh định kỳ) để không vượt giới hạn 2.000 request/ngày.
- Ràng buộc:
  - Pin thấp (< ngưỡng) → không nhận cuốc xa
  - Tài xế pin thấp → ưu tiên gợi ý về trạm sạc gần nhất thay vì repositioning đi xa
- Chạy A/B testing trên simulator với 3 kịch bản:
  1. Không có repositioning (chỉ matching phản ứng thụ động)
  2. Có repositioning nhưng KHÔNG chống herding
  3. Có repositioning + CÓ chống herding
- Đo metric cho từng kịch bản:
  - Thời gian chờ khách trung bình
  - Tỷ lệ hủy cuốc
  - Quãng đường chạy rỗng (deadhead) của tài xế
  - **Độ lệch chuẩn tỷ lệ cung/cầu giữa các zone theo thời gian** (đo mức mất cân bằng do chính hệ thống gây ra)

**Platform/Infra Track:**

- Thêm OpenTelemetry tracing cho luồng request chính (forecast → suggester → matching), để đo latency từng bước phục vụ A/B testing.
- Phối hợp chặt với Business/AI Track ở tuần này vì tracing cần hiểu rõ luồng nghiệp vụ.

**Deliverable:**

- Bảng so sánh KPI của 3 kịch bản, chứng minh rõ giá trị của cơ chế chống herding
- Cost Prediction Model train xong, có MAE trên tập test, đã log vào MLflow
- OpenTelemetry tracing hoạt động, đo được latency từng bước trong luồng chính

---

## Tuần 5 — NLG Explainer + Giao diện demo

**Mục tiêu:** Có sản phẩm demo trực quan, tương tác được.

**Business/AI Track:**

- Tích hợp Claude/GPT API cho NLG:
  - Input: dữ liệu có cấu trúc, ví dụ:
    ```json
    {
      "zone": "Cầu Giấy",
      "predicted_demand_change": "+40% trong 20 phút tới",
      "reason": "giờ tan tầm + trời mưa",
      "suggested_action": "di chuyển đến Cầu Giấy"
    }
    ```
  - Output: câu giải thích tự nhiên cho tài xế
- Xây giao diện (React + Leaflet):
  - Bản đồ: heatmap zone theo mức thiếu/thừa xe, icon tài xế theo trạng thái (idle/incoming/busy)
  - **Vẽ đường đi thực tế của tài xế lên map** (route theo road network, không phải đường thẳng): khi có gợi ý repositioning hoặc match, gọi OpenRouteService Directions API cho đúng cặp điểm đi/đến (vị trí tài xế → điểm đến), lấy geometry (GeoJSON/polyline) trong response, decode và vẽ bằng `Polyline`/`GeoJSON` layer của Leaflet
  - Panel gợi ý kèm giải thích tự nhiên
  - Dashboard so sánh KPI real-time (3 kịch bản tuần 4)
  - Nút chọn kịch bản: ngày thường / mưa / giờ cao điểm / ngày lễ

**Platform/Infra Track:**

- Dựng Prometheus + Grafana dashboard theo dõi API latency, forecast/matching engine metrics.

**Deliverable:**

- Web app demo hoàn chỉnh, đổi kịch bản trực tiếp và thấy hệ thống phản ứng ngay
- Bản đồ hiển thị đường đi thực tế (route) của tài xế theo road network, không phải đường chim bay
- Prometheus + Grafana dashboard hiển thị metric hệ thống và model

---

## Tuần 6 — Kiểm thử, hoàn thiện, báo cáo

**Mục tiêu:** Đóng gói sản phẩm, chuẩn bị bảo vệ/demo.

**Cả 2 người:**

- Kiểm thử kịch bản khắc nghiệt: mưa + giờ cao điểm + nhiều zone thiếu cùng lúc → kiểm tra cơ chế chống herding có ổn định không.
- Viết báo cáo gồm:
  - Problem statement
  - Kiến trúc hệ thống
  - Phương pháp: forecast, repositioning + chống herding, matching, NLG
  - Kết quả so sánh định lượng (bảng KPI 3 kịch bản)
  - Phần hạ tầng: CI/CD, Observability, MLflow — mỗi người viết phần mình phụ trách
  - Giới hạn: đây là proof-of-concept trên dữ liệu giả lập, chưa phải hệ thống production
  - Hướng phát triển: reinforcement learning cho repositioning, tích hợp dữ liệu thật từ GSM, VRP đầy đủ cho ghép chuyến, tự host OSRM để bỏ giới hạn rate-limit của OpenRouteService khi scale lên nhiều xe/khách hơn
- Chuẩn bị slide + kịch bản demo trực tiếp: chạy "ngày thường" → chuyển sang "mưa + lễ" → cho thấy dự báo, gợi ý điều xe, tránh dồn xe, và giải thích tự nhiên, tất cả trên 1 màn hình.

**Deliverable:**

- Sản phẩm hoàn chỉnh + báo cáo + slide + kịch bản demo

---

## Rủi ro & cách xử lý

| Rủi ro                                                                                                     | Cách xử lý                                                                                                                                                                                                                                                                                                                                        |
| ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Forecast model không đủ chính xác vì dữ liệu giả lập                                                       | Thiết kế simulator có seasonality rõ ràng để model dễ học; nêu rõ trong báo cáo đây là dữ liệu giả lập có kiểm soát                                                                                                                                                                                                                               |
| Khối lượng công việc lớn (5 module trong 6 tuần)                                                           | Ưu tiên làm luồng chính chạy end-to-end trước, tối ưu từng module sau; NLG là module độc lập nhất, có thể cắt/rút gọn nếu tuần 5 bị chậm tiến độ                                                                                                                                                                                                  |
| Thuật toán repositioning + chống herding phức tạp hơn dự kiến                                              | Bắt đầu với rule-based đơn giản (tuần 3), chỉ nâng cấp thêm nếu còn dư thời gian                                                                                                                                                                                                                                                                  |
| Acceptance Probability Model / Cost Prediction Model không đủ chính xác vì dữ liệu giả lập                 | Thiết kế rule sinh nhãn (chấp nhận/từ chối, thời gian di chuyển thực) có logic rõ ràng, đủ tín hiệu để model học được; nêu rõ trong báo cáo đây là giả lập có kiểm soát, không phải hành vi tài xế/traffic thật                                                                                                                                   |
| Tăng thêm 2 model (Acceptance, Cost Prediction) có thể làm tuần 3-4 quá tải                                | Đây là các model nhỏ (Logistic Regression/LightGBM), train nhanh trên tập dữ liệu giả lập, không tốn nhiều thời gian tune như Forecast Engine; nếu vẫn chậm, có thể lùi Cost Prediction Model sang dùng rule-based factor tạm và bổ sung sau nếu còn thời gian                                                                                    |
| Không có dữ liệu thật từ GSM                                                                               | Xác nhận sớm với mentor việc dùng dữ liệu giả lập có được chấp nhận; giải thích rõ trong báo cáo đây là giả định có chủ đích                                                                                                                                                                                                                      |
| Điểm nghẽn khi tích hợp 2 track (Platform/Infra Track cần API/output thật từ Business/AI Track)            | Đồng bộ interface/contract dữ liệu ngay từ tuần 1; daily sync ngắn, đặc biệt chặt ở tuần 3-4                                                                                                                                                                                                                                                      |
| MLflow/OpenTelemetry cần thời gian làm quen nếu Platform/Infra Track chưa dùng qua                         | Xác nhận sớm mức độ quen thuộc của Platform/Infra Track với 2 công cụ này; nếu chưa quen, học trước ở tuần 1 song song lúc Business/AI Track thiết kế bài toán                                                                                                                                                                                    |
| OpenRouteService giới hạn 2.000 request/ngày, có thể không đủ nếu gọi trực tiếp theo từng cặp tài xế-khách | Tách 2 loại nhu cầu: (1) cost matrix cho Matching Engine → gọi theo cặp zone-to-zone (centroid), cache + refresh định kỳ, không gọi theo real-time driver/rider; (2) vẽ route lên map ở Tuần 5 → chỉ gọi Directions API cho các gợi ý/match đã được xác nhận (số lượng nhỏ hơn nhiều so với toàn bộ ma trận), không gọi cho mọi cặp có thể xảy ra |
| OpenRouteService downtime/lỗi API ảnh hưởng luồng chính                                                    | Có fallback: nếu API lỗi, tạm dùng đường chim bay × hệ số hiệu chỉnh (ví dụ ×1.3) cho tick đó, log lại để không chặn luồng dispatch                                                                                                                                                                                                               |

---

## Nguồn dữ liệu

| Loại dữ liệu                                      | Nguồn                                                                               |
| ------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Thời tiết                                         | OpenWeatherMap API hoặc Open-Meteo (miễn phí)                                       |
| Ngày lễ VN                                        | Rule-based tự lập hoặc thư viện `holidays` (Python)                                 |
| Ranh giới zone Hà Nội                             | OpenStreetMap (Overpass API)                                                        |
| POI (sân bay, trung tâm thương mại...)            | OpenStreetMap, Google Places API                                                    |
| Traffic pattern                                   | Rule-based, tự thiết kế hệ số theo giờ/khu vực (tham khảo trực quan từ Google Maps) |
| Routing (quãng đường/thời gian theo road network) | OpenRouteService API (miễn phí, 2.000 request/ngày)                                 |
| Dữ liệu vận hành (tài xế, khách, cuốc xe)         | Tự sinh (synthetic) bằng simulator, calibrate quy mô theo số liệu công khai của GSM |

---

## Giá trị dự án chứng minh được (đầu ra định lượng)

> **Lưu ý:** các con số dưới đây là **kỳ vọng ước tính** (tham khảo từ các nghiên cứu/case study dispatch optimization trong ride-hailing), dùng làm mục tiêu để so sánh khi chạy A/B testing ở Tuần 4 — không phải kết quả đã đo thật. Kết quả thật sẽ thay số này vào báo cáo cuối (Tuần 6).

| Metric                                                                          | Kỳ vọng ước tính (so với kịch bản không repositioning)                                                                           |
| ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Thời gian chờ khách trung bình                                                  | Giảm **15–25%**                                                                                                                  |
| Tỷ lệ cuốc bị hủy/không tìm được tài xế (đặc biệt kịch bản mưa/lễ/giờ cao điểm) | Giảm **20–35%**                                                                                                                  |
| Quãng đường chạy rỗng (deadhead) của tài xế                                     | Giảm **20–30%** → tiết kiệm chi phí vận hành/pin                                                                                 |
| Độ lệch chuẩn tỷ lệ cung/cầu giữa các zone theo thời gian                       | Giảm **10–20%** so với kịch bản có repositioning nhưng KHÔNG chống herding → chứng minh cơ chế chống herding thực sự có tác dụng |
| Rủi ro xe hết pin giữa chuyến (số ca vi phạm ngưỡng pin)                        | Giảm **về gần 0** nhờ ràng buộc pin trong Matching Engine                                                                        |

- Thể hiện được 3 model ML phối hợp trong 1 hệ thống thực tế (Forecast, Acceptance Probability, Cost Prediction) kết hợp cùng thuật toán tối ưu hóa cổ điển (Hungarian) — đúng mô hình kết hợp ML + Operations Research phổ biến trong ngành ride-hailing thật

---

## Hiệu năng hệ thống kỳ vọng (Latency)

> **Lưu ý:** đây là **ước tính kỹ thuật** dựa trên đặc điểm thuật toán/model đã chọn, dùng làm mục tiêu (SLO tạm thời) để đối chiếu với số đo thật từ OpenTelemetry tracing + Prometheus/Grafana ở Tuần 4-5 — không phải benchmark đã chạy.

| Thành phần                                                                               | Latency kỳ vọng   | Ghi chú                                                                                                         |
| ---------------------------------------------------------------------------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------- |
| Forecast Engine (dự báo demand cho 20–30 zone/batch)                                     | 100–500ms         | Prophet thường chậm hơn XGBoost; nếu Prophet không đạt mục tiêu, ưu tiên XGBoost                                |
| Acceptance Probability Model (inference/cặp driver-zone)                                 | <20ms             | Logistic Regression/LightGBM nhỏ, rất nhanh                                                                     |
| Cost Prediction Model (inference/cặp driver-rider)                                       | <20ms             | Tương tự, model nhỏ, không phải bottleneck                                                                      |
| Matching Engine — Hungarian Algorithm (`scipy.linear_sum_assignment`, ma trận ~50×50)    | <200ms            | Độ phức tạp O(n³); tăng nhanh nếu số tài xế/khách cùng lúc lớn hơn nhiều                                        |
| OpenRouteService API call (bên ngoài, mỗi request)                                       | 200–800ms         | Phụ thuộc mạng/dịch vụ ngoài — lý do phải cache zone-to-zone thay vì gọi trực tiếp cho cost matrix              |
| Luồng chính end-to-end (forecast → suggester → matching, chưa tính NLG/routing hiển thị) | Mục tiêu <1s      | Đo bằng OpenTelemetry trace từng bước, là số liệu chính để báo cáo Tuần 4                                       |
| NLG Explainer (gọi Claude/GPT API)                                                       | 1–3s              | Gọi bất đồng bộ, không chặn luồng dispatch chính; UI hiển thị trạng thái "đang tạo giải thích..." trong lúc chờ |
| Dashboard refresh (KPI real-time)                                                        | 1–5s/lần cập nhật | Polling hoặc WebSocket tùy cách Frontend triển khai                                                             |
