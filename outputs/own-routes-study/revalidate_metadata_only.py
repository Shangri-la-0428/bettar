"""Recheck the saved study after exactly two roof presentation-text edits.

This script never reruns contact search and never edits an evaluation's stored
fingerprint. It verifies the old engine by reversing the two text substitutions
in memory, validates the original evidence under that reconstructed provenance,
then runs evaluate/make_bundle normally with the current engine. Publication is
conditional on identical geometry, poses, metrics and search records.

Run from any directory with the repository's Python environment. A second run
requires the archived original study as --input; the default current index will
correctly refuse to pretend it was generated under the old engine.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from boulderlab import engine, own_routes
from boulderlab.learned_experiment import read_json, write_json

OLD = "sha256:9309643b263d25d79315fb4b619804d406c52fe9dd2ae39631257a9601b1ce68"
NEW = "sha256:b314a55a201d54bc48b04bfd5ba3ee571a1b200a025d26b7c0b1d7912289962d"
SUBSTITUTIONS = (
    ('candidate["name"] = "屋檐 · 转换调整方案（增加动作）"',
     'candidate["name"] = "屋檐 · 出口支撑备选方案"'),
    ('full-route support and added transfers remain visible, not a global improvement claim',
     'full-route support and actual transfer/effort changes remain visible, not a global improvement claim'),
)


def restore_generation_hash():
    setting = ROOT / "boulderlab/setting.py"
    current = setting.read_bytes()
    restored = current
    for before, after in SUBSTITUTIONS:
        assert restored.count(after.encode()) == 1, "Expected metadata text is absent or ambiguous"
        restored = restored.replace(after.encode(), before.encode())
    read_bytes = Path.read_bytes
    def generation_bytes(path):
        return restored if path.resolve() == setting.resolve() else read_bytes(path)
    assert engine.code_hash() == NEW, "Current engine is not the reviewed metadata-only revision"
    # No source file is modified; compute the normal hash against restored bytes.
    with patch.object(Path, "read_bytes", generation_bytes):
        reconstructed = engine.code_hash()
    assert reconstructed == OLD, "Changes extend beyond the two reviewed presentation strings"
    return {"reconstructed_generation_engine_code_hash": reconstructed,
            "current_engine_code_hash": NEW,
            "setting_before_sha256": hashlib.sha256(restored).hexdigest(),
            "setting_after_sha256": hashlib.sha256(current).hexdigest(),
            "substitutions": [{"before": a, "after": b} for a, b in SUBSTITUTIONS],
            "source_files_modified_by_this_script": False}


def without_elapsed(value):
    """Solver timing is execution metadata, not a solved pose coordinate."""
    if isinstance(value,dict):
        return {key:without_elapsed(item) for key,item in value.items() if key != "elapsed_ms"}
    if isinstance(value,list): return [without_elapsed(item) for item in value]
    return value


def main(source, destination):
    proof = restore_generation_hash()
    data = read_json(source / "study.json")
    assert data["engine_code_hash"] == OLD
    assert data["generator_code_hash"] == own_routes.generator_hash()
    assert data["index_digest"] == engine.canonical_hash({k:v for k,v in data.items() if k != "index_digest"})
    original = copy.deepcopy(data)
    staging = ROOT / ".runtime/own-routes-study/revalidation-stage"
    archive = ROOT / ".runtime/own-routes-study/pre-metadata-revalidation"
    staging.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    write_json(archive / "study.json", original)
    checks = []
    old_files, new_files = set(), set()
    for row in data["routes"]:
        search_before = engine.canonical_hash(row["search"])
        for name, record in [("final", row), *( (name,row["completion"][name]) for name in ("before","after_support_completion") )]:
            old_relative = record["bundle_file"]
            old_files.add(old_relative)
            old = read_json(source / old_relative)
            assert old["manifest"]["code_hash"] == OLD
            assert old["manifest"]["bundle_digest"] == record["bundle_digest"]
            # The byte-level proof above establishes identical evaluation code.
            # This context only authenticates the old artifact; new evaluations
            # below execute unpatched and generate fresh fingerprints normally.
            with patch.object(engine, "code_hash", lambda: OLD):
                engine.validate_bundle(old)
            request, candidates = old["request"], old["candidates"]
            evaluations = [engine.evaluate(request,candidate) for candidate in candidates]
            fresh = engine.make_bundle(request,candidates,evaluations)
            assert fresh["request"] == old["request"] and fresh["candidates"] == old["candidates"]
            before_metrics = own_routes.metrics(request,candidates[0],old["evaluations"][0])
            after_metrics = own_routes.metrics(request,candidates[0],evaluations[0])
            assert record["metrics"] == before_metrics == after_metrics, "Revalidation changed numerical results"
            assert without_elapsed(evaluations[0]["poses"]) == without_elapsed(old["evaluations"][0]["poses"]), "Revalidation changed solved poses"
            relative = "bundles/" + fresh["manifest"]["bundle_digest"].split(":")[-1] + ".json.gz"
            write_json(staging / relative, fresh)
            new_files.add(relative)
            checks.append({"route_id":row["id"],"stage":name,
                "previous_bundle_file":old_relative,"previous_bundle_digest":old["manifest"]["bundle_digest"],
                "current_bundle_file":relative,"current_bundle_digest":fresh["manifest"]["bundle_digest"],
                "previous_evaluation_fingerprint":old["evaluations"][0]["fingerprint"],
                "current_evaluation_fingerprint":evaluations[0]["fingerprint"],
                "geometry_and_contact_sequence_unchanged":True,"solved_poses_identical":True,
                "pose_comparison_excludes":["elapsed_ms timing fields"],
                "metrics_identical":True,"previous_metrics":before_metrics,"current_metrics":after_metrics})
            record.update(bundle_file=relative,bundle_digest=fresh["manifest"]["bundle_digest"],metrics=after_metrics)
            print(f"{row['id']} / {name}: geometry, poses and metrics identical",flush=True)
        assert engine.canonical_hash(row["search"]) == search_before
        row["generation_engine_code_hash"] = OLD
    evidence = {"schema_version":"metadata-only-revalidation-v1",
        "reason":"Two roof presentation strings were corrected; contact search, geometry and mechanics code are byte-identical to the generating revision after reversing these strings.",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "generation_engine_code_hash":OLD,"evaluation_engine_code_hash":NEW,
        "previous_index_digest":original["index_digest"],"source_proof":proof,
        "contact_search_rerun":False,"original_search_records_preserved":True,
        "new_fingerprints_produced_by":"engine.evaluate and engine.make_bundle, without mutation",
        "checks":checks}
    data.update(engine_code_hash=NEW,generation_engine_code_hash=OLD,
        revalidation={"reason":"metadata_only_roof_labels","generation_engine_code_hash":OLD,
            "evaluation_engine_code_hash":NEW,"search_rerun":False,"all_numerical_metrics_identical":True,
            "evidence_file":"revalidation.json","evidence_digest":engine.canonical_hash(evidence)})
    data["index_digest"] = engine.canonical_hash({k:v for k,v in data.items() if k != "index_digest"})
    write_json(staging / "study.json",data)
    own_routes.load_study(staging)
    assert engine.code_hash()==NEW and own_routes.generator_hash()==data["generator_code_hash"]
    for relative in new_files:
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(staging/relative,target)
    write_json(destination/"revalidation.json",evidence)
    write_json(destination/"study.json",data)  # index publication is atomic and last
    own_routes.load_study(destination)
    for relative in old_files-new_files:
        old_path=destination/relative
        if old_path.exists():
            target=archive/relative;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.move(old_path,target)
    print(f"Published {len(checks)} independently re-evaluated bundles; archived original index and obsolete bundles in {archive}",flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,default=ROOT/"outputs/own-routes-study")
    parser.add_argument("--output",type=Path,default=ROOT/"outputs/own-routes-study")
    args=parser.parse_args()
    main(args.input.resolve(),args.output.resolve())
