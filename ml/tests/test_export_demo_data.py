import unittest
from unittest.mock import MagicMock

from ml.export_demo_data import _pooled_route_path, _route_path
from ml.routing_client import RouteResult

POINT_A = (21.0357936, 105.8050191)
POINT_B = (21.0230572, 105.8459077)


def _real_route_result(encoded_polyline: str = "_p~iF~ps|U_ulLnnqC") -> RouteResult:
    return RouteResult(
        distance_m=1000.0,
        duration_seconds=120.0,
        traffic_aware_duration_seconds=120.0,
        encoded_polyline=encoded_polyline,
        provider="google_routes",
        is_fallback=False,
    )


class RoutePathIdenticalPointsTest(unittest.TestCase):
    """Regression test: 2 stop trùng toạ độ (vd 2 khách pickup cùng zone
    trong 1 route ghép chuyến) từng khiến cả route ghép chuyến rơi về
    fallback, vì Google trả response thiếu distanceMeters/polyline cho
    quãng đường 0m và code coi đó là lỗi cần fallback."""

    def test_identical_points_skip_api_call_entirely(self):
        routes_client = MagicMock()
        result = _route_path(routes_client, POINT_A, POINT_A)
        routes_client.get_route.assert_not_called()
        self.assertEqual(result, [list(POINT_A)])

    def test_distinct_points_call_api_normally(self):
        routes_client = MagicMock()
        routes_client.get_route.return_value = _real_route_result()
        result = _route_path(routes_client, POINT_A, POINT_B)
        routes_client.get_route.assert_called_once()
        self.assertIsNotNone(result)


class PooledRoutePathTest(unittest.TestCase):
    def test_duplicate_leading_stop_does_not_force_whole_route_to_fallback(self):
        routes_client = MagicMock()
        routes_client.get_route.return_value = _real_route_result()
        # 2 stop đầu trùng nhau (đúng tình huống thật gặp trong scenario_normal.json)
        path = _pooled_route_path(routes_client, [POINT_A, POINT_A, POINT_B])
        self.assertIsNotNone(path)
        # Chỉ 1 lần gọi API thật (đoạn POINT_A -> POINT_B), đoạn trùng bị bỏ qua.
        routes_client.get_route.assert_called_once()

    def test_any_real_segment_failure_still_falls_back_whole_route(self):
        routes_client = MagicMock()
        routes_client.get_route.return_value = RouteResult(
            distance_m=100.0,
            duration_seconds=10.0,
            traffic_aware_duration_seconds=10.0,
            encoded_polyline=None,
            provider="haversine_fallback",
            is_fallback=True,
        )
        path = _pooled_route_path(routes_client, [POINT_A, POINT_B])
        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
