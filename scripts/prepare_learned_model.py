#!/usr/bin/env python3
"""Fetch the two pinned production artifacts; never unpickle the scaler."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from boulderlab.learned_generator import (DEFAULT_CACHE, MODEL_FILES, UPSTREAM_COMMIT,
                                         extract_scaler, generate_proposal,
                                         request_digest, verified_model_bytes)


def prepare(cache_dir):
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    base = ("https://raw.githubusercontent.com/EvanMcCormick37/ml-homewall-climb-generator/"
            + UPSTREAM_COMMIT + "/climb-backend/data/models/")
    for name, metadata in MODEL_FILES.items():
        target = cache / name
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".download")
            try:
                with urllib.request.urlopen(base + name, timeout=90) as response, temporary.open("wb") as output:
                    remaining = metadata["bytes"] + 1
                    while remaining:
                        part = response.read(min(1024 * 1024, remaining))
                        if not part:
                            break
                        output.write(part)
                        remaining -= len(part)
                verified_model_bytes(temporary, name)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        verified_model_bytes(target, name)
    scaler = extract_scaler(verified_model_bytes(cache / "scaler-weights.joblib", "scaler-weights.joblib"))
    (cache / "scaler.json").write_text(json.dumps(scaler, indent=2, allow_nan=False) + "\n")
    return {"cache_dir": str(cache.resolve()), "artifact_bytes": sum(v["bytes"] for v in MODEL_FILES.values()),
            "weights": MODEL_FILES, "scaler_loading": "fixed-byte primitive extraction; no pickle execution"}


def generate_batch(input_path, output_path, cache_dir):
    source = json.loads(Path(input_path).read_text())
    request = source.get("request", source)
    placements = request["reference_layout"]
    proposals = []
    for grade in (16, 18, 20):
        for seed in range(10):
            proposal = generate_proposal(request, placements, grade, seed, cache_dir)
            proposals.append(proposal)
            print(json.dumps({"grade": grade, "seed": seed, "holds": len(proposal["raw_selections"]),
                              "seconds": proposal["diagnostics"]["elapsed_seconds"]}), flush=True)
    repeat = generate_proposal(request, placements, 16, 2, cache_dir)
    original = proposals[2]
    deterministic = all(repeat[field] == original[field] for field in ("raw_tensor", "raw_slots", "raw_selections"))
    if not deterministic:
        raise RuntimeError("Seed 2 reproduction mismatch; refusing to publish a non-reproducible batch")
    result = {"schema_version": "learned-proposal-batch/1", "request_sha256": request_digest(request),
              "upstream_commit": UPSTREAM_COMMIT, "proposals": proposals,
              "verification": {"seed_2_repeat_bit_identical": True, "sample_count": len(proposals)}}
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(target.resolve()), "verification": result["verification"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    parser.add_argument("--generate-proposals", metavar="REQUEST_JSON")
    parser.add_argument("--output", default=str(DEFAULT_CACHE / "proposals.json"))
    args = parser.parse_args()
    print(json.dumps(prepare(args.cache_dir), ensure_ascii=False, indent=2))
    if args.generate_proposals:
        generate_batch(args.generate_proposals, args.output, args.cache_dir)
