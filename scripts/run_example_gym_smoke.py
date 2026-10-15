#!/usr/bin/env python3
"""Reproduce real regional generation with the whole synthetic gym retained."""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from boulderlab.draft_generation import generate_option, SECONDS
from boulderlab.engine import validate_bundle
from boulderlab.example_gym import GYM_ID, GYM_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/example-gym"))
    parser.add_argument("--seconds", type=float, default=SECONDS)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for region, wall, seed, style in (("overhang-bay", "overhang", 661506075, "balance"),
                                    ("roof-exit", "roof", 690569798, "sustained")):
        for variant in range(3):
            payload = dict(gym_id=GYM_ID, region_id=region, wall_profile=wall, style=style,
                           difficulty="medium", seed=seed, variant=variant)
            result = generate_option(payload, seconds=args.seconds)
            validate_bundle(result["bundle"])
            target = args.output / f"{region}-{variant}.json.gz"
            with gzip.open(target, "wt", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
            record = {k: result[k] for k in ("id", "label", "status", "metrics", "elapsed_ms",
                                             "geometry_digest", "sequence_digest")}
            record.update(options=payload, result_file=target.name)
            records.append(record)
            summary = {"gym_id": GYM_ID, "gym_version": GYM_VERSION,
                "per_option_search_seconds": args.seconds,
                "scope": "6 structural panels; 18 editable holds; 14 frozen neighbouring holds; independent search and current approximate checks",
                "limitations": ["Synthetic gym and stock, not a surveyed venue.",
                    "Geometry pass does not certify physical climbing feasibility.",
                    "A timeout does not prove no route exists; wall-clock-bounded search may vary with host load."],
                "cases": records}
            (args.output / "generation-smoke.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n")
            print(region, variant, result["status"],
                  f"release {result['metrics']['static_release_pass']}/{result['metrics']['static_release_total']}",
                  result["elapsed_ms"], flush=True)


if __name__ == "__main__":
    main()
