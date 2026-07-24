export type DriverStatus = "idle" | "reserved" | "incoming" | "busy" | "charging" | "offline";

export type ScenarioKey = "normal" | "rain" | "peak" | "holiday";

export type ExperimentCode = "A_PASSIVE" | "B_REPOSITION_NO_RESERVE" | "C_REPOSITION_SOFT_RESERVE";

export interface ZoneProperties {
  zone_id: string;
  name: string;
  h3_index: string;
  center_lat: number;
  center_lng: number;
  zone_type: string;
  base_demand_weight: number;
}

export interface ZoneState {
  zone_id: string;
  idle_drivers: number;
  incoming_drivers: number;
  outgoing_drivers: number;
  predicted_supply: number;
  predicted_demand: number;
  deficit: number;
}

export interface DriverPoint {
  driver_id: string;
  zone_id: string;
  lat: number;
  lng: number;
  // null when reconstructed from aggregate zone counts (supply_snapshots
  // doesn't persist individual driver battery per tick) — see MapView.
  battery_level: number | null;
  status: DriverStatus;
}

export interface RepositioningSuggestion {
  suggestion_id: string;
  driver_id: string;
  from_zone_id: string;
  from_zone_name: string;
  from: [number, number];
  target_zone_id: string;
  target_zone_name: string;
  to: [number, number];
  // Đường đi thật (đã decode encoded polyline từ Google Routes API), null nếu
  // đang chạy fallback Haversine (thiếu GOOGLE_ROUTES_API_KEY khi export data).
  path: [number, number][] | null;
  acceptance_probability: number;
  reason: string;
  explanation: string;
}

export interface KpiRow {
  metric: string;
  unit: string;
  values: Record<ExperimentCode, number>;
  lowerIsBetter: boolean;
}

// The 4 outcomes of the Luồng A cascade in ml/matching_flow.py
// (docs/business_design.md — "Đặc tả luồng Matching & Repositioning").
// There is no longer a single global "mode" for a batch — each request
// resolves independently.
export type MatchingAction =
  | "direct_assign"
  | "pooled_insertion"
  | "queued_waiting_for_incoming"
  | "queued_pending_reposition";

export interface PooledRouteStop {
  type: "pickup" | "dropoff";
  zone_id: string;
  zone_name: string;
  lat: number;
  lng: number;
}

export interface PooledRoute {
  driver_id: string;
  passengers: number;
  total_distance_m: number;
  // Đường đi thật nối các stop (đã decode encoded polyline), null nếu bất kỳ
  // đoạn nào rơi vào fallback Haversine (thiếu GOOGLE_ROUTES_API_KEY).
  path: [number, number][] | null;
  stops: PooledRouteStop[];
}

export interface MatchingSummary {
  requests: number;
  action_breakdown: Partial<Record<MatchingAction, number>>;
  avg_direct_assign_eta_seconds: number | null;
  avg_pooled_insertion_cost: number | null;
  pooled_routes: PooledRoute[];
}
