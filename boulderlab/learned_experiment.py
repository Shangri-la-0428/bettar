"""Saved, fixed-wall proposal experiments. No ML runtime is imported here."""
from __future__ import annotations

import copy
import gzip
import json
import random
import re
import time
from pathlib import Path

from .beta_audit import LIMBS, _audit_context, analyze_beta
from .engine import canonical_hash, code_hash, evaluate, make_bundle, validate_bundle, validate_request
from .setting import _sequence_search, _shell

FORMAT = "learned-experiment-v1"
CONDITIONS = (("V3", 16), ("V4", 18), ("V5", 20))
PROTOCOL = {
    "sample_count": 30, "seeds": list(range(10)), "search_seconds": 60,
    "beam_width": 22, "max_expansions": 16000, "max_transfers": 26,
    "max_ik_candidates_per_objective": 3,
    "objectives": ["fewer_transfers", "lower_proxy_effort"],
    "geometry_policy": "fixed installed wall; excluded holds remain collision geometry",
    "anchor_policy": "shared four starting contacts and matched TOP; generated start/finish become hand candidates",
    "random_policy": "seeded shared permutation within surface-permission strata; all anchors fixed; joint hand/foot roles and effective limb counts preserved",
    "repeat_policy": "identical effective contact masks share one search result; every proposal remains in the denominator",
    "ranking": "complete and P0 pass first, release feasible fraction descending, peak accumulated load ascending",
    "limitations": ["One wall with 18 holds; no estimate of generalization.",
                    "V grades are model conditions, not verified route grades.",
                    "Discrete skeleton and synthetic static/load checks; human forerunning required.",
                    "Budget-limited search failure is not proof of impossibility."],
}


def read_json(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def comparison_request_digest(request):
    """Bind scene, body, solver and anchors while allowing per-run route masks."""
    return canonical_hash({k: v for k, v in request.items() if k not in {"id", "route_constraints"}})


def wall_metadata(request):
    scene = request["scene"]
    panels = scene.get("wall_panels", [])
    if len(panels) > 1 or (panels and any(panels[0]["rotation_deg"][1:])):
        raise ValueError("学习生成对照仅支持单一正向仰角墙板。")
    angle = scene["angle_deg"] + (panels[0]["rotation_deg"][0] if panels else 0)
    return {"angle_deg": angle, "hold_count": len(request["reference_layout"]),
            "placements_digest": canonical_hash(request["reference_layout"]), "body_id": request["body"]["id"]}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    if path.suffix == ".gz":
        encoded = gzip.compress(encoded, mtime=0)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)


def _permissions(request):
    return {pid: set(item["limbs"]) for pid, item in _audit_context(request, request["reference_layout"]).items()}


def anchor_roles(request):
    roles = {"hand": set(), "foot": set()}
    for key in ("start_contacts", "end_contacts"):
        for limb, ref in request[key].items():
            if ref:
                roles["hand" if limb.endswith("H") else "foot"].add(ref["placement_id"])
    return roles


def role_mask(request, roles):
    permissions = _permissions(request)
    result = {limb: set() for limb in LIMBS}
    for role, ids in roles.items():
        for pid in ids:
            if pid not in permissions:
                raise ValueError(f"unknown proposed placement: {pid}")
            # A hand hold may also be a foothold, only if its selected surface permits it.
            for limb in permissions[pid]:
                if role == "hand" or limb.endswith("F"):
                    result[limb].add(pid)
    return {limb: sorted(ids) for limb, ids in result.items()}


def adapt_proposal(request, proposal):
    permissions = _permissions(request)
    roles = {"hand": set(), "foot": set()}
    dropped, remapped, duplicates = [], [], []
    seen = set()
    for selection in proposal["raw_selections"]:
        pid, role = selection.get("placement_id"), selection.get("role")
        if role == "null":
            continue
        if role not in {"start", "finish", "hand", "foot"} or pid not in permissions:
            raise ValueError(f"invalid model selection: {selection}")
        mapped = "hand" if role in {"start", "finish", "hand"} else "foot"
        if not any(limb.endswith("H" if mapped == "hand" else "F") for limb in permissions[pid]):
            dropped.append({"placement_id": pid, "role": role, "reason": "selected surface does not permit role"})
            continue
        if (pid, mapped) in seen:
            duplicates.append({"placement_id": pid, "role": mapped})
        seen.add((pid, mapped))
        roles[mapped].add(pid)
        if role != mapped:
            remapped.append({"placement_id": pid, "from": role, "to": mapped})
    anchors = anchor_roles(request)
    added = {role: sorted(ids - roles[role]) for role, ids in anchors.items()}
    for role, ids in anchors.items():
        roles[role].update(ids)
    return role_mask(request, roles), {"roles": {k: sorted(v) for k, v in roles.items()},
        "added_anchors": added, "remapped_roles": remapped,
        "dropped_incompatible": dropped, "duplicate_selections": duplicates}


def random_mask(request, adjusted_roles, seed):
    """Preserve joint roles, overlap and effective limb counts under permutation."""
    permissions, anchors = _permissions(request), anchor_roles(request)
    rng = random.Random(seed)
    fixed = anchors["hand"] | anchors["foot"]
    mapping = {pid: pid for pid in fixed}
    signatures = {tuple(sorted(allowed)) for pid, allowed in permissions.items() if pid not in fixed}
    for signature in sorted(signatures):
        pool = sorted(pid for pid, allowed in permissions.items()
                      if pid not in fixed and tuple(sorted(allowed)) == signature)
        shuffled = list(pool)
        rng.shuffle(shuffled)
        mapping.update(zip(pool, shuffled))
    roles = {}
    for role in ("hand", "foot"):
        ids = set(adjusted_roles[role])
        if not anchors[role] <= ids or ids - permissions.keys():
            raise ValueError("control roles must contain valid installed anchors and selections")
        # One shared mapping preserves overlaps; independently sampling each role
        # could give the control additional usable feet on universal hand holds.
        roles[role] = {mapping[pid] for pid in ids}
    return role_mask(request, roles), {"roles": {k: sorted(v) for k, v in roles.items()},
                                      "sampling_seed": seed, "anchors_preserved": True}


def all_contacts(request):
    permissions = _permissions(request)
    return {limb: sorted(pid for pid, allowed in permissions.items() if limb in allowed) for limb in LIMBS}


def request_with_mask(base, mask):
    request = copy.deepcopy(base)
    request["route_constraints"] = {"allowed_contacts": copy.deepcopy(mask)}
    request["id"] = "learned-wall-" + canonical_hash(mask)[-16:]
    validate_request(request)
    return request


def metrics_for(request, candidate, evaluation, mask):
    selected = set().union(*(set(ids) for ids in mask.values()))
    used = {ref["placement_id"] for state in candidate["states"] for ref in state["contacts"].values() if ref}
    complete = bool(candidate["events"]) and all(
        not ref or candidate["states"][-1]["contacts"][limb] == ref for limb, ref in request["end_contacts"].items())
    mechanics = (evaluation or {}).get("mechanics_report", {}).get("states", [])
    releases = [s for s in mechanics if s["is_release"]]
    landed = [s for s in mechanics if not s["is_release"]]
    analysis, summary = analyze_beta(request, candidate) if complete else ({"moves": []}, {})
    loads = [m["accumulated_load"] for m in analysis["moves"]]
    return {"hand_holds": len(set(mask["LH"]) | set(mask["RH"])),
            "foot_holds": len(set(mask["LF"]) | set(mask["RF"])),
            "selected_holds": len(selected), "used_holds": len(used) if complete else None,
            "skipped_holds": sorted(selected - used) if complete else None,
            "transfers": len(candidate["events"]) if complete else None,
            "hand_transfers": sum(e["limb"].endswith("H") for e in candidate["events"]) if complete else None,
            "foot_transfers": sum(e["limb"].endswith("F") for e in candidate["events"]) if complete else None,
            "p0_status": (evaluation or {}).get("summary", {}).get("status", "not_checked"),
            "static_release_pass": sum(s["status"] == "feasible" for s in releases),
            "static_release_total": len(releases),
            "static_landed_pass": sum(s["status"] == "feasible" for s in landed),
            "static_landed_total": len(landed),
            "peak_load": max(loads) if loads else None, "final_load": loads[-1] if loads else None,
            "total_proxy_effort": summary.get("total_proxy_effort")}


def result_rank(run):
    m = run.get("metrics", {})
    return (run["status"] != "complete", m.get("p0_status") != "pass",
            -m.get("static_release_pass", 0) / max(1, m.get("static_release_total", 0)),
            m.get("peak_load") if m.get("peak_load") is not None else float("inf"), run["id"])


def search_mask(base, mask, seconds=60):
    request = request_with_mask(base, mask)
    started = time.perf_counter()
    deadline = started + seconds
    records, stats = _sequence_search(request, request["reference_layout"], deadline=deadline)
    checked = []
    for index, record in enumerate(records):
        candidate = record["candidate"]
        candidate["id"] = request["id"] + f"-beta{index}"
        candidate["name"] = "固定墙面 · 独立搜索走法"
        candidate["design_notes"] = ["岩点组合来自独立实验记录；本手脚顺序由 bettar 搜索。",
                                     "未选岩点保留安装与碰撞几何。"]
        evaluation = evaluate(request, candidate, deadline=deadline)
        metrics = metrics_for(request, candidate, evaluation, mask)
        checked.append({"id": candidate["id"], "status": "complete", "candidate": candidate,
                        "evaluation": evaluation, "metrics": metrics})
    if checked:
        chosen = min(checked, key=result_rank)
        candidate, evaluation, metrics = chosen["candidate"], chosen["evaluation"], chosen["metrics"]
        status = "complete"
    else:
        candidate = _shell(request, request["reference_layout"])
        candidate["id"] = request["id"] + "-unresolved"
        candidate["name"] = "固定墙面 · 预算内未找到完整走法"
        candidate["layout_report"] = {"status": "no_sequence", "wall_profile": "overhang",
            "reason": "bounded independent search found no complete contact sequence; installed layout only",
            "search": stats, "limitations": PROTOCOL["limitations"]}
        evaluation = evaluate(request, candidate, deadline=deadline)
        metrics = metrics_for(request, candidate, evaluation, mask)
        status = "search_unresolved"
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    bundle = make_bundle(request, [candidate], [evaluation])
    return bundle, {"status": status, "metrics": metrics, "search": {
        "timeout_seconds": seconds, "elapsed_ms": elapsed, "time_budget_exhausted": time.perf_counter() >= deadline,
        "objectives": stats, "shortlisted": len(records),
        "checked": [{"candidate_id": c["id"], "metrics": c["metrics"]} for c in checked]}}


def aggregate(runs):
    result = {}
    for source, name in (("betazero", "model"), ("random", "random"), ("baseline", "baseline")):
        group = [r for r in runs if r["source"] == source]
        masks = {canonical_hash(r["selected_contacts"]) for r in group if r.get("selected_contacts")}
        result[name] = {"total": len(group), "complete": sum(r["status"] == "complete" for r in group),
            "p0_pass": sum(r.get("metrics", {}).get("p0_status") == "pass" and r["status"] == "complete" for r in group),
            "unique": len(masks), "search_unresolved": sum(r["status"] == "search_unresolved" for r in group),
            "generation_failed": sum(r["status"] == "generation_failed" for r in group)}
        if source == "betazero":
            result[name]["empty_proposals"] = sum(not r.get("proposal", {}).get("raw_selections") for r in group)
            result[name]["no_intermediate_holds"] = sum(r.get("no_intermediate_holds", False) for r in group)
    return result


def load_experiment(directory):
    path = Path(directory) / "experiment.json"
    if not path.is_file():
        raise FileNotFoundError("学习生成对照尚未生成；请运行 scripts/run_learned_experiment.py。")
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError("无效学习生成对照索引。")
    if data.get("schema_version") != FORMAT or data.get("engine_code_hash") != code_hash():
        raise ValueError("学习生成对照已过期；请使用当前检查器重新生成。")
    if data.get("index_digest") != canonical_hash({k: v for k, v in data.items() if k != "index_digest"}):
        raise ValueError("学习生成对照索引摘要不一致。")
    return data


def load_run(directory, run_id):
    if not re.fullmatch(r"[a-z0-9-]{1,100}", run_id):
        raise ValueError("无效实验编号。")
    return validate_saved_run(directory, load_experiment(directory), run_id)


def validate_saved_run(directory, data, run_id):
    """Check staged rows before publishing an index, or serve a published row."""
    if not re.fullmatch(r"[a-z0-9-]{1,100}", run_id):
        raise ValueError("无效实验编号。")
    run = next((r for r in data["runs"] if r["id"] == run_id), None)
    if run is None or not run.get("bundle_file"):
        raise FileNotFoundError("该样本没有保存的线路结果。")
    filename = run["bundle_file"]
    if not re.fullmatch(r"[a-z0-9-]+\.json\.gz", filename):
        raise ValueError("无效实验文件引用。")
    root = Path(directory).resolve()
    bundle_path = (root / "bundles" / filename).resolve()
    if not bundle_path.is_relative_to(root):
        raise ValueError("实验文件必须位于保存目录内。")
    bundle = validate_bundle(read_json(bundle_path))
    if bundle["manifest"]["bundle_digest"] != run["bundle_digest"]:
        raise ValueError("样本与结果包不匹配。")
    if bundle["request"].get("route_constraints", {}).get("allowed_contacts") != run["selected_contacts"]:
        raise ValueError("样本与选点约束不匹配。")
    if comparison_request_digest(bundle["request"]) != data.get("comparison_request_digest"):
        raise ValueError("样本的墙面、体型、求解参数或起终点与对照实验不匹配。")
    if wall_metadata(bundle["request"]) != data.get("wall"):
        raise ValueError("样本与墙面元数据不匹配。")
    if len(bundle["candidates"]) != 1 or len(bundle["evaluations"]) != 1:
        raise ValueError("实验样本必须包含一个候选及对应检查。")
    candidate, evaluation = bundle["candidates"][0], bundle["evaluations"][0]
    if canonical_hash(candidate["placements"]) != canonical_hash(bundle["request"]["reference_layout"]):
        raise ValueError("实验样本改变了固定安装几何。")
    expected_metrics = metrics_for(bundle["request"], candidate, evaluation, run["selected_contacts"])
    if expected_metrics != run.get("metrics"):
        raise ValueError("样本统计与检查结果包不匹配。")
    expected_status = "complete" if expected_metrics["transfers"] is not None else "search_unresolved"
    if run.get("status") != expected_status:
        raise ValueError("样本状态与完整走法检查不匹配。")
    return bundle
