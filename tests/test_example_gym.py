"""A regional draft retains real gym geometry and immutable neighbouring holds."""
from copy import deepcopy
import json

import numpy as np
import pytest

from boulderlab.draft_generation import build_request, generate_option, validate_options
from boulderlab.example_gym import GYM_ID, REGIONS, gym_metadata
from boulderlab.engine import evaluate, fingerprint, make_bundle, validate_bundle, validate_request
from boulderlab.geometry import placement_frames
from boulderlab.route_constraints import allowed_contact_ids, constraint_errors
from boulderlab.setting import _shell


def options(region="overhang-bay", **changes):
    spec = next(r for r in REGIONS if r["id"] == region)
    return {"gym_id": GYM_ID, "region_id": region, "wall_profile": spec["wall_profile"],
        "style": "balance", "difficulty": "medium", "seed": 42, "variant": 0, **changes}


def shell(request):
    candidate = _shell(request, request["reference_layout"])
    candidate["layout_report"] = {"status": "no_sequence", "reason": "Unsearched test layout",
        "wall_profile": request["setting_design"]["wall_profile"], "search": [], "limitations": []}
    return candidate


def test_metadata_has_shared_geometry_cross_panel_region_and_no_invented_path():
    gym = gym_metadata()
    assert len(gym["scene"]["wall_panels"]) == 6
    assert {r["id"] for r in gym["regions"]} == {r["id"] for r in REGIONS}
    assert len(next(r for r in gym["regions"] if r["id"] == "roof-exit")["patches"]) == 3
    assert gym["preview"]["candidate"]["states"] == []
    assert gym["preview"]["candidate"]["events"] == []
    gym["scene"]["wall_panels"].clear()
    assert len(gym_metadata()["scene"]["wall_panels"]) == 6


@pytest.mark.parametrize("region", [r["id"] for r in REGIONS])
def test_region_keeps_all_panels_and_neighbours_but_only_local_contacts(region):
    request = build_request(options(region))
    limits = request["route_constraints"]["installation_region"]
    assert len(request["scene"]["wall_panels"]) == 6
    assert len(request["reference_layout"]) == 32
    assert len(limits["fixed_placements"]) == 14
    assert constraint_errors(request, request["reference_layout"]) == []
    assert request["generation_brief"]["gym_id"] == GYM_ID
    assert request["generation_brief"]["region_id"] == region
    for ids in allowed_contact_ids(request, request["reference_layout"]).values():
        assert set(ids) <= set(limits["editable_placement_ids"])


def test_global_translation_preserves_local_contacts_directions_and_root_extent():
    local_options = options()
    local_options.pop("gym_id"); local_options.pop("region_id")
    local, gym = build_request(local_options), build_request(options())
    def frames(request):
        return placement_frames(request["reference_layout"], {i["id"]: i for i in request["scene"]["inventory"]},
            request["scene"]["angle_deg"], request["scene"]["wall_panels"])
    local_frames, gym_frames = frames(local), frames(gym)
    for pid, (position, rotation) in local_frames.items():
        assert np.allclose(gym_frames[pid][0], position+[-5., 0., 0.])
        assert np.allclose(gym_frames[pid][1], rotation)
    assert np.allclose(gym["solver"]["root_bounds"][0], np.array(local["solver"]["root_bounds"][0])-5.)
    assert gym["body"] == local["body"]
    assert gym["mechanics_parameters"] == local["mechanics_parameters"]


@pytest.mark.parametrize("change", [{"gym_id": "missing"}, {"region_id": "missing"},
    {"wall_profile": "roof"}, {"gym_id": None}])
def test_region_options_fail_closed(change):
    with pytest.raises(ValueError):
        validate_options(options(**change))


def test_partial_gym_selection_rejected_and_legacy_five_fields_still_work():
    payload = options(); payload.pop("region_id")
    with pytest.raises(ValueError): validate_options(payload)
    payload.pop("gym_id")
    assert validate_options(payload) == payload
    assert "installation_region" not in build_request(payload).get("route_constraints", {})


def test_full_rotated_footprint_not_only_hold_center_must_fit_region():
    request = build_request(options())
    candidate = shell(request)
    point = next(p for p in candidate["placements"] if p["id"] == "hand-2")
    point["u"] = 1.14  # center inside u_max 1.15; most of this hold is outside
    point["rotation_deg"] = 45.
    modified = deepcopy(request)
    modified["reference_layout"] = candidate["placements"]
    with pytest.raises(ValueError, match="complete footprint"):
        validate_request(modified)
    report = evaluate(request, candidate)
    assert any(c["id"] == "request_conformance" and c["status"] == "fail" for c in report["checks"])
    with pytest.raises(ValueError, match="complete footprint"):
        validate_bundle(make_bundle(request, [candidate], []))


@pytest.mark.parametrize("mutation", ["move", "rotate", "delete", "use"])
def test_neighbour_cannot_be_moved_removed_or_used_even_if_route_mask_expands(mutation):
    request = build_request(options())
    candidate = shell(request)
    fixed = request["route_constraints"]["installation_region"]["fixed_placements"][0]
    point = next(p for p in candidate["placements"] if p["id"] == fixed["id"])
    if mutation == "move": point["u"] += .01
    if mutation == "rotate": point["rotation_deg"] += 5
    if mutation == "delete": candidate["placements"].remove(point)
    if mutation == "use":
        request["route_constraints"]["allowed_contacts"]["LH"].append(point["id"])
        assert point["id"] not in allowed_contact_ids(request, candidate["placements"])["LH"]
    assert constraint_errors(request, candidate["placements"])
    with pytest.raises(ValueError):
        validate_bundle(make_bundle(request, [candidate], []))


def test_outside_area_installation_and_lost_context_rejected_before_search():
    request = build_request(options())
    request["reference_layout"][0]["wall_panel_id"] = "upper-wall"
    with pytest.raises(ValueError, match="outside the selected area"):
        validate_request(request)


def test_neighbour_geometry_still_participates_in_collision_check():
    request = build_request(options())
    region = request["route_constraints"]["installation_region"]
    original = request["reference_layout"][0]
    fixed = region["fixed_placements"][0]
    # A hypothetical already-installed obstacle overlapping the active start:
    # freeze that observed installation, then verify the actual collision.
    for p in (fixed, next(p for p in request["reference_layout"] if p["id"] == fixed["id"])):
        for key in ("u", "v", "wall_panel_id", "rotation_deg"):
            p[key] = original[key]
    candidate = shell(request)
    assert not constraint_errors(request, candidate["placements"])
    report = evaluate(request, candidate)
    assert any(c["id"] == "hold_collision" and c["status"] == "fail" and fixed["id"] in str(c)
        for c in report["checks"])


def test_regional_unresolved_result_roundtrips_and_region_changes_invalidate_result():
    result = generate_option(options("roof-exit"), seconds=.000001)
    assert result["status"] == "search_unresolved"
    bundle = result["bundle"]
    validate_bundle(json.loads(json.dumps(bundle)))
    region = bundle["request"]["route_constraints"]["installation_region"]
    assert all(not pid.startswith("context-") for ids in bundle["request"]["route_constraints"]["allowed_contacts"].values() for pid in ids)
    changed = deepcopy(bundle)
    changed["request"]["route_constraints"]["installation_region"]["patches"][0]["u_max"] -= .01
    assert fingerprint(changed["request"], changed["candidates"][0]) != fingerprint(bundle["request"], bundle["candidates"][0])
    with pytest.raises(ValueError): validate_bundle(changed)
    assert region["region_id"] == "roof-exit"
