import type { ExperimentCode, ScenarioKey } from "../types";

// Scenario labels + experiment labels only — the actual zone/driver/suggestion/KPI
// generators that used to live here were replaced by real exported data
// (see ml/export_demo_data.py and src/data/realData.ts) once Tuần 3/4 produced
// a trained Acceptance Model and a real A/B test result.

export const SCENARIOS: { key: ScenarioKey; label: string }[] = [
  { key: "normal", label: "Ngày thường" },
  { key: "rain", label: "Mưa" },
  { key: "peak", label: "Giờ cao điểm" },
  { key: "holiday", label: "Ngày lễ" },
];

export const EXPERIMENT_LABELS: Record<ExperimentCode, string> = {
  A_PASSIVE: "A. Không repositioning",
  B_REPOSITION_NO_RESERVE: "B. Repositioning, không chống herding",
  C_REPOSITION_SOFT_RESERVE: "C. Repositioning + chống herding",
};
