"""Small, reproducible rules-only setting study with independent four-limb search.

Spatial briefs propose a hand corridor. Feet are available on declared hand-hold
standing surfaces first; missing lower support is filled from installed stock.
No move list, mandatory hold coverage or learned weights enter the search.
"""
from __future__ import annotations
import copy
import hashlib
import itertools
import time
from pathlib import Path

from .engine import canonical_hash, code_hash, default_request, evaluate, make_bundle, validate_bundle
from .route_constraints import allowed_contact_ids
from .route_design import _contact_key
from .beta_audit import _audit_context, analyze_beta
from .setting import _sequence_search, _shell, _mechanical_proposal, _mechanical_rank
from .learned_experiment import read_json, write_json

FORMAT = "own-routes-study-v1"
BRIEFS = (
    {"id": "lateral-balance", "label": "斜向移重", "style": "balance", "program": "diagonal_balance",
     "intent": "手点横向渐移；独立搜索脚位和移重，观察方向与支撑的配合。"},
    {"id": "compact-strength", "label": "紧凑握持", "style": "power", "program": "opposing_sidepulls",
     "intent": "较窄空间中的侧拉与较高握持需求；保留把下方手点当脚点的选择。"},
    {"id": "sustained-transfer", "label": "持续转换", "style": "sustained", "program": "roof_exit",
     "intent": "左右交替的空间走向，观察连续换脚与前序负荷；本例仍是单面25°墙。"},
)
LIMITATIONS = [
    "风格是空间设计意图；实际动作与指标由独立搜索和检查得出，不是保证达到风格或V等级。",
    "已声明踩面可复用；不会因为名称为手点就禁止脚，也不会把所有手部内缘自动当踩面。",
    "一个岩点同时手脚占用仍保守禁止；不同面的手脚同时使用、抹脚、挂脚与动态尚未建模。",
    "姿态几何通过不代表静态支撑通过，更不代表真人可攀；静力和消耗参数未标定，需定线员试攀。",
    "有界束搜索并非穷举；预算内未找到完整走法不代表不可攀。",
]
PROTOCOL = {"generator": "rules_only_contact_support_completion_v1", "wall_angle_deg": 25,
    "per_route_seconds": 60, "beam_width": 22, "max_expansions_per_objective": 16000,
    "max_transfers": 26, "max_ik_candidates_per_objective": 3,
    "feet_completion": "enable declared standing surfaces, then add installed footholds bottom-up; search all four limbs after each addition",
    "budget_scope": "search and refinement; final evidence serialization and validation recorded separately",
    "geometry_refinement": "up to two proposals from solved release-state COM and contact-force directions, each independently searched and checked",
    "selection": "P0 pass, release feasible fraction, all-state feasible fraction, capacity utilization, proxy effort",
    "not_optimized": ["V grade", "mandatory point coverage", "fixed action count", "prescribed limb order"],
}


def generator_hash():
    return "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def contact_signature(candidate):
    by_id = {s["id"]: s for s in candidate["states"]}
    return [(e["limb"], by_id[e["to_state"]]["contacts"][e["limb"]]["placement_id"],
             by_id[e["to_state"]]["contacts"][e["limb"]].get("contact_id", "main")) for e in candidate["events"]]


def metrics(request, candidate, evaluation):
    complete = bool(candidate["events"]) and all(not ref or candidate["states"][-1]["contacts"][limb] == ref
                for limb, ref in request["end_contacts"].items())
    used, previously_hand, reused = set(), set(), set()
    hand_contacts, foot_contacts = set(), set()
    for state in candidate["states"]:
        for limb in ("LF", "RF"):
            ref = state["contacts"][limb]
            if ref:
                foot_contacts.add(ref["placement_id"])
                if ref["placement_id"] in previously_hand: reused.add(ref["placement_id"])
        for limb in ("LH", "RH"):
            ref = state["contacts"][limb]
            if ref: previously_hand.add(ref["placement_id"]); hand_contacts.add(ref["placement_id"])
        used.update(ref["placement_id"] for ref in state["contacts"].values() if ref)
    states = evaluation.get("mechanics_report", {}).get("states", [])
    released, landed = [s for s in states if s["is_release"]], [s for s in states if not s["is_release"]]
    analysis, summary = analyze_beta(request, candidate) if complete else ({"moves": []}, {})
    loads = [m["accumulated_load"] for m in analysis["moves"]]
    context = _audit_context(request,candidate["placements"],all_surfaces=True)
    selected = set().union(*(set(ids) for ids in request.get("route_constraints", {}).get("allowed_contacts", {}).values()))
    installed = {p["id"] for p in candidate["placements"]}
    return {"complete": complete, "p0_status": evaluation["summary"]["status"],
        "hand_moves": sum(e["limb"].endswith("H") for e in candidate["events"]),
        "foot_moves": sum(e["limb"].endswith("F") for e in candidate["events"]),
        "transfers": len(candidate["events"]), "used_hold_ids": sorted(used),
        "hand_used_ids": sorted(hand_contacts), "foot_used_ids": sorted(foot_contacts),
        "skipped_hold_ids": sorted((selected or installed)-used), "unselected_hold_ids": sorted(installed-selected),
        "hand_then_foot_ids": sorted(reused), "peak_load": max(loads) if loads else None,
        "final_load": loads[-1] if loads else None, "total_proxy_effort": summary.get("total_proxy_effort"),
        "static_release_pass": sum(s["status"] == "feasible" for s in released), "static_release_total": len(released),
        "static_landed_pass": sum(s["status"] == "feasible" for s in landed), "static_landed_total": len(landed),
        "mean_technical": analysis.get("summary", {}).get("mean_technical"),
        "peak_strength": analysis.get("summary", {}).get("peak_strength"),
        "hand_lateral_travel_m": round(sum(abs(float(context[_contact_key({"placement_id":m["to_placement_id"],"contact_id":m.get("to_contact_id","main")})]["uv"][0] - context[_contact_key({"placement_id":m["from_placement_id"],"contact_id":m.get("from_contact_id","main")})]["uv"][0])) for m in analysis["moves"] if m["limb"].endswith("H")),4)}


def _check(request, deadline):
    records, stats = _sequence_search(request, request["reference_layout"], deadline=deadline)
    checked = []
    for record in records:
        if time.perf_counter() >= deadline: break
        evaluation = evaluate(request, record["candidate"], sequence_policy="independent_beta", deadline=deadline)
        record["evaluation"] = evaluation
        checked.append(record)
    checked.sort(key=_mechanical_rank)
    selected = checked[0] if checked else None
    return selected, {"search": stats, "shortlisted": len(records), "checked": len(checked),
        "budget_exhausted": time.perf_counter() >= deadline,
        "status": "complete" if selected and selected["evaluation"]["summary"]["status"] == "pass" else "search_unresolved",
        "metrics": metrics(request, selected["candidate"], selected["evaluation"]) if selected else None,
        "checked_summaries": [{"geometry_status": r["evaluation"]["summary"]["status"],
             "mechanics": r["evaluation"].get("mechanics_report", {}).get("summary", {}),
             "sequence_digest": canonical_hash(contact_signature(r["candidate"]))} for r in checked]}


def make_spatial_request(brief):
    request = default_request(profile="setting", setting_program=brief["program"], hold_source="assets", wall_profile="overhang", budget=1)
    request["id"] = "own-" + brief["id"]
    request["setting_design"]["search"]["geometry_trials"] = 1
    return request


def initial_contact_mask(request):
    allowed = allowed_contact_ids(request, request["reference_layout"])
    inventory = {h["id"]: h for h in request["scene"]["inventory"]}
    dedicated = {p["id"] for p in request["reference_layout"] if inventory[p["inventory_id"]]["type"] == "foothold"}
    anchors = {r["placement_id"] for r in request["start_contacts"].values() if r}
    mask = {limb: sorted(ids-(dedicated-anchors) if limb.endswith("F") else ids) for limb, ids in allowed.items()}
    # Spatial priority only: create support from the bottom upward. It imposes
    # neither foot order nor mandatory point use on the independent solver.
    by_id = {p["id"]: p for p in request["reference_layout"]}
    pool = sorted(dedicated-anchors, key=lambda pid: (by_id[pid]["v"], abs(by_id[pid]["u"]), pid))
    return mask, pool


def generate_route(brief, seconds=60):
    started = time.perf_counter(); deadline = started + seconds
    request = make_spatial_request(brief)
    initial_layout = copy.deepcopy(request["reference_layout"])
    mask, pool = initial_contact_mask(request)
    request["route_constraints"] = {"allowed_contacts": mask}
    attempts, additions, best, best_request = [], [], None, None
    record, attempt = _check(request, deadline)
    attempt["added_foot_id"] = None; attempts.append(attempt)
    before = copy.deepcopy(attempt)
    before_state = (copy.deepcopy(request), copy.deepcopy(record))
    if record and record["evaluation"]["summary"]["status"] == "pass": best, best_request = record, copy.deepcopy(request)
    for pid in pool:
        if best is not None or time.perf_counter() >= deadline: break
        for limb in ("LF", "RF"): mask[limb] = sorted(set(mask[limb]) | {pid})
        additions.append(pid)
        record, attempt = _check(request, deadline)
        attempt["added_foot_id"] = pid; attempts.append(attempt)
        if record and record["evaluation"]["summary"]["status"] == "pass": best, best_request = record, copy.deepcopy(request)
    completed = copy.deepcopy(attempts[-1])
    completion_state = (copy.deepcopy(best_request or request), copy.deepcopy(best))
    refinement = []
    if best:
        initial_best = best
        for strength in (.65, -.65):
            if time.perf_counter() >= deadline: break
            proposed = copy.deepcopy(best_request)
            proposed["reference_layout"] = _mechanical_proposal(proposed, initial_layout, initial_best, strength)
            record, attempt = _check(proposed, deadline)
            attempt["strength"] = strength; refinement.append(attempt)
            if record and _mechanical_rank(record) < _mechanical_rank(best): best, best_request = record, proposed
        search_finished = time.perf_counter()
        request = best_request
        candidate, evaluation = best["candidate"], best["evaluation"]
        candidate["id"] = "own-" + brief["id"]; candidate["name"] = brief["label"]; candidate["parent_id"] = None
        candidate["design_notes"] = [brief["intent"], *LIMITATIONS]
        # IDs enter the evaluator fingerprint: re-evaluate the selected candidate.
        evaluation = evaluate(request, candidate)
        status = "complete" if evaluation["summary"]["status"] == "pass" else "unverified"
    else:
        search_finished = time.perf_counter()
        candidate = _shell(request, request["reference_layout"])
        candidate["id"] = "own-"+brief["id"]; candidate["name"] = brief["label"]
        candidate["layout_report"] = {"status": "no_sequence", "wall_profile": "overhang", "reason": "Budget-limited independent search found no geometry-passing sequence", "search": attempts, "limitations": LIMITATIONS}
        evaluation = evaluate(request,candidate); status = "search_unresolved"
    bundle = make_bundle(request,[candidate],[evaluation]); validate_bundle(bundle)
    # Retain source requests, full checked candidate and poses for both stages.
    # Validation serialization is outside the bounded search/refinement budget.
    evidence = {}
    for name, (stage_request, stage_record) in (("before", before_state), ("after_support_completion", completion_state)):
        stage_candidate = copy.deepcopy(stage_record["candidate"]) if stage_record else _shell(stage_request, stage_request["reference_layout"])
        if not stage_record:
            stage_candidate["layout_report"] = {"status":"no_sequence","wall_profile":"overhang",
               "reason":"No geometry-passing sequence found during this bounded support-completion stage", "search":[],"limitations":LIMITATIONS}
        stage_evaluation = evaluate(stage_request,stage_candidate)
        stage_bundle = make_bundle(stage_request,[stage_candidate],[stage_evaluation])
        evidence[name] = stage_bundle
        stage = before if name == "before" else completed
        stage["metrics"] = metrics(stage_request,stage_candidate,stage_evaluation)

    m = metrics(request,candidate,evaluation)
    standing = sorted({p["id"] for p in request["reference_layout"] if p["id"] in mask["LF"] and p["id"] in mask["LH"]})
    changes = [{"placement_id": after["id"], "before": before_p, "after": after}
         for before_p, after in zip(initial_layout, candidate["placements"]) if before_p != after]
    return bundle, {"_evidence_bundles": evidence, **{k:v for k,v in brief.items() if k != "program"}, "status": status, "metrics": m,
         "geometry_digest": canonical_hash(candidate["placements"]), "sequence_digest": canonical_hash(contact_signature(candidate)),
         "completion": {"before": before, "after_support_completion": completed, "after": {"status": status,"metrics": m},
                        "added_foot_ids": additions, "enabled_standing_ids": standing, "attempts": attempts},
         "geometry_refinement": {"proposals": refinement,"changes": changes},
         "search": {"elapsed_ms": round((search_finished-started)*1000,2), "timeout_seconds": seconds,
                    "validation_ms": round((time.perf_counter()-search_finished)*1000,2),
                    "budget_exhausted": search_finished >= deadline}}


def generate_study(directory, seconds=60):
    directory = Path(directory); directory.mkdir(parents=True,exist_ok=True)
    rows=[]
    frozen_engine, frozen_generator = code_hash(), generator_hash()
    for brief in BRIEFS:
        bundle,row = generate_route(brief,seconds)
        for name, evidence in row.pop("_evidence_bundles").items():
            evidence_digest = evidence["manifest"]["bundle_digest"]
            evidence_file = f"bundles/{evidence_digest.split(':')[-1]}.json.gz"
            row["completion"][name].update(bundle_file=evidence_file, bundle_digest=evidence_digest)
            write_json(directory/evidence_file,evidence)
        digest=bundle["manifest"]["bundle_digest"]
        row.update(bundle_digest=digest,bundle_file=f"bundles/{digest.split(':')[-1]}.json.gz")
        write_json(directory/row["bundle_file"],bundle); rows.append(row)
        print(f"{row['id']}: {row['status']}, {row['metrics']}",flush=True)
    if code_hash()!=frozen_engine or generator_hash()!=frozen_generator:
        raise ValueError("Generator changed during this run; index not published.")
    comparisons=pairwise(rows)
    for row in rows: _verify_row(directory,row)
    data={"schema_version":FORMAT,"engine_code_hash":frozen_engine,"generator_code_hash":frozen_generator,
        "protocol":{**PROTOCOL,"per_route_seconds":seconds},"limitations":LIMITATIONS,"routes":rows,"pairwise":comparisons}
    data["index_digest"]=canonical_hash(data)
    write_json(directory/"study.json",data)
    return data


def pairwise(rows):
    comparisons=[]
    for a,b in itertools.combinations(rows,2):
        ua,ub=set(a["metrics"]["used_hold_ids"]),set(b["metrics"]["used_hold_ids"])
        comparisons.append({"a":a["id"],"b":b["id"],"geometry_same":a["geometry_digest"]==b["geometry_digest"],
             "sequence_same":a["sequence_digest"]==b["sequence_digest"],"shared_used_fraction":len(ua&ub)/max(1,len(ua|ub)),
             "note":"IDs name inventory roles across independently installed layouts; geometry differences must be read with overlap."})
    return comparisons


def _bundle(directory, record):
    root=Path(directory).resolve(); path=(root/record["bundle_file"]).resolve()
    if not path.is_relative_to(root): raise ValueError("线路包路径超出保存目录。")
    bundle=read_json(path); validate_bundle(bundle)
    if record["bundle_digest"]!=bundle["manifest"]["bundle_digest"]: raise ValueError("线路包摘要不匹配。")
    return bundle


def _verify_row(directory,row):
    bundle=_bundle(directory,row)
    request,candidate,evaluation=bundle["request"],bundle["candidates"][0],bundle["evaluations"][0]
    if row["geometry_digest"]!=canonical_hash(candidate["placements"]) or row["sequence_digest"]!=canonical_hash(contact_signature(candidate)):
        raise ValueError("线路几何或动作摘要不匹配。")
    actual=metrics(request,candidate,evaluation)
    if row["metrics"]!=actual or row["completion"]["after"]["metrics"]!=actual: raise ValueError("线路指标与实际检查不匹配。")
    expected_status = "complete" if actual["complete"] and actual["p0_status"] == "pass" else "unverified" if actual["complete"] else "search_unresolved"
    if row["status"] != expected_status: raise ValueError("线路状态与实际检查不匹配。")
    before=None
    for name in ("before","after_support_completion"):
        stage=row["completion"][name]; proof=_bundle(directory,stage)
        sr,sc,se=proof["request"],proof["candidates"][0],proof["evaluations"][0]
        if stage["metrics"]!=metrics(sr,sc,se): raise ValueError("补脚点阶段指标与证据包不一致。")
        if name=="before": before=proof
    initial_mask=before["request"]["route_constraints"]["allowed_contacts"]
    final_mask=request["route_constraints"]["allowed_contacts"]
    added=set(final_mask["LF"])-set(initial_mask["LF"])
    if set(row["completion"]["added_foot_ids"])!=added or added != set(final_mask["RF"])-set(initial_mask["RF"]):
        raise ValueError("补入脚点名单与前后请求不一致。")
    changes=[{"placement_id":after["id"],"before":old,"after":after}
         for old,after in zip(before["candidates"][0]["placements"],candidate["placements"]) if old!=after]
    if row["geometry_refinement"]["changes"]!=changes: raise ValueError("几何修订与前后证据不一致。")
    return bundle


def load_study(directory):
    data=read_json(Path(directory)/"study.json")
    if not isinstance(data,dict) or data.get("schema_version")!=FORMAT: raise ValueError("未知自有线路对照格式。")
    if data.get("engine_code_hash")!=code_hash() or data.get("generator_code_hash")!=generator_hash():
        raise ValueError("自有线路对照已过期，请用当前算法重新生成。")
    if data.get("index_digest")!=canonical_hash({k:v for k,v in data.items() if k!="index_digest"}): raise ValueError("线路对照摘要不匹配。")
    rows=data.get("routes")
    if not isinstance(rows,list) or len(rows)!=len(BRIEFS) or {r.get("id") for r in rows if isinstance(r,dict)}!={b["id"] for b in BRIEFS}:
        raise ValueError("线路对照必须包含三个不重复的空间方案。")
    try:
        for row in rows:
            brief=next(b for b in BRIEFS if b["id"]==row["id"])
            if any(row[key]!=brief[key] for key in ("label","intent","style")): raise ValueError("空间意图与生成器不一致。")
            _verify_row(directory,row)
        if data.get("pairwise")!=pairwise(rows): raise ValueError("线路差异记录与实际结果不一致。")
    except (KeyError,TypeError,IndexError) as exc:
        raise ValueError("自有线路对照结构不完整。") from exc
    return data


def load_route(directory,route_id):
    if route_id not in {b["id"] for b in BRIEFS}: raise ValueError("未知自有线路。")
    data=load_study(directory)
    return _verify_row(directory,next(r for r in data["routes"] if r["id"]==route_id))
