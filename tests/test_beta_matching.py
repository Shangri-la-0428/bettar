"""A hand/foot role list does not describe simultaneous grip capacity."""
import json
from copy import deepcopy
from pathlib import Path

from boulderlab.beta_audit import _audit_context, _occupancy_error, _search, _make_candidate


def route():
    bundle = json.loads((Path(__file__).resolve().parents[1] / "fixtures/route-mixed_flow-bundle.json").read_text())
    return bundle["request"], bundle["candidates"][0]


def test_small_pocket_and_crimp_cannot_match_but_large_top_can():
    request, candidate = route()
    context = _audit_context(request, candidate["placements"])
    inventory = {item["id"]: item for item in request["scene"]["inventory"]}
    for placement in candidate["placements"]:
        if inventory[placement["inventory_id"]]["type"] in ("pocket", "crimp"):
            key = (placement["id"], placement["id"], "start-foot-left", "start-foot-right")
            assert _occupancy_error(context, key) == "hand_match_not_supported_by_selected_patch"
    assert _occupancy_error(context, ("top", "top", "start-foot-left", "start-foot-right")) is None
    small = deepcopy(request)
    next(item for item in small["scene"]["inventory"] if item["id"] == "top")["grip_surfaces"][0]["radii"] = [.011, .008]
    assert not _audit_context(small, candidate["placements"])["top"]["hand_match_allowed"]


def test_mixed_hand_foot_same_point_is_rejected_without_banning_later_reuse():
    request, candidate = route()
    context = _audit_context(request, candidate["placements"])
    assert _occupancy_error(context, ("start-left", "start-right", "start-left", "start-foot-right")) == "simultaneous_hand_foot_same_point"
    assert _occupancy_error(context, ("top", "top", "start-left", "start-foot-right")) is None


def test_all_searched_sequences_obey_matching_policy():
    request, original = route()
    context = _audit_context(request, original["placements"])
    options = dict(max_expansions=26000, beam_width=48, max_transfers=30, max_ik_candidates=2)
    for objective in ("fewer_transfers", "lower_proxy_effort"):
        sequences, stats = _search(request, original, objective, options)
        assert sequences
        assert stats["rejected"]["hand_match_not_supported_by_selected_patch"] > 0
        for sequence in sequences:
            alternate = _make_candidate(original, sequence, objective)
            for state in alternate["states"][::2]:
                key = tuple(state["contacts"][limb]["placement_id"] for limb in ("LH", "RH", "LF", "RF"))
                assert _occupancy_error(context, key) is None
