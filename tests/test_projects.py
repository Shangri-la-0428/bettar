"""Durable routesetting sessions preserve revisions without re-running search."""
from copy import deepcopy
import json
from threading import Barrier, Thread
from uuid import uuid4

import pytest

from boulderlab import engine, projects, server
from boulderlab.draft_generation import generate_option
from boulderlab.example_gym import gym_metadata
from test_style_api import call_api


@pytest.fixture
def gym():
    return gym_metadata()


def new_record(gym, **changes):
    return {"name": "仰角区 · 平衡", "gym_id": gym["id"], "gym_version": gym["version"],
            "region_id": "overhang-bay", "brief": {"wall_profile": "overhang", "style": "balance", "difficulty": "medium", "gym_id": gym["id"], "region_id": "overhang-bay"},
            "entries": [], "selected_variant": None, "notes": "", "status": "draft", **changes}


@pytest.fixture
def option(gym):
    return generate_option({**new_record(gym)["brief"], "seed": 27, "variant": 0}, seconds=.000001)


@pytest.fixture
def store(tmp_path, gym):
    return projects.ProjectStore(tmp_path / "records", gym)


def ready_record(gym, option):
    return new_record(gym, entries=[{"variant": 0, "state": "ready", "result": deepcopy(option),
                                    "selectedCandidateId": option["bundle"]["candidates"][0]["id"]},
                                   {"variant": 1, "state": "error", "error": "预算内未找到"},
                                   {"variant": 2, "state": "waiting"}], selected_variant=0)


def rewrite_archive(store, saved, change):
    path = store.directory / f"{saved['id']}.json"
    archive = json.loads(path.read_text())
    change(archive["record"])
    archive["digest"] = engine.canonical_hash(archive["record"])
    path.write_text(json.dumps(archive))


def test_empty_and_partial_session_survive_new_store_instance(store, gym, option, monkeypatch):
    monkeypatch.setattr(engine, "generate", lambda *_: pytest.fail("saving must not generate"))
    monkeypatch.setattr(engine, "evaluate", lambda *_: pytest.fail("saving must not solve poses"))
    empty = store.save(new_record(gym))
    assert empty["revision"] == 1 and empty["entries"] == []
    payload = {**ready_record(gym, option), "id": empty["id"], "revision": 1, "status": "generating", "notes": "下一步微调右手点"}
    saved = store.save(payload)
    assert saved["revision"] == 2 and saved["entries"][2]["state"] == "waiting"
    reopened = projects.ProjectStore(store.directory, gym).load(saved["id"])
    assert reopened["entries"][0]["result"]["bundle"] == saved["entries"][0]["result"]["bundle"]
    assert reopened["entries"][1]["error"] == "预算内未找到"
    assert reopened["entries"][2]["state"] == "error" and "未完成" in reopened["entries"][2]["error"]
    assert reopened["interrupted"] and reopened["status"] == "draft"
    assert reopened["notes"] == payload["notes"] and reopened["selected_variant"] == 0
    listing = store.list()
    assert listing["last_project_id"] == saved["id"] and len(listing["projects"]) == 1
    assert "entries" not in listing["projects"][0]


def test_manual_revision_and_selected_candidate_saved_without_stale_claim(store, gym, option):
    payload = ready_record(gym, option)
    result = payload["entries"][0]["result"]
    source = result["bundle"]["candidates"][0]
    edited = deepcopy(source)
    edited.update(id="manual-new", parent_id=source["id"], revision=2, generator="manual")
    edited["placements"][0]["rotation_deg"] += 5
    result["bundle"]["candidates"].append(edited)
    payload["entries"][0]["selectedCandidateId"] = edited["id"]
    saved = store.save(payload)
    opened = store.load(saved["id"])
    restored = opened["entries"][0]["result"]["bundle"]
    assert len(restored["candidates"]) == 2
    assert opened["entries"][0]["selectedCandidateId"] == "manual-new"
    assert all(item["candidate_id"] != "manual-new" for item in restored["evaluations"])
    assert engine.validate_bundle(restored) == restored


def test_same_fingerprint_forged_pass_is_rejected(store, gym, option):
    payload = ready_record(gym, option)
    bundle = payload["entries"][0]["result"]["bundle"]
    assert bundle["evaluations"]
    bundle["evaluations"][0]["summary"]["status"] = "pass"
    with pytest.raises(ValueError):
        store.save(payload)
    assert not store.list()["projects"]


def test_old_engine_reopens_editable_with_old_checks_removed(store, gym, option):
    saved = store.save(ready_record(gym, option))
    rewrite_archive(store, saved, lambda record: record["entries"][0]["result"]["bundle"]["manifest"].update(code_hash="sha256:old-engine"))
    opened = store.load(saved["id"])
    assert opened["compatibility"]["status"] == "stale" and not opened["compatibility"]["read_only"]
    restored = opened["entries"][0]["result"]["bundle"]
    assert restored["evaluations"] == []
    assert restored["request"] == saved["entries"][0]["result"]["bundle"]["request"]
    assert engine.validate_bundle(restored) == restored
    assert store.list()["projects"][0]["compatibility"]["status"] == "stale"


def test_old_engine_embedded_setting_checks_do_not_block_rechecking_geometry(store, gym, option):
    saved = store.save(ready_record(gym, option))
    def add_old_evidence(record):
        bundle = record["entries"][0]["result"]["bundle"]
        bundle["manifest"]["code_hash"] = "sha256:old-engine"
        bundle["candidates"][0]["setting_report"] = {"legacy_evaluation": "opaque obsolete engine evidence"}
    rewrite_archive(store, saved, add_old_evidence)
    opened = store.load(saved["id"])
    assert not opened["compatibility"]["read_only"]
    restored = opened["entries"][0]["result"]["bundle"]
    assert "setting_report" not in restored["candidates"][0]
    assert restored["candidates"][0]["placements"] == option["bundle"]["candidates"][0]["placements"]
    assert restored["evaluations"] == []
    assert engine.validate_bundle(restored) == restored


def test_changed_gym_preserves_old_scene_without_claiming_current_checks(store, gym, option):
    saved = store.save(ready_record(gym, option))
    different_gym = {**gym, "version": "next-wall-layout"}
    reopened = projects.ProjectStore(store.directory, different_gym).load(saved["id"])
    assert reopened["compatibility"]["read_only"]
    assert reopened["entries"][0]["result"]["bundle"]["evaluations"] == []
    assert reopened["gym_version"] == gym["version"]
    assert reopened["entries"][0]["result"]["bundle"]["request"]["scene"] == option["bundle"]["request"]["scene"]
    with pytest.raises(ValueError, match="墙体版本"):
        projects.ProjectStore(store.directory, different_gym).save(reopened)


def test_unknown_old_schema_is_preserved_read_only(store, gym, option):
    saved = store.save(ready_record(gym, option))
    rewrite_archive(store, saved, lambda record: record["entries"][0]["result"]["bundle"].update(schema_version="old-unknown-schema"))
    opened = store.load(saved["id"])
    assert opened["compatibility"]["read_only"] and opened["compatibility"]["status"] == "unavailable"
    assert opened["entries"][0]["result"]["bundle"]["evaluations"] == []
    assert opened["entries"][0]["result"]["bundle"]["schema_version"] == "old-unknown-schema"


def test_revision_conflict_and_atomic_failure_preserve_saved_content(store, gym, monkeypatch):
    saved = store.save(new_record(gym))
    changed = store.save({**saved, "notes": "较新的笔记"})
    with pytest.raises(projects.ProjectConflict) as error:
        store.save({**saved, "notes": "延迟旧请求"})
    assert error.value.revision == 2
    assert store.load(saved["id"])["notes"] == "较新的笔记"
    monkeypatch.setattr(projects.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        store.save({**changed, "notes": "未落盘"})
    assert store.load(saved["id"])["notes"] == "较新的笔记"
    assert list(store.directory.glob("*.tmp")) == []


def test_simultaneous_autosaves_cannot_overwrite_each_other(store, gym):
    saved = store.save(new_record(gym))
    barrier = Barrier(3)
    results = []
    def save(note):
        barrier.wait()
        try:
            results.append(store.save({**saved, "notes": note}))
        except projects.ProjectConflict as exc:
            results.append(exc)
    threads = [Thread(target=save, args=(note,)) for note in ("页面一", "页面二")]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, projects.ProjectConflict) for result in results) == 1
    accepted = next(result for result in results if isinstance(result, dict))
    assert store.load(saved["id"])["notes"] == accepted["notes"]


def test_corrupt_archive_is_reported_and_never_overwritten(store, gym):
    saved = store.save(new_record(gym))
    path = store.directory / f"{saved['id']}.json"
    path.write_text('{"broken":')
    with pytest.raises(projects.ProjectCorrupt, match="原文件已保留"):
        store.load(saved["id"])
    listing = store.list()
    assert listing["projects"] == [] and listing["errors"][0]["id"] == saved["id"]
    with pytest.raises(projects.ProjectCorrupt):
        store.save(saved)
    assert path.read_text() == '{"broken":'
    path.write_text('[' * 1001 + '0' + ']' * 1001)
    assert store.list()["errors"][0]["id"] == saved["id"]
    assert path.read_text().startswith('[' * 1001)


@pytest.mark.parametrize("changes", [{"id": "../../outside"}, {"selected_variant": True}, {"revision": True}, {"region_id": "roof-exit"}, {"notes": "a" * 10001}, {"entries": [{"variant": 0, "state": "ready"}]}])
def test_invalid_records_cannot_create_files(store, gym, changes):
    with pytest.raises(ValueError):
        store.save(new_record(gym, **changes))
    assert not store.list()["projects"]


def test_region_binding_size_and_count_limits_are_enforced(store, gym, option, monkeypatch):
    payload = ready_record(gym, option)
    payload["entries"][0]["result"]["bundle"]["request"]["route_constraints"]["installation_region"]["region_id"] = "roof-exit"
    with pytest.raises(ValueError, match="实际安装区域"):
        store.save(payload)
    monkeypatch.setattr(projects, "MAX_PROJECT_BYTES", 100)
    with pytest.raises(ValueError, match="16 MB"):
        store.save(new_record(gym))
    monkeypatch.setattr(projects, "MAX_PROJECT_BYTES", 16 * 1024 * 1024)
    monkeypatch.setattr(projects, "MAX_PROJECTS", 1)
    store.save(new_record(gym))
    with pytest.raises(ValueError, match="100 条"):
        store.save(new_record(gym))


def test_saving_cannot_unlock_neighbours_or_change_an_existing_request(store, gym, option):
    payload = ready_record(gym, option)
    saved = store.save(payload)
    modified = deepcopy(saved)
    modified["entries"][0]["result"]["bundle"]["request"]["body"]["upper_arm"] += .01
    with pytest.raises(ValueError, match="生成请求不能被改写"):
        store.save(modified)
    for part in ("patches", "fixed_placements", "editable_placement_ids"):
        forged = deepcopy(payload)
        region = forged["entries"][0]["result"]["bundle"]["request"]["route_constraints"]["installation_region"]
        if part == "patches":
            region[part][0]["u_min"] -= .1
        elif part == "fixed_placements":
            region[part][0]["rotation_deg"] += 1
        else:
            region[part].append("neighbour")
        with pytest.raises(ValueError):
            store.save(forged)


@pytest.fixture
def local_projects_api(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    httpd.web_port = 5174
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


def test_http_project_create_list_resume_conflict_and_local_boundary(local_projects_api, gym):
    base = local_projects_api
    assert call_api(base, "/api/gym")[1]["id"] == gym["id"]
    status, saved = call_api(base, "/api/projects", new_record(gym))
    assert status == 200, saved
    assert call_api(base, "/api/projects")[1]["last_project_id"] == saved["id"]
    assert call_api(base, f"/api/projects/{saved['id']}")[1]["revision"] == 1
    status, updated = call_api(base, "/api/projects", {**saved, "notes": "第二天继续"})
    assert status == 200 and updated["revision"] == 2
    status, conflict = call_api(base, "/api/projects", saved)
    assert status == 409 and conflict["current_revision"] == 2
    assert call_api(base, "/api/projects", new_record(gym), origin="https://example.org")[0] == 403
    assert call_api(base, "/api/projects/not-a-uuid")[0] == 422
    assert call_api(base, f"/api/projects/{uuid4()}")[0] == 404
    assert call_api(base, "/api/projects", {**saved, "id": str(uuid4())})[0] == 404


def test_http_corrupt_record_is_reported_without_losing_other_records(local_projects_api, gym):
    base = local_projects_api
    _, saved = call_api(base, "/api/projects", new_record(gym))
    broken_id = str(uuid4())
    broken = server.ROOT / ".runtime" / "projects" / f"{broken_id}.json"
    broken.write_text("not JSON")
    status, listing = call_api(base, "/api/projects")
    assert status == 200 and listing["last_project_id"] == saved["id"]
    assert listing["errors"][0]["id"] == broken_id
    status, response = call_api(base, f"/api/projects/{broken_id}")
    assert status == 422 and "原文件已保留" in response["error"]
    assert broken.read_text() == "not JSON"
