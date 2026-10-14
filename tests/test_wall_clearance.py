"""Exact finite-panel counterexamples; these are not human collision tests."""
import copy
import unittest

import numpy as np

from boulderlab.geometry import panel_frame, wall_basis
from boulderlab.wall_clearance import SEGMENTS, wall_clearance_report
from boulderlab.wall_profiles import panels_for


def joints_at(point):
    return {joint: list(point) for segment in SEGMENTS for joint in segment}


class WallClearanceTests(unittest.TestCase):
    def setUp(self):
        self.scene = {"angle_deg": 0, "wall_panels": panels_for("roof")}

    def torso_crossing(self, x=0, z=.4):
        joints = joints_at([x, 1.8, z])
        joints["neck"] = [x, 2.3, z]
        return joints

    def test_torso_crossing_real_roof_is_rejected_with_independent_intersection(self):
        report = wall_clearance_report(self.scene, self.torso_crossing())
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["segments_checked"], 15)
        hit = next(v for v in report["violations"] if v["segment"] == ["pelvis", "neck"])
        self.assertEqual(hit["panel_id"], "roof")
        self.assertTrue(np.allclose(hit["intersection_world_m"], [0, 2.1, .4]))
        self.assertTrue(np.allclose(hit["intersection_panel_uv_m"], [0, .4]))

    def test_same_height_crossing_beyond_roof_lip_is_not_infinite_plane_collision(self):
        report = wall_clearance_report(self.scene, self.torso_crossing(z=.9))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["violations"], [])

    def test_finite_side_edge_crossing_is_hit_but_just_outside_is_clear(self):
        self.assertEqual(wall_clearance_report(self.scene, self.torso_crossing(x=2.4))["status"], "fail")
        self.assertEqual(wall_clearance_report(self.scene, self.torso_crossing(x=2.401))["status"], "pass")
        self.assertEqual(wall_clearance_report(self.scene, self.torso_crossing(x=100))["status"], "pass")

    def test_contact_endpoint_touch_and_coplanar_segment_are_not_strict_crossings(self):
        joints = self.torso_crossing()
        joints["neck"] = [0, 2.1, .4]
        self.assertEqual(wall_clearance_report(self.scene, joints)["status"], "pass")
        joints = joints_at([0, 2.1, .4])
        joints["neck"] = [.3, 2.1, .4]
        self.assertEqual(wall_clearance_report(self.scene, joints)["status"], "pass")

    def test_millimetre_normal_tolerance_does_not_relax_real_crossing(self):
        joints = joints_at([0, 2.0995, .4]); joints["neck"] = [0, 2.1005, .4]
        self.assertEqual(wall_clearance_report(self.scene, joints)["status"], "pass")
        self.assertEqual(wall_clearance_report(self.scene, joints, tolerance_m=.0001)["status"], "fail")
        joints = joints_at([0, 2.098, .4]); joints["neck"] = [0, 2.102, .4]
        self.assertEqual(wall_clearance_report(self.scene, joints)["status"], "fail")

    def test_rotating_entire_structure_and_pose_preserves_hits(self):
        original = wall_clearance_report(self.scene, self.torso_crossing())
        scene = copy.deepcopy(self.scene); scene["angle_deg"] = 23
        rotation = wall_basis(23)
        joints = {k: (rotation @ v).tolist() for k, v in self.torso_crossing().items()}
        report = wall_clearance_report(scene, joints)
        self.assertEqual(report["status"], original["status"])
        self.assertEqual([(v["panel_id"], v["segment"], v["intersection_panel_uv_m"]) for v in report["violations"]],
                         [(v["panel_id"], v["segment"], v["intersection_panel_uv_m"]) for v in original["violations"]])

    def test_corner_uses_its_real_yawed_plane_and_finite_extent(self):
        for profile in ("dihedral", "arete"):
            scene = {"angle_deg": 17, "wall_panels": panels_for(profile)}
            panel = scene["wall_panels"][0]
            origin, rotation = panel_frame(panel, scene["angle_deg"])
            joints = joints_at((origin+rotation @ [0, 1, .15]).tolist())
            joints["neck"] = (origin+rotation @ [0, 1.3, -.15]).tolist()
            report = wall_clearance_report(scene, joints)
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any(v["panel_id"] == panel["id"] and v["segment"] == ["pelvis", "neck"] for v in report["violations"]))

    def test_missing_or_nonfinite_pose_is_unknown(self):
        joints = self.torso_crossing(); joints.pop("neck")
        self.assertEqual(wall_clearance_report(self.scene, joints)["status"], "unknown")
        joints = self.torso_crossing(); joints["neck"][0] = float("nan")
        self.assertEqual(wall_clearance_report(self.scene, joints)["status"], "unknown")
        self.assertEqual(wall_clearance_report(self.scene, None)["status"], "unknown")

    def test_missing_panels_does_not_invent_a_wall_or_clearance_claim(self):
        self.assertEqual(wall_clearance_report({"angle_deg": 0}, self.torso_crossing())["status"], "not_checked")
        for value in (-1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                wall_clearance_report(self.scene, self.torso_crossing(), tolerance_m=value)


if __name__ == "__main__":
    unittest.main()
