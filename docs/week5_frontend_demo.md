# Tuần 5 — Giao diện demo

> App chạy tại `frontend/` (React + Vite + react-leaflet). Chạy `python -m ml.export_demo_data` rồi `cd frontend && npm run dev` → http://localhost:5173.

## Trạng thái

| Deliverable Tuần 5 | Trạng thái |
|---|---|
| Bản đồ: heatmap zone theo deficit, icon tài xế theo trạng thái | ✅ Xong — dữ liệu thật |
| Panel gợi ý kèm giải thích | ✅ Số liệu thật, ⚠️ câu giải thích vẫn là template |
| Matching Engine hiển thị trên UI | ✅ Nối với cascade mới (`ml/matching_flow.py`, theo `docs/business_design.md`) — không còn Hungarian/`should_use_pooling` |
| Dashboard so sánh KPI real-time (3 kịch bản Tuần 4) | ✅ Xong — số thật từ A/B test 10 seed |
| Nút chọn kịch bản (ngày thường/mưa/giờ cao điểm/ngày lễ) | ✅ Xong |
| Vẽ route thực tế lên map (road network) | ❌ Chưa — vẫn là đường thẳng minh họa (không có Google/OpenRouteService API key) |
| Tích hợp Claude/GPT API cho NLG | ❌ Chưa — không có `ANTHROPIC_API_KEY` trong môi trường này, dùng template thay thế |
| Prometheus + Grafana dashboard | ❌ Chưa — nợ Platform/Infra Track |

## Cách lấy dữ liệu thật lên UI

Vì `backend/` (FastAPI, Tuần 1) chưa từng được xây, không có API sống để frontend gọi. Giải pháp: `ml/export_demo_data.py` xuất **1 tick lịch sử thật** cho mỗi trong 4 điều kiện kịch bản (chọn trong đúng 56 ngày dữ liệu simulator đã sinh ở Tuần 2, ưu tiên tick có tổng deficit lớn nhất trong mỗi điều kiện để demo có gì đó để xem) thành file JSON tĩnh (`frontend/public/data/scenario_*.json`), cộng với `kpi_real.json` (reshape từ `data/ab_test_multiseed`). Frontend chỉ `fetch()` các file này — không có model chạy trực tiếp trong trình duyệt.

- **Zone state / driver dots:** đúng số liệu `idle_drivers`, `incoming_drivers`, `deficit`... của tick thật đó (`supply_snapshots`). Vị trí từng chấm tài xế là jitter quanh tâm zone (simulator không lưu GPS trong-zone).
- **Gợi ý điều xe:** chạy thật `Repositioning Suggester` + `Acceptance Probability Model` đã train (Tuần 3) trên đúng deficit profile của tick đó. Driver pool lấy từ `drivers_final.json` (snapshot cuối run, vì simulator không lưu danh tính từng tài xế theo từng tick) — vậy nên đọc là "Suggester gợi ý gì khi đối mặt với đúng mẫu deficit của điều kiện này", không phải "replay y hệt lịch sử".
- **KPI dashboard:** số thật từ `data/ab_test_multiseed/ab_test_summary_multi_seed.csv`, không còn là số ước tính trong `report.md` nữa.

## Matching Engine trên UI

`ml/export_demo_data.py` xuất thêm khối `matching` cho mỗi kịch bản: dựng 30 request giả lập đúng bối cảnh giờ/thời tiết của tick, chạy thật `handle_new_request()` (Luồng A, `ml/matching_flow.py`) cho từng request một — mỗi request tự đi qua cascade 4 bước và trả về 1 trong 4 hành động (`direct_assign`/`pooled_insertion`/`queued_waiting_for_incoming`/`queued_pending_reposition`). Payload không còn field `mode` — thay bằng `action_breakdown` (đếm số request rơi vào mỗi hành động), vì cascade mới không có "chế độ chung cho cả batch" như bản Hungarian/`should_use_pooling` cũ. Component `MatchingPanel.tsx` đã cập nhật theo schema mới; `matching_engine.py` (bản cũ) giữ lại chỉ để tham khảo, không còn được import bởi `export_demo_data.py`.

**Quãng đường + vẽ route lên bản đồ:** mỗi route ghép chuyến (khi có ≥2 khách chung 1 tài xế) có `total_distance_m` (tổng haversine × 1.3 giữa các điểm dừng liên tiếp — tách riêng khỏi chi phí *biên* `avg_pooled_insertion_cost` dùng để ra quyết định chèn khách, không phải tổng quãng đường thực đi). Route được vẽ lên bản đồ bằng nét liền tím nối tâm các zone theo đúng thứ tự đón/trả (cùng giới hạn "chưa phải route thực tế theo road network" như đường gợi ý điều xe, vì chưa có Google Routes API key).

## Bug đã sửa khi verify demo

Bảng KPI 3 cột (A/B/C) bị **tràn ra ngoài panel** — cột C hoàn toàn không nhìn thấy được (panel `max-width: 420px` không đủ chứa 4 cột với label dài như "Quãng đường chạy rỗng (deadhead)"). Phát hiện bằng cách tự chụp ảnh màn hình demo thật (Playwright) chứ không chỉ đọc code — nhìn code CSS không thấy rõ vấn đề vì `width: 100%` "trông" có vẻ ổn. Sửa bằng: rút ngắn label metric, nới `.side-panel` lên 480px, thêm wrapper `overflow-x: auto` cho các màn hình hẹp hơn.

## Việc còn thiếu trước khi coi Tuần 5 hoàn thành

- [ ] Route thật lên map — cần API key Google Routes/OpenRouteService (chưa có).
- [ ] NLG thật qua Claude/GPT API — cần cấu hình `ANTHROPIC_API_KEY` (hoặc tương đương) rồi thay hàm template trong `ml/export_demo_data.py`.
- [ ] Prometheus + Grafana — nợ Platform/Infra Track (Docker/CI/MLflow cũng chưa làm, xem `docs/week4_matching_ab_test.md`).
- [ ] Dashboard hiện tại là **static export**, không phải "real-time" đúng nghĩa (phải re-export + reload trang khi model/dữ liệu đổi) — vì không có backend sống. Nếu cần thật sự real-time, phải xây `backend/` (FastAPI, nợ từ Tuần 1) trước.
