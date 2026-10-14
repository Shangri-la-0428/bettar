"""Reproduce fixed-wall beta audits; keep complete unknown and passing evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from boulderlab.beta_audit import audit_beta
from boulderlab.engine import body_profiles, code_hash

OUT = ROOT / "outputs/beta-audit-study"
OUT.mkdir(parents=True, exist_ok=True)
rows = []
for program in ("mixed_flow", "power_finish", "sustained_finish"):
    bundle = json.loads((ROOT / f"fixtures/route-{program}-bundle.json").read_text())
    request, candidate = bundle["request"], bundle["candidates"][0]
    report = audit_beta(request, candidate)
    (OUT / f"{program}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    row = {"program": program, "original": report["original"]["summary"],
           "alternatives": [{"objective": a["objective"], "summary": a["summary"],
                             "skipped_hold_ids": a["skipped_hold_ids"], "crux_bypass": a["crux_bypass"],
                             "evaluation": a["evaluation"]["summary"]} for a in report["alternatives"]],
           "search": report["search"], "status": report["status"]}
    rows.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)

# Same installed wall, alternative morphology and orientation; not a new layout.
base = json.loads((ROOT / "fixtures/route-mixed_flow-bundle.json").read_text())
for change in ("body_b", "start_hand_rotated_90"):
    request, candidate = deepcopy((base["request"], base["candidates"][0]))
    if change == "body_b":
        request["body"] = next(b for b in body_profiles() if b["id"] == "B")
    else:
        pid = request["start_contacts"]["LH"]["placement_id"]
        next(p for p in candidate["placements"] if p["id"] == pid)["rotation_deg"] += 90
        candidate["revision"] += 1
    report = audit_beta(request, candidate)
    (OUT / f"sensitivity-{change}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    row = {"change": change, "original": report["original"]["summary"],
           "alternatives": [{"objective": a["objective"], "summary": a["summary"],
                             "skipped_hold_ids": a["skipped_hold_ids"], "evaluation": a["evaluation"]["summary"]} for a in report["alternatives"]],
           "search": report["search"], "status": report["status"]}
    rows.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)

(OUT / "comparison.json").write_text(json.dumps({"code_hash": code_hash(), "cases": rows}, ensure_ascii=False, indent=2, allow_nan=False))
