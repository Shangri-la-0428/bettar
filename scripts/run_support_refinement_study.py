#!/usr/bin/env python3
"""Compare the six actually displayed v1 proposals against support feedback.

The frozen before bundles contain complete poses and reports. This is a small
diagnostic comparison, not a calibrated routesetting or human-climbability eval.
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from boulderlab.draft_generation import generate_option, VERSION
from boulderlab.engine import canonical_hash, validate_bundle
from boulderlab.own_routes import contact_signature, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="+", default=[f"{wall}-{letter}" for wall in ("roof", "overhang") for letter in "abc"])
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/support-refinement")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "after").mkdir(exist_ok=True)
    results = []
    for name in args.cases:
        if name not in {f"{wall}-{letter}" for wall in ("roof", "overhang") for letter in "abc"}:
            raise ValueError("Unknown saved comparison case")
        original = json.loads(gzip.decompress((ROOT / "outputs/support-refinement/before" / f"{name}.json.gz").read_bytes()))
        validate_bundle(original)
        brief = original["request"]["generation_brief"]
        options = {key: brief[key] for key in ("wall_profile", "style", "difficulty", "seed", "variant")}
        started = time.perf_counter()
        result = generate_option(options)
        after = result["bundle"]
        validate_bundle(after)
        # Improvement must not be purchased by changing the physical assumptions.
        for field in ("scene", "body", "mechanics_parameters", "solver", "start_contacts", "end_contacts"):
            assert after["request"][field] == original["request"][field], field
        before_metrics = metrics(original["request"], original["candidates"][0], original["evaluations"][0])
        after_file = f"after/{name}.json.gz"
        (args.output / after_file).write_bytes(gzip.compress(json.dumps(after, sort_keys=True, ensure_ascii=False).encode(), mtime=0))
        row = {"case": name, "conditions": options, "status": result["status"],
            "before": {"bundle_file": f"before/{name}.json.gz", "metrics": before_metrics,
                "geometry_digest": canonical_hash(original["candidates"][0]["placements"]),
                "sequence_digest": canonical_hash(contact_signature(original["candidates"][0]))},
            "after": {"bundle_file": after_file, "metrics": result["metrics"],
                "geometry_digest": result["geometry_digest"], "sequence_digest": result["sequence_digest"]},
            "refinement": result["refinement"], "search": result["search"],
            "elapsed_ms": round((time.perf_counter()-started)*1000, 2)}
        results.append(row)
        print(json.dumps({"case": name, "before_release": [before_metrics["static_release_pass"], before_metrics["static_release_total"]],
            "after_release": [result["metrics"]["static_release_pass"], result["metrics"]["static_release_total"]],
            "selected": result["refinement"]["selected_proposal"], "elapsed_ms": row["elapsed_ms"]}, ensure_ascii=False), flush=True)
    comparisons = {}
    for wall in ("roof", "overhang"):
        selected = [row for row in results if row["conditions"]["wall_profile"] == wall]
        if not selected:
            continue
        comparisons[wall] = {"samples": len(selected),
            "distinct_geometries": len({row["after"]["geometry_digest"] for row in selected}),
            "distinct_sequences": len({row["after"]["sequence_digest"] for row in selected}),
            "all_geometry_pass": all(row["after"]["metrics"]["p0_status"] == "pass" for row in selected),
            "all_complete": all(row["after"]["metrics"]["complete"] for row in selected)}
    report = {"generator_version": VERSION, "cases": results, "comparison": comparisons,
        "limitations": ["Same fixed seeds as the actual homepage examples; six cases only, not a population benchmark.",
            "All masses, friction, capacities, meshes, body and check thresholds are unchanged.",
            "Static support is assessed on discrete synthetic poses. Failed states and budget-limited searches remain visible.",
            "Seed fixes geometry proposals; bounded search may check fewer candidates under machine contention."]}
    (args.output / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
