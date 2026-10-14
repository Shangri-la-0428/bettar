"""The optional proposal adapter does not weaken normal route validation."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from boulderlab.engine import canonical_hash
from boulderlab.learned_generator import (CONDITIONS, DEFAULT_CACHE, FEATURES, MODEL_FILES,
                                         _discretize, build_hold_features, extract_scaler,
                                         load_scaler, request_digest, scaled_inputs,
                                         validate_scaler, verified_model_bytes)

ROOT = Path(__file__).resolve().parents[1]


def fixture_request():
    bundle = json.loads((ROOT / "fixtures/wall-overhang-bundle.json").read_text())
    request = bundle["request"]
    request["reference_layout"] = bundle["candidates"][0]["placements"]
    return request


def synthetic_scaler():
    scaler = {"schema_version": "betazero-scaler/1", "source_sha256": MODEL_FILES["scaler-weights.joblib"]["sha256"]}
    for kind, features in (("hold", FEATURES[:4]), ("condition", CONDITIONS)):
        scaler[kind] = {"features": features, "scale": [2.] * 4, "offset": [-1.] * 4,
                        "data_min": [0.] * 4, "data_max": [1.] * 4, "data_range": [1.] * 4}
    return scaler


def test_import_has_no_torch_or_joblib_dependency():
    result = subprocess.run([sys.executable, "-c",
                             "import sys; import boulderlab.learned_generator; "
                             "assert 'torch' not in sys.modules; assert 'joblib' not in sys.modules"],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_adapter_keeps_geometry_and_reads_actual_panel_angle():
    request = fixture_request()
    before = copy.deepcopy(request)
    encoded = build_hold_features(request, request["reference_layout"])
    assert request == before
    assert encoded["angle_deg"] == 25
    assert len(encoded["features"]) == 18
    first = request["reference_layout"][0]
    assert encoded["features"][0][:2] == pytest.approx([(first["u"] + 2.4) / .3048, first["v"] / .3048])
    assert sum(row[4] for row in encoded["features"]) == 10
    assert all(np.linalg.norm(row[2:4]) == pytest.approx(.5) for row in encoded["features"])
    assert all(row[6] == 0 for row in encoded["features"])


def test_pull_rotation_and_explicit_type_flags():
    request = fixture_request()
    placement = request["reference_layout"][0]
    placement["rotation_deg"] = 90
    item = next(item for item in request["scene"]["inventory"] if item["id"] == placement["inventory_id"])
    item["type"] = "pinch"
    item["tags"] = ["flat"]
    values = build_hold_features(request, request["reference_layout"])["features"][0]
    assert values[2:4] == pytest.approx([.5, 0], abs=1e-10)
    assert values[4:] == [0, 1, 1]
    item["type"] = "sloper"
    del item["tags"]
    assert build_hold_features(request, request["reference_layout"])["features"][0][5:] == [0, 0]


@pytest.mark.parametrize("mutation", ["two_panels", "mounted", "wrong_panel", "yaw", "duplicate"])
def test_adapter_rejects_unsupported_geometry(mutation):
    request = fixture_request()
    placements = request["reference_layout"]
    if mutation == "two_panels":
        request["scene"]["wall_panels"].append(copy.deepcopy(request["scene"]["wall_panels"][0]))
    elif mutation == "mounted":
        placements[0]["mount"] = {"parent_id": "other"}
    elif mutation == "wrong_panel":
        placements[0]["wall_panel_id"] = "unknown"
    elif mutation == "yaw":
        request["scene"]["wall_panels"][0]["rotation_deg"][2] = 5
    else:
        placements.append(copy.deepcopy(placements[0]))
    with pytest.raises(ValueError):
        build_hold_features(request, placements)


def test_scaler_refuses_unknown_pickle_bytes_without_loading():
    with pytest.raises(ValueError, match="unknown scaler"):
        extract_scaler(b"cos\nsystem\n(S'echo should-never-run'\ntR.")


@pytest.mark.parametrize("mutation", ["feature_order", "nonfinite", "range", "scale", "metadata"])
def test_scaler_validates_numeric_structure(mutation):
    scaler = synthetic_scaler()
    assert validate_scaler(scaler) == scaler
    if mutation == "feature_order":
        scaler["hold"]["features"] = list(reversed(FEATURES[:4]))
    elif mutation == "nonfinite":
        scaler["hold"]["scale"][0] = float("nan")
    elif mutation == "range":
        scaler["hold"]["data_max"][0] = 5
    elif mutation == "scale":
        scaler["hold"]["scale"][0] = -1
    else:
        scaler["source_sha256"] = "bad"
    with pytest.raises(ValueError):
        validate_scaler(scaler)


def test_scaling_uses_log_condition_and_does_not_clip_unseen_features():
    encoded = {"features": [[2, .5, 0, -.5, 0, 1, 0]], "angle_deg": 25}
    features, condition, diagnostics = scaled_inputs(encoded, "V3", synthetic_scaler())
    assert features[0].tolist() == [3, 0, -1, -2, 0, 1, 0]
    assert condition.tolist() == pytest.approx([31, -1, np.log(1000)*2-1, 49])
    assert diagnostics["holds_outside_training_range"] == 1
    assert diagnostics["condition_outside_training_range"]


def test_request_digest_matches_engine_and_semantic_reordering():
    request = fixture_request()
    request["route_constraints"] = {"allowed_contacts": {limb: ["z", "a"] for limb in ("LH", "RH", "LF", "RF")}}
    assert request_digest(request) == canonical_hash(request)
    original = request_digest(request)
    request["reference_layout"].reverse()
    request["scene"]["inventory"].reverse()
    for values in request["route_constraints"]["allowed_contacts"].values():
        values.reverse()
    assert request_digest(request) == canonical_hash(request) == original


def test_nulls_are_preserved_and_empty_projection_is_reported():
    tensor = np.zeros((20, 12))
    tensor[:, -1] = 1
    slots, selected, repairs = _discretize(tensor, np.zeros(20, dtype=int), np.zeros((1, 7)), ["only"])
    assert len(slots) == 20
    assert all(slot["role"] == "null" for slot in slots)
    assert selected == []
    assert repairs == ["all-null-output"]


def test_upstream_dedup_and_role_repair_remain_distinct_from_raw_slots():
    tensor = np.zeros((4, 12))
    tensor[:, 9] = 1  # all hand roles, two duplicate hold selections
    slots, selected, repairs = _discretize(tensor, np.array([1, 0, 1, 2]),
                                          np.array([[0, 0, 0, 0, 0, 0, 0],
                                                    [0, 1, 0, 0, 0, 0, 0],
                                                    [0, 2, 0, 0, 0, 0, 0]]), ["low", "mid", "high"])
    assert all(slot["role"] == "hand" for slot in slots)
    assert [(s["placement_id"], s["role"]) for s in selected] == [("low", "start"), ("mid", "hand"), ("high", "finish")]
    assert repairs == ["upstream-added-highest-finish", "upstream-added-low-start"]


def test_missing_and_modified_model_fail_explicitly(tmp_path):
    path = tmp_path / "weights"
    with pytest.raises(ValueError, match="not installed"):
        verified_model_bytes(path, "ddpm-weights.pth")
    path.write_bytes(b"untrusted or truncated data")
    with pytest.raises(ValueError, match="pinned production"):
        verified_model_bytes(path, "ddpm-weights.pth")


@pytest.mark.skipif(not (DEFAULT_CACHE / "scaler-weights.joblib").exists(), reason="optional real scaler is not installed")
def test_pinned_scaler_extracts_original_training_ranges():
    scaler = load_scaler()
    assert scaler["hold"]["data_min"][:2] == [0, 0]
    assert scaler["hold"]["data_max"][:2] == pytest.approx([15+1/3, 14+1/3])
    assert scaler["condition"]["data_min"][::3] == [10, -5]
    assert scaler["condition"]["data_max"][::3] == [32, 70]


@pytest.mark.skipif(os.environ.get("BETTAR_TEST_MODEL") != "1", reason="real optional-model inference explicitly enabled")
def test_real_model_seed_two_reproduces_bit_identical_tensor():
    worker = ROOT / ".runtime/venv-ml/bin/python"
    result = subprocess.run([str(worker), "-c", """
import json
from boulderlab.learned_generator import generate_proposal
r=json.load(open('fixtures/learned-wall-request.json'))
a=generate_proposal(r,r['reference_layout'],16,2)
b=generate_proposal(r,r['reference_layout'],16,2)
assert a['raw_tensor']==b['raw_tensor']
assert a['raw_selections']==b['raw_selections']
assert a['request_digest']==b['request_digest']
assert a['provenance']['inference']['timesteps']==100
print('real-seed-2-bit-identical')
"""], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "real-seed-2-bit-identical" in result.stdout
