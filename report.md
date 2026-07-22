# Kế hoạch 6 tuần: AI Điều Phối Đội Xe cho GSM (Xanh SM)

## Vấn đề cần giải quyết

Hãng gọi xe điện như Xanh SM phải điều phối hàng nghìn xe sao cho xe có mặt đúng nơi có nhu cầu, nhưng cung-cầu lệch theo giờ/khu vực khiến:

- **Nơi thiếu xe:** khách chờ lâu, hủy chuyến.
- **Nơi thừa xe:** tài xế chờ không, tốn pin.

**Bài toán: AI điều phối đội xe**, gồm các thành phần:

- Dự báo nhu cầu theo khu vực và thời điểm.
- Gợi ý tài xế di chuyển đến vùng sắp có nhu cầu cao *trước khi* nhu cầu xảy ra.
- Ghép cặp tài xế-khách theo cascade (gán trực tiếp → ghép chuyến dùng chung nếu không đủ nhanh → chờ xe incoming → kích hoạt điều xe) để tối ưu phân bổ xe.
- Cân nhắc trạng thái pin và trạm sạc.
- Giải thích gợi ý cho tài xế bằng ngôn ngữ tự nhiên.

**Mục tiêu:** Giảm thời gian chờ của khách và tăng thu nhập tài xế qua phân bổ thông minh.

## Team & phân chia vai trò (2 người)

| Track | Phạm vi công việc |
|---|---|
| **Business/AI Track** | Simulator, Forecast Engine, Repositioning Suggester (+ chống herding), Matching Engine, NLG Explainer, giao diện demo |
| **Platform/Infra Track** | Docker/Docker Compose, CI/CD (GitHub Actions), OpenTelemetry tracing, Prometheus/Grafana, MLflow, structured logging |

> **Trạng thái triển khai thực tế**: khối **Platform/Infra Track** (Docker, CI/CD, MLflow, OpenTelemetry, Prometheus/Grafana) chưa được triển khai trong repo hiện tại — không có `Dockerfile`, `docker-compose.yml`, `.github/workflows/`, hay import `mlflow`/`opentelemetry` nào trong code. Khối **Business/AI Track** (simulator, 3 model ML, matching engine, frontend demo) đã chạy end-to-end và có artifact thật. Các mục Deliverable/tính năng bên dưới được đánh dấu ✅ (đã làm, có artifact) / ❌ (chưa làm, còn ở mức kế hoạch) theo đúng trạng thái này.


## Kiến trúc tổng thể

```
[Simulator/Data] → [Forecast Engine (ML)] → [Repositioning Suggester (ML) + Supply Tracker]
        → [Matching Engine] → [NLG Explainer (LLM)] → [Dashboard/Map UI]
```

**5 module chính:**
1. **Forecast Engine (ML)** — dự báo nhu cầu theo zone/thời điểm (Prophet/XGBoost).
2. **Repositioning Suggester (ML) + Supply Tracker** — gợi ý tài xế di chuyển, có cơ chế chống dồn xe (herding); xếp hạng tài xế bằng **Acceptance Probability Model** (ML) thay vì chỉ theo khoảng cách.
3. **Matching Engine** — mỗi request mới chạy qua cascade 4 bước (xem `docs/business_design.md` mục "Đặc tả luồng Matching & Repositioning"): (1) gán thẳng nếu có tài xế idle đủ gần (ETA nhanh), (2) không thì thử chèn vào tuyến ghép chuyến của tài xế đang chạy (**ride-pooling**, chấm điểm bằng **Cost Prediction Model**), (3) không chèn được thì kiểm tra xe `incoming` đã đủ bù chưa, (4) nếu chưa mới kích hoạt Repositioning Suggester. Không còn "chế độ toàn cục" bật/tắt theo mưa/giờ cao điểm như thiết kế trước — quyết định ghép-chuyến-hay-không diễn ra ở từng request. Ràng buộc pin/trạm sạc áp dụng xuyên suốt cascade.
4. **NLG Explainer (LLM)** — sinh giải thích gợi ý bằng ngôn ngữ tự nhiên.
5. **CI/CD & Observability**
   - Containerize toàn bộ hệ thống (Backend & Frontend).
   - CI/CD tự động bằng GitHub Actions.
   - Thu thập metrics, logs, traces bằng OpenTelemetry.
   - Giám sát API, Forecast Engine và Matching Engine bằng Prometheus + Grafana.
   - Theo dõi chất lượng model.

**3 model ML trong project (để phân biệt rõ với phần thuật toán tối ưu/rule-based thuần túy):**

| Model | Mục đích | Dùng ở module |
|---|---|---|
| **Demand Forecast Model** (Prophet/XGBoost) | Dự báo nhu cầu theo zone/thời điểm | Forecast Engine |
| **Acceptance Probability Model** (Logistic Regression/Gradient Boosting) | Dự đoán khả năng tài xế chấp nhận & hoàn thành tốt nếu được gợi ý đến 1 zone, dựa trên khoảng cách, pin, lịch sử chấp nhận gợi ý | Repositioning Suggester |
| **Cost Prediction Model** (Gradient Boosting/LightGBM) | Dự đoán chi phí di chuyển thực tế (thời gian/quãng đường hiệu chỉnh theo traffic + thời tiết) — dùng làm ETA cho bước gán trực tiếp và để chấm điểm chèn khách vào tuyến ghép chuyến | Matching Engine |


**Tech stack đề xuất:**
- Backend: Python (FastAPI)
- Forecast: Prophet hoặc XGBoost
- Acceptance Probability Model: scikit-learn (Logistic Regression) hoặc LightGBM
- Cost Prediction Model: LightGBM/XGBoost
- Matching: cascade tự viết theo `docs/business_design.md` (gán trực tiếp → chèn ghép chuyến → chờ incoming → kích hoạt repositioning), không dùng Hungarian Algorithm; insertion heuristic cho bước ghép chuyến (có thể dùng OR-Tools nếu cần tối ưu batch nhỏ)
- Frontend: React + Leaflet (bản đồ)
- NLG: Claude/GPT API
- Data thời tiết: OpenWeatherMap API (thật); traffic/ngày lễ: rule-based/giả lập
- Routing: Google Routes API — tính quãng đường/thời gian theo road network thật (traffic-aware ETA, polyline), dùng làm feature cho Cost Prediction Model; cache kết quả theo cặp zone để tránh gọi lại API nhiều lần
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
- ✅ Tài liệu đặc tả bài toán (problem statement) — `docs/business_design.md`
- ✅ Sơ đồ kiến trúc hệ thống (5 module + data flow)
- ✅ Sơ đồ cơ chế chống herding
- ❌ Repo khởi tạo với Dockerfile cơ bản (backend + frontend) và pipeline CI rỗng (GitHub Actions chạy được) — chưa triển khai, không có `Dockerfile`/`.github/workflows/` trong repo

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
- ✅ Simulator chạy được, log ra trạng thái cung-cầu theo zone theo thời gian (dạng bảng/JSON theo tick) — `data/generated/` (56 ngày, 374k requests, 300 tài xế, 30 zone)
- ❌ Docker Compose chạy được toàn bộ stack, CI pipeline hoạt động ổn định — chưa triển khai
- ❌ MLflow tracking server sẵn sàng — chưa triển khai, metrics hiện lưu trực tiếp ra JSON tĩnh (`ml/artifacts/*_metrics.json`) thay vì log vào MLflow

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
- ✅ Module Forecast + Suggester chạy end-to-end
- ✅ Biểu đồ dự báo vs thực tế (đánh giá độ chính xác) — `ml/artifacts/forecast_vs_actual.png`
- ✅ Acceptance Probability Model train xong, có accuracy/AUC trên tập test — `ml/artifacts/acceptance_model.joblib` + `acceptance_metrics.json`
- ❌ Model version + metrics (MAE/RMSE, accuracy/AUC) được log vào MLflow — chưa triển khai, metrics hiện chỉ lưu JSON tĩnh, không có version tracking

---

## Tuần 4 — Matching Engine + ràng buộc pin/trạm sạc + A/B testing

**Mục tiêu:** Hoàn thiện luồng dispatch thực tế và chứng minh giá trị bằng số liệu.

**Business/AI Track:**
- Train **Cost Prediction Model** (LightGBM/XGBoost):
  - Feature: khoảng cách/thời gian di chuyển (`ml/cost_model.py`), giờ, zone, thời tiết, mức tắc đường (traffic factor). **Cập nhật so với kế hoạch ban đầu**: dữ liệu train thực tế dùng công thức Haversine × 1.3 giả lập (`training_provider: synthetic_seeded_traffic`), **không gọi Google Routes API thật** — `GoogleRoutesClient` (`ml/routing_client.py`) chỉ dùng cho `demo_provider` (hiển thị demo/frontend), tách riêng khỏi pipeline training để tránh phụ thuộc/chi phí API khi train
  - Label: thời gian di chuyển thực tế (giả lập có nhiễu, phản ánh traffic/thời tiết ảnh hưởng phi tuyến tính)
  - Output: `predicted_cost(driver, rider)` — dùng thay cho công thức tuyến tính cố định `w1×distance + w2×wait + w3×battery`
  - Đánh giá: MAE trên tập test
- Xây Matching Engine theo cascade 4 bước cho mỗi request mới (đặc tả đầy đủ ở `docs/business_design.md`, mục "Đặc tả luồng Matching & Repositioning"):
  1. **Gán trực tiếp:** nếu có tài xế `idle` đủ gần (ETA ≤ ngưỡng cấu hình `eta_fast_threshold_seconds`), gán thẳng, kết thúc.
  2. **Chèn vào tuyến ghép chuyến (ride-pooling):** không thì thử chèn điểm đón/trả vào tuyến của tài xế đang chạy còn chỗ, tại mọi vị trí hợp lệ (không vượt `vehicle_capacity = 4`, đón trước trả, ETA đón/detour trong ngưỡng — ngưỡng siết lại khi trời mưa); chấm điểm bằng hàm chi phí có trọng số (`w1×wait_time + w2×extra_time_khách_cũ + w3×(1-fill_rate) + w4×detour_penalty`), `predicted_cost` lấy từ **Cost Prediction Model**; chọn phương án chi phí thấp nhất.
  3. **Chờ xe incoming:** không chèn được thì kiểm tra `expected_deficit` của zone đã ≤ 0 chưa (đã có đủ xe `incoming`/soft-reserve); nếu rồi thì xếp hàng đợi theo aging priority (chống đói khách gần mốc hủy 10 phút).
  4. **Kích hoạt Repositioning Suggester:** nếu vẫn còn thiếu, gọi `find_and_reserve_driver_for_zone()` — cùng hàm soft-reserve dùng chung với Luồng B (xử lý tài xế idle) để tránh viết trùng logic.
  - Không còn khái niệm "chế độ toàn cục bật/tắt theo mưa/giờ cao điểm" — ghép chuyến chỉ là bước 2 của cascade, xảy ra tự nhiên khi bước 1 không đủ nhanh.
- Ràng buộc:
  - Pin thấp (< ngưỡng) → không nhận cuốc xa
  - Tài xế pin thấp → ưu tiên gợi ý về trạm sạc gần nhất thay vì repositioning đi xa
  - Số hành khách trên xe không vượt `vehicle_capacity = 4`; điểm đón của mỗi khách phải đứng trước điểm trả tương ứng trong tuyến; thời gian hành trình của mỗi khách không tăng quá 20% so với đi riêng (15% khi trời mưa)
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
- ✅ Bảng so sánh KPI của 3 kịch bản, chứng minh rõ giá trị của cơ chế chống herding — `docs/week4_matching_ab_test.md`
- ⚠️ Cost Prediction Model train xong, có MAE trên tập test — ✅ đã train (`ml/artifacts/cost_model.joblib` + `cost_model_metrics.json`), nhưng ❌ chưa log vào MLflow (MLflow chưa triển khai)
- ❌ OpenTelemetry tracing hoạt động, đo được latency từng bước trong luồng chính — chưa triển khai

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
  - **Cập nhật so với kế hoạch ban đầu**: đã cài `ClaudeExplainer` (`ml/nlg_explainer.py`) — gọi thật `claude-opus-4-8` khi có `ANTHROPIC_API_KEY`, fallback về template ghép chuỗi khi thiếu key hoặc lỗi API/mạng (không bao giờ làm sập luồng export demo data). Môi trường hiện tại chưa cấu hình `ANTHROPIC_API_KEY` nên đang chạy qua nhánh fallback, đã kiểm chứng bằng `ml/tests/test_nlg_explainer.py`; chỉ cần set biến môi trường là chuyển sang gọi LLM thật ngay, không cần sửa code gọi module này ở nơi khác — đúng mẫu thiết kế đã dùng cho `GoogleRoutesClient`
- Xây giao diện (React + Leaflet):
  - Bản đồ: heatmap zone theo mức thiếu/thừa xe, icon tài xế theo trạng thái (idle/incoming/busy)
  - **Vẽ đường đi thực tế của tài xế lên map** (route theo road network, không phải đường thẳng): khi có gợi ý repositioning hoặc match, gọi Google Routes API cho đúng cặp điểm đi/đến (vị trí tài xế → điểm đến), lấy `encoded_polyline` và `traffic_aware_duration_seconds` trong response, decode và vẽ bằng `Polyline`/`GeoJSON` layer của Leaflet.
    **Cập nhật so với kế hoạch ban đầu**: `GoogleRoutesClient` (`ml/routing_client.py`) đã code xong đầy đủ (gọi API thật + cache + fallback Haversine × 1.3), nhưng chưa có `GOOGLE_ROUTES_API_KEY` hoạt động trong môi trường demo → `MapView.tsx` hiện đang vẽ **đường thẳng nối tâm zone** thay cho polyline thật, có chú thích rõ trên UI ("chưa phải route thực tế — cần Google Routes API key"). Ngoài ra pickup/dropoff hiện dùng tâm zone (`center_lat`/`center_lng`), chưa phải toạ độ cụ thể trong zone như thiết kế ở `docs/business_design.md`.
  - Panel gợi ý kèm giải thích tự nhiên
  - Dashboard so sánh KPI real-time (3 kịch bản tuần 4)
  - Nút chọn kịch bản: ngày thường / mưa / giờ cao điểm / ngày lễ

**Platform/Infra Track:**
- Dựng Prometheus + Grafana dashboard theo dõi API latency, forecast/matching engine metrics.

**Deliverable:**
- ✅ Web app demo hoàn chỉnh, đổi kịch bản trực tiếp và thấy hệ thống phản ứng ngay — `frontend/` (React + Leaflet, chạy được, đọc data export tĩnh)
- ❌ Bản đồ hiển thị đường đi thực tế (route) của tài xế theo road network, không phải đường chim bay — chưa có, đang vẽ đường thẳng minh hoạ (thiếu `GOOGLE_ROUTES_API_KEY`)
- ❌ Prometheus + Grafana dashboard hiển thị metric hệ thống và model — chưa triển khai

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
  - Hướng phát triển: reinforcement learning cho repositioning, tích hợp dữ liệu thật từ GSM, VRP đầy đủ cho ghép chuyến, tự host OSRM để giảm chi phí/phụ thuộc gọi Google Routes API khi scale lên nhiều xe/khách hơn
- Chuẩn bị slide + kịch bản demo trực tiếp: chạy "ngày thường" → chuyển sang "mưa + lễ" → cho thấy dự báo, gợi ý điều xe, tránh dồn xe, và giải thích tự nhiên, tất cả trên 1 màn hình.

**Deliverable:**
- Sản phẩm hoàn chỉnh + báo cáo + slide + kịch bản demo

---

## Rủi ro & cách xử lý

| Rủi ro | Cách xử lý |
|---|---|
| Forecast model không đủ chính xác vì dữ liệu giả lập | Thiết kế simulator có seasonality rõ ràng để model dễ học; nêu rõ trong báo cáo đây là dữ liệu giả lập có kiểm soát |
| Khối lượng công việc lớn (5 module trong 6 tuần) | Ưu tiên làm luồng chính chạy end-to-end trước, tối ưu từng module sau; NLG là module độc lập nhất, có thể cắt/rút gọn nếu tuần 5 bị chậm tiến độ |
| Thuật toán repositioning + chống herding phức tạp hơn dự kiến | Bắt đầu với rule-based đơn giản (tuần 3), chỉ nâng cấp thêm nếu còn dư thời gian |
| Acceptance Probability Model / Cost Prediction Model không đủ chính xác vì dữ liệu giả lập | Thiết kế rule sinh nhãn (chấp nhận/từ chối, thời gian di chuyển thực) có logic rõ ràng, đủ tín hiệu để model học được; nêu rõ trong báo cáo đây là giả lập có kiểm soát, không phải hành vi tài xế/traffic thật |
| Tăng thêm 2 model (Acceptance, Cost Prediction) có thể làm tuần 3-4 quá tải | Đây là các model nhỏ (Logistic Regression/LightGBM), train nhanh trên tập dữ liệu giả lập, không tốn nhiều thời gian tune như Forecast Engine; nếu vẫn chậm, có thể lùi Cost Prediction Model sang dùng rule-based factor tạm và bổ sung sau nếu còn thời gian |
| Không có dữ liệu thật từ GSM | Xác nhận sớm với mentor việc dùng dữ liệu giả lập có được chấp nhận; giải thích rõ trong báo cáo đây là giả định có chủ đích |
| Điểm nghẽn khi tích hợp 2 track (Platform/Infra Track cần API/output thật từ Business/AI Track) | Đồng bộ interface/contract dữ liệu ngay từ tuần 1; daily sync ngắn, đặc biệt chặt ở tuần 3-4 |
| MLflow/OpenTelemetry cần thời gian làm quen nếu Platform/Infra Track chưa dùng qua | Xác nhận sớm mức độ quen thuộc của Platform/Infra Track với 2 công cụ này; nếu chưa quen, học trước ở tuần 1 song song lúc Business/AI Track thiết kế bài toán |
| Google Routes API phát sinh chi phí/quota nếu gọi trực tiếp mọi cặp tài xế-khách | Lọc top 3-5 ứng viên bằng Haversine, cache route theo cặp zone trong thời gian ngắn và chỉ lấy route chi tiết cho gợi ý/match cần hiển thị hoặc chấm điểm chèn tuyến |
| Google Routes API downtime/lỗi/hết quota ảnh hưởng luồng chính | Có fallback: dùng Haversine × hệ số đường vòng 1,3 và traffic giả lập cho tick đó; trả `is_fallback: true` và ghi log (đúng theo mục 2.8 `business_design.md`) |

---

## Nguồn dữ liệu

| Loại dữ liệu | Nguồn |
|---|---|
| Thời tiết | OpenWeatherMap API hoặc Open-Meteo (miễn phí) |
| Ngày lễ VN | Rule-based tự lập hoặc thư viện `holidays` (Python) |
| Ranh giới zone Hà Nội | OpenStreetMap (Overpass API) |
| POI (sân bay, trung tâm thương mại...) | OpenStreetMap, Google Places API |
| Traffic pattern | Rule-based, tự thiết kế hệ số theo giờ/khu vực (tham khảo trực quan từ Google Maps) |
| Routing (quãng đường/thời gian theo road network) | Google Routes API (`ml/routing_client.py`, có cache theo cặp toạ độ + fallback Haversine tự động khi không có API key) |
| Dữ liệu vận hành (tài xế, khách, cuốc xe) | Tự sinh (synthetic) bằng simulator, calibrate quy mô theo số liệu công khai của GSM |
| Trạm sạc | Tự sinh 8 trạm phủ đều 30 zone bằng farthest-point sampling (`data/generate_charging_stations.py`) — chưa có dữ liệu trạm sạc thật của GSM |

---

## Giá trị dự án chứng minh được (đầu ra định lượng)

**Cập nhật**: đã chạy A/B test thật (7 ngày × 3 kịch bản × 10 seed, `docs/week4_matching_ab_test.md`) — thay bảng kỳ vọng ban đầu bằng số liệu thực đo. Một số kết quả **khác với dự đoán ban đầu**, giữ nguyên trung thực thay vì chỉnh cho khớp giả thuyết.

| Metric | Kỳ vọng ban đầu | Kết quả thực đo (A_PASSIVE → C_SOFT_RESERVE) | Nhận định |
|---|---|---|---|
| Thời gian chờ khách trung bình | Giảm 15–25% | 8,86s → 6,59s (**-25,6%**) | ✅ Đạt kỳ vọng |
| Tỷ lệ cuốc bị hủy | Giảm 20–35% | 4,05% → 2,65% (**-34,6%**) | ✅ Đạt kỳ vọng, sát cận trên |
| Quãng đường chạy rỗng (deadhead) của tài xế | Giảm 20–30% | 228.467m → 242.728m (**+6,2%**, tăng chứ không giảm) | ❌ **Ngược kỳ vọng** — deadhead tăng vì cộng thêm quãng đường tài xế di chuyển theo gợi ý repositioning; hệ thống đánh đổi ít deadhead-do-chờ-khách lấy nhiều deadhead-do-điều-xe-chủ-động |
| Độ lệch chuẩn tỷ lệ cung/cầu (C so với B — hiệu quả chống herding) | Giảm 10–20% | B=4,34 → C=4,50 (**+3,7%**, C cao hơn B) | ❌ **Không xác nhận được** trực tiếp trên metric này; tuy nhiên C dùng **ít hơn 11% lượt điều xe** (5.955 so với 6.680) để đạt KPI khách hàng gần tương đương B — giá trị chống herding thể hiện rõ ở **hiệu quả vận hành**, không phải ở chính metric lệch chuẩn cung/cầu như giả thuyết ban đầu |
| Rủi ro xe hết pin giữa chuyến | Giảm về gần 0 | Ràng buộc pin có trong Matching Engine (phạt chi phí nặng cho cuốc xa khi pin thấp) | ⚠️ Chưa đo số ca vi phạm cụ thể trong A/B test — cần bổ sung nếu muốn số liệu định lượng |

Chi tiết đầy đủ + độ lệch chuẩn giữa 10 seed: `data/ab_test_multiseed/ab_test_summary_multi_seed.csv`, phân tích trung thực về đánh đổi B vs C: `docs/week4_matching_ab_test.md` mục "Nhận định trung thực".

- Thể hiện được 3 model ML phối hợp trong 1 hệ thống thực tế (Forecast, Acceptance Probability, Cost Prediction) kết hợp cùng cascade dispatch theo quy tắc (gán trực tiếp → ghép chuyến → soft-reserve) — đúng mô hình kết hợp ML + logic vận hành phổ biến trong ngành ride-hailing thật

---

## Hiệu năng hệ thống kỳ vọng (Latency)
| Thành phần | Latency kỳ vọng | Ghi chú |
|---|---|---|
| Forecast Engine (dự báo demand cho 20–30 zone/batch) | 100–500ms | Prophet thường chậm hơn XGBoost; nếu Prophet không đạt mục tiêu, ưu tiên XGBoost |
| Acceptance Probability Model (inference/cặp driver-zone) | <20ms | Logistic Regression/LightGBM nhỏ, rất nhanh |
| Cost Prediction Model (inference/cặp driver-rider) | <20ms | Tương tự, model nhỏ, không phải bottleneck |
| Matching Engine — cascade/request (gán trực tiếp hoặc chèn ghép chuyến) | <200ms | Bước chèn ghép chuyến duyệt top 5 tài xế × vị trí chèn hợp lệ; tăng nhanh nếu route hiện có nhiều điểm dừng |
| Google Routes API call (bên ngoài, mỗi request) | 200–1.000ms | Phụ thuộc mạng/dịch vụ ngoài — lý do phải cache zone-to-zone thay vì gọi trực tiếp cho cost matrix |
| Luồng chính end-to-end (forecast → suggester → matching, chưa tính NLG/routing hiển thị) | Mục tiêu <1s | Đo bằng OpenTelemetry trace từng bước, là số liệu chính để báo cáo Tuần 4 |
| NLG Explainer (gọi Claude/GPT API) | 1–3s | Gọi bất đồng bộ, không chặn luồng dispatch chính; UI hiển thị trạng thái "đang tạo giải thích..." trong lúc chờ |
| Dashboard refresh (KPI real-time) | 1–5s/lần cập nhật | Polling hoặc WebSocket tùy cách Frontend triển khai |