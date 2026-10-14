"""The own-algorithm study is read-only and does not require model inference."""
from threading import Thread

import pytest

from boulderlab import server, own_routes
from test_style_api import call_api


@pytest.fixture
def own_api(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    httpd.web_port = 5174
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", tmp_path / "outputs" / "own-routes-study"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


def test_missing_study_keeps_health_available(own_api):
    base, _ = own_api
    status, body = call_api(base, "/api/health")
    assert status == 200 and body["ok"]
    status, body = call_api(base, "/api/own-routes-study")
    assert status == 503 and body["error"]


def test_saved_study_uses_validated_loaders_and_is_read_only(own_api, monkeypatch):
    base, directory = own_api
    index = {"schema_version": "own-routes-study-v1", "routes": []}
    bundle = {"id": "reviewable-example"}
    calls = []
    monkeypatch.setattr(own_routes, "load_study", lambda path: calls.append(path) or index)
    monkeypatch.setattr(own_routes, "load_route", lambda path, route_id: calls.append((path, route_id)) or bundle)
    assert call_api(base, "/api/own-routes-study") == (200, index)
    assert call_api(base, "/api/own-routes-study/routes/lateral-balance") == (200, bundle)
    assert calls == [directory, (directory, "lateral-balance")]
    status, _ = call_api(base, "/api/own-routes-study", {})
    assert status == 404
    status, _ = call_api(base, "/api/own-routes-study", origin="https://example.org")
    assert status == 403


def test_saved_result_validation_failure_is_visible(own_api, monkeypatch):
    base, _ = own_api
    def stale(*_):
        raise ValueError("保存的线路检查已过期，请重新生成。")
    monkeypatch.setattr(own_routes, "load_route", stale)
    status, body = call_api(base, "/api/own-routes-study/routes/lateral-balance")
    assert status == 422 and "过期" in body["error"]
