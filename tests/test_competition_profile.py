"""Competition-inspired templates obey the same geometry and evidence boundary."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from boulderlab.engine import (contact_world, default_request, evaluate, generate,
                              propose, validate_bundle, validate_request, wall_basis)

ROOT = Path(__file__).resolve().parents[1]


def study(angle=0, mode="free"):
    request = default_request(profile="competition", angle_deg=angle, mode=mode)
    request["solver"]["max_nfev"] = 0
    return request


def result(report, check):
    return [c for c in report["checks"] if c["id"] == check]


def test_basic_default_remains_the_original_fixture():
    expected = json.loads((ROOT / "fixtures/default-request.json").read_text())
    assert default_request() == expected == default_request(profile="basic")
    assert (expected["scene"]["width"], expected["scene"]["height"], expected["hand_moves"]) == (3, 3, 2)
    assert len(expected["scene"]["inventory"]) == 16


@pytest.mark.parametrize("angle", [0, 10])
def test_profile_has_sparse_scaled_inventory_and_shared_contact_contract(angle):
    request = study(angle)
    assert validate_request(request) is request
    assert request["hand_moves"] == 4 and request["scenario"] == "competition_sequence"
    assert (request["scene"]["width"], request["scene"]["height"]) == (4.8, 4.2)
    inventory = request["scene"]["inventory"]
    assert len(inventory) == len(request["reference_layout"]) == 12
    assert {h["type"] for h in inventory} == {"sloper", "pinch", "rail", "volume", "foothold"}
    for item in inventory:
        assert item["contact"]["position"] == [0, 0, item["depth"]]
    assert min(h["width"] for h in inventory if h["type"] == "volume") >= .7
    assert max(h["width"] for h in inventory if h["type"] == "foothold") <= .12
    candidate = propose(request)
    report = evaluate(request, candidate)
    for check in ("schema", "inventory", "boundary", "hold_collision", "request_conformance"):
        assert {c["status"] for c in result(report, check)} == {"pass"}
    xs = [p["u"] for p in candidate["placements"]]
    ys = [p["v"] for p in candidate["placements"]]
    assert max(xs) - min(xs) > 2.5 and max(ys) - min(ys) > 3


@pytest.mark.parametrize("edit", ["hand_count", "wall_size", "scenario", "unknown_marker", "reversed_phase", "metadata_extension"])
def test_profile_schema_and_brief_reject_inconsistent_contract(edit):
    request = study()
    if edit == "hand_count":
        request["hand_moves"] = 3
    elif edit == "wall_size":
        request["scene"]["width"] = 3
    elif edit == "scenario":
        request["scenario"] = "foot_first"
    elif edit == "unknown_marker":
        request["design_brief"]["top_placement_ids"] = ["missing"]
    elif edit == "reversed_phase":
        request["design_brief"]["phases"][0].update(event_start=5, event_end=1)
    else:
        request["design_brief"]["validated_grade"] = "world-class"
    with pytest.raises(ValueError):
        validate_request(request)


def test_tilted_wall_contact_transform_and_rotated_macro_boundary():
    request = study(10)
    candidate = propose(request)
    item = next(h for h in request["scene"]["inventory"] if h["id"] == "volume_01")
    placement = next(p for p in candidate["placements"] if p["id"] == "volume_01")
    world = contact_world(request, placement, item)
    assert np.allclose(world, wall_basis(10) @ [placement["u"], placement["v"], item["depth"]])
    # Center remains legal; its full rotated macro footprint crosses the margin.
    placement.update(u=2.02, v=2.0, rotation_deg=45)
    report = evaluate(request, candidate)
    boundary = result(report, "boundary")[0]
    assert boundary["status"] == "fail" and "volume_01" in boundary["placement_ids"]


def test_sequence_uses_four_distinct_hand_transfers_and_intervening_feet():
    request = study()
    candidate = propose(request)
    assert [event["limb"] for event in candidate["events"]] == ["LF", "RH", "RF", "LH", "LF", "RH", "RF", "LH"]
    assert len(candidate["states"]) == 17
    expected_targets = ["volume_01", "sloper_01", "foothold_03", "pinch_02", "foothold_04", "sloper_02", "foothold_05", "rail_02"]
    actual = [candidate["states"][2*i+2]["contacts"][e["limb"]]["placement_id"] for i, e in enumerate(candidate["events"])]
    assert actual == expected_targets
    final = candidate["states"][-1]["contacts"]
    assert final["LH"] != final["RH"]
    assert {final[l]["placement_id"] for l in ("LH", "RH")} == set(request["design_brief"]["top_placement_ids"])
    check = result(evaluate(request, candidate), "request_conformance")[0]
    assert check["evidence"] == {"hand_moves": 4, "foot_moves": 4}
    # Preserve counts, references and endpoints but change the first foot target:
    # the declared competition phase is a constraint, not a descriptive bypass.
    for state in candidate["states"][2:9]:
        state["contacts"]["LF"] = deepcopy(request["start_contacts"]["RF"])
    assert result(evaluate(request, candidate), "request_conformance")[0]["status"] == "fail"


def test_variants_are_reproducible_and_fixed_mode_retains_layout():
    request = study()
    variants = [propose(request, i) for i in range(3)]
    assert variants == [propose(deepcopy(request), i) for i in range(3)]
    assert len({json.dumps(c["placements"], sort_keys=True) for c in variants}) == 3
    assert variants[0]["states"] == variants[1]["states"] == variants[2]["states"]
    for candidate in variants:
        report = evaluate(request, candidate)
        assert result(report, "boundary")[0]["status"] == "pass"
        assert result(report, "hold_collision")[0]["status"] == "pass"
    fixed = study(mode="fixed")
    assert all(propose(fixed, i)["placements"] == fixed["reference_layout"] for i in range(3))


def test_unknown_and_failed_attempts_are_retained_with_all_p1_unchecked():
    request = study()
    # Deliberate editable bad layout, without invalidating contact references.
    request["reference_layout"][0]["u"] = -2.15
    bundle = generate(request)
    assert bundle["manifest"]["attempted_candidates"] == bundle["manifest"]["evaluation_count"] == request["budget"] == 3
    assert all(e["summary"]["status"] == "fail" for e in bundle["evaluations"])
    for evaluation in bundle["evaluations"]:
        assert all(c["status"] == "not_checked" for c in evaluation["checks"] if c.get("scope") == "P1")
        assert all(not p.get("joints") for p in evaluation["poses"])
    validate_bundle(bundle)
    known_geometry = generate(study())
    assert all(e["summary"]["status"] == "unknown" for e in known_geometry["evaluations"])


@pytest.mark.parametrize("name", ["demo-bundle.json", "competition-demo-bundle.json"])
def test_served_demo_bundles_match_current_engine(name):
    validate_bundle(json.loads((ROOT / "fixtures" / name).read_text()))
