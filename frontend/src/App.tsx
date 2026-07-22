import { useEffect, useMemo, useState } from "react";
import MapView from "./components/MapView";
import ScenarioSwitcher from "./components/ScenarioSwitcher";
import SuggestionPanel from "./components/SuggestionPanel";
import KpiDashboard from "./components/KpiDashboard";
import MatchingPanel from "./components/MatchingPanel";
import type { DriverPoint, MatchingSummary, RepositioningSuggestion, ScenarioKey, ZoneState } from "./types";

interface ScenarioPayload {
  scenario: ScenarioKey;
  source_tick: { timestamp: string; weather: string; hour_local: number; is_weekend: boolean; is_holiday: boolean };
  zone_states: ZoneState[];
  driver_points: DriverPoint[];
  suggestions: RepositioningSuggestion[];
  matching: MatchingSummary;
}

export default function App() {
  const [scenario, setScenario] = useState<ScenarioKey>("normal");
  const [zonesGeoJson, setZonesGeoJson] = useState<GeoJSON.FeatureCollection | null>(null);
  const [payload, setPayload] = useState<ScenarioPayload | null>(null);
  const [loadedScenario, setLoadedScenario] = useState<ScenarioKey | null>(null);

  useEffect(() => {
    fetch("/data/hanoi_zones.geojson")
      .then((res) => res.json())
      .then(setZonesGeoJson)
      .catch((err) => console.error("Không tải được zone geojson", err));
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(`/data/scenario_${scenario}.json`)
      .then((res) => res.json())
      .then((data: ScenarioPayload) => {
        if (cancelled) return;
        setPayload(data);
        setLoadedScenario(scenario);
      })
      .catch((err) => console.error(`Không tải được scenario_${scenario}.json — đã chạy python -m ml.export_demo_data chưa?`, err));
    return () => {
      cancelled = true;
    };
  }, [scenario]);

  const currentPayload = loadedScenario === scenario ? payload : null;

  const zoneStates = useMemo(() => {
    const map = new Map<string, ZoneState>();
    for (const state of currentPayload?.zone_states ?? []) map.set(state.zone_id, state);
    return map;
  }, [currentPayload]);
  const drivers = currentPayload?.driver_points ?? [];
  const suggestions = currentPayload?.suggestions ?? [];
  const matching = currentPayload?.matching ?? null;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>GSM — AI Điều Phối Đội Xe</h1>
          <p className="muted">
            Zone (H3), cung/cầu mỗi zone, gợi ý điều xe (Repositioning Suggester + Acceptance Model) và KPI A/B
            đều lấy từ dữ liệu simulator + model đã train thật ở Tuần 2-4 — không phải số mô phỏng.{" "}
            {currentPayload && (
              <>
                Đang xem tick thật {new Date(currentPayload.source_tick.timestamp).toLocaleString("vi-VN")} ·{" "}
                {currentPayload.source_tick.weather} · {currentPayload.source_tick.hour_local}h
                {currentPayload.source_tick.is_holiday ? " · ngày lễ" : ""}.
              </>
            )}{" "}
            Câu giải thích trong panel gợi ý vẫn là template (chưa gọi Claude/GPT API — chưa có API key).
          </p>
        </div>
        <ScenarioSwitcher active={scenario} onChange={setScenario} />
      </header>

      <main className="app-main">
        <section className="map-section">
          <MapView
            zonesGeoJson={zonesGeoJson}
            zoneStates={zoneStates}
            drivers={drivers}
            suggestions={suggestions}
            pooledRoutes={matching?.pooled_routes ?? []}
          />
          <div className="legend map-legend">
            <span className="legend-item">
              <span className="legend-swatch" style={{ background: "rgb(143,35,35)" }} />
              Thiếu xe (deficit)
            </span>
            <span className="legend-item">
              <span className="legend-swatch" style={{ background: "rgb(240,239,236)", border: "1px solid #c3c2b7" }} />
              Cân bằng
            </span>
            <span className="legend-item">
              <span className="legend-swatch" style={{ background: "rgb(24,79,149)" }} />
              Thừa xe
            </span>
            <span className="legend-item">
              <span className="legend-swatch" style={{ background: "#0ca30c" }} />
              Tài xế idle
            </span>
            <span className="legend-item">
              <span className="legend-swatch" style={{ background: "#4a3aa7" }} />
              Đang chở khách
            </span>
            <span className="legend-item">
              <span className="legend-swatch" style={{ background: "#2a78d6" }} />
              Đang di chuyển tới (incoming)
            </span>
            <span className="legend-item">
              <span className="legend-swatch" style={{ background: "#fab219" }} />
              Đang sạc
            </span>
            <span className="legend-item">
              <span className="legend-swatch" style={{ background: "#7b3aed" }} />
              Route ghép chuyến (ride-pooling)
            </span>
          </div>
        </section>

        <aside className="side-panel">
          <MatchingPanel matching={matching} />
          <SuggestionPanel suggestions={suggestions} />
          <KpiDashboard />
        </aside>
      </main>
    </div>
  );
}
