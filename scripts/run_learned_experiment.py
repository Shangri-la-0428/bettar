"""Run and save the 30-proposal fixed-wall study without an ML dependency.

Generate proposals with the optional ML interpreter first (see README). This
runner consumes their JSON, preserves every seed, and uses the normal engine.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from boulderlab.engine import canonical_hash, code_hash, validate_request
from boulderlab.learned_experiment import (
    CONDITIONS, FORMAT, PROTOCOL, adapt_proposal, aggregate, all_contacts, anchor_roles,
    comparison_request_digest, random_mask, read_json, result_rank, search_mask, validate_saved_run, wall_metadata, write_json,
)


def run(args):
    request = validate_request(read_json(args.request))
    proposal_data = read_json(args.proposals)
    proposals = proposal_data["proposals"] if isinstance(proposal_data, dict) else proposal_data
    lookup = {(p["grade"], p["seed"]): p for p in proposals}
    expected = {(grade, seed) for _, grade in CONDITIONS for seed in PROTOCOL["seeds"]}
    if set(lookup) != expected or len(proposals) != len(expected):
        raise ValueError("proposal file must contain exactly V3/16, V4/18, V5/20 × seeds 0–9")
    request_digest = canonical_hash(request)
    for p in proposals:
        if p.get("request_digest") != request_digest:
            raise ValueError("proposal was generated from another wall request")
    frozen = code_hash()
    out = args.output
    source = copy.deepcopy(proposals[0].get("provenance", {}))
    experiment = {"schema_version": FORMAT, "id": "betazero-fixed-wall-v1", "title": "学习生成对照",
        "created_at": datetime.now(timezone.utc).isoformat(), "engine_code_hash": frozen,
        "source": source, "request_digest": request_digest,
        "comparison_request_digest": comparison_request_digest(request), "wall": wall_metadata(request),
        "protocol": PROTOCOL, "conditions": [], "runs": [], "summary": {}}
    checkpoint_dir = ROOT / ".runtime" / "learned-study" / "checks" / canonical_hash({"engine": frozen, "request": request, "protocol": PROTOCOL})[-24:]
    seen, mask_results = {}, {}

    def record_case(run_id, source_name, mask, adjustments, *, condition=None, grade=None, seed=None, pair_id=None, raw=None):
        if code_hash() != frozen:
            raise RuntimeError("Engine changed during experiment; rerun after code is frozen")
        signature = canonical_hash(mask)
        checkpoint = checkpoint_dir / (signature[-24:] + ".json.gz")
        reused = signature in mask_results or checkpoint.is_file()
        if signature in mask_results:
            bundle, result = mask_results[signature]
        elif checkpoint.is_file():
            saved = read_json(checkpoint)
            from boulderlab.engine import validate_bundle
            bundle, result = validate_bundle(saved["bundle"]), saved["result"]
            mask_results[signature] = (bundle, result)
        else:
            bundle, result = search_mask(request, mask, PROTOCOL["search_seconds"])
            write_json(checkpoint, {"bundle": bundle, "result": result})
            mask_results[signature] = (bundle, result)
        # A mask alone does not identify the wall/body/check result. Immutable
        # content names keep a failed replacement run from overwriting bundles
        # still referenced by the previously published index.
        filename = bundle["manifest"]["bundle_digest"].removeprefix("sha256:") + ".json.gz"
        write_json(out / "bundles" / filename, bundle)
        row = {"id": run_id, "source": source_name, "condition": condition, "grade": grade, "seed": seed,
            "pair_id": pair_id, "selected_contacts": mask, "adjustments": adjustments,
            "duplicate_of": seen.get((source_name, signature)), "shared_check": reused,
            "bundle_url": f"/api/learned-experiment/runs/{run_id}", "bundle_file": filename,
            "bundle_digest": bundle["manifest"]["bundle_digest"], **copy.deepcopy(result)}
        if raw is not None:
            row["proposal"] = raw
            anchors = set().union(*anchor_roles(request).values())
            selected = set().union(*(set(ids) for ids in mask.values()))
            row["no_intermediate_holds"] = not bool(selected - anchors)
            if not raw["raw_selections"]:
                row["error"] = "模型原始选点为空；画面中的共同起终点由 bettar 补入，不是模型生成的完整线路。"
            elif row["no_intermediate_holds"]:
                row["error"] = "模型未提供可用的中间点；仅保留共同起终点，未找到完整走法。"
        seen.setdefault((source_name, signature), run_id)
        experiment["runs"].append(row)
        write_json(out / "progress.json", {"engine_code_hash": frozen, "completed": len(experiment["runs"]), "runs": experiment["runs"]})
        print(f"{len(experiment['runs']):02d}/61 {run_id}: {row['status']} P0={row['metrics']['p0_status']} selected={row['metrics']['selected_holds']} shared={reused}", flush=True)

    record_case("baseline-all", "baseline", all_contacts(request), {"all_installed_contacts": True})
    for condition, grade in CONDITIONS:
        for seed in PROTOCOL["seeds"]:
            proposal = lookup[(grade, seed)]
            model_id, random_id = f"betazero-{condition.lower()}-{seed}", f"random-{condition.lower()}-{seed}"
            try:
                if proposal.get("error"):
                    raise ValueError(proposal["error"])
                mask, adjusted = adapt_proposal(request, proposal)
                control, random_adjusted = random_mask(request, adjusted["roles"], grade * 10000 + seed)
            except (ValueError, KeyError, TypeError) as exc:
                for rid, src in ((model_id, "betazero"), (random_id, "random")):
                    experiment["runs"].append({"id": rid, "source": src, "condition": condition, "grade": grade,
                        "seed": seed, "pair_id": random_id if src == "betazero" else model_id,
                        "status": "generation_failed", "error": str(exc), "metrics": {}, "search": {},
                        "selected_contacts": None, "adjustments": {}, "duplicate_of": None, "bundle_url": None,
                        "proposal": proposal if src == "betazero" else None})
                continue
            record_case(model_id, "betazero", mask, adjusted, condition=condition, grade=grade, seed=seed, pair_id=random_id, raw=proposal)
            record_case(random_id, "random", control, random_adjusted, condition=condition, grade=grade, seed=seed, pair_id=model_id)
        group = [r for r in experiment["runs"] if r["source"] == "betazero" and r["condition"] == condition]
        representative = min(group, key=result_rank)
        experiment["conditions"].append({"label": condition, "grade": grade, "representative_run_id": representative["id"]})
    if code_hash() != frozen:
        raise RuntimeError("Engine changed during experiment; results were not published")
    experiment["summary"] = aggregate(experiment["runs"])
    experiment["index_digest"] = canonical_hash(experiment)
    for row in experiment["runs"]:
        if row["bundle_url"]:
            validate_saved_run(out, experiment, row["id"])
    write_json(out / "experiment.json", experiment)
    (out / "progress.json").unlink(missing_ok=True)
    print(experiment["summary"], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, default=ROOT / "fixtures" / "learned-wall-request.json")
    parser.add_argument("--proposals", type=Path, default=ROOT / ".runtime" / "learned-model" / "proposals.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "learned-study")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
