#!/usr/bin/env python3
"""Independently check seeded-fresh diagnosis proposals against paired random.

Writes a separate offline result set, preserving the original web experiment.
Run scripts/diagnose_betazero.py first with the default backend parameters and
all 30 bettar18-25 seeded_fresh cases. No ML dependency is needed here.
"""
import argparse
import copy
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from boulderlab.engine import canonical_hash, code_hash, validate_bundle
from boulderlab.learned_experiment import all_contacts, read_json, search_mask, write_json
from boulderlab.learned_generator import (
    MODEL_FILES, UPSTREAM_COMMIT, UPSTREAM_REPOSITORY, build_hold_features,
    canonical_sha256, load_scaler, request_digest,
)
from scripts.run_learned_experiment import run


def foot_ablation(request, original_dir, output):
    """Diagnostic repair only: all *originally legal* feet, unchanged hands.

    This is a separate experiment, never reported as the model's raw proposal.
    Both model and paired random receive the identical foot pool.
    """
    original = read_json(original_dir / "experiment.json")
    all_ids = all_contacts(request)
    results, seen, rows = {}, {}, []
    source_base = original["runs"][0]
    base_bundle = validate_bundle(read_json(original_dir / "bundles" / source_base["bundle_file"]))
    results[canonical_hash(source_base["selected_contacts"])] = (base_bundle, {k:source_base[k] for k in ("status","metrics","search")})
    frozen = code_hash()
    for row in original["runs"]:
        if code_hash() != frozen:
            raise RuntimeError("Engine changed during foot diagnostic")
        mask = copy.deepcopy(row["selected_contacts"])
        mask.update({limb:all_ids[limb] for limb in ("LF","RF")})
        signature = canonical_hash(mask)
        if signature not in results:
            results[signature] = search_mask(request, mask, 60)
        bundle, result = results[signature]
        filename = bundle["manifest"]["bundle_digest"].removeprefix("sha256:") + ".json.gz"
        write_json(output / "bundles" / filename, bundle)
        rows.append({"id":row["id"],"source":row["source"],"grade":row["grade"],"seed":row["seed"],"selected_contacts":mask,"duplicate_of":seen.get(signature),"bundle_file":filename,"bundle_digest":bundle["manifest"]["bundle_digest"],**result})
        seen.setdefault(signature,row["id"])
        print(f"feet-diagnostic {len(rows)}/61 {row['id']}: {result['status']}",flush=True)
    summary = {}
    for source in ("betazero","random","baseline"):
        group = [r for r in rows if r["source"] == source]
        summary[source] = {"total":len(group),"complete":sum(r["status"] == "complete" for r in group),"p0_pass":sum(r["metrics"]["p0_status"] == "pass" for r in group)}
    data = {"schema_version":"betazero-foot-ablation/1","engine_code_hash":frozen,"source_experiment_digest":original["index_digest"],"policy":"Keep selected hand permissions; give BOTH groups every originally legal foot contact. Hand holds remain hand-only. This is an external repair, not learned foot generation.","summary":summary,"runs":rows}
    data["digest"] = canonical_hash(data)
    write_json(output / "experiment.json",data)
    print(summary,flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnosis", type=Path, default=ROOT / "outputs/betazero-diagnosis/comparison.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/betazero-diagnosis/bettar-recheck")
    parser.add_argument("--all-feet-ablation", action="store_true", help="Separate, explicitly repaired foot-pool comparison")
    args = parser.parse_args()
    data = read_json(args.diagnosis)
    protocol = data["protocol"]
    if (data["upstream_commit"] != UPSTREAM_COMMIT
            or data["weight_sha256"] != MODEL_FILES["ddpm-weights.pth"]["sha256"]
            or any(protocol[k] != v for k, v in {"steps":100,"guidance":3,"projection_start":.8,"x_offset":0}.items())):
        raise ValueError("Unexpected diagnosis provenance or sampling parameters")
    request_path = ROOT / "fixtures/learned-wall-request.json"
    request = read_json(request_path)
    adapted = build_hold_features(request, request["reference_layout"])
    if data["inputs"]["bettar18-25"]["feature_digest"] != canonical_sha256(adapted):
        raise ValueError("Diagnosis used another physical input")
    rows = [r for r in data["runs"] if r["case"] == "bettar18-25" and r["noise_mode"] == "seeded_fresh"]
    expected = {(grade, seed) for grade in (16,18,20) for seed in range(10)}
    if len(rows) != 30 or {(r["grade"],r["seed"]) for r in rows} != expected:
        raise ValueError("Expected exactly 30 paired proposals")
    scaler = load_scaler()
    proposals = []
    for row in rows:
        proposal = {k:copy.deepcopy(row[k]) for k in ("seed","grade","raw_selections","raw_slots","raw_tensor","diagnostics")}
        proposal.update(schema_version="learned-proposal/1",request_digest=request_digest(request),grade_condition=row["grade"],input_features=adapted)
        proposal["diagnostics"]["upstream_role_repairs"] = row["role_repairs"]
        proposal["provenance"] = {
            "generator":"BetaZero", "upstream_repository":UPSTREAM_REPOSITORY,
            "upstream_commit":UPSTREAM_COMMIT, "adapter_version":"betazero-diagnosis/seeded-fresh-1",
            "weight_sha256":data["weight_sha256"],
            "scaler_source_sha256":MODEL_FILES["scaler-weights.joblib"]["sha256"],
            "scaler_parameters_sha256":canonical_sha256(scaler),
            "physical_input_sha256":canonical_sha256({"scene":request["scene"],"placements":request["reference_layout"]}),
            "diagnosis_digest":canonical_sha256(data),
            "inference":{"timesteps":100,"slots":20,"guidance":3,"projection_start":.8,"x_offset":0,"noise_mode":"seeded_fresh","seeded_rng":True,"upstream_deterministic":False},
        }
        proposals.append(proposal)
    proposal_path = ROOT / ".runtime/betazero-diagnosis/seeded-fresh-proposals.json"
    write_json(proposal_path,{"proposals":proposals})
    run(SimpleNamespace(request=request_path,proposals=proposal_path,output=args.output))
    if args.all_feet_ablation:
        foot_ablation(request,args.output,args.output.parent / "feet-ablation")


if __name__ == "__main__":
    main()
