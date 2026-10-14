"""Read-only saved-study HTTP endpoints remain independent of optional ML."""
from threading import Thread

import pytest

from boulderlab import server
from test_learned_experiment import save_example, save_index
from test_style_api import call_api


@pytest.fixture
def learned_api(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    httpd.web_port = 5174
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", tmp_path / "outputs" / "learned-study"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


def test_uninstalled_model_and_missing_study_do_not_break_startup(learned_api):
    base, _ = learned_api
    status, body = call_api(base, "/api/health")
    assert status == 200 and body["ok"]
    status, body = call_api(base, "/api/learned-experiment")
    assert status == 503 and "run_learned_experiment.py" in body["error"]


def test_index_and_saved_case_roundtrip_and_post_is_not_generation(learned_api, example):
    base, directory = learned_api
    data, bundle = save_example(directory, *example)
    status, body = call_api(base, "/api/learned-experiment")
    assert status == 200 and body == data
    status, body = call_api(base, "/api/learned-experiment/runs/saved-case")
    assert status == 200 and body == bundle
    status, _ = call_api(base, "/api/learned-experiment", {})
    assert status == 404


def test_invalid_ids_foreign_origin_and_forged_case_evidence_are_rejected(learned_api, example):
    base, directory = learned_api
    data, _ = save_example(directory, *example)
    for invalid in ("%2e%2e", "bad/id", "bad.json"):
        status, _ = call_api(base, "/api/learned-experiment/runs/" + invalid)
        assert status == 422
    status, _ = call_api(base, "/api/learned-experiment", origin="https://example.org")
    assert status == 403
    data["runs"][0]["metrics"]["p0_status"] = "pass"
    save_index(directory, data)
    status, body = call_api(base, "/api/learned-experiment/runs/saved-case")
    assert status == 422 and "统计" in body["error"]
