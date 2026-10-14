"""Wall evidence remains independently required after a bundle is re-signed."""
from copy import deepcopy
from unittest.mock import patch

import numpy as np
import pytest

from boulderlab.engine import evaluate, make_bundle
from boulderlab.kinematics import forward_kinematics


def with_panel(example):
    request, candidate = deepcopy(example)
    request["scene"]["wall_panels"] = [{
        "id": "panel", "label": "test wall", "origin": [0, 0, 0],
        "rotation_deg": [0, 0, 0], "width": 3, "height": 3,
    }]
    for placements in (request["reference_layout"], candidate["placements"]):
        for placement in placements:
            placement["wall_panel_id"] = "panel"
    return request, candidate


def resummarize(evaluation):
    checks = [c for c in evaluation["checks"] if c.get("scope") != "P1"]
    evaluation["summary"] = {
        "status": "fail" if any(c["status"] == "fail" for c in checks) else
                  "pass" if all(c["status"] == "pass" for c in checks) else "unknown",
        "passed": sum(c["status"] == "pass" for c in checks), "total": len(checks),
    }


def test_missing_pose_cannot_claim_wall_clearance(example):
    request, candidate = with_panel(example)
    report = evaluate(request, candidate)
    checks = [c for c in report["checks"] if c["id"] == "skeleton_wall"]
    assert len(checks) == len(candidate["states"])
    assert all(c["status"] == "unknown" for c in checks)
    make_bundle(request, [candidate], [report])


@pytest.mark.parametrize("mutation", ["remove", "pass", "evidence", "exclude_from_p0"])
def test_re_signed_bundle_cannot_drop_or_forge_wall_checks(example, mutation):
    request, candidate = with_panel(example)
    report = evaluate(request, candidate)
    wall = next(c for c in report["checks"] if c["id"] == "skeleton_wall")
    if mutation == "remove":
        report["checks"].remove(wall)
    elif mutation == "pass":
        wall["status"] = "pass"
    elif mutation == "evidence":
        wall["evidence"] = {"reason": "no_collision"}
    else:
        wall["scope"] = "P1"
    resummarize(report)
    with pytest.raises(ValueError, match="skeleton-wall|P0 check"):
        make_bundle(request, [candidate], [report])


def test_evaluator_recomputes_wall_crossing_instead_of_trusting_ik_evidence(example):
    request, candidate = with_panel(example)
    q = np.zeros(22)
    q[:3] = [0, 1.2, .1]
    q[3] = np.deg2rad(-45)  # Pelvis is in front; neck passes through the wall.
    joints = {k: v.tolist() for k, v in forward_kinematics(request["body"], q).items()}
    fake_solver_result = {"status": "pass", "q": q.tolist(), "joints": joints,
                          "residual_m": 0., "evidence": {"wall_clearance": {"status": "pass"}}}
    # Isolate the independent evaluator from a buggy optimizer's success flag.
    # This deliberately mocked pose is not claimed as a valid contact solution.
    with patch("boulderlab.engine.solve_pose", side_effect=lambda *a, **k: deepcopy(fake_solver_result)):
        report = evaluate(request, candidate)
    checks = [c for c in report["checks"] if c["id"] == "skeleton_wall"]
    assert checks and all(c["status"] == "fail" for c in checks)
    assert any(v["segment"] == ["pelvis", "neck"] for v in checks[0]["evidence"]["violations"])
    assert report["summary"]["status"] == "fail"
