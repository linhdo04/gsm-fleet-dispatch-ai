import type { DriverPoint, KpiRow, RepositioningSuggestion, ScenarioKey, ZoneState } from "../types";

// Real data exported by `python -m ml.export_demo_data` (see ml/export_demo_data.py)
// from the actual Tuần 2 simulator run + Tuần 3 Acceptance Model + Tuần 4 A/B test —
// replaces the seeded-random generators that used to live in mock/scenario.ts.

interface SourceTick {
  timestamp: string;
  weather: string;
  hour_local: number;
  is_weekend: boolean;
  is_holiday: boolean;
}

interface ScenarioPayload {
  scenario: ScenarioKey;
  source_tick: SourceTick;
  zone_states: ZoneState[];
  driver_points: DriverPoint[];
  suggestions: RepositioningSuggestion[];
}

export interface RealScenarioData {
  tick: SourceTick;
  zoneStates: Map<string, ZoneState>;
  drivers: DriverPoint[];
  suggestions: RepositioningSuggestion[];
}

export async function loadScenario(scenario: ScenarioKey): Promise<RealScenarioData> {
  const res = await fetch(`/data/scenario_${scenario}.json`);
  if (!res.ok) {
    throw new Error(
      `Không tải được /data/scenario_${scenario}.json (${res.status}) — chạy ` +
        `\`python -m ml.export_demo_data\` trước để sinh file này.`,
    );
  }
  const payload: ScenarioPayload = await res.json();
  return {
    tick: payload.source_tick,
    zoneStates: new Map(payload.zone_states.map((z) => [z.zone_id, z])),
    drivers: payload.driver_points,
    suggestions: payload.suggestions,
  };
}

export async function loadKpi(): Promise<KpiRow[]> {
  const res = await fetch("/data/kpi_real.json");
  if (!res.ok) {
    throw new Error(
      `Không tải được /data/kpi_real.json (${res.status}) — chạy \`python -m ml.export_demo_data\` trước.`,
    );
  }
  return res.json();
}
