import { useMemo } from "react";
import { GeoJSON, MapContainer, CircleMarker, Polyline, Popup, TileLayer, Tooltip } from "react-leaflet";
import type { Layer, PathOptions } from "leaflet";
import type { DriverPoint, PooledRoute, RepositioningSuggestion, ZoneState } from "../types";
import { deficitColor, STATUS_COLOR } from "../color";

const HANOI_CENTER: [number, number] = [21.028511, 105.804817];

interface Props {
  zonesGeoJson: GeoJSON.FeatureCollection | null;
  zoneStates: Map<string, ZoneState>;
  drivers: DriverPoint[];
  suggestions: RepositioningSuggestion[];
  pooledRoutes?: PooledRoute[];
}

const DRIVER_RADIUS = 5;

export default function MapView({ zonesGeoJson, zoneStates, drivers, suggestions, pooledRoutes = [] }: Props) {
  const maxAbsDeficit = useMemo(() => {
    let max = 1;
    for (const state of zoneStates.values()) {
      max = Math.max(max, Math.abs(state.deficit));
    }
    return max;
  }, [zoneStates]);

  const styleZone = (feature?: GeoJSON.Feature): PathOptions => {
    const zoneId = feature?.properties?.zone_id as string | undefined;
    const state = zoneId ? zoneStates.get(zoneId) : undefined;
    const ratio = state ? state.deficit / maxAbsDeficit : 0;
    return {
      color: "rgba(11,11,11,0.2)",
      weight: 1,
      fillColor: deficitColor(ratio),
      fillOpacity: 0.55,
    };
  };

  const onEachZone = (feature: GeoJSON.Feature, layer: Layer) => {
    const props = feature.properties as { zone_id: string; name: string };
    const state = zoneStates.get(props.zone_id);
    layer.bindTooltip(
      `<strong>${props.name}</strong><br/>` +
        `Cầu dự báo: ${state?.predicted_demand ?? "-"}<br/>` +
        `Cung dự báo: ${state?.predicted_supply ?? "-"}<br/>` +
        `Deficit: ${state?.deficit ?? "-"}`,
      { sticky: true },
    );
  };

  return (
    <MapContainer center={HANOI_CENTER} zoom={12} className="map-container">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {zonesGeoJson && (
        <GeoJSON
          key={JSON.stringify([...zoneStates.values()].map((s) => s.deficit))}
          data={zonesGeoJson}
          style={styleZone}
          onEachFeature={onEachZone}
        />
      )}

      {drivers.map((d) => (
        <CircleMarker
          key={d.driver_id}
          center={[d.lat, d.lng]}
          radius={DRIVER_RADIUS}
          pathOptions={{
            color: "rgba(255,255,255,0.9)",
            weight: 1,
            fillColor: STATUS_COLOR[d.status] ?? STATUS_COLOR.offline,
            fillOpacity: 0.95,
          }}
        >
          <Popup>
            <strong>{d.driver_id}</strong>
            <br />
            Trạng thái: {d.status}
            {d.battery_level !== null && (
              <>
                <br />
                Pin: {d.battery_level}%
              </>
            )}
          </Popup>
        </CircleMarker>
      ))}

      {suggestions.map((s) => (
        <Polyline
          key={s.suggestion_id}
          positions={s.path ?? [s.from, s.to]}
          pathOptions={{ color: "#eb6834", weight: s.path ? 3 : 2, dashArray: s.path ? undefined : "6 6" }}
        >
          <Tooltip sticky>
            Gợi ý: {s.driver_id} → {s.target_zone_name}
            <br />
            {s.path ? (
              <em>Route thực tế (Google Routes API)</em>
            ) : (
              <em>Đường minh họa — chưa phải route thực tế (cần Google Routes API key)</em>
            )}
          </Tooltip>
        </Polyline>
      ))}

      {pooledRoutes.map((route) => (
        <Polyline
          key={`pool-${route.driver_id}`}
          positions={route.path ?? route.stops.map((s) => [s.lat, s.lng] as [number, number])}
          pathOptions={{ color: "#7b3aed", weight: 3, opacity: 0.85, dashArray: route.path ? undefined : "6 6" }}
        >
          <Tooltip sticky>
            Ghép chuyến: {route.driver_id} chở {route.passengers} khách · {(route.total_distance_m / 1000).toFixed(1)}{" "}
            km
            <br />
            {route.stops.map((s) => `${s.type === "pickup" ? "Đón" : "Trả"} ${s.zone_name}`).join(" → ")}
            <br />
            {route.path ? (
              <em>Route thực tế (Google Routes API)</em>
            ) : (
              <em>Đường minh họa nối tâm zone — chưa phải route thực tế (cần routing API key)</em>
            )}
          </Tooltip>
        </Polyline>
      ))}
    </MapContainer>
  );
}
