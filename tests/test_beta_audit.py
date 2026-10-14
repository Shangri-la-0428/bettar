"""A route's prescribed point coverage is not evidence against shortcuts."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from boulderlab.beta_audit import _search, _make_candidate, _used, analyze_beta, audit_beta
from boulderlab.engine import evaluate, fingerprint
from boulderlab.full_route import make_brief

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = dict(max_expansions=26000, beam_width=48, max_transfers=30, max_ik_candidates=2)


@pytest.fixture(scope="module")
def route():
    bundle = json.loads((ROOT / "fixtures/route-mixed_flow-bundle.json").read_text())
    return bundle["request"], bundle["candidates"][0]


@pytest.fixture(scope="module")
def shortcut(route):
    request, candidate = route
    sequences, stats = _search(request, candidate, "fewer_transfers", OPTIONS)
    assert sequences, stats
    return _make_candidate(candidate, sequences[0], "fewer_transfers")


def test_shortcut_keeps_installed_wall_but_skips_prescribed_points(route, shortcut):
    request, original = route
    assert shortcut["placements"] == original["placements"]
    assert len(shortcut["events"]) < len(original["events"])
    assert _used(original) - _used(shortcut)
    assert _used(shortcut) <= {p["id"] for p in original["placements"]}
    assert shortcut["states"][0]["contacts"] == request["start_contacts"]
    for limb in ("LH", "RH"):
        assert shortcut["states"][-1]["contacts"][limb] == request["end_contacts"][limb]
    analysis, summary = analyze_beta(request, shortcut)
    assert summary["hand_moves"] != request["hand_moves"]
    assert analysis["phases"] == []


def test_shortcut_does_not_match_hands_on_small_pockets_or_crimps(route, shortcut):
    request, _ = route
    placements = {p["id"]: p for p in shortcut["placements"]}
    inventory = {h["id"]: h for h in request["scene"]["inventory"]}
    for state in shortcut["states"]:
        contacts = state["contacts"]
        if contacts["LH"] and contacts["LH"] == contacts["RH"]:
            hold = inventory[placements[contacts["LH"]["placement_id"]]["inventory_id"]]
            assert hold["type"] not in {"pocket", "crimp"}
        for hand in ("LH", "RH"):
            for foot in ("LF", "RF"):
                if contacts[hand] and contacts[foot]:
                    assert contacts[hand] != contacts[foot], "One representative point cannot model concurrent hand/foot contacts"


def test_search_does_not_consume_prescribed_phases_count_or_unused_pool(route):
    request, original = route
    expected, _ = _search(request, original, "fewer_transfers", OPTIONS)
    changed = deepcopy(request)
    changed["route_design"] = make_brief("sustained_finish", 8)
    changed["hand_moves"] = 8
    changed["reference_layout"] = []  # Search may only read the installed wall.
    actual, _ = _search(changed, original, "fewer_transfers", OPTIONS)
    assert actual == expected and actual
    assert analyze_beta(changed, original) == analyze_beta(request, original)


def test_reordering_inventory_does_not_change_alternative(route):
    request, candidate = deepcopy(route)
    expected, _ = _search(request, candidate, "fewer_transfers", OPTIONS)
    request["scene"]["inventory"].reverse()
    candidate["placements"].reverse()
    actual, _ = _search(request, candidate, "fewer_transfers", OPTIONS)
    assert actual == expected


def test_retained_hand_orientation_changes_same_action_support_cost(route):
    request, original = route
    before, _ = analyze_beta(request, original)
    changed = deepcopy(original)
    first = original["events"][0]["limb"]
    retained = "RH" if first == "LH" else "LH"
    pid = original["states"][0]["contacts"][retained]["placement_id"]
    next(p for p in changed["placements"] if p["id"] == pid)["rotation_deg"] += 180
    after, _ = analyze_beta(request, changed)
    assert before["moves"][0]["to_placement_id"] == after["moves"][0]["to_placement_id"]
    assert before["moves"][0]["orientation_support"]["pull_mismatch"] != after["moves"][0]["orientation_support"]["pull_mismatch"]
    assert before["moves"][0]["proxy_effort"] != after["moves"][0]["proxy_effort"]
    assert fingerprint(request, changed) != fingerprint(request, original)


def test_foot_position_and_body_size_change_geometric_effort(route):
    request, original = route
    before, total = analyze_beta(request, original)
    changed = deepcopy(original)
    pids = {original["states"][0]["contacts"][l]["placement_id"] for l in ("LF", "RF")}
    for p in changed["placements"]:
        if p["id"] in pids: p["u"] += .35
    after, foot_total = analyze_beta(request, changed)
    assert before["moves"][0]["orientation_support"] != after["moves"][0]["orientation_support"]
    assert foot_total["total_proxy_effort"] != total["total_proxy_effort"]
    longer = deepcopy(request)
    longer["body"]["forearm"] += .1
    _, body_total = analyze_beta(longer, original)
    assert body_total["total_proxy_effort"] != total["total_proxy_effort"]


def test_alternative_still_needs_normal_ik_and_surface_permissions(route, shortcut):
    request, _ = deepcopy(route)
    request["solver"].update(max_nfev=0, restarts=1)
    standard = evaluate(request, shortcut)
    independent = evaluate(request, shortcut, sequence_policy="independent_beta")
    assert any(c["status"] == "fail" and "hand_moves" in str(c) for c in standard["checks"])
    assert independent["summary"]["status"] == "unknown"
    assert any(p["status"] == "unknown" for p in independent["poses"])
    assert not independent.get("design_analysis")
    invalid = deepcopy(shortcut)
    pid = invalid["states"][0]["contacts"]["LH"]["placement_id"]
    item_id = next(p["inventory_id"] for p in invalid["placements"] if p["id"] == pid)
    item = next(i for i in request["scene"]["inventory"] if i["id"] == item_id)
    item["grip_surfaces"][0]["limbs"] = ["LF", "RF"]
    bad = evaluate(request, invalid, sequence_policy="independent_beta")
    assert bad["summary"]["status"] == "fail"


def test_budget_and_unknown_are_not_reported_as_no_possible_shortcut(route):
    request, original = deepcopy(route)
    request["solver"].update(max_nfev=0, restarts=1)
    report = audit_beta(request, original, search_options={"max_expansions": 1})
    assert report["search"]["budget_exhausted"]
    assert report["alternatives"] == []
    assert report["search"]["expanded"] <= report["search"]["expansion_limit"]
    assert report["original"]["evaluation"]["summary"]["status"] == "unknown"
    assert any("不证明" in item for item in report["limitations"])


def test_ik_budget_failure_preserves_unverified_paths(route):
    request, original = deepcopy(route)
    request["solver"].update(max_nfev=0, restarts=1)
    report = audit_beta(request, original)
    assert not report["alternatives"]
    assert report["unverified_alternatives"]
    assert all(a["evaluation"]["summary"]["status"] != "pass" for a in report["unverified_alternatives"])
    assert report["search"]["verified_alternatives"] == 0


def test_real_audit_does_not_mutate_original_and_rechecks_every_returned_path(route):
    request, original = deepcopy(route)
    saved = deepcopy((request, original))
    report = audit_beta(request, original)
    assert (request, original) == saved
    assert report["source"]["fingerprint"] == fingerprint(request, original)
    assert report["alternatives"], report["search"]
    for alt in report["alternatives"]:
        assert alt["candidate"]["placements"] == original["placements"]
        assert alt["evaluation"]["summary"]["status"] == "pass"
        assert alt["evaluation"]["poses"]
        assert all(p["status"] == "pass" for p in alt["evaluation"]["poses"])
        assert all(c["status"] == "not_checked" for c in alt["evaluation"]["checks"] if c.get("scope") == "P1")
        assert bool(alt["crux_bypass"]["contacted"]) == (report["original"]["crux"]["placement_id"] in _used(alt["candidate"]))


def test_unmodeled_regrip_cannot_inflate_shortcut_savings(route):
    request, original = deepcopy(route)
    steps = [("LH", original["states"][0]["contacts"]["LH"]["placement_id"])]
    steps.extend((e["limb"], original["states"][2*i+2]["contacts"][e["limb"]]["placement_id"])
                 for i, e in enumerate(original["events"]))
    regrip = _make_candidate(original, steps, "fewer_transfers")
    request["solver"].update(max_nfev=0, restarts=1)
    assert evaluate(request, regrip)["summary"]["status"] == "unknown"
    with pytest.raises(ValueError, match="regrip|regrab|原地|no.op"):
        audit_beta(request, regrip)


def test_independent_audit_checks_cannot_be_imported_as_generation_evidence(route, shortcut):
    from boulderlab.engine import _validate_evaluation
    request, _ = deepcopy(route)
    request["solver"].update(max_nfev=0, restarts=1)
    result = evaluate(request, shortcut, sequence_policy="independent_beta")
    assert result["sequence_policy"] == "independent_beta"
    with pytest.raises(ValueError, match="audit report"):
        _validate_evaluation(request, shortcut, result)
