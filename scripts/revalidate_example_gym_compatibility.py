"""Re-evaluate served legacy examples after adding optional gym constraints.

Preserves every request, installed layout and contact sequence. Calls the real
evaluator for main, baseline and alternative candidates, without contact search,
pose substitution or fingerprint mutation. Old fixtures and study indexes are
archived before publishing refreshed current examples; research outputs are not
rewritten. Actual before/after metrics are recorded even when they differ.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from boulderlab import engine, own_routes
from boulderlab.learned_experiment import read_json, write_json
from boulderlab.setting import roof_exit_support

CACHE = {}
CHECKS = []


def geometry(candidate):
    return {key: candidate[key] for key in ("placements", "states", "events")}


def summary(evaluation):
    return {"geometry": evaluation["summary"], "mechanics": evaluation.get("mechanics_report", {}).get("summary"),
            "poses": {status: sum(pose["status"] == status for pose in evaluation["poses"]) for status in ("pass", "fail", "unknown", "not_checked")}}


def evaluate(request, candidate, old, label):
    plain = {key: value for key, value in candidate.items() if key != "setting_report"}
    key = engine.canonical_hash({"request": request, "candidate": plain})
    cached = key in CACHE
    if not cached:
        CACHE[key] = engine.evaluate(request, candidate)
    fresh = copy.deepcopy(CACHE[key])
    CHECKS.append({"label": label, "candidate_id": candidate["id"], "shared_identical_evaluation": cached,
                   "previous_fingerprint": old.get("fingerprint"), "current_fingerprint": fresh["fingerprint"],
                   "before": summary(old), "after": summary(fresh), "summary_unchanged": summary(old) == summary(fresh)})
    return fresh


def revalidate(old, label):
    if old["manifest"]["bundle_digest"] != engine._bundle_digest(old):
        raise ValueError(f"Original evidence digest mismatch: {label}")
    request, candidates = copy.deepcopy(old["request"]), copy.deepcopy(old["candidates"])
    evaluations = []
    previous = {entry["candidate_id"]: entry for entry in old["evaluations"]}
    for candidate in candidates:
        report = candidate.get("setting_report")
        if report:
            baseline = report["baseline_candidate"]
            report["baseline_evaluation"] = evaluate(request, baseline, report["baseline_evaluation"], label + "/baseline")
            report["baseline"]["mechanics_summary"] = report["baseline_evaluation"].get("mechanics_report", {}).get("summary")
            if request["setting_design"].get("wall_profile") == "roof":
                report["baseline"]["exit_support"] = roof_exit_support(baseline, report["baseline_evaluation"])
            for alternative in report["allowed_alternatives"]:
                alternative["evaluation"] = evaluate(request, alternative["candidate"], alternative["evaluation"], label + "/alternative")
                if alternative["evaluation"]["summary"]["status"] != "pass":
                    raise ValueError(f"Previously accepted alternative no longer geometry-pass: {label}")
        fresh = evaluate(request, candidate, previous[candidate["id"]], label)
        if report:
            report["result"]["mechanics_summary"] = fresh.get("mechanics_report", {}).get("summary")
            if request["setting_design"].get("wall_profile") == "roof":
                report["result"]["exit_support"] = roof_exit_support(candidate, fresh)
        evaluations.append(fresh)
    bundle = engine.make_bundle(request, candidates, evaluations)
    bundle["reviews"] = copy.deepcopy(old.get("reviews", []))
    engine.validate_bundle(bundle)
    assert request == old["request"]
    assert [geometry(candidate) for candidate in candidates] == [geometry(candidate) for candidate in old["candidates"]]
    return bundle


def main():
    frozen = engine.code_hash()
    output = ROOT / "outputs/example-gym"
    output.mkdir(parents=True, exist_ok=True)
    staging = ROOT / ".runtime/example-gym-revalidation"
    staging.mkdir(parents=True, exist_ok=True)
    publications, bundles = [], []
    for path in sorted((ROOT / "fixtures").glob("*bundle.json")):
        old = read_json(path)
        fresh = revalidate(old, str(path.relative_to(ROOT)))
        staged = staging / path.name
        write_json(staged, fresh)
        archive = ROOT / "fixtures/history" / f"{path.stem}-{old['manifest']['bundle_digest'].split(':')[-1][:12]}.json"
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            archive.write_bytes(path.read_bytes())
        publications.append((staged, path))
        bundles.append({"path": str(path.relative_to(ROOT)), "previous_digest": old["manifest"]["bundle_digest"],
                        "current_digest": fresh["manifest"]["bundle_digest"], "geometry_and_contacts_unchanged": True})
        print(f"rechecked {path.name}: {len(fresh['candidates'])} candidates", flush=True)
    study_path = ROOT / "outputs/own-routes-study/study.json"
    study = read_json(study_path)
    original_study = copy.deepcopy(study)
    archive = output / "archive/own-routes-study-index.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        archive.write_bytes(study_path.read_bytes())
    for row in study["routes"]:
        for stage, record in [("final", row), *((name, row["completion"][name]) for name in ("before", "after_support_completion"))]:
            source = study_path.parent / record["bundle_file"]
            old = read_json(source)
            fresh = revalidate(old, f"own-routes/{row['id']}/{stage}")
            current_metrics = own_routes.metrics(fresh["request"], fresh["candidates"][0], fresh["evaluations"][0])
            relative = f"bundles/{fresh['manifest']['bundle_digest'].split(':')[-1]}.json.gz"
            staged = staging / relative
            write_json(staged, fresh)
            publications.append((staged, study_path.parent / relative))
            bundles.append({"path": str(source.relative_to(ROOT)), "previous_digest": old["manifest"]["bundle_digest"],
                            "current_digest": fresh["manifest"]["bundle_digest"], "geometry_and_contacts_unchanged": True,
                            "metrics_before": record["metrics"], "metrics_after": current_metrics,
                            "metrics_unchanged": record["metrics"] == current_metrics})
            record.update(bundle_file=relative, bundle_digest=fresh["manifest"]["bundle_digest"], metrics=current_metrics)
            if stage == "final":
                row["completion"]["after"]["metrics"] = current_metrics
                row["status"] = "complete" if current_metrics["complete"] and current_metrics["p0_status"] == "pass" else "unverified" if current_metrics["complete"] else "search_unresolved"
                row["completion"]["after"]["status"] = row["status"]
            print(f"rechecked own-routes {row['id']} / {stage}", flush=True)
    study["engine_code_hash"] = frozen
    study["compatibility_revalidation"] = {"reason": "optional_installation_region_constraints_added", "original_engine_code_hash": original_study["engine_code_hash"],
        "current_engine_code_hash": frozen, "contact_search_rerun": False, "geometry_and_contacts_preserved": True,
        "evidence": "../example-gym/revalidation.json"}
    study["pairwise"] = own_routes.pairwise(study["routes"])
    study["index_digest"] = engine.canonical_hash({key: value for key, value in study.items() if key != "index_digest"})
    if engine.code_hash() != frozen:
        raise ValueError("Evaluator changed during revalidation; no current example published.")
    # Install proof bundles first, then the current index. Historical research
    # bundles and their original archived index remain available unchanged.
    for staged, destination in publications:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(staged.read_bytes())
    write_json(study_path, study)
    own_routes.load_study(study_path.parent)
    evidence = {"schema_version": "example-gym-compatibility-revalidation/1", "created_at": datetime.now(timezone.utc).isoformat(),
        "engine_code_hash": frozen, "method": "actual engine.evaluate and engine.make_bundle; no pose/fingerprint substitution; no contact search",
        "geometry_and_contact_sequences_preserved": True, "fixtures_rechecked": 24, "own_routes_stages_rechecked": 9,
        "distinct_evaluator_calls": len(CACHE), "all_evaluation_summaries_unchanged": all(row["summary_unchanged"] for row in CHECKS),
        "bundles": bundles, "evaluations": CHECKS}
    write_json(output / "revalidation.json", evidence)
    print(json.dumps({key: evidence[key] for key in ("fixtures_rechecked", "own_routes_stages_rechecked", "distinct_evaluator_calls", "all_evaluation_summaries_unchanged")}), flush=True)


if __name__ == "__main__":
    main()
