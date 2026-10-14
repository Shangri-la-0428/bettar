"""HTTP boundaries for independently fingerprinted same-wall comparisons."""
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from boulderlab import server


@pytest.fixture
def local_api():
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    httpd.web_port = 5174
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


def call_api(base, path, payload=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    request = Request(base + path, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    try:
        response = urlopen(request, timeout=20)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def test_style_request_has_shared_board_and_distinct_goals(local_api):
    requests = []
    for goal, _ in server.STYLE_EXAMPLES:
        status, body = call_api(local_api, "/api/request", {
            "profile": "style", "style_goal": goal, "rhythm": "late_crux", "angle_deg": 30,
        })
        assert status == 200, body
        requests.append(body["request"])
    assert {r["route_design"]["style_goal"] for r in requests} == {"power", "sustained", "technical"}
    for request in requests:
        assert request["mode"] == "fixed"
        assert request["hand_moves"] == 4
        assert request["scene"] == requests[0]["scene"]
        assert request["reference_layout"] == requests[0]["reference_layout"]
        assert request["start_contacts"] == requests[0]["start_contacts"]
        assert request["end_contacts"] == requests[0]["end_contacts"]


def test_comparison_validates_before_generation(local_api, monkeypatch):
    generated = []
    monkeypatch.setattr(server, "generate", lambda request: generated.append(request))
    for payload in ({"style_goal": "compare"}, {"rhythm": "unknown"}, {"angle_deg": 41}):
        status, _ = call_api(local_api, "/api/style-comparison", payload)
        assert status == 422
    assert not generated


def test_comparison_retains_each_request_and_saves_each_bundle(local_api, monkeypatch):
    saved = []
    monkeypatch.setattr(server, "generate", lambda request: {"request": request, "candidates": []})
    monkeypatch.setattr(server, "save_run", saved.append)
    status, body = call_api(local_api, "/api/style-comparison", {
        "body_id": "B", "angle_deg": 10, "seed": 96, "budget": 2, "rhythm": "early_crux",
    })
    assert status == 200, body
    assert len(body["examples"]) == len(saved) == 3
    for example in body["examples"]:
        request = example["bundle"]["request"]
        assert request["route_design"]["style_goal"] == example["id"]
        assert request["route_design"]["rhythm"] == "early_crux"
        assert request["body"]["id"] == "B"
        assert request["scene"]["angle_deg"] == 10
        assert request["seed"] == 96 and request["budget"] == 2


def test_missing_examples_is_actionable_and_foreign_origin_cannot_generate(local_api, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    status, body = call_api(local_api, "/api/style-examples")
    assert status == 503 and "示例尚未生成" in body["error"]
    status, _ = call_api(local_api, "/api/style-comparison", {}, origin="https://example.org")
    assert status == 403


def test_full_route_requests_default_to_ten_moves_and_keep_shared_inputs(local_api):
    requests = []
    for program, _ in server.ROUTE_EXAMPLES:
        status, body = call_api(local_api, "/api/request", {"profile": "route", "route_program": program})
        assert status == 200, body
        requests.append(body["request"])
    assert {r["route_design"]["program"] for r in requests} == {p for p, _ in server.ROUTE_EXAMPLES}
    for request in requests:
        assert request["hand_moves"] == 10 and request["mode"] == "free"
        for key in ("scene", "reference_layout", "start_contacts", "end_contacts"):
            assert request[key] == requests[0][key]


def test_full_route_invalid_settings_rejected_before_any_generation(local_api, monkeypatch):
    generated = []
    monkeypatch.setattr(server, "generate", lambda request: generated.append(request))
    for payload in ({"hand_moves": 2}, {"hand_moves": 9}, {"hand_moves": True}, {"angle_deg": 41}, {"route_program": "unknown"}):
        status, body = call_api(local_api, "/api/route-comparison", payload)
        assert status == 422, body
    assert not generated


def test_full_route_comparison_preserves_settings_and_saves_separate_bundles(local_api, monkeypatch):
    saved = []
    monkeypatch.setattr(server, "generate", lambda request: {"request": request, "candidates": []})
    monkeypatch.setattr(server, "save_run", saved.append)
    status, body = call_api(local_api, "/api/route-comparison", {
        "body_id": "B", "angle_deg": 10, "hand_moves": 12, "seed": 96, "budget": 2,
    })
    assert status == 200, body
    assert len(body["examples"]) == len(saved) == 3
    for example in body["examples"]:
        request = example["bundle"]["request"]
        assert request["route_design"]["program"] == example["id"]
        assert request["body"]["id"] == "B" and request["scene"]["angle_deg"] == 10
        assert request["hand_moves"] == 12 and request["seed"] == 96 and request["budget"] == 2


def test_full_route_missing_examples_and_origin_boundary(local_api, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    status, body = call_api(local_api, "/api/route-examples")
    assert status == 503 and "--profile route" in body["error"]
    status, _ = call_api(local_api, "/api/route-comparison", {}, origin="https://example.org")
    assert status == 403


def test_beta_audit_uses_current_request_and_candidate_without_mutating_bundle(local_api, monkeypatch):
    calls = []
    payload = {"request": {"id": "current-request"}, "candidate": {"id": "current-revision"}}
    def audit(request, candidate):
        calls.append((request, candidate))
        return {"schema_version": "beta-audit/1", "alternatives": []}
    monkeypatch.setattr(server, "audit_beta", audit)
    monkeypatch.setattr(server, "save_run", lambda _: pytest.fail("Audit is not a replacement route bundle"))
    status, body = call_api(local_api, "/api/beta-audit", payload)
    assert status == 200 and body["schema_version"] == "beta-audit/1"
    assert calls == [(payload["request"], payload["candidate"])]


def test_beta_audit_rejects_unknown_options_missing_fields_and_foreign_origin(local_api, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "audit_beta", lambda *args: calls.append(args))
    for payload in ({}, {"request": {}}, {"request": {}, "candidate": {}, "search_options": {"max_expansions": 100000000}}):
        status, _ = call_api(local_api, "/api/beta-audit", payload)
        assert status == 422
    status, _ = call_api(local_api, "/api/beta-audit", {"request": {}, "candidate": {}}, origin="https://example.org")
    assert status == 403
    assert not calls


def test_setting_comparison_rejects_unimplemented_controls_before_generation(local_api, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "generate", lambda request: calls.append(request))
    for payload in ({"hand_moves": 10}, {"angle_deg": 25}, {"body_id": "absent"}, {"seed": True}, {"hold_source": "unregistered"}):
        status, _ = call_api(local_api, "/api/setting-comparison", payload)
        assert status == 422
    assert not calls


def test_setting_comparison_keeps_three_separately_validated_requests(local_api, monkeypatch):
    saved = []
    monkeypatch.setattr(server, "generate", lambda request: {"request": request, "candidates": []})
    monkeypatch.setattr(server, "save_run", saved.append)
    status, body = call_api(local_api, "/api/setting-comparison", {"body_id": "B", "seed": 96, "budget": 2})
    assert status == 200, body
    assert len(body["examples"]) == len(saved) == 3
    for example in body["examples"]:
        request = example["bundle"]["request"]
        assert request["setting_design"]["program"] == example["id"]
        assert request["body"]["id"] == "B" and request["seed"] == 96
        assert request["budget"] == 2


def test_setting_missing_examples_is_actionable_and_foreign_origin_blocked(local_api, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    status, body = call_api(local_api, "/api/setting-examples")
    assert status == 503 and "--profile setting" in body["error"]
    status, _ = call_api(local_api, "/api/setting-comparison", {}, origin="https://example.org")
    assert status == 403


@pytest.mark.parametrize("source", ["assets", "templates"])
def test_setting_source_survives_request_and_comparison_boundaries(local_api, monkeypatch, source):
    status, single = call_api(local_api, "/api/request", {"profile": "setting", "hold_source": source})
    assert status == 200, single
    monkeypatch.setattr(server, "generate", lambda request: {"request": request, "candidates": []})
    monkeypatch.setattr(server, "save_run", lambda _: None)
    status, comparison = call_api(local_api, "/api/setting-comparison", {"hold_source": source})
    assert status == 200, comparison
    requests = [single["request"]] + [e["bundle"]["request"] for e in comparison["examples"]]
    for request in requests:
        assert request["setting_design"]["hold_source"] == source
        imported = [item for item in request["scene"]["inventory"] if item.get("asset_id")]
        assert bool(imported) == (source == "assets")
    status, body = call_api(local_api, "/api/setting-examples?hold_source=unregistered")
    assert status == 422, body
