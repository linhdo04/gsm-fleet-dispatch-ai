import { useEffect, useState } from "react";
import type { ExperimentCode, KpiRow } from "../types";
import { EXPERIMENT_LABELS } from "../mock/scenario";
import { SCENARIO_COLOR } from "../color";

const EXPERIMENTS: ExperimentCode[] = ["A_PASSIVE", "B_REPOSITION_NO_RESERVE", "C_REPOSITION_SOFT_RESERVE"];

export default function KpiDashboard() {
  const [rows, setRows] = useState<KpiRow[] | null>(null);

  useEffect(() => {
    fetch("/data/kpi_real.json")
      .then((res) => res.json())
      .then(setRows)
      .catch((err) => console.error("Không tải được kpi_real.json — đã chạy python -m ml.export_demo_data chưa?", err));
  }, []);

  return (
    <div className="panel">
      <h2>So sánh KPI — 3 kịch bản A/B (Tuần 4)</h2>
      <p className="panel-caveat">
        Kết quả A/B test <strong>thật</strong> chạy trên simulator: 7 ngày × 3 kịch bản, trung bình 10 seed
        (<code>ml/ab_testing.py --multi-seed</code>) — không phải số ước tính trong report.md nữa. Xem phân tích đầy
        đủ (kèm giới hạn của phép so sánh) ở <code>docs/week4_matching_ab_test.md</code>.
      </p>

      <div className="legend" aria-hidden="false">
        {EXPERIMENTS.map((code) => (
          <span key={code} className="legend-item">
            <span className="legend-swatch" style={{ background: SCENARIO_COLOR[code] }} />
            {EXPERIMENT_LABELS[code]}
          </span>
        ))}
      </div>

      {!rows && <p className="muted">Đang tải…</p>}
      {rows && (
        <div className="kpi-table-wrap">
        <table className="kpi-table">
          <thead>
            <tr>
              <th scope="col">Metric</th>
              {EXPERIMENTS.map((code) => (
                <th scope="col" key={code}>
                  {EXPERIMENT_LABELS[code].split(".")[0]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const max = Math.max(...EXPERIMENTS.map((c) => row.values[c]));
              return (
                <tr key={row.metric}>
                  <th scope="row">
                    {row.metric} <span className="muted">({row.unit})</span>
                  </th>
                  {EXPERIMENTS.map((code) => {
                    const value = row.values[code];
                    const widthPct = max > 0 ? Math.max(6, (value / max) * 100) : 0;
                    return (
                      <td key={code}>
                        <div className="kpi-cell">
                          <span className="kpi-value">{value}</span>
                          <div className="kpi-bar-track">
                            <div
                              className="kpi-bar-fill"
                              style={{ width: `${widthPct}%`, background: SCENARIO_COLOR[code] }}
                            />
                          </div>
                        </div>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      )}
    </div>
  );
}
