import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ml.geocoding_client import GeocodingClient, GeocodingError

# Toạ độ thật của HN-Z001 trong data/hanoi_zones.json (h3 index cố định,
# resolution 7) để test ánh xạ zone không phụ thuộc vào việc data gốc đổi.
ZONE_H3_INDEX = "87415cb4bffffff"
ZONE_LAT, ZONE_LNG = 21.0357936, 105.8050191


def _write_test_zones(tmp_dir: Path) -> Path:
    zones_path = tmp_dir / "zones.json"
    zones_path.write_text(
        json.dumps([{"zone_id": "HN-Z001", "name": "Hà Nội Zone 001", "h3_index": ZONE_H3_INDEX}]),
        encoding="utf-8",
    )
    return zones_path


class NoApiKeyRaisesTest(unittest.TestCase):
    """No GOOGLE_GEOCODING_API_KEY configured — must raise clearly instead of
    silently returning made-up coordinates (unlike routing_client.py, there
    is no honest offline estimate for geocoding a text address)."""

    def test_raises_without_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {}, clear=True):
                client = GeocodingClient(api_key=None, zones_path=_write_test_zones(Path(tmp)))
                with self.assertRaises(GeocodingError):
                    client.geocode("17 ngõ 182 Lương Thế Vinh, Thanh Xuân, Hà Nội")


class SuccessfulGeocodeTest(unittest.TestCase):
    def test_maps_to_known_zone(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = GeocodingClient(api_key="fake-key-for-test", zones_path=_write_test_zones(Path(tmp)))
            fake_payload = {
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "17 Ngõ 182 P. Lương Thế Vinh, Thanh Xuân, Hà Nội",
                        "geometry": {"location": {"lat": ZONE_LAT, "lng": ZONE_LNG}},
                    }
                ],
            }

            class FakeResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return fake_payload

            with patch("ml.geocoding_client.requests.get", return_value=FakeResponse()):
                result = client.geocode("17 ngõ 182 Lương Thế Vinh, Thanh Xuân, Hà Nội")

            self.assertEqual(result.zone_id, "HN-Z001")
            self.assertEqual(result.zone_name, "Hà Nội Zone 001")
            self.assertAlmostEqual(result.lat, ZONE_LAT)
            self.assertAlmostEqual(result.lng, ZONE_LNG)

    def test_address_outside_zone_coverage_returns_none_zone(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = GeocodingClient(api_key="fake-key-for-test", zones_path=_write_test_zones(Path(tmp)))
            fake_payload = {
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "Somewhere far away",
                        "geometry": {"location": {"lat": 10.762622, "lng": 106.660172}},
                    }
                ],
            }

            class FakeResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return fake_payload

            with patch("ml.geocoding_client.requests.get", return_value=FakeResponse()):
                result = client.geocode("some address outside Hanoi zones")

            self.assertIsNone(result.zone_id)
            self.assertIsNone(result.zone_name)


class ApiErrorStatusRaisesTest(unittest.TestCase):
    def test_zero_results_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = GeocodingClient(api_key="fake-key-for-test", zones_path=_write_test_zones(Path(tmp)))

            class FakeResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"status": "ZERO_RESULTS", "results": []}

            with patch("ml.geocoding_client.requests.get", return_value=FakeResponse()):
                with self.assertRaises(GeocodingError):
                    client.geocode("địa chỉ không tồn tại xyz123")


if __name__ == "__main__":
    unittest.main()
