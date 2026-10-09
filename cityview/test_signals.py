import math
import unittest

from cityview.signals import face_dir, face_yaw, pedestrian_signal_yaw, vehicle_signal_yaw


class FaceYawTests(unittest.TestCase):
    def test_local_plus_y_lands_on_requested_facing(self):
        for fx, fy in ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (0.6, -0.8)):
            yaw = face_yaw(fx, fy)
            gx, gy = face_dir(yaw)
            self.assertAlmostEqual(gx, fx / math.hypot(fx, fy), places=6)
            self.assertAlmostEqual(gy, fy / math.hypot(fx, fy), places=6)


class VehicleSignalYawTests(unittest.TestCase):
    def test_head_looks_at_oncoming_traffic(self):
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
        yaw = pedestrian_signal_yaw(0.0, -1.0, 1.0)
        fx, fy = face_dir(yaw)
        self.assertAlmostEqual(fx, 0.0, places=6)
        self.assertAlmostEqual(fy, 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
