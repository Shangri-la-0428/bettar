from copy import deepcopy
import math

import pytest

from boulderlab.engine import contact_world, evaluate, fingerprint
from conftest import assert_status, checks


def test_ac01_ac02_ac16_valid_manual_example(example):
    request, candidate = example
    report = evaluate(request, candidate)
    for identifier in ("schema", "inventory", "request_conformance", "boundary", "hold_collision"):
        assert_status(report, identifier, "pass")


@pytest.mark.parametrize("mutation", [
    lambda r, c: r.update(schema_version="99.0"),
    lambda r, c: r.pop("scene"),
    lambda r, c: r["scene"].update(width="3 m"),
    lambda r, c: r["scene"].update(height=float("nan")),
    lambda r, c: r["scene"].update(width=-3),
    lambda r, c: r.update(hand_moves=5),
    lambda r, c: r.update(budget=2.5),
    lambda r, c: r["body"].update(upper_arm=float("inf")),
    lambda r, c: c["placements"][0].update(u=float("nan")),
    lambda r, c: c["placements"][0].update(rotation_deg=float("inf")),
])
def test_ac01_malformed_input_is_rejected(example, mutation):
    request, candidate = example
    mutation(request, candidate)
    try:
        report = evaluate(request, candidate)
    except ValueError as error:
        assert str(error).strip()
    else:
        assert_status(report, "schema", "fail")


@pytest.mark.parametrize("kind", ["missing_inventory", "double_use", "duplicate_placement_id"])
def test_ac02_inventory_errors(example, kind):
    request, candidate = example
    if kind == "missing_inventory":
        candidate["placements"][0]["inventory_id"] = "not-in-inventory"
    elif kind == "double_use":
        candidate["placements"][1]["inventory_id"] = candidate["placements"][0]["inventory_id"]
    else:
        candidate["placements"][1]["id"] = candidate["placements"][0]["id"]
    report = evaluate(request, candidate)
    assert any(c["status"] == "fail" for c in report["checks"]
               if c["id"] in {"schema", "inventory"}), report


@pytest.mark.parametrize("delta,expected", [(0, "pass"), (-0.01, "pass"), (0.01, "fail")])
def test_ac03_whole_hold_boundary(example, delta, expected):
    request, candidate = example
    # Hand-calculated right installation limit: 1.5 - .2 - .12/2 = 1.24.
    candidate["placements"][0]["u"] = 1.24 + delta
    assert_status(evaluate(request, candidate), "boundary", expected)


def test_ac03_rotation_changes_whole_box_extent(example):
    request, candidate = example
    placement = candidate["placements"][0]
    hold = next(h for h in request["scene"]["inventory"] if h["id"] == placement["inventory_id"])
    hold.update(width=0.4, height=0.12)
    placement.update(u=1.20, rotation_deg=0)
    assert_status(evaluate(request, candidate), "boundary", "fail")
    placement["rotation_deg"] = 90
    assert_status(evaluate(request, candidate), "boundary", "pass")


def test_ac03_contact_transform_combines_wall_tilt_and_hold_rotation(example):
    request, candidate = example
    request["scene"]["angle_deg"] = 10
    placement = candidate["placements"][0]
    placement.update(u=0.3, v=1.4, rotation_deg=90)
    hold = next(h for h in request["scene"]["inventory"] if h["id"] == placement["inventory_id"])
    hold["contact"]["position"] = [0.1, 0.2, 0.08]
    angle = math.radians(10)
    expected = [0.1, 1.5 * math.cos(angle) - 0.08 * math.sin(angle),
                1.5 * math.sin(angle) + 0.08 * math.cos(angle)]
    assert list(contact_world(request, placement, hold)) == pytest.approx(expected, abs=1e-10)


def test_ac08_direction_metadata_changes_dependencies_but_not_force_claim(example):
    request, candidate = example
    hold = request["scene"]["inventory"][0]
    previous = fingerprint(request, candidate)
    hold["pull_direction"] = [1, 0, 0]
    candidate["placements"][0]["rotation_deg"] = 90
    assert fingerprint(request, candidate) != previous
    report = evaluate(request, candidate)
    assert_status(report, "force", "not_checked")
    assert_status(report, "grade_experience", "not_checked")


@pytest.mark.parametrize("gap,expected", [(0.02, "pass"), (0, "fail"), (-0.01, "fail"), (0.5e-6, "fail")])
def test_ac04_touch_and_overlap_are_conflicts(example, gap, expected):
    request, candidate = example
    candidate["placements"][0].update(u=-0.8, v=1.1)
    candidate["placements"][1].update(u=-0.8 + 0.12 + gap, v=1.1)
    assert_status(evaluate(request, candidate), "hold_collision", expected)


def test_ac06_excessive_hand_span_has_hard_evidence(example):
    request, candidate = example
    body = request["body"]
    body["upper_arm"] = body["forearm"] = 0.1
    body["shoulder_width"] = 0.1
    candidate["placements"][0]["u"] = -0.8
    candidate["placements"][1]["u"] = 0.8
    report = evaluate(request, candidate)
    failures = [c for c in checks(report, "hand_span") if c["status"] == "fail"]
    assert failures
    assert any(c.get("evidence") for c in failures), failures


def test_ac06_endpoint_offsets_are_included_in_upper_bound(example):
    request, candidate = example
    body = request["body"]
    body.update(upper_arm=0.1, forearm=0.1, shoulder_width=0.1)
    candidate["placements"][0]["u"] = -0.65
    candidate["placements"][1]["u"] = 0.65
    assert any(c["status"] == "fail" for c in checks(evaluate(request, candidate), "hand_span"))
    body["endpoint_offsets"].update(LH=[0.4, 0, 0], RH=[-0.4, 0, 0])
    # d=1.3; conservative B=.1 + 2*(.1+.1) + .4+.4 + 2*.015=1.33.
    # Passing this bound must still leave IK unknown, not prove reachability.
    report = evaluate(request, candidate)
    assert_status(report, "hand_span", "pass")
    assert_status(report, "ik", "unknown")


def test_ac07_zero_budget_is_unknown_not_impossible(example):
    report = evaluate(*example)
    assert_status(report, "ik", "unknown")
    assert report["summary"]["status"] != "pass"
    assert all(not pose.get("joints") for pose in report["poses"]), report["poses"]


def test_ac08_unimplemented_checks_remain_visible(example):
    report = evaluate(*example)
    for identifier in ("force", "balance", "body_collision", "transition", "grade_experience"):
        assert_status(report, identifier, "not_checked")


@pytest.mark.parametrize("field,change", [("u", 0.05), ("rotation_deg", 15)])
def test_ac15_fixed_layout_cannot_move_or_rotate(example, field, change):
    request, candidate = example
    request["mode"] = "fixed"
    assert_status(evaluate(request, candidate), "fixed_layout", "pass")
    candidate["placements"][0][field] += change
    assert_status(evaluate(request, candidate), "fixed_layout", "fail")


@pytest.mark.parametrize("kind", ["unknown_contact", "wrong_limb", "wrong_finish", "wrong_start",
                                     "hand_count", "hidden_limb_change", "not_released", "broken_chain",
                                     "empty_states", "missing_limb"])
def test_ac16_sequence_and_request_violations(example, kind):
    request, candidate = example
    if kind == "unknown_contact":
        candidate["states"][0]["contacts"]["LH"]["contact_id"] = "nonexistent"
    elif kind == "wrong_limb":
        used = candidate["placements"][0]["inventory_id"]
        next(h for h in request["scene"]["inventory"] if h["id"] == used)["contact"]["limbs"] = ["LF", "RF"]
    elif kind == "wrong_finish":
        request["end_contacts"]["LH"] = deepcopy(request["start_contacts"]["LH"])
    elif kind == "wrong_start":
        request["start_contacts"]["LH"] = deepcopy(request["end_contacts"]["LH"])
    elif kind == "hand_count":
        request["hand_moves"] = 3  # Fixture completes exactly two hand transfers.
    elif kind == "hidden_limb_change":
        candidate["states"][1]["contacts"]["RH"] = deepcopy(candidate["states"][0]["contacts"]["LH"])
    elif kind == "not_released":
        candidate["states"][1]["contacts"]["LF"] = deepcopy(candidate["states"][0]["contacts"]["LF"])
    elif kind == "broken_chain":
        candidate["events"][1]["from_state"] = "s0"
    elif kind == "empty_states":
        candidate["states"] = []
        candidate["events"] = []
    else:
        candidate["states"][0]["contacts"].pop("RF")
    report = evaluate(request, candidate)
    assert any(c["status"] == "fail" for c in report["checks"]
               if c["id"] in {"schema", "request_conformance"}), report


def test_ac16_foot_first_requires_actual_relocation_not_release_regrab(example):
    request, candidate = example
    original = deepcopy(candidate["states"][0]["contacts"]["LF"])
    for state in candidate["states"][2:]:
        state["contacts"]["LF"] = deepcopy(original)
    request["end_contacts"] = deepcopy(candidate["states"][-1]["contacts"])
    report = evaluate(request, candidate)
    assert_status(report, "request_conformance", "fail")


def test_ac16_same_hand_release_regrab_is_not_a_completed_transfer(example):
    request, candidate = example
    original = deepcopy(candidate["states"][0]["contacts"]["RH"])
    for state in candidate["states"][4:]:
        state["contacts"]["RH"] = deepcopy(original)
    request["end_contacts"] = deepcopy(candidate["states"][-1]["contacts"])
    report = evaluate(request, candidate)
    assert_status(report, "request_conformance", "fail")
