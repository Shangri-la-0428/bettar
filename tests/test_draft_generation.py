"""Homepage briefs affect real layouts and retain independently checked results."""
from copy import deepcopy
import json
from threading import Thread
from types import SimpleNamespace

import pytest

from boulderlab import draft_generation as drafts, server
from boulderlab.engine import canonical_hash, validate_bundle
from boulderlab.route_constraints import allowed_contact_ids
from test_style_api import call_api


def brief(**changes):
    return {"wall_profile": "overhang", "style": "balance", "difficulty": "medium", "seed": 42, "variant": 0, **changes}


@pytest.mark.parametrize("change", [{"seed": True}, {"seed": -1}, {"seed": 1.2}, {"variant": True}, {"variant": 3},
    {"style": "dynamic"}, {"wall_profile": "default"}, {"difficulty": "V5"}, {"extra": "ignored"}])
def test_bad_controls_fail_before_geometry_or_search(monkeypatch, change):
    monkeypatch.setattr(drafts, "default_request", lambda **_: pytest.fail("invalid controls reached generation"))
    with pytest.raises(ValueError):
        drafts.generate_option(brief(**change))


def test_seed_repeats_real_geometry_and_variants_are_not_relabels():
    requests = [drafts.build_request(brief(variant=i)) for i in range(3)]
    assert drafts.build_request(brief()) == requests[0]
    assert len({canonical_hash(request["reference_layout"]) for request in requests}) == 3
    assert drafts.build_request(brief(seed=43))["reference_layout"] != requests[0]["reference_layout"]
    for request in requests:
        assert request["scene"] == requests[0]["scene"]
        assert request["start_contacts"] == requests[0]["start_contacts"]
        assert request["end_contacts"] == requests[0]["end_contacts"]


@pytest.mark.parametrize("wall", list(drafts.WALLS))
def test_style_never_changes_the_selected_wall(wall):
    requests = [drafts.build_request(brief(wall_profile=wall, style=style)) for style in drafts.STYLES]
    assert len({canonical_hash(request["reference_layout"]) for request in requests}) == 3
    for request in requests:
        assert request["scene"]["wall_panels"] == requests[0]["scene"]["wall_panels"]
        assert request["setting_design"]["wall_profile"] == wall
        assert {p["wall_panel_id"] for p in request["reference_layout"]} <= {p["id"] for p in request["scene"]["wall_panels"]}


def test_difficulty_changes_spacing_without_changing_mesh_friction_body_or_checks():
    requests = [drafts.build_request(brief(difficulty=level)) for level in drafts.DIFFICULTIES]
    assert len({canonical_hash(request["reference_layout"]) for request in requests}) == 3
    for request in requests:
        assert request["scene"] == requests[0]["scene"]
        assert request["body"] == requests[0]["body"]
        assert request["mechanics_parameters"] == requests[0]["mechanics_parameters"]
        assert request["solver"] == requests[0]["solver"]
    # The actual corridor, not just the brief text, gets wider.
    assert abs(next(p for p in requests[0]["reference_layout"] if p["id"] == "hand-1")["u"]) < abs(next(p for p in requests[-1]["reference_layout"] if p["id"] == "hand-1")["u"])


def test_no_time_returns_editable_honest_layout_and_roundtrips():
    result = drafts.generate_option(brief(wall_profile="roof"), seconds=.000001)
    assert result["status"] == "search_unresolved"
    assert result["search"]["budget_exhausted"]
    assert not result["metrics"]["complete"]
    bundle = result["bundle"]
    assert bundle["candidates"][0]["events"] == []
    assert bundle["candidates"][0]["layout_report"]["wall_profile"] == "roof"
    assert result["brief"] == bundle["request"]["generation_brief"]
    assert validate_bundle(json.loads(json.dumps(bundle))) == bundle
    unrestricted = deepcopy(bundle["request"])
    del unrestricted["route_constraints"]
    legal = allowed_contact_ids(unrestricted, unrestricted["reference_layout"])
    for limb, ids in bundle["request"]["route_constraints"]["allowed_contacts"].items():
        assert set(ids) <= legal[limb]
    assert "start-left" in bundle["request"]["route_constraints"]["allowed_contacts"]["LF"]


def test_control_provenance_participates_in_integrity():
    result = drafts.generate_option(brief(), seconds=.000001)
    tampered = deepcopy(result["bundle"])
    tampered["request"]["generation_brief"]["difficulty"] = "hard"
    with pytest.raises(ValueError):
        validate_bundle(tampered)


def test_live_endpoint_saves_bundle_and_rejects_invalid_controls(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    actual_generate = drafts.generate_option
    monkeypatch.setattr(drafts, "generate_option", lambda payload: actual_generate(payload, seconds=.000001))
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    httpd.web_port = 5174
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        status, result = call_api(base, "/api/draft-option", brief())
        assert status == 200, result
        assert result["label"] == "方案 A"
        assert result["status"] == "search_unresolved"
        saved = list((tmp_path / ".runtime/runs").glob("*.json"))
        assert len(saved) == 1
        assert json.loads(saved[0].read_text()) == result["bundle"]
        assert call_api(base, "/api/validate", {"bundle": result["bundle"]})[0] == 200
        assert call_api(base, "/api/draft-option", brief(variant=99))[0] == 422
        assert len(list((tmp_path / ".runtime/runs").glob("*.json"))) == 1
        assert call_api(base, "/api/draft-option", brief(), origin="https://example.org")[0] == 403
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def support_evaluation(release_pass, *, geometry="pass", release_total=4):
    """Controlled checker outcomes; not synthetic poses claimed to be valid."""
    failed = release_total - release_pass
    return {"summary": {"status": geometry}, "mechanics_report": {"summary": {
        "status": "infeasible" if failed else "feasible", "release_states": release_total,
        "release_infeasible_states": failed, "release_unknown_states": 0,
        "feasible_states": release_pass + 1, "infeasible_states": failed,
        "unknown_states": 0, "max_capacity_utilization": .8}}}


def test_reachable_first_beta_does_not_hide_better_supported_beta(monkeypatch):
    request = drafts.build_request(brief())
    searches, checked = [], []

    def search(_request, shell, objective, _options, **_):
        assert shell["events"] == []
        searches.append(objective)
        # Both objectives discover a duplicate: check each distinct beta once.
        return [["short"], ["supported"]], {"objective": objective}

    def evaluate(_request, candidate, **_):
        checked.append(candidate["id"])
        return support_evaluation(1 if candidate["id"] == "short" else 3)

    monkeypatch.setattr(drafts, "_search", search)
    monkeypatch.setattr(drafts, "_make_candidate", lambda shell, steps, _objective:
        {**deepcopy(shell), "id": steps[0]})
    monkeypatch.setattr(drafts, "evaluate", evaluate)
    monkeypatch.setattr(drafts, "analyze_beta", lambda *_: ({}, {"total_proxy_effort": 1.}))
    monkeypatch.setattr(drafts, "time", SimpleNamespace(perf_counter=lambda: 100.))
    selected, diagnostics = drafts._attempt(request, 120., "方案 A")

    assert set(searches) == {"fewer_transfers", "lower_proxy_effort"}
    assert checked == ["short", "supported"]
    assert selected["candidate"]["id"] == "supported"
    assert diagnostics["checked"] == 2
    assert diagnostics["support"][0]["release_pass"] == 3


def installation_proposal(request, label, offset):
    points = deepcopy(request["reference_layout"])
    point = next(p for p in points if p["id"] == "foot-3")
    before = deepcopy(point)
    point["u"] += offset
    return {"label": label, "placements": points,
        "changes": [{"placement_id": point["id"], "before": before, "after": deepcopy(point)}],
        "rationale": {"source_state_ids": ["release-2"], "policy": "moment-arm diagnostic"}}


def test_refinement_searches_changed_geometry_and_retains_only_better_support(monkeypatch):
    from boulderlab import support_refinement

    seed_request = drafts.build_request(brief())
    proposals = [installation_proposal(seed_request, label, shift) for label, shift in
        [("worse", -.02), ("better", .02), ("geometry-fails", .04), ("unresolved", -.04)]]
    searched = []

    def search(request, shell, objective, _options, **_):
        label = request["generation_brief"]["support_proposal"]
        # A new shell, not the prior route's event order, enters every search.
        assert shell["events"] == []
        assert shell["placements"] == request["reference_layout"]
        searched.append((label, objective, deepcopy(shell["placements"])))
        return ([] if label == "unresolved" else [[label]]), {"objective": objective}

    outcomes = {"seed": support_evaluation(2), "worse": support_evaluation(1),
        "better": support_evaluation(3), "geometry-fails": support_evaluation(4, geometry="fail")}
    monkeypatch.setattr(drafts, "initial_contact_mask", lambda request:
        ({limb: sorted(ids) for limb, ids in allowed_contact_ids(request, request["reference_layout"]).items()}, []))
    monkeypatch.setattr(drafts, "_search", search)
    monkeypatch.setattr(drafts, "_make_candidate", lambda shell, steps, _objective:
        {**deepcopy(shell), "id": steps[0]})
    monkeypatch.setattr(drafts, "evaluate", lambda request, _candidate, **_:
        deepcopy(outcomes[request["generation_brief"]["support_proposal"]]))
    monkeypatch.setattr(drafts, "analyze_beta", lambda *_: ({}, {"total_proxy_effort": 1.}))
    monkeypatch.setattr(support_refinement, "support_proposals", lambda *_: deepcopy(proposals))
    monkeypatch.setattr(drafts, "time", SimpleNamespace(perf_counter=lambda: 100.))
    # This test isolates scheduling/selection; integrity is exercised below.
    monkeypatch.setattr(drafts, "make_bundle", lambda request, candidates, evaluations:
        deepcopy({"request": request, "candidates": candidates, "evaluations": evaluations}))
    monkeypatch.setattr(drafts, "validate_bundle", lambda bundle: bundle)
    monkeypatch.setattr(drafts, "metrics", lambda *_: {})

    result = drafts.generate_option(brief())
    assert {label for label, _, _ in searched} == {"seed", *(p["label"] for p in proposals)}
    for proposal in proposals:
        actual = [points for label, _, points in searched if label == proposal["label"]]
        assert actual and all(points == proposal["placements"] for points in actual)
    assert [p["accepted"] for p in result["refinement"]["proposals"]] == [False, True, False, False]
    assert result["bundle"]["candidates"][0]["id"] == "better"
    assert result["refinement"]["before"]["release_pass"] == 2
    assert result["refinement"]["after"]["release_pass"] == 3
    assert result["brief"]["support_proposal"] == "better"
    assert result["brief"]["support_adjustments"] == proposals[1]["changes"]
    assert result["bundle"]["request"]["reference_layout"] == proposals[1]["placements"]


def test_expired_search_returns_no_sequence_without_inventing_support(monkeypatch):
    from boulderlab import support_refinement

    clock = [100.]
    searches = []

    def exhausted_search(_request, _shell, objective, _options, **_):
        searches.append(objective)
        clock[0] = 100. + drafts.SECONDS + 1.
        return [], {"budget_exhausted": True}

    monkeypatch.setattr(drafts, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    monkeypatch.setattr(drafts, "_search", exhausted_search)
    monkeypatch.setattr(support_refinement, "support_proposals", lambda *_:
        pytest.fail("no checked beta exists from which to infer support changes"))
    result = drafts.generate_option(brief())

    assert searches == ["fewer_transfers"]
    assert result["status"] == "search_unresolved"
    assert result["search"]["budget_exhausted"]
    assert result["bundle"]["candidates"][0]["events"] == []
    assert result["refinement"]["before"] is None
    assert result["refinement"]["after"] is None
    assert result["refinement"]["proposals"] == []
    assert result["brief"]["support_adjustments"] == []


def test_accepted_support_provenance_roundtrips_and_is_integrity_protected(monkeypatch):
    from boulderlab import support_refinement

    actual_evaluate = drafts.evaluate
    seed_request = drafts.build_request(brief())
    proposal = installation_proposal(seed_request, "checked-support-layout", .02)

    def checked_layout(request, _deadline, _label):
        candidate = drafts._shell(request, request["reference_layout"])
        candidate["layout_report"] = {"status": "no_sequence", "wall_profile": "overhang",
            "reason": "Controlled serialization fixture; no complete climb claimed", "search": [], "limitations": []}
        evaluation = actual_evaluate(request, candidate, deadline=0.)
        # Same unresolved support outcome; transparent proxy effort breaks the
        # tie. Real request, geometry, checks and fingerprints remain intact.
        effort = 2. if request["generation_brief"]["support_proposal"] == "seed" else 1.
        return {"candidate": candidate, "evaluation": evaluation, "analysis": {},
            "summary": {"total_proxy_effort": effort}}, {"checked": 1}

    monkeypatch.setattr(drafts, "initial_contact_mask", lambda request:
        ({limb: sorted(ids) for limb, ids in allowed_contact_ids(request, request["reference_layout"]).items()}, []))
    monkeypatch.setattr(drafts, "_attempt", checked_layout)
    monkeypatch.setattr(support_refinement, "support_proposals", lambda *_: [deepcopy(proposal)])
    monkeypatch.setattr(drafts, "time", SimpleNamespace(perf_counter=lambda: 100.))
    result = drafts.generate_option(brief())

    assert result["refinement"]["proposals"][0]["accepted"]
    assert result["refinement"]["selected_proposal"] == proposal["label"]
    assert result["status"] == "unverified"
    assert not result["metrics"]["complete"]
    exported = json.loads(json.dumps(result["bundle"]))
    assert validate_bundle(exported) == exported
    assert exported["request"]["generation_brief"]["support_adjustments"] == proposal["changes"]
    assert exported["request"]["generation_brief"]["support_rationale"] == proposal["rationale"]
    exported["request"]["generation_brief"]["support_adjustments"][0]["after"]["u"] += .1
    with pytest.raises(ValueError):
        validate_bundle(exported)
