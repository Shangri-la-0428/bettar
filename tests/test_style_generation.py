"""Behavioral acceptance for fixed-board, style-conditioned route search.

These assertions exercise changes in goals and inputs; they do not certify
physical exertion, continuous movement, a climbing grade, or real climbability.
"""
from copy import deepcopy

import pytest

from boulderlab.engine import (canonical_hash, default_request, evaluate,
                              fingerprint, make_bundle, validate_bundle,
                              validate_request)
from boulderlab.route_design import analyze_route, make_brief, search_routes


def request_for(style="power", rhythm="early_crux", **kwargs):
    request = default_request(profile="style", style_goal=style, rhythm=rhythm,
                              seed=42, budget=3, **kwargs)
    # Most tests isolate planning and provenance from nonlinear IK convergence.
    request["solver"].update(max_nfev=0, restarts=1)
    return request


def route_signature(candidate):
    states = {state["id"]: state for state in candidate["states"]}
    return tuple((event["limb"],
                  states[event["to_state"]]["contacts"][event["limb"]]["placement_id"])
                 for event in candidate["events"])


def used_placements(candidate):
    return {contact["placement_id"] for state in candidate["states"]
            for contact in state["contacts"].values() if contact}


def canonical_board(request):
    return canonical_hash({"scene": request["scene"],
                           "reference_layout": request["reference_layout"],
                           "start_contacts": request["start_contacts"],
                           "end_contacts": request["end_contacts"]})


def test_styles_choose_different_contacts_on_the_same_fixed_board():
    requests = [request_for(style) for style in ("power", "sustained", "technical")]
    assert len({canonical_board(request) for request in requests}) == 1
    candidates = [search_routes(request) for request in requests]
    assert all(candidates)
    assert len({route_signature(routes[0]) for routes in candidates}) == 3
    # Style differences must come from contact selection/sequence, not moving
    # the installed board or quietly changing its holds, body, start or finish.
    for request, routes in zip(requests, candidates):
        assert request["mode"] == "fixed"
        assert all(route["placements"] == request["reference_layout"] for route in routes)
        assert len({route_signature(route) for route in routes}) == len(routes)
        assert all(route["states"][0]["contacts"] == request["start_contacts"]
                   and route["states"][-1]["contacts"] == request["end_contacts"]
                   for route in routes)


def test_phase_timing_changes_the_selected_route_without_changing_the_board():
    early = request_for(rhythm="early_crux")
    late = request_for(rhythm="late_crux")
    assert canonical_board(early) == canonical_board(late)
    early_routes, late_routes = search_routes(early), search_routes(late)
    assert early_routes and late_routes
    assert route_signature(early_routes[0]) != route_signature(late_routes[0])


def test_technical_example_moves_actual_peak_later_when_requested():
    early, late = (request_for("technical", rhythm)
                   for rhythm in ("early_crux", "late_crux"))
    ea = analyze_route(early, search_routes(early)[0])
    la = analyze_route(late, search_routes(late)[0])
    assert ea["summary"]["crux_event_index"] < la["summary"]["crux_event_index"]
    assert la["summary"]["crux_event_index"] >= len(la["moves"])/2


def test_search_is_deterministic_under_inventory_and_layout_reordering():
    original = request_for("technical", "sustained")
    reordered = deepcopy(original)
    reordered["scene"]["inventory"].reverse()
    reordered["reference_layout"].reverse()
    first, second = search_routes(original), search_routes(reordered)
    assert [route_signature(route) for route in first] == [route_signature(route) for route in second]
    assert [analyze_route(original, route) for route in first] == [analyze_route(reordered, route) for route in second]
    assert fingerprint(original, first[0]) == fingerprint(reordered, second[0])


def test_search_uses_geometry_and_attributes_instead_of_hold_id_roles():
    original = request_for("technical", "late_crux")
    renamed = deepcopy(original)
    identifiers = sorted(hold["id"] for hold in renamed["scene"]["inventory"])
    mapping = {identifier: f"anonymous-{len(identifiers)-i:02d}" for i, identifier in enumerate(identifiers)}
    inverse = {new: old for old, new in mapping.items()}
    for hold in renamed["scene"]["inventory"]:
        hold["id"] = mapping[hold["id"]]
    for placement in renamed["reference_layout"]:
        placement["id"] = mapping[placement["id"]]
        placement["inventory_id"] = mapping[placement["inventory_id"]]
    for key in ("start_contacts", "end_contacts"):
        for ref in renamed[key].values():
            ref["placement_id"] = mapping[ref["placement_id"]]
    validate_request(renamed)
    first, second = search_routes(original), search_routes(renamed)
    assert [route_signature(route) for route in first] == [
        tuple((limb, inverse[pid]) for limb, pid in route_signature(route)) for route in second]


def test_steeper_wall_is_an_explicit_style_profile_extension():
    validate_request(request_for(angle_deg=40))
    with pytest.raises(ValueError):
        default_request(profile="basic", angle_deg=40)


def test_missing_nonanchor_contact_is_replaced_instead_of_reused():
    request = request_for("technical", "sustained")
    first = search_routes(request)[0]
    anchors = {contact["placement_id"] for key in ("start_contacts", "end_contacts")
               for contact in request[key].values() if contact}
    removed_id = next(pid for _, pid in route_signature(first) if pid not in anchors)
    removed_inventory = next(p["inventory_id"] for p in request["reference_layout"] if p["id"] == removed_id)
    request["reference_layout"] = [p for p in request["reference_layout"] if p["id"] != removed_id]
    request["scene"]["inventory"] = [hold for hold in request["scene"]["inventory"] if hold["id"] != removed_inventory]
    validate_request(request)
    replacements = search_routes(request)
    assert replacements
    assert all(removed_id not in used_placements(route) for route in replacements)
    assert route_signature(replacements[0]) != route_signature(first)


def test_style_estimates_do_not_upgrade_unimplemented_physics():
    request = request_for()
    candidate = search_routes(request)[0]
    report = evaluate(request, candidate)
    p1 = [check for check in report["checks"] if check.get("scope") == "P1"]
    assert {check["id"] for check in p1} == {"force", "balance", "body_collision", "transition", "grade_experience"}
    assert all(check["status"] == "not_checked" for check in p1)
    assert report["summary"]["status"] != "pass"
    assert not any(pose.get("joints") for pose in report["poses"])
    analysis = report["design_analysis"]
    assert analysis["source"] == "synthetic_assumption"
    assert analysis["limitations"]
    assert set(analysis["dimensions"]) == {"strength", "power", "technical", "load"}
    assert all(0 <= value <= 100 for value in analysis["dimensions"].values())
    assert not ({"v_grade", "font_grade", "grade", "remaining_energy_percent",
                 "recovery_percent", "success_probability"} & analysis.keys())


def test_changing_intent_does_not_change_estimated_demands_of_same_route():
    request = request_for("power", "early_crux")
    candidate = search_routes(request)[0]
    baseline = analyze_route(request, candidate)
    altered = deepcopy(request)
    altered["route_design"] = make_brief("technical", "late_crux")
    changed = analyze_route(altered, candidate)
    assert baseline["dimensions"] == changed["dimensions"]
    assert [phase["estimate"] for phase in baseline["phases"]] == [phase["estimate"] for phase in changed["phases"]]
    assert {key: value for key, value in baseline["summary"].items() if key != "objective"} == {
        key: value for key, value in changed["summary"].items() if key != "objective"}
    assert baseline["summary"]["objective"] != changed["summary"]["objective"]
    for before, after in zip(baseline["moves"], changed["moves"]):
        for key in ("strength", "power", "technical", "load", "burden", "accumulated_load", "attributes"):
            assert before[key] == after[key], key
    assert fingerprint(request, candidate) != fingerprint(altered, candidate)


@pytest.mark.parametrize("condition", ["body", "angle", "orientation", "hold_attribute", "position"])
def test_demand_estimates_respond_to_actual_context(condition):
    request = request_for()
    candidate = search_routes(request)[0]
    before = analyze_route(request, candidate)
    changed_request, changed_candidate = deepcopy(request), deepcopy(candidate)
    hand_target = next(pid for limb, pid in route_signature(candidate) if limb.endswith("H"))
    target = next(p for p in changed_candidate["placements"] if p["id"] == hand_target)
    if condition == "body":
        changed_request["body"]["upper_arm"] += .05
        changed_request["body"]["forearm"] += .05
    elif condition == "angle":
        changed_request["scene"]["angle_deg"] = 40
    elif condition == "orientation":
        target["rotation_deg"] += 90
    elif condition == "position":
        target["u"] += .12
    else:
        hold = next(h for h in changed_request["scene"]["inventory"] if h["id"] == target["inventory_id"])
        hold["design_attributes"]["force_demand"] += .1
    after = analyze_route(changed_request, changed_candidate)
    assert before["dimensions"] != after["dimensions"]
    assert fingerprint(request, candidate) != fingerprint(changed_request, changed_candidate)
    # A changed hypothetical input gets a fresh estimate; it does not inherit
    # the old value or turn a proxy into a force/transition pass.
    report = evaluate(changed_request, changed_candidate)
    assert report["design_analysis"] == after
    assert all(c["status"] == "not_checked" for c in report["checks"] if c.get("scope") == "P1")


def test_search_budget_is_bounded_and_exhaustion_does_not_claim_impossibility():
    request = request_for()
    for candidate in search_routes(request):
        stats = candidate["search_metadata"]
        assert 0 < stats["expanded"] <= stats["expansion_limit"] == request["route_design"]["search"]["max_expansions"]
        assert stats["beam_width"] == request["route_design"]["search"]["beam_width"]
        assert 0 < stats["returned_candidates"] <= request["budget"]
        assert stats["complete_sequences"] >= stats["returned_candidates"]
        assert all(type(value) is int and value >= 0 for value in stats["rejected"].values())
    request["route_design"]["search"]["max_expansions"] = 1
    validate_request(request)
    with pytest.raises(ValueError, match="预算.*不能.*断言"):
        search_routes(request)


def test_no_intermediate_holds_reports_limited_search_failure():
    request = request_for()
    anchors = {contact["placement_id"] for key in ("start_contacts", "end_contacts")
               for contact in request[key].values() if contact}
    request["reference_layout"] = [p for p in request["reference_layout"] if p["id"] in anchors]
    inventory_ids = {p["inventory_id"] for p in request["reference_layout"]}
    request["scene"]["inventory"] = [h for h in request["scene"]["inventory"] if h["id"] in inventory_ids]
    validate_request(request)
    with pytest.raises(ValueError, match="语法.*未找到"):
        search_routes(request)


@pytest.mark.parametrize("field", ["dimensions", "move", "phase", "summary", "search", "missing_analysis"])
def test_forged_analysis_is_rejected_even_with_a_new_bundle_digest(field):
    request = request_for()
    candidate = search_routes(request)[0]
    evaluation = evaluate(request, candidate)
    if field == "dimensions":
        evaluation["design_analysis"]["dimensions"]["power"] += 1
    elif field == "move":
        evaluation["design_analysis"]["moves"][1]["strength"] += 1
    elif field == "phase":
        evaluation["design_analysis"]["phases"][0]["estimate"]["technical"] += 1
    elif field == "summary":
        evaluation["design_analysis"]["summary"]["total_load"] += 1
    elif field == "search":
        evaluation["design_analysis"]["search"]["expanded"] += 1
    else:
        evaluation.pop("design_analysis")
    # make_bundle builds a current checksum. Rejection must be due to a
    # recomputed-analysis mismatch, not only a checksum or stale fingerprint.
    with pytest.raises(ValueError, match="design analysis"):
        make_bundle(request, [candidate], [evaluation])


def test_style_bundle_roundtrip_preserves_current_analysis():
    request = request_for()
    candidate = search_routes(request)[0]
    bundle = make_bundle(request, [candidate])
    assert validate_bundle(bundle) == bundle
    assert bundle["evaluations"][0]["design_analysis"] == analyze_route(request, candidate)


def test_search_evidence_is_reproduced_instead_of_trusting_candidate_metadata():
    request = request_for()
    candidate = search_routes(request)[0]
    original = analyze_route(request, candidate)
    candidate["search_metadata"] = {"expanded": 999999999, "expansion_limit": 1,
                                    "scope": "forged_success", "returned_candidates": -1}
    actual = analyze_route(request, candidate)
    assert actual["search"] == original["search"]
    assert actual["search"]["reproduced_for_current_route"] is True
    assert actual["search"]["expanded"] <= actual["search"]["expansion_limit"]


def test_manual_revision_does_not_present_original_search_as_current_evidence():
    request = request_for()
    candidate = search_routes(request)[0]
    assert analyze_route(request, candidate)["search"]["reproduced_for_current_route"] is True
    # Keep old metadata deliberately; the evaluator must establish provenance
    # itself instead of relying solely on a careful web editor.
    candidate["placements"][0]["u"] += .01
    search = analyze_route(request, candidate)["search"]
    assert search["reproduced_for_current_route"] is False
    assert search["scope"] == "current_route_not_reproduced_by_generator"
    assert "expanded" not in search


def test_phase_plan_must_cover_hand_transfers_once_in_order():
    request = request_for()
    request["route_design"]["phases"][1]["hand_move_index"] = 0
    with pytest.raises(ValueError, match="ordered hand transfers"):
        validate_request(request)

