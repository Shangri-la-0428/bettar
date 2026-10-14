"""Behavioral checks for mixed routes; these are not real-climbing validation."""
from copy import deepcopy

import pytest

from boulderlab.engine import default_request, validate_request, canonical_hash


def request_for(program="mixed_flow", hand_moves=10, **kwargs):
    request = default_request(profile="route", route_program=program,
                              hand_moves=hand_moves, seed=42, budget=3, **kwargs)
    request["solver"].update(max_nfev=0, restarts=1)
    return request


def signature(candidate):
    states = {s["id"]: s for s in candidate["states"]}
    return tuple((e["limb"], states[e["to_state"]]["contacts"][e["limb"]]["placement_id"])
                 for e in candidate["events"])


def used_ids(candidate):
    used = {r["placement_id"] for state in candidate["states"]
            for r in state["contacts"].values() if r}
    placements = {p["id"]: p for p in candidate["placements"]}
    pending = list(used)
    while pending:
        mount = placements[pending.pop()].get("mount")
        if mount and mount["parent_id"] not in used:
            used.add(mount["parent_id"])
            pending.append(mount["parent_id"])
    return used


@pytest.mark.parametrize("moves", [8, 10, 12])
def test_route_lengths_have_real_transfers_and_no_spare_installed_holds(moves):
    from boulderlab.full_route import search_routes
    request = request_for(hand_moves=moves)
    validate_request(request)
    candidates = search_routes(request)
    assert candidates
    for candidate in candidates:
        sequence = signature(candidate)
        assert sum(limb.endswith("H") for limb, _ in sequence) == moves
        assert {p["id"] for p in candidate["placements"]} == used_ids(candidate)
        assert len(candidate["placements"]) < len(request["scene"]["inventory"])
        assert len(candidate["states"]) == 1 + 2 * len(candidate["events"])
        states = {s["id"]: s for s in candidate["states"]}
        previous = candidate["states"][0]["id"]
        for event in candidate["events"]:
            assert event["from_state"] == previous
            before = states[previous]["contacts"][event["limb"]]
            after = states[event["to_state"]]["contacts"][event["limb"]]
            assert before != after, "No-op contacts must not inflate route length"
            previous = event["to_state"]
        end = candidate["states"][-1]["contacts"]
        assert end["LH"]["placement_id"] == end["RH"]["placement_id"]
        assert end["LF"] and end["RF"]
        placements = {p["id"]: p for p in candidate["placements"]}
        start_y = max(placements[r["placement_id"]]["v"] for limb, r in candidate["states"][0]["contacts"].items() if limb.endswith("H"))
        assert placements[end["LH"]["placement_id"]]["v"] - start_y >= 2.0


def test_programs_search_distinct_routes_in_same_pool():
    from boulderlab.full_route import search_routes
    requests = [request_for(program) for program in ("mixed_flow", "power_finish", "sustained_finish")]
    shared = [canonical_hash({key: r[key] for key in ("scene", "body", "reference_layout", "start_contacts", "end_contacts")}) for r in requests]
    assert len(set(shared)) == 1
    assert len({signature(search_routes(r)[0]) for r in requests}) == 3


def test_footwork_is_not_one_forced_transfer_per_hand():
    from boulderlab.full_route import search_routes
    routes = search_routes(request_for())
    grouped = []
    for route in routes:
        feet = 0
        for event in route["events"]:
            if event["limb"].endswith("H"):
                grouped.append(feet)
                feet = 0
            else:
                feet += 1
    assert any(count != 1 for count in grouped)
    assert all(0 <= count <= 2 for count in grouped)


def test_removed_selected_hold_is_not_silently_recreated():
    from boulderlab.full_route import search_routes
    request = request_for()
    first = search_routes(request)[0]
    anchors = {ref["placement_id"] for key in ("start_contacts", "end_contacts")
               for ref in request[key].values() if ref}
    removed = next(pid for limb, pid in signature(first) if limb.endswith("H") and pid not in anchors)
    inventory_id = next(p["inventory_id"] for p in request["reference_layout"] if p["id"] == removed)
    request["reference_layout"] = [p for p in request["reference_layout"] if p["id"] != removed]
    request["scene"]["inventory"] = [h for h in request["scene"]["inventory"] if h["id"] != inventory_id]
    validate_request(request)
    replacements = search_routes(request)
    assert replacements
    assert all(removed not in used_ids(route) for route in replacements)


def test_pool_order_does_not_change_result():
    from boulderlab.full_route import search_routes
    request = request_for()
    reordered = deepcopy(request)
    reordered["reference_layout"].reverse()
    reordered["scene"]["inventory"].reverse()
    assert [signature(c) for c in search_routes(request)] == [signature(c) for c in search_routes(reordered)]


def test_earlier_hold_demand_increases_late_burden_without_changing_late_move():
    from boulderlab.full_route import search_routes, analyze_route
    request = request_for()
    candidate = search_routes(request)[0]
    baseline = analyze_route(request, candidate)
    altered = deepcopy(request)
    first_hand = next(pid for limb, pid in signature(candidate) if limb.endswith("H"))
    inventory_id = next(p["inventory_id"] for p in candidate["placements"] if p["id"] == first_hand)
    hold = next(h for h in altered["scene"]["inventory"] if h["id"] == inventory_id)
    hold["design_attributes"]["force_demand"] += .1
    changed = analyze_route(altered, candidate)
    assert changed["moves"][-1]["fresh_burden"] == baseline["moves"][-1]["fresh_burden"]
    assert changed["moves"][-1]["prior_load"] > baseline["moves"][-1]["prior_load"]
    assert changed["moves"][-1]["effective_burden"] > baseline["moves"][-1]["effective_burden"]


def test_initial_load_affects_context_and_not_intrinsic_demand():
    from boulderlab.full_route import search_routes, analyze_route
    request = request_for()
    candidate = search_routes(request)[0]
    fresh = analyze_route(request, candidate)
    loaded = analyze_route(request, candidate, initial_load=80)
    assert fresh["dimensions"] == loaded["dimensions"]
    for before, after in zip(fresh["moves"], loaded["moves"]):
        assert before["fresh_burden"] == after["fresh_burden"]
        assert before["rest_opportunity"] == after["rest_opportunity"]
        assert before["effective_burden"] < after["effective_burden"]
    assert loaded["history_comparison"]["late_move_delta"] > fresh["history_comparison"]["late_move_delta"]


def test_phase_names_and_targets_cannot_manufacture_recovery():
    from boulderlab.full_route import search_routes, analyze_route, make_brief
    request = request_for()
    candidate = search_routes(request)[0]
    before = analyze_route(request, candidate)
    changed_request = deepcopy(request)
    changed_request["route_design"] = make_brief("power_finish", 10)
    after = analyze_route(changed_request, candidate)
    assert before["dimensions"] == after["dimensions"]
    for left, right in zip(before["moves"], after["moves"]):
        for key in ("strength", "power", "technical", "load", "prior_load", "rest_opportunity", "recovery_proxy", "effective_burden", "accumulated_load"):
            assert left[key] == right[key], key
    assert before["summary"]["objective"] != after["summary"]["objective"]


def test_search_budget_and_unknown_physics_remain_explicit():
    from boulderlab.full_route import search_routes
    from boulderlab.engine import evaluate
    request = request_for()
    candidate = search_routes(request)[0]
    stats = candidate["search_metadata"]
    assert 0 < stats["expanded"] <= stats["expansion_limit"]
    report = evaluate(request, candidate)
    assert report["summary"]["status"] != "pass"
    assert all(check["status"] == "not_checked" for check in report["checks"] if check.get("scope") == "P1")
    request["route_design"]["search"]["max_expansions"] = 1
    with pytest.raises(ValueError, match="预算耗尽.*未找到完整候选"):
        search_routes(request)


def test_history_report_tampering_is_rejected_with_a_new_digest():
    from boulderlab.full_route import search_routes
    from boulderlab.engine import evaluate, make_bundle
    request = request_for()
    candidate = search_routes(request)[0]
    report = evaluate(request, candidate)
    report["design_analysis"]["history_comparison"]["late_move_delta"] += 1
    with pytest.raises(ValueError, match="design analysis"):
        make_bundle(request, [candidate], [report])


@pytest.mark.parametrize("case", ["missing_start", "fixed_finish_foot"])
def test_route_grammar_rejects_unsupported_anchor_conditions(case):
    request = request_for()
    if case == "missing_start":
        request["start_contacts"]["LF"] = None
    else:
        request["end_contacts"]["LF"] = deepcopy(request["start_contacts"]["LF"])
    with pytest.raises(ValueError):
        validate_request(request)


def test_opaque_id_renaming_preserves_geometric_search_choices():
    from boulderlab.full_route import search_routes
    request = request_for()
    baseline = search_routes(request)
    renamed = deepcopy(request)
    placement_ids = [p["id"] for p in request["reference_layout"]]
    inventory_ids = [item["id"] for item in request["scene"]["inventory"]]
    # Reverse lexical order and erase hand/foot/row hints. Separate namespaces
    # also ensure the search does not assume placement IDs equal stock IDs.
    placements = {pid: f"opaque-{len(placement_ids)-i:03d}" for i, pid in enumerate(placement_ids)}
    inventory = {iid: f"stock-{len(inventory_ids)-i:03d}" for i, iid in enumerate(inventory_ids)}
    for item in renamed["scene"]["inventory"]:
        item["id"] = inventory[item["id"]]
    for placement in renamed["reference_layout"]:
        placement["id"] = placements[placement["id"]]
        placement["inventory_id"] = inventory[placement["inventory_id"]]
    for key in ("start_contacts", "end_contacts"):
        for ref in renamed[key].values():
            if ref:
                ref["placement_id"] = placements[ref["placement_id"]]
    validate_request(renamed)
    reverse = {new: original for original, new in placements.items()}
    actual = search_routes(renamed)
    restored = [tuple((limb, reverse[pid]) for limb, pid in signature(candidate)) for candidate in actual]
    assert restored == [signature(candidate) for candidate in baseline]
    assert [{reverse[p["id"]] for p in c["placements"]} for c in actual] == [
        {p["id"] for p in c["placements"]} for c in baseline]
