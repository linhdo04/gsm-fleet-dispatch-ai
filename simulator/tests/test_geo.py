import json
import unittest

import h3
import numpy as np

from simulator.engine import PROJECT_ROOT
from simulator.geo import random_point_in_zone


class RandomPointInZoneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.zones = json.loads((PROJECT_ROOT / "data" / "hanoi_zones.json").read_text(encoding="utf-8"))

    def test_generated_points_stay_inside_the_zones_own_h3_cell(self) -> None:
        rng = np.random.default_rng(42)
        for zone in self.zones[:10]:
            for _ in range(20):
                lat, lng = random_point_in_zone(zone, rng)
                self.assertEqual(h3.latlng_to_cell(lat, lng, zone["h3_resolution"]), zone["h3_index"])

    def test_points_are_not_all_the_same_centroid(self) -> None:
        rng = np.random.default_rng(7)
        zone = self.zones[0]
        points = {random_point_in_zone(zone, rng) for _ in range(30)}
        self.assertGreater(len(points), 1)


if __name__ == "__main__":
    unittest.main()
