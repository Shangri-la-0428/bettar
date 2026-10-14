"""Optional, offline BetaZero hold-set proposals, never movement sequences.

The ordinary application does not import torch. The model's production
architecture, schedule and manifold projection are pinned to the upstream
commit below; its MIT license is in assets/learned/BETAZERO-LICENSE.txt.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
import time

import numpy as np

from .geometry import rotation_z, selected_contact

UPSTREAM_COMMIT = "6f0acb414a5f1ab070aa62d02ac98f2602011821"
UPSTREAM_REPOSITORY = "https://github.com/EvanMcCormick37/ml-homewall-climb-generator"
ADAPTER_VERSION = "betazero-fixed-wall/2"
DEFAULT_CACHE = Path(__file__).resolve().parent.parent / ".runtime/learned-model"
MODEL_FILES = {
    "ddpm-weights.pth": {
        "bytes": 87027568,
        "git_blob_sha1": "785c38c0f9e153159899826d5c78425b0f9ef880",
        "sha256": "b8bf14a7e5a82a78b4516ab3e382c3fa0d6edab83378f5f3b038301fca0de5aa",
    },
    "scaler-weights.joblib": {
        "bytes": 1841,
        "git_blob_sha1": "e7813e2898677f40100615fd0c3a77d562e54d0f",
        "sha256": "1fc77830c37e1dc80c2fd7399176e8a09de0b861c454353e14fc127df5039a48",
    },
}
FEATURES = ["x", "y", "pull_x", "pull_y", "is_foot", "pinch", "flat"]
CONDITIONS = ["grade", "quality", "ascents", "angle"]
ROLES = ["start", "finish", "hand", "foot", "null"]
_MODELS = {}


def canonical_sha256(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def request_digest(request):
    """Engine-compatible canonical request hash without importing its runtime.

    Requests contain only these schema-defined unordered ID collections. A
    regression test binds this lightweight worker helper to engine.canonical_hash.
    """
    def normalize(value, path=()):
        if isinstance(value, dict):
            return {key: normalize(item, path + (key,)) for key, item in value.items()}
        if isinstance(value, list):
            values = [normalize(item, path + (i,)) for i, item in enumerate(value)]
            if path in {("scene", "inventory"), ("reference_layout",)}:
                values.sort(key=lambda item: item["id"])
            if len(path) == 3 and path[:2] == ("route_constraints", "allowed_contacts"):
                values.sort()
            return values
        return int(value) if isinstance(value, float) and value.is_integer() else value
    return canonical_sha256(normalize(request))


def verified_model_bytes(path, name):
    """Bind downloaded bytes to the pinned Git blob and an independent digest."""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("BetaZero is not installed; run scripts/prepare_learned_model.py") from exc
    expected = MODEL_FILES[name]
    blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if (len(data) != expected["bytes"] or blob != expected["git_blob_sha1"]
            or hashlib.sha256(data).hexdigest() != expected["sha256"]):
        raise ValueError(f"BetaZero {name} does not match the pinned production artifact")
    return data


def extract_scaler(data):
    """Read fixed float64 slices from one exact file, never unpickle anything.

    This is deliberately NOT a general joblib loader. Each offset was inspected
    in the pinned 1841-byte file: the raw joblib arrays have shape (4,), dtype
    little-endian f8 and C order. A changed upstream file needs explicit review.
    The full digest check prevents interpreting arbitrary pickle instructions.
    """
    expected = MODEL_FILES["scaler-weights.joblib"]
    if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
        raise ValueError("Cannot extract an unknown scaler artifact")
    fields = ["scale", "offset", "data_min", "data_max", "data_range"]
    offsets = {"condition": [672, 768, 864, 960, 1056],
               "hold": [1472, 1552, 1632, 1712, 1792]}
    result = {"schema_version": "betazero-scaler/1", "source_sha256": expected["sha256"]}
    for kind, starts in offsets.items():
        result[kind] = {name: list(struct.unpack_from("<4d", data, start))
                        for name, start in zip(fields, starts)}
        result[kind]["features"] = CONDITIONS if kind == "condition" else FEATURES[:4]
    validate_scaler(result)
    return result


def validate_scaler(value):
    if (not isinstance(value, dict) or value.get("schema_version") != "betazero-scaler/1"
            or value.get("source_sha256") != MODEL_FILES["scaler-weights.joblib"]["sha256"]):
        raise ValueError("Invalid BetaZero scaler metadata")
    for kind, names in (("condition", CONDITIONS), ("hold", FEATURES[:4])):
        record = value.get(kind, {})
        if record.get("features") != names:
            raise ValueError("Invalid BetaZero scaler feature order")
        arrays = {}
        for field in ("scale", "offset", "data_min", "data_max", "data_range"):
            array = np.asarray(record.get(field), dtype=float)
            if array.shape != (4,) or not np.isfinite(array).all():
                raise ValueError("BetaZero scaler requires four finite numbers per field")
            arrays[field] = array
        if (np.any(arrays["scale"] <= 0) or np.any(arrays["data_range"] <= 0)
                or not np.allclose(arrays["data_max"] - arrays["data_min"], arrays["data_range"], atol=1e-12)
                or not np.allclose(arrays["scale"] * arrays["data_range"], 2, atol=1e-12)
                or not np.allclose(arrays["scale"] * arrays["data_min"] + arrays["offset"], -1, atol=1e-12)):
            raise ValueError("Inconsistent BetaZero min-max scaler")
    return value


def load_scaler(cache_dir=None):
    cache = Path(cache_dir or DEFAULT_CACHE)
    expected = extract_scaler(verified_model_bytes(cache / "scaler-weights.joblib", "scaler-weights.joblib"))
    try:
        value = json.loads((cache / "scaler.json").read_text())
    except FileNotFoundError as exc:
        raise ValueError("Missing primitive scaler.json; run scripts/prepare_learned_model.py") from exc
    validate_scaler(value)
    if value != expected:
        raise ValueError("Primitive scaler parameters differ from the pinned artifact")
    return value


def build_hold_features(request, placements):
    """Encode one installed plane without changing positions or permissions.

    x/y use mounting coordinates in feet, with x=0 at the panel's left edge.
    Pull is the selected patch's local pull rotated into panel axes, normalized
    in that 2-D plane and multiplied by the explicit neutral useability 0.5.
    """
    scene = request["scene"]
    panels = scene.get("wall_panels", [])
    if len(panels) != 1:
        raise ValueError("BetaZero first experiment supports exactly one wall panel")
    panel = panels[0]
    if (any("mount" in p or p.get("wall_panel_id") != panel["id"] for p in placements)
            or any(abs(float(v)) > 1e-8 for v in panel["rotation_deg"][1:])):
        raise ValueError("BetaZero first experiment requires unmounted holds on one unturned plane")
    if not placements or len({p["id"] for p in placements}) != len(placements):
        raise ValueError("BetaZero requires unique installed hold IDs")
    inventory = {item["id"]: item for item in scene["inventory"]}
    features, annotations = [], []
    for placement in placements:
        item = inventory[placement["inventory_id"]]
        if item["type"] == "volume":
            raise ValueError("BetaZero first experiment does not encode volumes")
        contact = selected_contact(placement, item)
        limbs = contact["limbs"]
        pull = rotation_z(placement["rotation_deg"]) @ np.asarray(contact.get("pull_direction", item["pull_direction"]), float)
        length = float(np.linalg.norm(pull[:2]))
        if length < 1e-10:
            raise ValueError("Selected contact has no wall-tangent pull direction")
        pull_xy = pull[:2] / length * .5
        flat = "flat" in item.get("tags", [])
        foot_only = not bool(set(limbs).intersection({"LH", "RH"}))
        feature = [(placement["u"] + panel["width"] / 2) / .3048,
                   placement["v"] / .3048, *pull_xy.tolist(),
                   float(foot_only), float(item["type"] == "pinch"), float(flat)]
        features.append(feature)
        annotations.append({"placement_id": placement["id"], "allowed_limbs": list(limbs),
                            "useability": .5, "useability_basis": "upstream-neutral-unannotated",
                            "flat": flat, "flat_basis": "explicit-tag" if flat else "unannotated-false"})
    values = np.asarray(features)
    if not np.isfinite(values).all():
        raise ValueError("Hold features must be finite")
    angle = float(scene.get("angle_deg", 0)) + float(panel["rotation_deg"][0])
    return {"placement_ids": [p["id"] for p in placements], "features": features,
            "feature_order": FEATURES, "annotations": annotations, "angle_deg": angle,
            "coordinate_convention": "panel-left-bottom-feet; selected-patch-pull-in-panel-axes"}


def scaled_inputs(adapted, grade, scaler):
    grade = {"V3": 16, "V4": 18, "V5": 20}.get(grade, grade)
    if isinstance(grade, bool) or not isinstance(grade, (int, float)) or not math.isfinite(grade):
        raise ValueError("Grade must be a finite upstream numeric condition or V3/V4/V5")
    features = np.asarray(adapted["features"], dtype=float).copy()
    features[:, :4] = features[:, :4] * scaler["hold"]["scale"] + scaler["hold"]["offset"]
    # Upstream quality -> log(1-(quality-3)); ascents -> log(ascents).
    transformed = np.array([float(grade), 0, math.log(1000), adapted["angle_deg"]])
    condition = transformed * scaler["condition"]["scale"] + scaler["condition"]["offset"]
    diagnostics = {
        "condition_input": {"grade": grade, "quality": 3, "ascents": 1000, "angle": adapted["angle_deg"]},
        "condition_scaled": condition.tolist(),
        "holds_outside_training_range": int(np.any(np.abs(features[:, :4]) > 1 + 1e-6, axis=1).sum()),
        "condition_outside_training_range": bool(np.any(np.abs(condition) > 1 + 1e-6)),
        "limitation": "Uncalibrated transfer from board data; neither movement order nor climbing grade validation",
    }
    return features, condition, diagnostics


def _load_model(cache):
    verified_model_bytes(cache / "ddpm-weights.pth", "ddpm-weights.pth")
    key = str(cache.resolve())
    if key in _MODELS:
        return _MODELS[key]
    try:
        import torch
        from ._betazero_torch import ClimbDDPM, Noiser
    except ImportError as exc:
        raise ValueError("Optional ML runtime missing; install requirements-ml.txt in .runtime/venv-ml") from exc
    torch.set_num_threads(2)
    state = torch.load(cache / "ddpm-weights.pth", map_location="cpu", weights_only=True)
    if not isinstance(state, dict) or not all(isinstance(k, str) and isinstance(v, torch.Tensor) for k, v in state.items()):
        raise ValueError("BetaZero checkpoint is not a tensor state_dict")
    state = {k.removeprefix("_orig_mod."): v for k, v in state.items()}
    model = ClimbDDPM(Noiser())
    model.load_state_dict(state, strict=True)
    model.eval()
    _MODELS[key] = model
    return model


def _nearest(torch, flat, manifold):
    # Exact upstream weighting and foot-role threshold. No compatibility repairs.
    hand = flat[:, -2] < .85
    weights = torch.tensor([1., 1., .8, .8, 2., .1, .1])
    foot_weights = torch.tensor([1., 1., .05, .05, 1., .05, .05])
    idx = torch.empty(len(flat), dtype=torch.long)
    for mask, w in ((hand, weights), (~hand, foot_weights)):
        if mask.any():
            idx[mask] = torch.cdist(flat[mask, :7] * w, manifold * w).min(dim=1).indices
    return idx


def _discretize(tensor, nearest, manifold, placement_ids):
    """Match upstream dedup and start/finish repair, while retaining raw slots."""
    roles = np.argmax(tensor[:, 7:], axis=1)
    slots = [{"slot": i, "hold_index": int(index), "placement_id": placement_ids[index],
              "role": ROLES[int(role)]} for i, (index, role) in enumerate(zip(nearest, roles))]
    c = np.stack([nearest, roles, manifold[nearest, 1]], axis=1)
    c = c[c[:, 1] != 4]
    if not len(c):
        return slots, [], ["all-null-output"]
    c = c[c[:, 1].argsort()]
    _, unique_indices = np.unique(c[:, 0], return_index=True)
    c = c[unique_indices]
    repairs = []
    if not np.any(c[:, 1] == 1):
        c[np.argmax(c[:, 2]), 1] = 1
        repairs.append("upstream-added-highest-finish")
    if not np.any(c[:, 1] == 0):
        minimum = np.argmin(c[:, 2] + (c[:, 1] == 3).astype(np.float32))
        if minimum != np.argmax(c[:, 2]) or len(c) == 1:
            c[minimum, 1] = 0
            repairs.append("upstream-added-low-start")
    selections = [{"hold_index": int(index), "placement_id": placement_ids[int(index)], "role": ROLES[int(role)]}
                  for index, role in c[:, :2]]
    return slots, selections, repairs


def generate_proposal(request, placements, grade, seed, cache_dir=None, sampling_mode="seeded_fresh"):
    """Generate a raw hold set. Bettar anchor/role fixes belong to the experiment.

    The 20 diffusion slots are exchangeable model slots, NOT transfer order.
    Inference uses CPU, float32, 100 steps, CFG=3, projection_start=.8 and fixed
    x_offset=0. This removes upstream's optional random horizontal translation.
    A local seeded RNG draws fresh noise each step, matching the upstream normal
    branch without losing reproducibility. recursive_noisy is retained only to
    reproduce the first experiment's problematic deterministic=True branch.
    """
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("Seed must be a nonnegative int below 2**63")
    if sampling_mode not in {"seeded_fresh", "recursive_noisy"}:
        raise ValueError("Unknown BetaZero sampling mode")
    started = time.monotonic()
    cache = Path(cache_dir or DEFAULT_CACHE)
    scaler = load_scaler(cache)
    adapted = build_hold_features(request, placements)
    features, condition, diagnostics = scaled_inputs(adapted, grade, scaler)
    model = _load_model(cache)
    import torch
    generator = torch.Generator(device="cpu").manual_seed(seed)
    manifold = torch.tensor(features, dtype=torch.float32)
    cond = torch.tensor(condition.reshape(1, 4), dtype=torch.float32)
    translation = torch.zeros(1, 1, 12)
    translation[0, 0, :2] = manifold.mean(dim=0)[:2]
    guidance = 1.5 if diagnostics["condition_input"]["grade"] > 22 else 3.
    with torch.inference_mode():
        noisy = torch.randn((1, 20, 12), generator=generator)
        t = torch.ones((1, 1))
        for _ in range(100):
            clean = model.predict_cfg(noisy, cond, t, guidance)
            if t[0].item() < .8:
                a = (.8 - t) / .8
                strength = torch.where(t > .8, torch.zeros_like(t), 1 + torch.cos((a + .5) * torch.pi)).unsqueeze(2)
                translated = clean + translation
                flat = translated.reshape(-1, 12)
                indexes = _nearest(torch, flat, manifold)
                projected_features = manifold[indexes] * (flat[:, -1] < .95).unsqueeze(1)
                projected = torch.cat([projected_features.reshape(1, 20, 7), translated[:, :, 7:]], dim=2)
                clean = strength * (projected - translation) + (1 - strength) * clean
            t -= .01
            noise = (torch.randn(noisy.shape, generator=generator)
                     if sampling_mode == "seeded_fresh" else noisy)
            noisy = model.forward_diffusion(clean, t, noise)
        output = clean + translation
        nearest = _nearest(torch, output.reshape(-1, 12), manifold).numpy()
        tensor = output[0].numpy()
    if not np.isfinite(tensor).all():
        raise ValueError("BetaZero produced non-finite outputs")
    slots, selections, repairs = _discretize(tensor, nearest, manifold.numpy(), adapted["placement_ids"])
    diagnostics.update(upstream_role_repairs=repairs, raw_non_null_slots=sum(s["role"] != "null" for s in slots),
                       selected_holds=len(selections), elapsed_seconds=round(time.monotonic() - started, 4))
    return {
        "schema_version": "learned-proposal/1", "seed": seed,
        "grade": diagnostics["condition_input"]["grade"], "request_digest": request_digest(request),
        "grade_condition": diagnostics["condition_input"]["grade"],
        "raw_selections": selections, "raw_slots": slots, "raw_tensor": tensor.tolist(),
        "input_features": adapted,
        "provenance": {
            "generator": "BetaZero", "upstream_repository": UPSTREAM_REPOSITORY,
            "upstream_commit": UPSTREAM_COMMIT, "adapter_version": ADAPTER_VERSION,
            "weight_sha256": MODEL_FILES["ddpm-weights.pth"]["sha256"],
            "scaler_source_sha256": MODEL_FILES["scaler-weights.joblib"]["sha256"],
            "scaler_parameters_sha256": canonical_sha256(scaler),
            "physical_input_sha256": canonical_sha256({"scene": request["scene"], "placements": placements}),
            "runtime": {"torch": torch.__version__, "numpy": np.__version__, "device": "cpu", "threads": 2},
            "inference": {"timesteps": 100, "slots": 20, "guidance": guidance,
                          "projection_start": .8, "x_offset": 0, "deterministic": True,
                          "seeded_rng": True, "noise_mode": sampling_mode,
                          "upstream_deterministic": sampling_mode == "recursive_noisy"},
        },
        "diagnostics": diagnostics,
    }
