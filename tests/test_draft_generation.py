"""Homepage briefs affect real layouts and retain independently checked results."""
from copy import deepcopy
import json
from threading import Thread

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
