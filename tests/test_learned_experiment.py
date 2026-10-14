"""Saved learned proposals must be comparable and cannot manufacture evidence."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from boulderlab import learned_experiment as study
from boulderlab.engine import canonical_hash, code_hash, evaluate, make_bundle, validate_bundle
from boulderlab.route_constraints import allowed_contact_ids

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def role_wall(monkeypatch):
    hands, feet, all_limbs = {"LH", "RH"}, {"LF", "RF"}, set(study.LIMBS)
    permissions = {"left": all_limbs, "right": all_limbs, "top": hands,
                   "lf": feet, "rf": feet, **{p: all_limbs for p in "abcdef"}, "edge": hands, "toe": feet}
    monkeypatch.setattr(study, "_permissions", lambda request: permissions)
    ref = lambda pid: {"placement_id": pid, "contact_id": "main"}
    request = {"start_contacts": {"LH": ref("left"), "RH": ref("right"), "LF": ref("lf"), "RF": ref("rf")},
               "end_contacts": {"LH": ref("top"), "RH": ref("top"), "LF": None, "RF": None}}
    return request, permissions


def test_generated_roles_remap_preserve_anchors_and_drop_incompatible_surface(role_wall):
    request, _ = role_wall
    proposal = {"raw_selections": [
        {"placement_id": "a", "role": "start"}, {"placement_id": "a", "role": "finish"},
        {"placement_id": "toe", "role": "hand"}, {"placement_id": "edge", "role": "foot"},
        {"placement_id": "b", "role": "foot"}, {"placement_id": None, "role": "null"}]}
    mask, adjusted = study.adapt_proposal(request, proposal)
    assert adjusted["roles"] == {"hand": ["a", "left", "right", "top"], "foot": ["b", "lf", "rf"]}
    assert len(adjusted["remapped_roles"]) == 2
    assert len(adjusted["dropped_incompatible"]) == 2
    assert adjusted["duplicate_selections"] == [{"placement_id": "a", "role": "hand"}]
    assert "a" in mask["LH"] and "a" in mask["LF"]
    assert "b" not in mask["RH"] and "b" in mask["RF"]
    assert "top" not in mask["LF"]


def test_empty_model_output_is_retained_as_anchor_only_proposal(role_wall):
    request, _ = role_wall
    mask, adjusted = study.adapt_proposal(request, {"raw_selections": [{"role": "null"}] * 20})
    assert adjusted["roles"] == {k: sorted(v) for k, v in study.anchor_roles(request).items()}
    control, _ = study.random_mask(request, adjusted["roles"], 42)
    assert control == mask


@pytest.mark.parametrize("selection", [{"placement_id": "missing", "role": "hand"},
                                       {"placement_id": "a", "role": "mystery"}])
def test_unknown_model_selections_are_not_silently_replaced(role_wall, selection):
    with pytest.raises(ValueError, match="invalid model selection"):
        study.adapt_proposal(role_wall[0], {"raw_selections": [selection]})


def test_random_control_preserves_joint_roles_and_effective_counts(role_wall):
    request, _ = role_wall
    roles = {"hand": ["left", "right", "top", "a", "edge"], "foot": ["lf", "rf", "a", "b", "toe"]}
    original = study.role_mask(request, roles)
    masks = []
    for seed in range(30):
        mask, metadata = study.random_mask(request, roles, seed)
        assert mask == study.random_mask(request, roles, seed)[0]
        assert {l: len(ids) for l, ids in mask.items()} == {l: len(ids) for l, ids in original.items()}
        assert {r: len(ids) for r, ids in metadata["roles"].items()} == {r: len(ids) for r, ids in roles.items()}
        assert len(set(metadata["roles"]["hand"]) & set(metadata["roles"]["foot"])) == 1
        for role, anchors in study.anchor_roles(request).items():
            assert anchors <= set(metadata["roles"][role])
        masks.append(canonical_hash(mask))
    assert len(set(masks)) > 1


def test_representative_ranking_prefers_verified_then_release_and_load():
    def row(identifier, status="complete", p0="pass", release=2, peak=10):
        return {"id": identifier, "status": status, "metrics": {
            "p0_status": p0, "static_release_pass": release, "static_release_total": 4, "peak_load": peak}}
    rows = [row("no-sequence", "search_unresolved", "unknown"), row("fail", p0="fail", release=4, peak=0),
            row("load-high", release=3, peak=12), row("release-low", release=2, peak=1), row("chosen", release=3, peak=9)]
    assert min(rows, key=study.result_rank)["id"] == "chosen"
    assert min([{"id": "failed", "status": "generation_failed", "metrics": {}}], key=study.result_rank)["id"] == "failed"


def test_no_sequence_retains_all_physical_holds_and_failure_is_bounded(monkeypatch):
    request = study.read_json(ROOT / "fixtures" / "learned-wall-request.json")
    request["solver"].update(max_nfev=0, restarts=1)
    mask, _ = study.adapt_proposal(request, {"raw_selections": []})
    monkeypatch.setattr(study, "_sequence_search", lambda *a, **kw: ([], [{"termination_reason": "frontier_empty"}]))
    bundle, result = study.search_mask(request, mask, seconds=5)
    assert result["status"] == "search_unresolved"
    assert result["metrics"]["transfers"] is None and result["metrics"]["peak_load"] is None
    assert bundle["candidates"][0]["placements"] == request["reference_layout"]
    assert len(bundle["candidates"][0]["placements"]) == 18
    assert len(set().union(*(set(ids) for ids in mask.values()))) < 18
    validate_bundle(bundle)


def save_example(directory, request, candidate):
    request = deepcopy(request)
    mask = {limb: sorted(ids) for limb, ids in allowed_contact_ids(request, candidate["placements"]).items()}
    request["route_constraints"] = {"allowed_contacts": mask}
    evaluation = evaluate(request, candidate)
    bundle = make_bundle(request, [candidate], [evaluation])
    study.write_json(directory / "bundles" / "saved-case.json.gz", bundle)
    data = {"schema_version": study.FORMAT, "engine_code_hash": code_hash(),
            "comparison_request_digest": study.comparison_request_digest(request), "wall": study.wall_metadata(request),
            "runs": [{"id": "saved-case", "status": "complete", "selected_contacts": mask,
                      "bundle_file": "saved-case.json.gz", "bundle_digest": bundle["manifest"]["bundle_digest"],
                      "metrics": study.metrics_for(request, candidate, evaluation, mask)}]}
    save_index(directory, data)
    return data, bundle


def save_index(directory, data):
    data["index_digest"] = canonical_hash({k: v for k, v in data.items() if k != "index_digest"})
    study.write_json(directory / "experiment.json", data)


def test_saved_roundtrip_validates_same_wall_metrics_and_masks(tmp_path, example):
    _, expected = save_example(tmp_path, *example)
    assert study.load_run(tmp_path, "saved-case") == expected


@pytest.mark.parametrize("field", ["metrics", "status", "mask", "wall", "body_solver", "bundle_digest"])
def test_rehashed_index_cannot_forge_bundle_evidence(tmp_path, example, field):
    data, _ = save_example(tmp_path, *example)
    run = data["runs"][0]
    if field == "metrics":
        run["metrics"]["p0_status"] = "pass"
    elif field == "status":
        run["status"] = "search_unresolved"
    elif field == "mask":
        run["selected_contacts"]["RH"].remove("h4")
    elif field == "wall":
        data["wall"]["angle_deg"] += 1
    elif field == "body_solver":
        data["comparison_request_digest"] = "sha256:" + "0" * 64
    else:
        run["bundle_digest"] = "sha256:" + "0" * 64
    save_index(tmp_path, data)
    with pytest.raises(ValueError):
        study.load_run(tmp_path, "saved-case")


def test_corrupted_index_bundle_and_traversal_are_rejected(tmp_path, example):
    data, bundle = save_example(tmp_path, *example)
    data["wall"]["angle_deg"] += 1
    study.write_json(tmp_path / "experiment.json", data)
    with pytest.raises(ValueError, match="索引摘要"):
        study.load_experiment(tmp_path)
    data["wall"]["angle_deg"] -= 1
    for name in ("../../outside.json.gz", "/tmp/outside.json.gz", "outside.json"):
        data["runs"][0]["bundle_file"] = name
        save_index(tmp_path, data)
        with pytest.raises(ValueError, match="文件引用"):
            study.load_run(tmp_path, "saved-case")
    for run_id in ("../saved-case", "%2e%2e", "UPPERCASE"):
        with pytest.raises(ValueError, match="实验编号"):
            study.load_run(tmp_path, run_id)
    data["runs"][0]["bundle_file"] = "saved-case.json.gz"
    save_index(tmp_path, data)
    bundle["candidates"][0]["placements"][0]["u"] += .1
    study.write_json(tmp_path / "bundles" / "saved-case.json.gz", bundle)
    with pytest.raises(ValueError, match="integrity"):
        study.load_run(tmp_path, "saved-case")


def test_bundle_symlink_cannot_escape_saved_directory(tmp_path, example):
    study_dir = tmp_path / "study"
    _, bundle = save_example(study_dir, *example)
    outside = tmp_path / "outside.json.gz"
    study.write_json(outside, bundle)
    saved = study_dir / "bundles" / "saved-case.json.gz"
    saved.unlink()
    saved.symlink_to(outside)
    with pytest.raises(ValueError, match="保存目录内"):
        study.load_run(study_dir, "saved-case")


def test_serving_saved_results_requires_no_ml_runtime():
    code = """
import sys
class NoML:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'sklearn', 'joblib', 'diffusers'}:
            raise RuntimeError('Unexpected ML import: ' + fullname)
sys.meta_path.insert(0, NoML())
import boulderlab.server
import boulderlab.learned_experiment
print('optional-model-ok')
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "optional-model-ok"


@pytest.mark.parametrize("validation_fails", (False, True))
def test_runner_preserves_all_failures_and_publishes_only_verified_index(tmp_path, example, monkeypatch, validation_fails):
    spec = importlib.util.spec_from_file_location("study_runner_test", ROOT / "scripts" / "run_learned_experiment.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    request = example[0]
    request_path, proposals_path = tmp_path / "request.json", tmp_path / "proposals.json"
    study.write_json(request_path, request)
    proposals = [{"grade": grade, "seed": seed, "request_digest": canonical_hash(request),
                  "error": "deliberate inference failure", "provenance": {"runtime": "test"}}
                 for _, grade in study.CONDITIONS for seed in range(10)]
    study.write_json(proposals_path, {"proposals": proposals})
    baseline = make_bundle(request, [example[1]], [evaluate(request, example[1])])
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "search_mask", lambda *a: (baseline, {"status": "complete",
                        "metrics": {"p0_status": "unknown", "selected_holds": 7}, "search": {}}))
    def validate_staged(*args):
        if validation_fails:
            raise ValueError("deliberate saved-case validation failure")
        return baseline
    monkeypatch.setattr(runner, "validate_saved_run", validate_staged)
    args = SimpleNamespace(request=request_path, proposals=proposals_path, output=tmp_path / "output")
    if validation_fails:
        previous_request = deepcopy(request)
        previous_request["body"]["forearm"] += .01
        previous, _ = save_example(args.output, previous_request, example[1])
        # Prior versions named bundles by mask alone; a different body with the
        # same wall mask must not be overwritten before the new index is ready.
        old_name = canonical_hash(study.all_contacts(request))[-24:] + ".json.gz"
        old_path = args.output / "bundles" / old_name
        (args.output / "bundles" / "saved-case.json.gz").rename(old_path)
        previous["runs"][0]["bundle_file"] = old_name
        save_index(args.output, previous)
        old_bytes = old_path.read_bytes()
        with pytest.raises(ValueError, match="saved-case validation failure"):
            runner.run(args)
        assert study.read_json(args.output / "experiment.json") == previous
        assert old_path.read_bytes() == old_bytes
        study.load_run(args.output, "saved-case")
        return
    runner.run(args)
    data = study.read_json(tmp_path / "output" / "experiment.json")
    assert len(data["runs"]) == 61 and len(data["conditions"]) == 3
    assert data["summary"]["model"]["total"] == 30
    assert data["summary"]["model"]["generation_failed"] == 30
    assert data["summary"]["model"]["p0_pass"] == 0
    assert all(row["bundle_url"] is None for row in data["runs"] if row["source"] == "betazero")
