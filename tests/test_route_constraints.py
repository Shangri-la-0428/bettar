"""A route's selected contacts never replace the physical wall inventory."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from boulderlab import beta_audit
from boulderlab.engine import _validate_evaluation, evaluate, fingerprint, make_bundle, validate_bundle, validate_request
from boulderlab.route_constraints import allowed_contact_ids, constraint_errors
from conftest import assert_status, checks


def select_all(request, candidate):
    request["route_constraints"] = {"allowed_contacts": {
        limb: sorted(ids) for limb, ids in allowed_contact_ids(request, candidate["placements"]).items()
    }}
    return request["route_constraints"]["allowed_contacts"]


def add_intermediate_hand_move(request, candidate):
    """Add RH -> h4 before RH -> h3; LH still finishes on h4."""
    moves = [("LF", "f3"), ("RH", "h4"), ("RH", "h3"), ("LH", "h4")]
    updated = beta_audit._make_candidate(candidate, moves, "fewer_transfers")
    request["hand_moves"] = 3
    return updated


def test_absent_mask_and_all_mask_have_same_contact_permissions(example):
    request, candidate = example
    before = allowed_contact_ids(request, candidate["placements"])
    original = evaluate(request, candidate)
    select_all(request, candidate)
    assert before == allowed_contact_ids(request, candidate["placements"])
    restricted = evaluate(request, candidate)
    assert restricted["checks"] == json.loads(json.dumps(original["checks"]).replace(original["fingerprint"], restricted["fingerprint"]))
    assert restricted["poses"] == original["poses"]
    validate_bundle(make_bundle(request, [candidate], evaluations=[restricted]))


def test_mask_cannot_grant_a_surface_new_limb_permissions(example):
    request, candidate = example
    mask = select_all(request, candidate)
    assert "f1" not in mask["LH"]
    mask["LH"].append("f1")
    assert "f1" not in allowed_contact_ids(request, candidate["placements"])["LH"]
    request["start_contacts"]["LH"] = {"placement_id": "f1", "contact_id": "main"}
    with pytest.raises(ValueError, match="surface permissions"):
        validate_request(request)


@pytest.mark.parametrize("limb", ("LH", "RH", "LF", "RF"))
def test_all_four_masks_are_required_and_empty_mask_rejects_required_start(example, limb):
    request, candidate = example
    mask = select_all(request, candidate)
    old = mask.pop(limb)
    with pytest.raises(ValueError, match="required property"):
        validate_request(request)
    mask[limb] = []
    with pytest.raises(ValueError, match="start_contacts"):
        validate_request(request)
    mask[limb] = old
    validate_request(request)


@pytest.mark.parametrize("anchor", ("start_contacts", "end_contacts"))
def test_required_anchors_must_be_selected(example, anchor):
    request, candidate = example
    mask = select_all(request, candidate)
    mask["LH"].remove(request[anchor]["LH"]["placement_id"])
    with pytest.raises(ValueError, match=anchor):
        validate_request(request)


def test_unknown_ids_checked_against_reference_and_candidate_geometry(example):
    request, candidate = example
    mask = select_all(request, candidate)
    mask["LH"].append("missing")
    with pytest.raises(ValueError, match="unknown placement IDs missing"):
        validate_request(request)
    # A reference selection can still disappear from a free-layout candidate.
    request["reference_layout"].append({**candidate["placements"][0], "id": "missing"})
    validate_request(request)
    report = evaluate(request, candidate)
    assert_status(report, "request_conformance", "fail")
    assert "unknown placement IDs missing" in checks(report, "request_conformance")[0]["detail"]


def test_denied_intermediate_contact_fails_evaluation_and_import(example):
    request, original = example
    candidate = add_intermediate_hand_move(request, original)
    assert_status(evaluate(request, candidate), "request_conformance", "pass")
    mask = select_all(request, candidate)
    mask["RH"].remove("h4")
    validate_request(request)  # Both requested anchors are still selected.
    report = evaluate(request, candidate)
    assert_status(report, "request_conformance", "fail")
    assert "RH contact h4 excluded" in checks(report, "request_conformance")[0]["detail"]
    # Embedded baseline/alternative reports enter through this same validator.
    with pytest.raises(ValueError, match="RH contact h4 excluded"):
        _validate_evaluation(request, candidate, report)
    for evaluations in ([], [report]):
        with pytest.raises(ValueError, match="RH contact h4 excluded"):
            validate_bundle(make_bundle(request, [candidate], evaluations=evaluations))


def test_unselected_hold_remains_a_physical_collision_obstacle(example):
    request, candidate = example
    mask = select_all(request, candidate)
    unused = next(h for h in request["scene"]["inventory"]
                  if h["id"] not in {p["inventory_id"] for p in candidate["placements"]})
    obstacle = {**candidate["placements"][0], "id": "unselected-obstacle", "inventory_id": unused["id"]}
    candidate["placements"].append(obstacle)
    request["reference_layout"].append(deepcopy(obstacle))
    assert all("unselected-obstacle" not in ids for ids in mask.values())
    report = evaluate(request, candidate)
    assert_status(report, "request_conformance", "pass")
    assert_status(report, "hold_collision", "fail")
    assert "unselected-obstacle" in str(checks(report, "hold_collision"))
    assert len(candidate["placements"]) == 8


def test_mask_membership_changes_fingerprint_but_list_order_does_not(example):
    request, candidate = example
    original = fingerprint(request, candidate)
    mask = select_all(request, candidate)
    selected = fingerprint(request, candidate)
    assert original != selected
    for ids in mask.values():
        ids.reverse()
    assert fingerprint(request, candidate) == selected
    mask["RH"].remove("h4")
    assert fingerprint(request, candidate) != selected


def test_search_filters_targets_but_retains_full_geometry_context(monkeypatch):
    bundle = json.loads((Path(__file__).resolve().parents[1] / "fixtures/wall-overhang-bundle.json").read_text())
    request, candidate = bundle["request"], bundle["candidates"][0]
    all_ids = {p["id"] for p in candidate["placements"]}
    all_allowed = allowed_contact_ids(request, candidate["placements"])
    mask = {limb: sorted({refs[limb]["placement_id"] for refs in
                         (request["start_contacts"], request["end_contacts"]) if refs[limb]})
            for limb in beta_audit.LIMBS}
    mask["LH"].append(request["start_contacts"]["RH"]["placement_id"])
    mask["RH"].append(request["start_contacts"]["LH"]["placement_id"])
    request["route_constraints"] = {"allowed_contacts": mask}
    assert any(set(mask[l]) < all_allowed[l] for l in beta_audit.LIMBS)
    assert not constraint_errors(request, candidate["placements"])
    attempted = []

    def observed_step(req, context, before, limb, target, load):
        assert set(context) == all_ids
        attempted.append((limb, target))
        return None, 0., {}, 0., 0., 1., {"proxy_penalty": 0.}

    monkeypatch.setattr(beta_audit, "_step", observed_step)
    monkeypatch.setattr(beta_audit, "_valid_contact_geometry", lambda *args: True)
    monkeypatch.setattr(beta_audit, "_setting_contact_corridor", lambda *args: True)
    monkeypatch.setattr(beta_audit, "_occupancy_error", lambda *args: None)
    options = dict(max_expansions=100, beam_width=4, max_transfers=1, max_ik_candidates=1)
    beta_audit._search(request, candidate, "fewer_transfers", options)
    assert attempted
    assert all(target in mask[limb] for limb, target in attempted)
    request["route_constraints"]["allowed_contacts"]["LH"] = []
    with pytest.raises(ValueError, match="start_contacts"):
        beta_audit._search(request, candidate, "fewer_transfers", options)
