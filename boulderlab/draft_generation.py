"""Interactive rules-only proposals, with a bounded independent beta search.

The brief changes installed geometry, never an invented move order or grade.
Keep this adapter separate from the signed, saved research experiments.
"""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
import random
import time

from .beta_audit import _make_candidate, _search, analyze_beta
from .engine import canonical_hash, default_request, evaluate, make_bundle, validate_bundle, validate_request
from .own_routes import contact_signature, initial_contact_mask, metrics
from .setting import _mechanical_rank, _shell
from .wall_profiles import PROFILES, fit_installed_footprints, repair_panel_spacing

VERSION = "rules-draft-options-v2"
SECONDS = 40
STYLES = {
    "balance": ("技巧移重", "diagonal_balance"),
    "power": ("力量握持", "opposing_sidepulls"),
    "sustained": ("持续输出", "roof_exit"),
}
DIFFICULTIES = {"easy": ("轻松", .88), "medium": ("适中", 1.), "hard": ("挑战", 1.13)}
WALLS = {key: PROFILES[key] for key in ("overhang", "roof", "dihedral", "arete")}
LIMITATIONS = [
    "难度是间距与脚点支撑的设计目标，未经标定，不是已验证的 V 等级。",
    "风格决定空间种子；实际手脚走法由有界搜索发现，可跳过岩点。",
    "几何、静态支撑和消耗是近似检查，最终线路需定线员修改与试攀。",
    "预算内未找到完整走法不等于不可攀；没有用保存示例替代本次生成。",
]


def validate_options(payload):
    expected = {"wall_profile", "style", "difficulty", "seed", "variant"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("生成线路需要墙面、风格、难度、种子和方案编号。")
    for key, choices in (("wall_profile", WALLS), ("style", STYLES), ("difficulty", DIFFICULTIES)):
        if not isinstance(payload[key], str) or payload[key] not in choices:
            raise ValueError(f"不支持的生成选项：{key}。")
    if type(payload["seed"]) is not int or not 0 <= payload["seed"] <= 2147483647:
        raise ValueError("种子须为 0 到 2147483647 的整数。")
    if type(payload["variant"]) is not int or payload["variant"] not in (0, 1, 2):
        raise ValueError("方案编号须为 0、1 或 2。")
    return dict(payload)


def build_request(payload):
    """Reproducible installed geometry; retain real mesh/contact annotations."""
    options = validate_options(payload)
    style_label, program = STYLES[options["style"]]
    difficulty_label, spread = DIFFICULTIES[options["difficulty"]]
    request = default_request(profile="setting", setting_program=program,
        wall_profile=options["wall_profile"], hold_source="assets", seed=options["seed"], budget=1)
    request["id"] = f"draft-{options['seed']}-{options['variant']}"
    request["setting_design"]["search"]["geometry_trials"] = 1
    original = copy.deepcopy(request["reference_layout"])
    anchors = {ref["placement_id"] for ref in request["start_contacts"].values() if ref}
    inventory = {item["id"]: item for item in request["scene"]["inventory"]}
    panels = {panel["id"]: panel for panel in request["scene"]["wall_panels"]}
    # Coherent bends give three different hand/foot corridors, rather than
    # relabelling the same route. Jitter explores a small, reproducible region.
    rng = random.Random(options["seed"] * 7 + options["variant"])
    bend = (-.13, 0., .13)[options["variant"]]
    for placement in request["reference_layout"]:
        if placement["id"] in anchors:
            continue
        panel = panels[placement["wall_panel_id"]]
        progress = max(0., min(1., placement["v"] / panel["height"]))
        foot = inventory[placement["inventory_id"]]["type"] == "foothold"
        # Difficulty changes reach and support positions. It never changes
        # friction, body capacities, mesh dimensions or the check thresholds.
        placement["u"] = round(placement["u"] * spread + bend * math.sin(math.pi * progress)
            + rng.uniform(-.018, .018), 5)
        placement["v"] = round(placement["v"] + (spread - 1.) * (.10 if foot else .20)
            + rng.uniform(-.012, .012), 5)
        placement["rotation_deg"] = round(placement["rotation_deg"]
            + (options["variant"] - 1) * (3. if foot else 6.) + rng.uniform(-2., 2.), 3)
    fitted = fit_installed_footprints(request, "fit generated proposal inside the selected wall panel")
    spacing = repair_panel_spacing(request)
    adjustments = [{"placement_id": after["id"], "before": before, "after": copy.deepcopy(after)}
        for before, after in zip(original, request["reference_layout"]) if before != after]
    brief = {**options, "labels": {"wall": WALLS[options["wall_profile"]], "style": style_label,
        "difficulty": difficulty_label}, "generator_version": VERSION,
        "generator_code_hash": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()
            + Path(__file__).with_name("support_refinement.py").read_bytes()).hexdigest(),
        "difficulty_policy": {"horizontal_spread": spread, "support": "progressively enable installed foot support; declared hand-hold standing faces remain available"},
        "variant_policy": {"corridor_bend_m": bend, "position_jitter_m": [.018, .012], "rotation_jitter_deg": 2.},
        "adjustments": adjustments, "panel_fit": fitted, "spacing": spacing, "limitations": LIMITATIONS,
        "support_policy": "Check several independently searched betas; feed failed release/landing contact directions and moment arms into bounded layout proposals; independently search and check every proposal; retain only a better geometry-first static-support rank.",
        "support_adjustments": [], "support_proposal": "seed"}
    request["generation_brief"] = brief
    request["setting_design"]["intent"] = f"{style_label} · {difficulty_label}；{LIMITATIONS[0]}"
    validate_request(request)
    return request


def _supported(record):
    return record is not None and record["evaluation"]["summary"]["status"] == "pass" and \
        record["evaluation"].get("mechanics_report", {}).get("summary", {}).get("status") == "feasible"


def _support_summary(record):
    if record is None:
        return None
    summary = record["evaluation"].get("mechanics_report", {}).get("summary", {})
    release = summary.get("release_states", 0)
    return {"geometry_status": record["evaluation"]["summary"]["status"],
        "release_pass": release-summary.get("release_infeasible_states", release)-summary.get("release_unknown_states", 0),
        "release_total": release, "feasible_states": summary.get("feasible_states", 0),
        "total_states": sum(summary.get(f"{key}_states", 0) for key in ("feasible", "infeasible", "unknown")),
        "unknown_states": summary.get("unknown_states", 0),
        "max_capacity_utilization": summary.get("max_capacity_utilization"),
        "status": summary.get("status", "unknown")}


def _attempt(request, deadline, label):
    shell = _shell(request, request["reference_layout"])
    options = {**request["setting_design"]["search"], "max_transfers": 26, "max_ik_candidates": 3}
    searched, search = [], []
    for objective in ("fewer_transfers", "lower_proxy_effort"):
        if time.perf_counter() >= deadline:
            break
        sequences, stats = _search(request, shell, objective, options, deadline=deadline)
        searched.append((objective, sequences))
        search.append(stats)
    # Interleave short and lower-effort betas so the first geometry-pass short
    # sequence cannot monopolize the candidate checking budget.
    choices, seen = [], set()
    for index in range(options["max_ik_candidates"]):
        for objective, sequences in searched:
            if index >= len(sequences):
                continue
            signature = tuple(sequences[index])
            if signature not in seen:
                choices.append((objective, sequences[index])); seen.add(signature)
    checked = []
    for objective, steps in choices:
        if time.perf_counter() >= deadline:
            break
        candidate = _make_candidate(shell, steps, objective)
        candidate["parent_id"] = None
        candidate["name"] = label
        candidate["design_notes"] = LIMITATIONS
        evaluation = evaluate(request, candidate, deadline=deadline)
        analysis, summary = analyze_beta(request, candidate)
        checked.append({"candidate": candidate, "evaluation": evaluation, "analysis": analysis, "summary": summary})
        # Geometry pass alone says nothing about the remaining contacts during
        # a release. Do not discard better-supported independently found betas.
        if _supported(checked[-1]):
            break
    checked.sort(key=_mechanical_rank)
    return (checked[0] if checked else None), {"search": search, "checked": len(checked),
        "statuses": [record["evaluation"]["summary"]["status"] for record in checked],
        "support": [_support_summary(record) for record in checked]}


def generate_option(payload, *, seconds=SECONDS):
    options = validate_options(payload)
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 < seconds <= SECONDS:
        raise ValueError(f"生成预算必须大于 0 且不超过 {SECONDS} 秒。")
    started = time.perf_counter()
    request = build_request(options)
    deadline = time.perf_counter() + seconds
    label = "方案 " + "ABC"[options["variant"]]
    mask, pool = initial_contact_mask(request)
    request["route_constraints"] = {"allowed_contacts": mask}
    best, best_request, attempts = None, None, []
    stages = sorted({0, min(3, len(pool)), len(pool)})
    # Reserve time for feedback, instead of spending the whole budget on a
    # reachable layout and merely attaching a support warning afterwards.
    baseline_deadline = min(deadline, time.perf_counter() + seconds*.40)
    for index, support_count in enumerate(stages):
        if time.perf_counter() >= deadline:
            break
        for limb in ("LF", "RF"):
            mask[limb] = sorted(set(mask[limb]) | set(pool[:support_count]))
        # Leave most of the budget for the fully supported independent search.
        stage_deadline = baseline_deadline if index == len(stages) - 1 else min(baseline_deadline, time.perf_counter() + seconds * .10)
        record, attempt = _attempt(request, stage_deadline, label)
        attempt["enabled_foot_ids"] = pool[:support_count]
        attempts.append(attempt)
        if record is not None and (best is None or _mechanical_rank(record) < _mechanical_rank(best)):
            best, best_request = record, copy.deepcopy(request)
        if _supported(best):
            break
    if best is None and time.perf_counter() < deadline:
        # A difficult seed can use the remaining time to find any checked
        # sequence; no feedback is possible until one has been evaluated.
        record, attempt = _attempt(request, deadline, label)
        attempt["enabled_foot_ids"] = pool
        attempts.append(attempt)
        if record is not None:
            best, best_request = record, copy.deepcopy(request)
    baseline = copy.deepcopy(best)
    refinement = []
    if best is not None and not _supported(best) and time.perf_counter() < deadline:
        from .support_refinement import support_proposals
        proposal_request = copy.deepcopy(best_request)
        proposals = support_proposals(proposal_request, best)
        proposals.sort(key=lambda item: item["label"] != "roof-exit-support")
        for index, proposal in enumerate(proposals):
            if time.perf_counter() >= deadline:
                break
            proposed = copy.deepcopy(proposal_request)
            proposed["reference_layout"] = proposal["placements"]
            proposed["generation_brief"]["support_proposal"] = proposal["label"]
            proposed["generation_brief"]["support_adjustments"] = proposal["changes"]
            proposed["generation_brief"]["support_rationale"] = proposal["rationale"]
            # Every proposed layout is searched from scratch. No old movement
            # order is carried over to make moved holds appear useful.
            remaining_proposals = len(proposals)-index
            trial_deadline = min(deadline, time.perf_counter() + (deadline-time.perf_counter())/remaining_proposals)
            record, attempt = _attempt(proposed, trial_deadline, label)
            improved = record is not None and _mechanical_rank(record) < _mechanical_rank(best)
            refinement.append({"proposal": proposal["label"], "changes": proposal["changes"],
                "rationale": proposal["rationale"], "search": attempt, "support": _support_summary(record), "accepted": improved})
            if improved:
                best, best_request = record, proposed
            if _supported(best):
                break
    search_finished = time.perf_counter()
    if best is None:
        candidate = _shell(request, request["reference_layout"])
        candidate["name"] = label
        candidate["design_notes"] = LIMITATIONS
        candidate["layout_report"] = {"status": "no_sequence", "wall_profile": options["wall_profile"],
            "reason": "Budget-limited independent search found no checked complete sequence", "search": attempts, "limitations": LIMITATIONS}
        evaluation = evaluate(request, candidate, deadline=deadline)
        status = "search_unresolved"
    else:
        request = best_request
        candidate, evaluation = best["candidate"], best["evaluation"]
        status = "complete" if evaluation["summary"]["status"] == "pass" else "unverified"
    bundle = make_bundle(request, [candidate], [evaluation])
    validate_bundle(bundle)
    return {"id": request["id"], "label": label, "status": status,
        "metrics": metrics(request, candidate, evaluation), "bundle": bundle,
        "brief": request["generation_brief"], "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "geometry_digest": canonical_hash(candidate["placements"]), "sequence_digest": canonical_hash(contact_signature(candidate)),
        "refinement": {"before": _support_summary(baseline), "after": _support_summary(best),
            "proposals": refinement, "selected_proposal": request["generation_brief"]["support_proposal"],
            "selection": "geometry pass, release-state feasible fraction, all-state feasible fraction, required capacity utilization, proxy effort"},
        "search": {"timeout_seconds": seconds, "elapsed_ms": round((search_finished - started) * 1000, 2),
            "budget_exhausted": search_finished >= deadline, "attempts": attempts,
            "budget_scope": "contact search and pose checks; geometry preparation, bundle validation and serialization recorded in total elapsed_ms"}}
