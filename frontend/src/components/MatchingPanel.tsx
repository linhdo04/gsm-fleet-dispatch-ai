import type { MatchingAction, MatchingSummary } from "../types";

interface Props {
  matching: MatchingSummary | null;
}

const ACTION_LABEL: Record<MatchingAction, string> = {
  direct_assign: "Gán trực tiếp (tài xế idle đủ gần)",
  pooled_insertion: "Chèn vào tuyến ghép chuyến",
  queued_waiting_for_incoming: "Chờ xe incoming (đã đủ bù)",
  queued_pending_reposition: "Chờ, đã kích hoạt điều xe",
};

const ACTION_ORDER: MatchingAction[] = [
  "direct_assign",
  "pooled_insertion",
  "queued_waiting_for_incoming",
  "queued_pending_reposition",
];

export default function MatchingPanel({ matching }: Props) {
  if (!matching) return null;
  const pooledCount = matching.action_breakdown.pooled_insertion ?? 0;

  return (
    <div className="panel">
      <h2>Matching Engine — cascade 4 bước</h2>
      <p className="panel-caveat">
        Batch giả lập <strong>{matching.requests}</strong> cuốc mới cho đúng bối cảnh (giờ/thời tiết) của tick đang
        xem, chạy thật qua <code>ml/matching_flow.py</code> (Luồng A, theo{" "}
        <code>docs/business_design.md</code>) — mỗi request tự đi qua 4 bước: gán trực tiếp → chèn ghép chuyến → chờ
        xe incoming → kích hoạt điều xe. Không còn "chế độ" chung cho cả batch.
      </p>

      <ul className="matching-breakdown">
        {ACTION_ORDER.filter((action) => matching.action_breakdown[action]).map((action) => (
          <li key={action}>
            <span className="matching-stat-value">{matching.action_breakdown[action]}</span>
            <span className="muted"> {ACTION_LABEL[action]}</span>
          </li>
        ))}
      </ul>

      <div className="matching-stats">
        {matching.avg_direct_assign_eta_seconds != null && (
          <div>
            <span className="matching-stat-value">{matching.avg_direct_assign_eta_seconds}s</span>
            <span className="muted"> ETA trung bình khi gán trực tiếp</span>
          </div>
        )}
        {matching.avg_pooled_insertion_cost != null && (
          <div>
            <span className="matching-stat-value">{matching.avg_pooled_insertion_cost}</span>
            <span className="muted"> chi phí biên trung bình khi chèn ghép chuyến (Cost Prediction Model)</span>
          </div>
        )}
      </div>

      {pooledCount > 0 && matching.pooled_routes.length > 0 && (
        <>
          <p className="muted" style={{ marginTop: 10 }}>
            {matching.pooled_routes.length} tài xế đang ghép ≥2 khách trong cùng chuyến, ví dụ:
          </p>
          <ul className="suggestion-list">
            {matching.pooled_routes.slice(0, 3).map((route) => (
              <li key={route.driver_id} className="suggestion-item">
                <div className="suggestion-header">
                  <strong>{route.driver_id}</strong>
                  <span className="badge">{route.passengers} khách chung xe</span>
                </div>
                <p className="muted">
                  {route.stops.map((s) => `${s.type === "pickup" ? "Đón" : "Trả"} ở ${s.zone_name}`).join(" → ")}
                </p>
                <p className="muted">
                  Tổng quãng đường: <strong>{(route.total_distance_m / 1000).toFixed(1)} km</strong> · vẽ trên bản đồ
                  bằng nét liền tím
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
      {pooledCount > 0 && matching.pooled_routes.length === 0 && (
        <p className="muted">Có request được chèn vào tuyến, nhưng chưa tài xế nào ghép đủ ≥2 khách khác nhau.</p>
      )}
    </div>
  );
}
