# So sánh thuật toán Repositioning: Greedy (p_accept) vs Minimum Cost Flow (OR-Tools)

> Bối cảnh: có người đề xuất tiếp cận bài toán "Fleet Rebalancing" bằng clustering (K-Means/DBSCAN) + Minimum Cost Flow (OR-Tools) + Hungarian Algorithm + surge pricing. Dự án hiện tại **không** đi theo hướng đó (xem so sánh chi tiết trong hội thoại) — zone đã cố định bằng H3, Matching Engine dùng Hungarian cho bài toán ghép tài xế-khách (khác với repositioning), và Repositioning Suggester dùng greedy + Acceptance Probability Model. Để trả lời câu hỏi "greedy có phải lựa chọn tốt không", tài liệu này code thử phương án Minimum Cost Flow và so sánh trực tiếp trên cùng 1 kịch bản.

Code: `ml/repositioning_mcf.py`. Chạy: `python -m ml.repositioning_mcf --output ml/artifacts`.

## Kịch bản dùng để so sánh

Giống hệt kịch bản demo ở Tuần 3 (`ml/repositioning_suggester.py: load_demo_scenario`) để đảm bảo công bằng — cùng fleet snapshot thật (`drivers_final.json`), cùng danh sách zone thiếu xe:

| | Giá trị |
|---|---:|
| Số zone thiếu xe | 17 |
| Tổng deficit cần bù | 13,13 |
| Số zone thừa xe (có tài xế idle, không nằm trong danh sách thiếu) | 10 |
| Tổng tài xế idle khả dụng ở các zone thừa | 67 |

**Cách xây bài toán MCF:** coi mỗi zone thừa là "nguồn cấp" (supply = số tài xế idle), mỗi zone thiếu là "nơi tiêu thụ" (demand), chi phí mỗi cạnh = khoảng cách zone-to-zone (haversine × 1.3, giống công thức đang dùng trong simulator). Giải bằng `ortools.graph.python.min_cost_flow.SimpleMinCostFlow`. Vì MCF chỉ ra được "chuyển N xe từ X sang Y" ở mức zone, để so sánh công bằng với greedy (vốn ra gợi ý ở mức từng tài xế), bước 2 luôn dùng lại **Acceptance Probability Model** để chọn cụ thể N tài xế nào trong zone X.

## Kết quả — 3 phương án

Sau khuyến nghị "kết hợp 2 tầng" (MCF quyết định số lượng, Acceptance Model chọn tài xế cụ thể), phần dưới đây code thử **3 phương án** trên cùng 1 kịch bản: greedy hiện tại, MCF thuần khoảng cách (baseline gốc), và MCF 2 tầng (hybrid).

| Chỉ số | Greedy (p_accept) | MCF thuần khoảng cách | MCF 2 tầng (hybrid) |
|---|---:|---:|---:|
| Runtime | 202 ms | 93 ms | 955 ms |
| Số tài xế được gợi ý | 34 | 17 | 28 |
| Số zone thực sự nhận được gợi ý (/17) | **17** | **17** | 13 |
| Tổng quãng đường di chuyển | 112.633 m | **91.591 m** | 131.766 m |
| Quãng đường trung bình/tài xế | **3.313 m** | 5.388 m | 4.706 m |
| p_accept trung bình/tài xế | **0,628** | 0,417 | 0,458 |
| Tỷ lệ bù đắp kỳ vọng / deficit cần | 162% *(dư)* | 54% *(thiếu)* | **97,7%** *(gần đúng nhất)* |

*(Số liệu đầy đủ: `ml/artifacts/repositioning_comparison.json`, `greedy_suggestions.csv`, `mcf_distance_suggestions.csv`, `mcf_hybrid_suggestions.csv`.)*

## Vì sao 2 thuật toán gốc ra số tài xế khác hẳn nhau (34 vs 17)

Đây không phải lỗi, mà là hệ quả tất yếu của 2 cách định nghĩa "đã đủ" khác nhau:

- **MCF** làm tròn deficit lên số nguyên rồi coi đó là mục tiêu cứng — gửi **đúng** từng đấy tài xế, không hơn, như thể mỗi lời mời chắc chắn thành công.
- **Greedy** trừ deficit bằng **kỳ vọng** `p_accept` (một lời mời không chắc chắn thành công — xem lần sửa bug trước). Với deficit nhỏ (trung bình 0,77/zone) nhưng p_accept mỗi tài xế cũng chỉ quanh 0,6-0,65, một tài xế thường không đủ bù kỳ vọng → cần thêm tài xế thứ 2 → tổng kỳ vọng dư ra đáng kể (162%).

## Thử "kết hợp 2 tầng" như khuyến nghị — không đơn giản như tưởng

Làm theo đúng gợi ý ban đầu, việc "để MCF quyết định số lượng, tránh over/under-shoot" hoá ra cần **2 lần sửa**, không phải 1:

**Lần 1 — chỉ sửa chi phí (cost = khoảng cách / p_accept trung bình của zone):** hầu như không đổi gì (7,08 → 7,14 kỳ vọng bù đắp). Lý do: trong dataset này, `distance_m` là như nhau cho mọi tài xế cùng zone (tính theo tâm zone), nên p_accept trung bình của cả zone gần như chỉ là một hàm đơn điệu của khoảng cách — không mang thêm thông tin gì mới so với chi phí khoảng cách thuần, nên MCF chọn ra gần như đúng cặp zone y hệt như trước.

**Lần 2 — sửa luôn "số lượng" (demand = deficit / p_accept khả dụng tốt nhất, không chỉ chi phí):** đây mới là chỗ khuyến nghị ban đầu nói tới ("layer 1 quyết định số lượng"). Nhưng làm thẳng — ép MCF gửi *đúng* con số đã inflate — lại **tệ hơn cả baseline**: tổng demand nhảy từ 17 lên 45, vượt quá khả năng cung ứng gần của nhiều zone, buộc MCF phải với tới tài xế rất xa để lấp cho đủ chỉ tiêu đã bị thổi phồng → tổng quãng đường tăng vọt lên 326.376m và p_accept trung bình tụt xuống 0,26 — **thua cả 2 phương án ban đầu**. Bài học: coi con số đã "chia cho xác suất" là mục tiêu *cứng* thì cũng mắc đúng lỗi mà bug #2 đã sửa ở greedy — chỉ là lặp lại nó ở tầng khác.

**Fix cuối cùng — làm "mềm" mục tiêu bằng phạt (soft demand):** thay vì ép MCF lấp đủ số đã inflate bằng mọi giá, thêm một "lối thoát" (arc ảo từ nguồn thẳng tới zone thiếu) với chi phí phạt cố định — MCF chỉ chấp nhận đi xa nếu chi phí thật còn rẻ hơn cái giá phạt đó, nếu không thì thà bỏ qua zone đó còn hơn. Với ngưỡng phạt chọn hợp lý (phân vị 25% của chi phí thực tế), kết quả mới cân bằng hơn hẳn: **tỷ lệ bù đắp 97,7%** — sát 100% nhất trong 3 phương án, không dư (162%) cũng không thiếu (54%).

**Nhưng vẫn có cái giá phải trả:** để đạt tỷ lệ bù đắp cân bằng đó, hybrid **bỏ hẳn 4/17 zone** (không gửi tài xế nào — vì mọi lựa chọn cho 4 zone đó đều "quá đắt" so với ngưỡng phạt), dồn tài xế cho 13 zone còn lại kỹ hơn. Tổng quãng đường (131.766m) cũng cao hơn cả 2 phương án gốc vì các cặp được chọn ở xa hơn phương án greedy. Nói cách khác: **con số tổng "97,7%" đẹp là nhờ đánh đổi — bỏ rơi hoàn toàn phần khó, phục vụ tốt phần dễ** — không phải ai cũng được phục vụ đều.

## Phát hiện quan trọng nhất: chi phí thuần khoảng cách thì mù với hành vi tài xế

MCF thuần khoảng cách cho **tổng quãng đường thấp nhất** (91.591m) — đúng như quảng cáo, vì nó tối ưu đúng cái được yêu cầu. Nhưng vì hàm chi phí chỉ có khoảng cách, nó sẵn sàng điều một tài xế đi xa (trung bình 5.388m, có cặp tới 8.776m) miễn tổng khoảng cách toàn hệ thống nhỏ nhất — **không biết** rằng quãng đường xa hơn thì Acceptance Model dự đoán tài xế sẽ *ít chấp nhận hơn* (p_accept trung bình chỉ 0,417). Greedy dùng trực tiếp `p_accept` để xếp hạng nên vẫn giữ được chỉ số quan trọng hơn (0,628) dù thua về tổng quãng đường.

*(Phát hiện phụ: khoảng cách của greedy bị dồn rất chặt quanh 3.284-3.374m — chính là artifact "3 khoảng cách rời rạc" đã ghi nhận ở `week2_data_sanity_check.md`, vì greedy giới hạn candidate trong bán kính 5km/top-N gần nhất. MCF không bị giới hạn bán kính này nên khoảng cách trải rộng hơn.)*

## Đánh đổi khác (không chỉ số liệu)

| | Greedy + p_accept | MCF (thuần hoặc 2 tầng) |
|---|---|---|
| Input cần có | Chạy được ngay từng tick, online/incremental | Cần biết toàn bộ supply/demand của mọi zone cùng lúc (batch) |
| Đầu ra | Trực tiếp ở mức từng tài xế | Chỉ ra số lượng zone-to-zone; cần thêm bước chọn tài xế cụ thể |
| Đảm bảo tối ưu | Không — greedy, có thể kẹt ở lời giải cục bộ | Có, nhưng chỉ tối ưu đúng hàm chi phí đã khai báo — hàm chi phí "đúng" hoá ra khó thiết kế (xem trên) |
| Phụ thuộc thư viện | Không cần gì thêm | Cần `ortools` (đã cài thành công, xem `requirements-ml.txt`) |
| Độ phức tạp vận hành | Thấp — một vòng lặp, dễ giải thích | Cao hơn hẳn — cần ước lượng p_accept theo cặp zone, hiệu chỉnh ngưỡng phạt, dễ "tối ưu nhầm" nếu hàm chi phí sai |

## Khuyến nghị

**Giữ greedy + Acceptance Probability Model làm lõi**, như kết luận ban đầu — bài toán thực sự quan tâm xác suất tài xế chấp nhận, không phải khoảng cách hay tổng số lượng thuần tuý. Đây vẫn đúng ngay cả sau khi thử code hybrid: bản 2 tầng có tỷ lệ bù đắp tổng đẹp hơn, nhưng đạt được bằng cách bỏ rơi hẳn các zone khó (4/17 zone) thay vì phục vụ đều — một đánh đổi cần cân nhắc kỹ trước khi coi là "tốt hơn" greedy trong thực tế vận hành, chứ không phải một chiến thắng rõ ràng.

Nếu vẫn muốn theo hướng 2 tầng cho Tuần 4, bài học từ lần thử này là: đừng inflate "số lượng" rồi ép cứng — phải làm mềm bằng cơ chế phạt/ngưỡng, và cần quyết định rõ chính sách cho các zone "quá đắt để phục vụ" (bỏ qua hẳn? hạ chuẩn tạm thời? chờ tick sau?) thay vì để thuật toán tự ý bỏ rơi.
