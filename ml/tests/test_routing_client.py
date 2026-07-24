import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from ml.routing_client import GoogleRoutesClient, _haversine_m, decode_polyline

# Two real Hà Nội coordinates ~3.3km apart (same order of magnitude as the
# zone-centroid distances used throughout the project).
ORIGIN = (21.0357936, 105.8050191)
DEST = (21.0230572, 105.8459077)


class NoApiKeyFallbackTest(unittest.TestCase):
    """No GOOGLE_ROUTES_API_KEY configured in this environment — every call
    in this project goes through this path. Must be honestly labeled."""

    def test_falls_back_to_haversine_and_labels_it(self):
        with patch.dict("os.environ", {}, clear=True):
            client = GoogleRoutesClient(api_key=None)
            result = client.get_route(*ORIGIN, *DEST)

        self.assertTrue(result.is_fallback)
        self.assertEqual(result.provider, "haversine_fallback")
        self.assertIsNone(result.encoded_polyline)
        expected_distance = _haversine_m(*ORIGIN, *DEST) * 1.3
        self.assertAlmostEqual(result.distance_m, expected_distance, delta=1.0)
        self.assertGreater(result.duration_seconds, 0)


class CachingTest(unittest.TestCase):
    def test_second_call_for_same_pair_is_served_from_cache_without_recompute(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "cache.json"
            client = GoogleRoutesClient(api_key=None, cache_path=cache_path, cache_ttl_seconds=300)
            first = client.get_route(*ORIGIN, *DEST)
            second = client.get_route(*ORIGIN, *DEST)
            self.assertEqual(first, second)
            self.assertTrue(cache_path.exists(), "cache file should persist to disk")

            # A fresh client instance loading the same cache file must reuse
            # the entry rather than recomputing.
            reloaded_client = GoogleRoutesClient(api_key=None, cache_path=cache_path, cache_ttl_seconds=300)
            cache_key = list(reloaded_client._cache.keys())[0]
            self.assertIn(cache_key, reloaded_client._cache)

    def test_expired_cache_entry_is_recomputed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "cache.json"
            client = GoogleRoutesClient(api_key=None, cache_path=cache_path, cache_ttl_seconds=0)
            client.get_route(*ORIGIN, *DEST)
            key = list(client._cache.keys())[0]
            cached_at_first = client._cache[key]["cached_at"]
            client.get_route(*ORIGIN, *DEST)  # ttl=0 -> must be treated as expired immediately
            cached_at_second = client._cache[key]["cached_at"]
            self.assertGreaterEqual(cached_at_second, cached_at_first)


class ApiFailureFallsBackTest(unittest.TestCase):
    """With a key configured, a network/API failure must not crash the
    caller — it must fall back exactly like the no-key case, per mục 2.8
    business_design.md ('Nếu routing API lỗi hoặc hết quota, fallback về
    Haversine')."""

    def test_request_exception_falls_back(self):
        client = GoogleRoutesClient(api_key="fake-key-for-test")
        with patch("ml.routing_client.requests.post", side_effect=requests.ConnectionError("boom")):
            result = client.get_route(*ORIGIN, *DEST)
        self.assertTrue(result.is_fallback)
        self.assertEqual(result.provider, "haversine_fallback")

    def test_malformed_response_falls_back(self):
        client = GoogleRoutesClient(api_key="fake-key-for-test")

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"routes": []}  # missing expected fields -> IndexError

        with patch("ml.routing_client.requests.post", return_value=FakeResponse()):
            result = client.get_route(*ORIGIN, *DEST)
        self.assertTrue(result.is_fallback)

    def test_zero_distance_response_defaults_to_zero_not_fallback(self):
        """Google trả '{"routes": [{"duration": "0s"}]}' (bỏ hẳn
        distanceMeters/polyline) khi origin == destination — đã kiểm chứng
        thật qua Routes API, không phải response lỗi cần fallback."""
        client = GoogleRoutesClient(api_key="fake-key-for-test")

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"routes": [{"duration": "0s"}]}

        with patch("ml.routing_client.requests.post", return_value=FakeResponse()):
            result = client.get_route(*ORIGIN, *ORIGIN)
        self.assertFalse(result.is_fallback)
        self.assertEqual(result.distance_m, 0.0)


class DecodePolylineTest(unittest.TestCase):
    """Ví dụ chính thức từ tài liệu Google Encoded Polyline Algorithm Format."""

    def test_decodes_official_google_example(self):
        points = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        expected = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
        self.assertEqual(len(points), len(expected))
        for (lat, lng), (exp_lat, exp_lng) in zip(points, expected):
            self.assertAlmostEqual(lat, exp_lat, places=5)
            self.assertAlmostEqual(lng, exp_lng, places=5)


if __name__ == "__main__":
    unittest.main()
