#!/usr/bin/env python3
"""Offline, paired native-wall diagnosis; no application defaults are changed.

Uses the pinned production model with its two actual noise branches plus a
separate fixed-initial-noise diagnostic. Full upstream DB stays in local cache;
only whitelisted numerical hold inputs are read. No pickle/joblib execution.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import urllib.request

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from boulderlab.learned_generator import (
    DEFAULT_CACHE, FEATURES, MODEL_FILES, ROLES, UPSTREAM_COMMIT,
    _discretize, _load_model, _nearest, build_hold_features, canonical_sha256,
    load_scaler, scaled_inputs,
)

DB_SHA256 = "9fcf87f93830e7d761fc6ba089de8463c5e574d75b35f6b8e46bbb9ea13f8ff5"
DB_BYTES = 806912
CACHE = ROOT / ".runtime/betazero-diagnosis"
LAYOUTS = {"kilter": "layout-0aa86d03949f", "home": "layout-ac0b5267bdc7"}
MODES = ("recursive_noisy", "seeded_fresh", "fixed_initial")


def native_wall(name):
    path = CACHE / "climb-backend/data/storage.db"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/EvanMcCormick37/ml-homewall-climb-generator/{UPSTREAM_COMMIT}/climb-backend/data/storage.db"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(DB_BYTES + 1)
        if len(data) != DB_BYTES or hashlib.sha256(data).hexdigest() != DB_SHA256:
            raise ValueError("Native database does not match pinned bytes")
        path.write_bytes(data)
    if hashlib.sha256(path.read_bytes()).hexdigest() != DB_SHA256:
        raise ValueError("Native database hash mismatch")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute("SELECT hold_index,x,y,pull_x,pull_y,useability,is_foot,tags FROM holds WHERE layout_id=? ORDER BY rowid", (LAYOUTS[name],)).fetchall()
    values = []
    for _, x, y, px, py, use, foot, tags in rows:
        tags = json.loads(tags) if isinstance(tags, str) else []
        values.append([x, y, px * use, py * use, float(foot), float("pinch" in tags), float("flat" in tags)])
    a = np.asarray(values, dtype=float)
    ids = [str(row[0]) for row in rows]
    if a.shape != (len(rows), 7) or not np.isfinite(a).all() or len(set(ids)) != len(ids):
        raise ValueError("Invalid native numeric inputs")
    return {"features": values, "placement_ids": ids, "angle_deg": 40 if name == "kilter" else 30}


def inference(adapted, grade, seed, mode, x_offset=0, guidance_value=3., projection_start=.8):
    """All branches share initial RNG seed; fresh draws have their own local RNG.

    recursive_noisy reproduces pinned production deterministic=True. seeded_fresh
    reproduces production deterministic=False, with the random stream seeded for
    this test. fixed_initial tests the noise reuse described in the upstream
    settings/help text and older training generator, not the production branch.
    """
    import torch
    if mode not in MODES:
        raise ValueError("Unknown noise mode")
    if not 0 <= projection_start <= .8:
        raise ValueError("Projection start must be in [0, .8]")
    started = time.monotonic()
    features, condition, diagnostics = scaled_inputs(adapted, grade, load_scaler())
    model = _load_model(DEFAULT_CACHE)
    g = torch.Generator(device="cpu").manual_seed(seed)
    manifold = torch.tensor(features, dtype=torch.float32)
    cond = torch.tensor(condition.reshape(1, 4), dtype=torch.float32)
    translation = torch.zeros(1, 1, 12)
    translation[0, 0, :2] = manifold.mean(dim=0)[:2]
    # The service draws this BEFORE initial diffusion noise when offset is None.
    if x_offset is None:
        offset_rng = g if mode == "seeded_fresh" else torch.Generator(device="cpu").manual_seed(seed)
        x_offset = torch.clamp(torch.randn((1,), generator=offset_rng), -1, 1).item() / 2
    x_range = (manifold[:, 0].max() - manifold[:, 0].min()).item()
    translation[0, 0, 0] = x_offset * x_range / 2 + manifold.mean(dim=0)[0].item()
    trace = []
    guidance = guidance_value * (.5 if grade > 22 else 1.)
    with torch.inference_mode():
        initial = torch.randn((1, 20, 12), generator=g)
        noisy = initial.clone()
        t = torch.ones(1, 1)
        for step in range(100):
            clean = model.predict_cfg(noisy, cond, t, guidance)
            if step in (0, 1, 5, 10, 19, 20, 21, 50, 90, 99):
                trace.append({"step": step, "t": t.item(), "role_counts": torch.argmax(clean[0, :, 7:], dim=1).bincount(minlength=5).tolist(), "null_min": clean[0, :, -1].min().item(), "null_max": clean[0, :, -1].max().item(), "tensor_digest": canonical_sha256(clean[0].tolist())})
            if t[0].item() < projection_start:
                phase = (projection_start - t) / projection_start
                strength = ((1 + torch.cos((phase + .5) * torch.pi)) if projection_start > .5 else (1 - torch.cos(phase * torch.pi / 2))).unsqueeze(2)
                translated = clean + translation
                flat = translated.reshape(-1, 12)
                indexes = _nearest(torch, flat, manifold)
                projected_features = manifold[indexes] * (flat[:, -1] < .95).unsqueeze(1)
                projected = torch.cat([projected_features.reshape(1, 20, 7), translated[:, :, 7:]], dim=2)
                clean = strength * (projected - translation) + (1 - strength) * clean
            t -= .01
            noise = noisy if mode == "recursive_noisy" else initial if mode == "fixed_initial" else torch.randn(noisy.shape, generator=g)
            noisy = model.forward_diffusion(clean, t, noise)
        output = clean + translation
        nearest = _nearest(torch, output.reshape(-1, 12), manifold).numpy()
        tensor = output[0].numpy()
    if not np.isfinite(tensor).all():
        raise ValueError("Nonfinite model output")
    slots, selected, repairs = _discretize(tensor, nearest, manifold.numpy(), adapted["placement_ids"])
    roles = Counter(s["role"] for s in selected)
    raw_roles = Counter(s["role"] for s in slots)
    valid = [s for s in slots if s["role"] != "null"]
    role_mismatch = sum(bool(adapted["features"][s["hold_index"]][4]) and s["role"] != "foot" for s in selected)
    diagnostics.update(elapsed_seconds=round(time.monotonic()-started,4), selected_holds=len(selected), raw_non_null_slots=len(valid), duplicate_slots=len(valid)-len({s["hold_index"] for s in valid}), raw_roles=dict(raw_roles), roles=dict(roles), hand_role_on_foot_only=role_mismatch)
    return {"seed": seed, "grade": grade, "noise_mode": mode, "x_offset": x_offset,
            "diagnostics": diagnostics, "raw_tensor": tensor.tolist(), "raw_slots": slots,
            "raw_selections": selected, "role_repairs": repairs, "trace": trace}


def cases():
    request = json.loads((ROOT / "fixtures/learned-wall-request.json").read_text())
    ours = build_hold_features(request, request["reference_layout"])
    kilter, home = native_wall("kilter"), native_wall("home")
    result = {"bettar18-25": ours, "kilter642-40": kilter, "home204-30": home,
              "kilter642-25": {**kilter, "angle_deg": 25}}
    for subset_seed in range(3):
        g = np.random.default_rng(subset_seed)
        a = np.asarray(kilter["features"])
        indexes = np.sort(np.concatenate([g.choice(np.flatnonzero(a[:,4] == 0),8,replace=False), g.choice(np.flatnonzero(a[:,4] == 1),10,replace=False)]))
        result[f"kilter18-subset{subset_seed}-25"] = {"features": a[indexes].tolist(), "placement_ids": [kilter["placement_ids"][i] for i in indexes], "angle_deg": 25}
    neutral = np.asarray(kilter["features"]).copy()
    lengths = np.linalg.norm(neutral[:,2:4],axis=1)
    neutral[:,2:4] *= np.divide(.5,lengths,out=np.zeros_like(lengths),where=lengths>1e-12)[:,None]
    neutral[:,6] = 0
    result["kilter642-neutral-25"] = {**kilter, "features": neutral.tolist(), "angle_deg": 25}
    return result


def summarize(rows):
    counts = [r["diagnostics"]["selected_holds"] for r in rows]
    return {"samples":len(rows),"empty":counts.count(0),"single":counts.count(1),"selected_mean":float(np.mean(counts)),"selected_median":float(np.median(counts)),"selected_range":[min(counts),max(counts)],"non_null_slots_mean":float(np.mean([r["diagnostics"]["raw_non_null_slots"] for r in rows])),"duplicate_slots_mean":float(np.mean([r["diagnostics"]["duplicate_slots"] for r in rows])),"raw_start_and_finish":sum(r["diagnostics"]["raw_roles"].get("start",0)>0 and r["diagnostics"]["raw_roles"].get("finish",0)>0 for r in rows),"role_mismatch_total":sum(r["diagnostics"]["hand_role_on_foot_only"] for r in rows)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cases", nargs="+", default=["bettar18-25","kilter642-40","home204-30"])
    p.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    p.add_argument("--seeds", type=int, default=10)
    p.add_argument("--grades", nargs="+", type=int, default=[16,18,20])
    p.add_argument("--native-offset", action="store_true")
    p.add_argument("--guidance", type=float, default=3.)
    p.add_argument("--projection-start", type=float, default=.8)
    p.add_argument("--output", default="outputs/betazero-diagnosis/comparison.json")
    args=p.parse_args(); all_cases=cases(); runs=[]; summaries=[]
    for case in args.cases:
        adapted=all_cases[case]
        for mode in args.modes:
            rows=[]
            for grade in args.grades:
                for seed in range(args.seeds):
                    row=inference(adapted,grade,seed,mode,None if args.native_offset else 0,args.guidance,args.projection_start)
                    row["case"]=case; rows.append(row)
            runs.extend(rows); summary={"case":case,"mode":mode,**summarize(rows)}; summaries.append(summary)
            print(json.dumps(summary),flush=True)
    output={"schema_version":"betazero-diagnosis/1","upstream_commit":UPSTREAM_COMMIT,"weight_sha256":MODEL_FILES["ddpm-weights.pth"]["sha256"],"source_db_sha256":DB_SHA256,"protocol":{"grades":args.grades,"seeds":list(range(args.seeds)),"steps":100,"guidance":args.guidance,"projection_start":args.projection_start,"x_offset":"upstream-random" if args.native_offset else 0,"roles":ROLES,"comparison_metric":"selected hold sets, NOT complete routes or verified grades"},"inputs":{k:{"hold_count":len(v["features"]),"angle":v["angle_deg"],"feature_digest":canonical_sha256(v),"feature_order":FEATURES} for k,v in all_cases.items() if k in args.cases},"summary":summaries,"runs":runs}
    target=ROOT/args.output;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(output,indent=2,ensure_ascii=False,allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
