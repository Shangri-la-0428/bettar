"""Replay a recorded Codex design suggestion against the rules baseline.

No model API calls. Both arms use the same frozen engine and evaluation budget.
The B suggestion is authored once in this Codex session and recorded here.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from boulderlab.engine import default_request, propose, evaluate, make_bundle, code_hash
from scipy.optimize import linear_sum_assignment
import numpy as np

STRATEGY = {
    "id": "codex-foot-preparation-v1",
    "source": "One explicit design suggestion authored in the current Codex conversation; replayed as deterministic edits, no model API.",
    "reason": "Try preparing both feet before the hand sequence. In free mode, lower destination hand holds by 0.06 m and raise destination footholds by 0.03 m, aiming to reduce endpoint reach demands. This is a geometric hypothesis, not a claim about force, stability or climbing quality.",
    "fixed_mode": "Only reorder foot events before hand events; preserve every installation position and orientation.",
    "calls": 1,
    "token_usage": None,
    "model_identifier": None,
    "unknown_cost_reason": "The local session exposes no per-suggestion token/cost record; software editing and design time are not inferred as model latency.",
}


def codex_proposal(request, original):
    candidate = deepcopy(original)
    candidate["id"] += "-codex"
    candidate["generator"] = "codex"
    candidate["name"] += " · Codex 建议"
    candidate["design_notes"] = [STRATEGY["reason"], "Current-session design suggestion, replayed; no API call."]
    states = {s["id"]: s for s in original["states"]}
    moves = [(e["limb"], deepcopy(states[e["to_state"]]["contacts"][e["limb"]])) for e in original["events"]]
    moves = [m for m in moves if m[0].endswith("F")] + [m for m in moves if m[0].endswith("H")]
    contacts = deepcopy(original["states"][0]["contacts"])
    candidate["states"] = [{"id": "s0", "label": "起始接触", "contacts": deepcopy(contacts)}]
    candidate["events"] = []
    for i, (limb, target) in enumerate(moves):
        before = candidate["states"][-1]["id"]
        release, arrival = f"s{2*i+1}", f"s{2*i+2}"
        contacts[limb] = None
        candidate["states"].append({"id": release, "label": f"{limb} 释放", "contacts": deepcopy(contacts)})
        contacts[limb] = target
        candidate["states"].append({"id": arrival, "label": f"{limb} 换点", "contacts": deepcopy(contacts)})
        candidate["events"].append({"limb": limb, "from_state": before, "release_state": release, "to_state": arrival})
    if request["mode"] == "free":
        hands = {target["placement_id"] for limb, target in moves if limb.endswith("H")}
        feet = {target["placement_id"] for limb, target in moves if limb.endswith("F")}
        for placement in candidate["placements"]:
            if placement["id"] in hands:
                placement["v"] = round(placement["v"] - .06, 5)
            if placement["id"] in feet:
                placement["v"] = round(placement["v"] + .03, 5)
    return candidate


def equivalent(request, a, b):
    """Compare equivalent physical holds, excluding IDs and solver initial states."""
    inventory = {h["id"]: h for h in request["scene"]["inventory"]}
    groups = {}
    for arm, candidate in enumerate([a, b]):
        for p in candidate["placements"]:
            h = inventory[p["inventory_id"]]
            key = (h["type"], h["width"], h["height"], h["depth"])
            groups.setdefault(key, [[], []])[arm].append(p)
    mapping = {}
    for key, (left, right) in groups.items():
        if len(left) != len(right):
            return False
        distances = np.array([[np.hypot(x["u"]-y["u"], x["v"]-y["v"]) for y in right] for x in left])
        rows, cols = linear_sum_assignment(distances)
        for i, j in zip(rows, cols):
            if distances[i,j] >= .05:
                return False
            period = 360 if key[0] == "directional_edge" else 180
            delta = abs((left[i]["rotation_deg"]-right[j]["rotation_deg"] + period/2) % period - period/2)
            if delta >= 15:
                return False
            mapping[left[i]["id"]] = right[j]["id"]
    def sequence(candidate, remap):
        states = {s["id"]: s for s in candidate["states"]}
        return [(e["limb"], remap.get(states[e["to_state"]]["contacts"][e["limb"]]["placement_id"], states[e["to_state"]]["contacts"][e["limb"]]["placement_id"])) for e in candidate["events"]]
    return sequence(a, mapping) == sequence(b, {})


def run_pair(task):
    case, seed, budget, directory, expected_hash = task
    if code_hash() != expected_hash:
        raise RuntimeError("Engine changed after experiment freeze")
    request = default_request(**{k:v for k,v in case.items() if k != "id"}, seed=seed, budget=budget)
    original = [propose(request, i) for i in range(budget)]
    results = []
    # Fixed A-then-B order: timings are descriptive, not evidence of speed superiority.
    for arm in ["A", "B"]:
        started = time.perf_counter()
        candidates = original if arm == "A" else [codex_proposal(request, c) for c in original]
        evaluations = [evaluate(request, c) for c in candidates]
        bundle = make_bundle(request, candidates, evaluations)
        path = Path(directory) / f"{case['id']}-seed{seed}-{arm}.json"
        path.write_text(json.dumps(bundle, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        statuses = {s:sum(e["summary"]["status"] == s for e in evaluations) for s in ("pass", "fail", "unknown")}
        distinct = []
        distinct_pass = []
        passed_ids = {e["candidate_id"] for e in evaluations if e["summary"]["status"] == "pass"}
        for c in candidates:
            if not any(equivalent(request,c,d) for d in distinct): distinct.append(c)
            if c["id"] in passed_ids and not any(equivalent(request,c,d) for d in distinct_pass): distinct_pass.append(c)
        first = next((i+1 for i,e in enumerate(evaluations) if e["summary"]["status"] == "pass"), None)
        results.append({"case":case["id"],"scenario":case["scenario"],"mode":case["mode"],"body":case["body_id"],"seed":seed,"arm":arm,"attempts":len(candidates),"distinct":len(distinct),"distinct_pass":len(distinct_pass),"statuses":statuses,"first_pass_evaluation":first,"first_pass_evaluation_ms":sum(e["elapsed_ms"] for e in evaluations[:first]) if first else None,"evaluation_ms":sum(e["elapsed_ms"] for e in evaluations),"total_ms":round((time.perf_counter()-started)*1000,2),"evidence_path":str(path.relative_to(ROOT))})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["development","holdout"], default="development")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    config = json.loads((ROOT/"fixtures/experiment-cases.json").read_text())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    directory = ROOT/".runtime/experiments"/f"{args.set}-{stamp}"
    directory.mkdir(parents=True)
    frozen = code_hash()
    script = Path(__file__).read_bytes()
    (directory/"experiment-source.py").write_bytes(script)
    record = {"set":args.set,"created_at":stamp,"code_hash":frozen,"strategy":STRATEGY,"config":config,"workers":args.workers,"arm_order":"A then B; timings descriptive only","results":[]}
    record["script_record"] = {"sha256": hashlib.sha256(script).hexdigest(), "path": str((directory/"experiment-source.py").relative_to(ROOT)), "capture_method": "Captured before execution"}
    (directory/"freeze.json").write_text(json.dumps(record,ensure_ascii=False,indent=2))
    tasks = [(c,s,config["candidate_budget"],str(directory),frozen) for c in config[args.set] for s in config["seeds"]]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run_pair,t) for t in tasks]):
            rows=future.result(); record["results"].extend(rows)
            print(json.dumps([{k:r[k] for k in ("case","seed","arm","statuses","distinct")} for r in rows]), flush=True)
    if code_hash() != frozen: raise RuntimeError("Engine changed during experiment; results cannot be treated as same-version comparison")
    record["results"].sort(key=lambda r:(r["case"],r["seed"],r["arm"]))
    record["totals"]={arm:{"attempts":sum(r["attempts"] for r in record["results"] if r["arm"]==arm),"pass":sum(r["statuses"]["pass"] for r in record["results"] if r["arm"]==arm),"fail":sum(r["statuses"]["fail"] for r in record["results"] if r["arm"]==arm),"unknown":sum(r["statuses"]["unknown"] for r in record["results"] if r["arm"]==arm)} for arm in ("A","B")}
    (directory/"summary.json").write_text(json.dumps(record,ensure_ascii=False,indent=2))
    out=ROOT/"outputs/mvp-implementation"; out.mkdir(exist_ok=True)
    (out/f"{args.set}-experiment.json").write_text(json.dumps(record,ensure_ascii=False,indent=2))
    print(json.dumps({"complete":args.set,"totals":record["totals"],"directory":str(directory)},ensure_ascii=False),flush=True)


if __name__ == "__main__": main()
