import math
import unittest

from cityview.signals import (
    face_dir,
    face_yaw,
    junction_approaches,
    pedestrian_signal_yaw,
    vehicle_signal_yaw,
    zebra_bars,
)


class FaceYawTests(unittest.TestCase):
    def test_local_plus_y_lands_on_requested_facing(self):
        for fx, fy in ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (0.6, -0.8)):
            yaw = face_yaw(fx, fy)
            gx, gy = face_dir(yaw)
            self.assertAlmostEqual(gx, fx / math.hypot(fx, fy), places=6)
            self.assertAlmostEqual(gy, fy / math.hypot(fx, fy), places=6)


class VehicleSignalYawTests(unittest.TestCase):
    def test_head_looks_at_oncoming_traffic(self):
        # Traffic inbound +X (eastbound toward junction): lenses face west (−X).
        yaw = vehicle_signal_yaw(1.0, 0.0)
        fx, fy = face_dir(yaw)
        self.assertAlmostEqual(fx, -1.0, places=6)
        self.assertAlmostEqual(fy, 0.0, places=6)

    def test_northbound_approach_faces_south(self):
        yaw = vehicle_signal_yaw(0.0, 1.0)
        fx, fy = face_dir(yaw)
        self.assertAlmostEqual(fx, 0.0, places=6)
        self.assertAlmostEqual(fy, -1.0, places=6)


class PedestrianSignalYawTests(unittest.TestCase):
    def test_right_curb_faces_across_the_carriageway(self):
        # Eastbound: right curb south (rx, ry)=(0,-1); face into the road (+Y).
        yaw = pedestrian_signal_yaw(0.0, -1.0, 1.0)
        fx, fy = face_dir(yaw)
        self.assertAlmostEqual(fx, 0.0, places=6)
        self.assertAlmostEqual(fy, 1.0, places=6)


class ZebraLayoutTests(unittest.TestCase):
    def test_bars_are_centred_across_the_carriageway(self):
        bars = zebra_bars(6.0)
        self.assertGreaterEqual(len(bars), 3)
        self.assertAlmostEqual(sum(bars) / len(bars), 0.0, places=6)
        self.assertLess(max(abs(b) for b in bars) + 0.25, 3.0)

    def test_crossing_arms_set_zebra_clear_of_the_junction(self):
        roads = [
            {"kind": "residential", "width": 6.0, "points": [[-20, 0], [20, 0]]},
            {"kind": "residential", "width": 6.0, "points": [[0, -20], [0, 20]]},
        ]
        arms = junction_approaches(0.0, 0.0, roads)
        self.assertEqual(len(arms), 4)
        for ap in arms:
            # Zebra sits past the crossing road's kerb, not on top of the junction.
            along = ap["ax"] * ap["tx"] + ap["ay"] * ap["ty"]  # 0 at junction for these roads
            zebra_along = (ap["zebra_x"] - ap["ax"]) * ap["tx"] + (ap["zebra_y"] - ap["ay"]) * ap["ty"]
            self.assertLess(zebra_along, -3.0)
            stop_along = (ap["stop_x"] - ap["ax"]) * ap["tx"] + (ap["stop_y"] - ap["ay"]) * ap["ty"]
            self.assertLess(stop_along, zebra_along)


if __name__ == "__main__":
    unittest.main()
