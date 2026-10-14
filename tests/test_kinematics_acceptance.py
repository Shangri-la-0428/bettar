import math

import numpy as np
import pytest

from boulderlab.engine import default_request
from boulderlab.kinematics import forward_kinematics, solve_pose


ENDPOINTS = {"LH": "left_wrist", "RH": "right_wrist",
             "LF": "left_ankle", "RF": "right_ankle"}


def independent_bone_checks(body, joints):
    j = {name: np.asarray(position, dtype=float) for name, position in joints.items()}
    for side in ("left", "right"):
        for a, b, field in (("shoulder", "elbow", "upper_arm"), ("elbow", "wrist", "forearm"),
                            ("hip", "knee", "thigh"), ("knee", "ankle", "shin")):
            assert np.linalg.norm(j[f"{side}_{a}"] - j[f"{side}_{b}"]) == pytest.approx(body[field], abs=1e-7)
    for a, b, field in (("left_shoulder", "right_shoulder", "shoulder_width"),
                        ("left_hip", "right_hip", "hip_width"), ("pelvis", "neck", "torso")):
        assert np.linalg.norm(j[a] - j[b]) == pytest.approx(body[field], abs=1e-7)
    for side in ("left", "right"):
        for a, b, c, field in (("shoulder", "elbow", "wrist", "elbow"), ("hip", "knee", "ankle", "knee")):
            first = j[f"{side}_{b}"] - j[f"{side}_{a}"]
            second = j[f"{side}_{c}"] - j[f"{side}_{b}"]
            cosine = np.dot(first, second) / np.linalg.norm(first) / np.linalg.norm(second)
            angle = math.degrees(math.acos(np.clip(cosine, -1, 1)))
            low, high = body["joint_limits_deg"][field]
            assert low - 1e-5 <= angle <= high + 1e-5


@pytest.mark.parametrize("profile", ["A", "B"])
def test_ac05_neutral_fk_matches_hand_calculated_coordinates(profile):
    body = default_request(body_id=profile)["body"]
    q = np.zeros(22)
    q[:3] = [0.1, 1.1, 0.4]
    joints = forward_kinematics(body, q)
    root = np.asarray(q[:3])
    assert np.asarray(joints["pelvis"]) == pytest.approx(root)
    assert np.asarray(joints["neck"]) == pytest.approx(root + [0, body["torso"], 0])
    for side, sign in (("left", -1), ("right", 1)):
        shoulder = root + [sign * body["shoulder_width"] / 2, body["torso"], 0]
        hip = root + [sign * body["hip_width"] / 2, 0, 0]
        assert np.asarray(joints[f"{side}_shoulder"]) == pytest.approx(shoulder)
        assert np.asarray(joints[f"{side}_wrist"]) == pytest.approx(shoulder + [0, body["upper_arm"] + body["forearm"], 0])
        assert np.asarray(joints[f"{side}_ankle"]) == pytest.approx(hip + [0, -body["thigh"] - body["shin"], 0])
    independent_bone_checks(body, joints)


@pytest.mark.parametrize("profile", ["A", "B"])
def test_ac05_real_ik_returns_independently_checkable_solution(profile):
    request = default_request(body_id=profile)
    body, solver = request["body"], request["solver"]
    known_q = np.zeros(22)
    known_q[:3] = [0, 1.1, 0.4]
    known_q[9] = known_q[13] = math.radians(25)
    known_q[17] = known_q[21] = math.radians(20)
    targets = {limb: forward_kinematics(body, known_q)[joint] for limb, joint in ENDPOINTS.items()}
    initial = known_q.copy()
    initial[:3] += [0.04, -0.03, 0.02]
    initial[6:] += 0.025
    assert not np.allclose(initial, known_q)
    result = solve_pose(body, targets, solver, seed=7, initial=initial)
    assert result["status"] == "pass", result
    independent_bone_checks(body, result["joints"])
    q = np.asarray(result["q"])
    assert q.shape == (22,) and np.isfinite(q).all()
    for i, (lower, upper) in enumerate(solver["root_bounds"]):
        assert lower - 1e-7 <= q[i] <= upper + 1e-7
    for i, (lower, upper) in enumerate(solver["root_rotation_deg"]):
        assert lower - 1e-5 <= math.degrees(q[3 + i]) <= upper + 1e-5
    for start, joint, bend in ((6, "shoulder", "elbow"), (10, "shoulder", "elbow"),
                               (14, "hip", "knee"), (18, "hip", "knee")):
        limits = body["joint_limits_deg"][joint] + [body["joint_limits_deg"][bend]]
        for i, (lower, upper) in enumerate(limits):
            assert lower - 1e-5 <= math.degrees(q[start + i]) <= upper + 1e-5
    # Endpoint offsets are zero in both frozen test profiles.
    errors = [np.linalg.norm(np.asarray(result["joints"][ENDPOINTS[limb]]) - target)
              for limb, target in targets.items()]
    assert max(errors) <= solver["contact_tolerance_m"] + 1e-8
    assert result["residual_m"] == pytest.approx(max(errors), abs=1e-7)


def test_ac07_ik_budget_exhaustion_is_unknown():
    request = default_request()
    request["solver"]["max_nfev"] = 0
    result = solve_pose(request["body"], {"LH": [0, 2, 0.1]}, request["solver"])
    assert result["status"] == "unknown"
    assert not result.get("joints")


def test_ac07_numerical_failure_is_unknown(monkeypatch):
    import boulderlab.kinematics as kinematics

    def broken_solver(*args, **kwargs):
        raise FloatingPointError("acceptance injected numerical failure")

    monkeypatch.setattr(kinematics, "least_squares", broken_solver)
    request = default_request()
    result = kinematics.solve_pose(request["body"], {"LH": [0, 2, 0.1]}, request["solver"])
    assert result["status"] == "unknown"
    assert not result.get("joints")
    assert result.get("evidence")


def test_ac07_time_budget_exhaustion_is_unknown():
    request = default_request()
    request["solver"]["timeout_seconds"] = 0
    result = solve_pose(request["body"], {"LH": [0, 2, 0.1]}, request["solver"])
    assert result["status"] == "unknown"
    assert not result.get("joints")
