"""Analytical equilibrium fixtures, contact semantics and report provenance."""
import copy
import json
import math
from pathlib import Path
import unittest
import numpy as np

from boulderlab.statics import solve_equilibrium, mechanics_report, segment_com, DEFAULT_PARAMETERS
from boulderlab.engine import default_request, propose, evaluate, make_bundle, validate_bundle, _bundle_digest, fingerprint


def contact(point=(0,0,0), axis=(0,1,0), slope=.65, capacity=1000):
    return {"position":list(point),"axis":list(axis),"slope":slope,"capacity_n":capacity}


class EquilibriumTests(unittest.TestCase):
    def test_horizontal_surface_without_friction_supports_weight(self):
        result=solve_equilibrium([contact(slope=0)],[0,1,0],[0,-700,0])
        self.assertEqual(result["status"],"feasible")
        self.assertAlmostEqual(result["capacity_utilization"],.7)
        np.testing.assert_allclose(result["forces"][0]["force"],[0,700,0],atol=1e-8)
        self.assertLess(result["torque_residual_nm"],1e-7)

    def test_lower_capacity_changes_feasibility_without_changing_required_force(self):
        result=solve_equilibrium([contact(capacity=600)],[0,1,0],[0,-700,0])
        self.assertEqual(result["status"],"infeasible")
        self.assertEqual(result["reason"],"declared_axial_capacity_exceeded")
        self.assertAlmostEqual(result["capacity_utilization"],700/600)

    def test_single_contact_cannot_supply_free_moment(self):
        result=solve_equilibrium([contact()],[.3,1,0],[0,-700,0])
        self.assertEqual(result["status"],"infeasible")
        self.assertIsNone(result["capacity_utilization"])

    def test_two_supports_and_release_of_critical_contact(self):
        points=[contact((-.5,0,0),slope=0),contact((.5,0,0),slope=0)]
        balanced=solve_equilibrium(points,[0,1,0],[0,-700,0])
        self.assertEqual(balanced["status"],"feasible")
        self.assertAlmostEqual(balanced["capacity_utilization"],.35)
        self.assertEqual(solve_equilibrium(points[:1],[0,1,0],[0,-700,0])["status"],"infeasible")

    def test_com_outside_passive_supports_is_not_rescued_by_unbounded_tension(self):
        points=[contact((-.5,0,0),slope=0),contact((.5,0,0),slope=0)]
        self.assertEqual(solve_equilibrium(points,[.8,1,0],[0,-700,0])["status"],"infeasible")

    def test_all_outward_vertical_wall_normals_cannot_hang_without_grasp(self):
        points=[contact((-.3,1,0),(0,0,1),.9),contact((.3,0,0),(0,0,1),.9)]
        self.assertEqual(solve_equilibrium(points,[0,.5,.2],[0,-700,0])["status"],"infeasible")

    def test_tilted_plane_friction_threshold(self):
        theta=math.radians(20);normal=[math.sin(theta),math.cos(theta),0]
        for delta,expected in [(-.02,"infeasible"),(.02,"feasible")]:
            result=solve_equilibrium([contact(axis=normal,slope=math.tan(theta)+delta)],[0,1,0],[0,-700,0])
            self.assertEqual(result["status"],expected)

    def test_polygon_is_conservative_not_outer_square(self):
        a=math.pi/8;force=np.array([.49*math.cos(a),1,.49*math.sin(a)])
        result=solve_equilibrium([contact(slope=.5)],[0,0,0],-force)
        self.assertEqual(result["status"],"infeasible")

    def test_world_rotation_covariance(self):
        a=.6;r=np.array([[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1]])
        result=solve_equilibrium([contact(axis=r @ [0,1,0])],r @ [0,1,0],r @ [0,-700,0])
        self.assertEqual(result["status"],"feasible")
        self.assertAlmostEqual(result["capacity_utilization"],.7)

    def test_rotating_contact_without_rotating_gravity_changes_equilibrium(self):
        result=solve_equilibrium([contact(axis=(1,0,0),slope=.1)],[0,0,0],[0,-700,0])
        self.assertEqual(result["status"],"infeasible")

    def test_empty_contact_set_is_unknown(self):
        self.assertEqual(solve_equilibrium([], [0,1,0], [0,-700,0])["status"], "unknown")

    def test_com_segment_weights_sum_to_one(self):
        names=["pelvis","neck"]+[f"{side}_{joint}" for side in ("left","right") for joint in ("shoulder","elbow","wrist","hip","knee","ankle")]
        np.testing.assert_allclose(segment_com({k:[1,2,3] for k in names}),[1,2,3])


class MechanicsReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request=default_request()
        cls.request["mechanics_parameters"]=copy.deepcopy(DEFAULT_PARAMETERS)
        cls.candidate=propose(cls.request)
        cls.evaluation=evaluate(cls.request,cls.candidate)
        cls.bundle=make_bundle(cls.request,[cls.candidate],[cls.evaluation])

    def test_missing_contact_frame_is_unknown_not_force_solution(self):
        report=self.evaluation["mechanics_report"]
        self.assertEqual(report["summary"]["status"],"unknown")
        self.assertEqual(report["summary"]["release_states"],len(self.candidate["events"]))
        self.assertTrue(all(s["status"]=="unknown" for s in report["states"]))

    def test_missing_ik_pose_is_unknown(self):
        report=mechanics_report(self.request,self.candidate,{"fingerprint":"fixture","poses":[]})
        self.assertTrue(all(s["reason"]=="ik_pose_unavailable" for s in report["states"]))

    def test_invalid_frames_preserve_p0_failure_and_unknown_mechanics(self):
        cases=[]
        unknown_inventory=copy.deepcopy(self.candidate)
        unknown_inventory["placements"][0]["inventory_id"]="missing-instance"
        cases.append(unknown_inventory)
        missing_panel=copy.deepcopy(self.candidate)
        missing_panel["placements"][0]["wall_panel_id"]="missing-panel"
        cases.append(missing_panel)
        bad_mount=copy.deepcopy(self.candidate)
        bad_mount["placements"][0]["mount"]={"parent_id":"missing-volume","face_id":"face_1"}
        cases.append(bad_mount)
        for candidate in cases:
            evaluation=evaluate(self.request,candidate)
            self.assertEqual(evaluation["summary"]["status"],"fail")
            report=evaluation["mechanics_report"]
            self.assertEqual(report["summary"]["status"],"unknown")
            self.assertTrue(all(s["reason"]=="contact_geometry_unavailable" for s in report["states"]))

    def test_mechanics_parameters_are_in_fingerprint(self):
        changed=copy.deepcopy(self.request);changed["mechanics_parameters"]["friction_coefficient_foot"]+=.1
        self.assertNotEqual(fingerprint(changed,self.candidate),fingerprint(self.request,self.candidate))

    def test_report_tampering_rejected_after_outer_digest_recalculated(self):
        bundle=copy.deepcopy(self.bundle)
        bundle["evaluations"][0]["mechanics_report"]["summary"]["status"]="feasible"
        bundle["manifest"]["bundle_digest"]=_bundle_digest(bundle)
        with self.assertRaisesRegex(ValueError,"mechanics report mismatch"):
            validate_bundle(bundle)

    def test_report_covers_all_states_and_never_draws_failed_forces(self):
        source=json.loads((Path(__file__).resolve().parents[1]/"fixtures/setting-opposing_sidepulls-bundle.json").read_text())
        request=copy.deepcopy(source["request"]);request["mechanics_parameters"]=copy.deepcopy(DEFAULT_PARAMETERS)
        candidate=source["candidates"][0];report=mechanics_report(request,candidate,source["evaluations"][0])
        self.assertEqual({s["id"] for s in candidate["states"]},{s["state_id"] for s in report["states"]})
        self.assertEqual(report["summary"]["release_states"],len(candidate["events"]))
        for state in report["states"]:
            if state["status"]!="feasible":
                self.assertTrue(all(c["force_world_n"] is None for c in state["contacts"]))
            else:
                self.assertLess(state["force_residual_n"],1e-4)
                self.assertLess(state["torque_residual_nm"],1e-4)
                self.assertTrue(all(c["capacity_margin_n"]>=-1e-4 for c in state["contacts"]))
        failed={s["state_id"] for s in report["states"] if s["status"]=="infeasible"}
        if failed:self.assertIn(report["summary"]["worst_state_id"],failed)


if __name__=="__main__":unittest.main()
