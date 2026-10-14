"""Opt-in parity against hash-verified, pinned upstream inference source.

Default application/test imports do not require torch, pandas or joblib. The
explicit model test uses the isolated ML interpreter and existing audit cache;
it never downloads executable sources or deserializes a pickle.
"""
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]

# Only selected classes are compiled, after their bytes match both the pinned
# tree manifest and these independently recorded Git blob IDs. In particular,
# upstream imports, joblib loader, module initialization and DB pool are omitted.
PARITY_WORKER = r'''
import ast
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch
from torch import Tensor, nn
import torch.nn.functional as F

from boulderlab.learned_generator import (
    DEFAULT_CACHE, UPSTREAM_COMMIT, _load_model, build_hold_features,
    generate_proposal, load_scaler, scaled_inputs,
)
from scripts.diagnose_betazero import inference, native_wall

tree = json.loads((DEFAULT_CACHE / "tree.json").read_text())
assert tree["sha"] == UPSTREAM_COMMIT and not tree["truncated"]
entries = {entry["path"]: entry for entry in tree["tree"]}
scope = {
    "torch": torch, "Tensor": Tensor, "nn": nn, "F": F, "math": math,
    "Path": Path, "np": np, "ClimbsFeatureScaler": object,
}
sources = [
    ("ddpm_model.py", "60f3f6c691bf2808bfc0747858794a2d1cdeca16",
     {"SinusoidalPositionEmbeddings", "ResidualBlock1D", "Noiser", "ClimbDDPM"}),
    ("generation_utils.py", "5df4faee5f6bc0e9eea3ab2aecb31b82cf9bd0ed",
     {"ClimbDDPMGenerator"}),
]
source_evidence = []
for filename, known_blob, names in sources:
    path = "climb-backend/app/services/utils/" + filename
    entry = entries[path]
    data = (DEFAULT_CACHE / "upstream" / filename).read_bytes()
    blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    assert entry["type"] == "blob" and entry["size"] == len(data)
    assert blob == entry["sha"]
    assert blob == known_blob
    parsed = ast.parse(data, filename=path)
    parsed.body = [node for node in parsed.body
                   if isinstance(node, ast.ClassDef) and node.name in names]
    assert {node.name for node in parsed.body} == names
    exec(compile(parsed, path, "exec"), scope)
    source_evidence.append({"path": path, "git_blob_sha1": blob})

torch.set_num_threads(2)
# Restricted production loader supplies only validated tensor weights. The
# oracle architecture itself is the selected original upstream class code.
native_model = scope["ClimbDDPM"](scope["Noiser"]())
native_model.load_state_dict(_load_model(DEFAULT_CACHE).state_dict(), strict=True)
native_model.eval()
request = json.loads(Path("fixtures/learned-wall-request.json").read_text())
adapted_walls = {
    "bettar18": build_hold_features(request, request["reference_layout"]),
    "kilter642": native_wall("kilter"),
}
assert len(adapted_walls["bettar18"]["features"]) == 18
assert len(adapted_walls["kilter642"]["features"]) == 642

def oracle(adapted, grade, seed, x_offset, guidance, projection):
    features, condition, _ = scaled_inputs(adapted, grade, load_scaler())
    gen = scope["ClimbDDPMGenerator"].__new__(scope["ClimbDDPMGenerator"])
    gen.device = torch.device("cpu")
    gen.ddpm = native_model
    gen.deterministic_noise_generator = torch.Generator(device="cpu")
    gen.holds_manifolds = {"wall": torch.tensor(features, dtype=torch.float32)}
    gen.holds_com = {"wall": gen.holds_manifolds["wall"].mean(dim=0)}
    gen.holds_lookup = {"wall": np.arange(len(features))}
    gen._build_cond_tensor = lambda n, diff, angle: torch.tensor(
        np.tile(condition, (n, 1)), dtype=torch.float32)
    # Capture the actual final tensor, including all-null failures, before the
    # original index-conversion routine's empty-array argmax can throw.
    gen._project_onto_indices = lambda output, *_: output.detach().cpu().numpy()
    # The original False branch uses global RNG for both optional random
    # translation and every fresh noise draw. Seed immediately before calling.
    torch.manual_seed(seed)
    return gen.generate("wall", 1, adapted["angle_deg"], grade, 100,
                        False, projection, x_offset, guidance, seed)[0]

checks = []
for wall_name in adapted_walls:
    for x_offset in (0, None):
        for guidance, projection in ((3., .8), (5., .5)):
            seed, grade = 3, 18
            adapted = adapted_walls[wall_name]
            actual = inference(adapted, grade, seed, "seeded_fresh", x_offset,
                               guidance_value=guidance, projection_start=projection)
            expected = oracle(adapted, grade, seed, x_offset, guidance, projection)
            actual_tensor = np.asarray(actual["raw_tensor"])
            difference = float(np.max(np.abs(expected - actual_tensor)))
            case = {"wall": wall_name, "seed": seed, "grade": grade,
                    "x_offset": x_offset, "guidance": guidance,
                    "projection_start": projection,
                    "exact_tensor_match": bool(np.array_equal(expected, actual_tensor)),
                    "max_absolute_difference": difference}
            assert case["exact_tensor_match"], json.dumps(case)
            checks.append(case)

old = generate_proposal(request, request["reference_layout"], 18, 3, sampling_mode="recursive_noisy")
diagnosed = inference(adapted_walls["bettar18"], 18, 3, "recursive_noisy", 0)
assert old["raw_tensor"] == diagnosed["raw_tensor"]
assert old["raw_slots"] == diagnosed["raw_slots"]
assert old["raw_selections"] == diagnosed["raw_selections"]
assert old["diagnostics"]["upstream_role_repairs"] == diagnosed["role_repairs"]
fixed = generate_proposal(request, request["reference_layout"], 18, 3)
fresh = inference(adapted_walls["bettar18"], 18, 3, "seeded_fresh", 0)
assert fixed["raw_tensor"] == fresh["raw_tensor"]
assert fixed["raw_selections"] == fresh["raw_selections"]
assert fixed["provenance"]["adapter_version"] == "betazero-fixed-wall/2"
assert fixed["provenance"]["inference"]["upstream_deterministic"] is False
assert fixed["provenance"]["inference"]["seeded_rng"] is True
assert fixed["provenance"]["inference"]["noise_mode"] == "seeded_fresh"
print(json.dumps({"fresh_noise_cases": checks, "recursive_matches_saved_adapter": True,
                  "fixed_adapter_matches_native_fresh": True, "pinned_source_blobs": source_evidence}))
'''


@pytest.mark.skipif(os.environ.get("BETTAR_TEST_MODEL") != "1",
                    reason="real optional-model and pinned upstream parity explicitly enabled")
def test_noise_diagnosis_matches_pinned_native_generator_and_existing_adapter():
    worker = ROOT / ".runtime/venv-ml/bin/python"
    result = subprocess.run([str(worker), "-c", PARITY_WORKER], cwd=ROOT,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout)
    assert len(evidence["fresh_noise_cases"]) == 8
    assert all(case["exact_tensor_match"] for case in evidence["fresh_noise_cases"])
    assert evidence["recursive_matches_saved_adapter"]
    assert evidence["fixed_adapter_matches_native_fresh"]
