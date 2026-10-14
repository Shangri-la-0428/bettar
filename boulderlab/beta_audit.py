"""Independent, bounded beta search on an unchanged installed route.

This is an adversarial geometry audit, not a climbing simulator. No requested
phase, requested number of hand moves, or point-coverage requirement enters the
search. Every returned sequence is checked again by the normal IK evaluator.
"""
from __future__ import annotations

import copy
import hashlib
import math
import time
from collections import Counter
from pathlib import Path

import numpy as np

from .full_route import _history
from .geometry import selected_contact, wall_basis
from .route_constraints import allowed_contact_ids, constraint_errors
from .route_design import DIMS, _context, _metrics, _ref, _valid_contact_geometry

MODEL_VERSION = "independent-beta-proxy-3"
LIMBS = ("LH", "RH", "LF", "RF")
MATCHING_POLICY = {
    "source": "conservative_synthetic_search_assumption",
    "allowed_types": ["jug", "sloper", "rail"],
    "min_hold_width_m": .24, "min_hold_height_m": .10,
    "min_selected_patch_major_diameter_m": .08, "min_selected_patch_minor_diameter_m": .03,
    "simultaneous_hand_foot_same_point": False, "simultaneous_feet_same_point": False,
    "meaning": "wide-hold matching permission only; independent hand contact locations and collision are not modeled",
}
LIMITATIONS = [
    "仅检查已安装岩点的当前选中抓握面；不会借用候选库存，也未搜索其它抓握面、抹脚、挂脚、跑跳或同时移动多肢。",
    "允许任意单肢顺序、双手匹配、跳点及有限回撤；不要求原动作数、阶段顺序或每个点被使用。",
    "受限搜索有剪枝和预算；未找到更优解不证明点不可跳、难点不可绕过或当前走法最优。",
    "拉向与手脚配合只作为透明几何代理量；抓握力、摩擦、力矩、平衡、连续转换与真人可攀性均未验证。",
    "负荷和恢复系数未经真人标定，模型负担较低不等于真人一定更省力。IK 只验证离散接触姿态，失败收敛保留为未知。",
    "审计总负担在原动作负荷上加入保留手拉向与名义躯干/脚支撑的代理惩罚；原走法和替代走法使用同一公式。峰值仍沿用带前序负荷的手动作负担。",
    "双手匹配仅按保守合成假设允许：Jug/Sloper/Rail 宽≥0.24m、高≥0.10m，选中抓握面主/次直径≥0.08/0.03m；Pocket、Crimp 及其它小面不允许。阈值不是人体尺寸或真实可匹配证明。",
    "一个抓握面仍只有一个代表接触点；禁止双脚或手脚同时占用该点，允许先用手后改用脚。大面双手匹配也尚未建模两个独立手掌位置或碰撞。",
    "独立束搜索没有通过的替代时，补充逐项删除原序列单个动作的有界跳点挑战；最多另验两条，不删除几何，仍需完整起终点及同一 IK 复核。",
]


def audit_code_hash():
    return "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _contacts(key):
    return {limb: _ref(pid) for limb, pid in zip(LIMBS, key)}


def _key(contacts):
    return tuple(contacts[l]["placement_id"] for l in LIMBS)


def _audit_context(request, placements):
    context = _context(request, placements)
    inventory = {item["id"]: item for item in request["scene"]["inventory"]}
    by_id = {p["id"]: p for p in placements}
    to_wall = wall_basis(request["scene"]["angle_deg"]).T
    for pid, p in context.items():
        # Mounted points have face-local u/v. Use their actual world contacts
        # projected onto the wall for this audit's hand/foot descriptors.
        p["uv"] = (to_wall @ p["position"])[:2]
        item = inventory[by_id[pid]["inventory_id"]]
        contact = selected_contact(by_id[pid], item)
        diameters = sorted((2*radius for radius in contact.get("radii", [])), reverse=True)
        p["hand_match_allowed"] = (item["type"] in MATCHING_POLICY["allowed_types"] and
            item["width"] >= MATCHING_POLICY["min_hold_width_m"] and item["height"] >= MATCHING_POLICY["min_hold_height_m"] and
            len(diameters) == 2 and diameters[0] >= MATCHING_POLICY["min_selected_patch_major_diameter_m"] and
            diameters[1] >= MATCHING_POLICY["min_selected_patch_minor_diameter_m"] and {"LH", "RH"} <= set(p["limbs"]))
    return context


def _occupancy_error(context, key):
    """Role permission is not simultaneous capacity of one contact patch."""
    hands, feet = key[:2], key[2:]
    if set(hands) & set(feet): return "simultaneous_hand_foot_same_point"
    if feet[0] == feet[1]: return "simultaneous_feet_same_point"
    if hands[0] == hands[1] and not context[hands[0]]["hand_match_allowed"]:
        return "hand_match_not_supported_by_selected_patch"
    return None


def _setting_contact_corridor(context, contacts, body, solver):
    """A local 3-D search corridor, not a feasibility test.

    On a horizontal ceiling projected world height loses the progress axis:
    feet and hands may have the same height while being far apart in depth.
    Measure separation along the actual hand/foot centroid axis instead. The
    old upright corridor remains the declared grammar on non-roof structures.
    Every accepted state still needs the unchanged joint/contact and wall
    clearance checks. In particular this does not permit hooks or free feet.
    """
    from .full_route import _contact_valid
    if not any(p.get("inclination", 0.) > .85 for p in context.values()):
        return _contact_valid(context, contacts, body, solver)
    if not _valid_contact_geometry(context, contacts, body, solver):
        return False
    hands = np.array([context[contacts[l]["placement_id"]]["position"] for l in ("LH", "RH")])
    feet = np.array([context[contacts[l]["placement_id"]]["position"] for l in ("LF", "RF")])
    hand_mid, foot_mid = hands.mean(axis=0), feet.mean(axis=0)
    axis = hand_mid-foot_mid
    separation = float(np.linalg.norm(axis))
    arm = body["upper_arm"]+body["forearm"]
    leg = body["thigh"]+body["shin"]
    if not .45 < separation < body["torso"]+arm*.65+leg*.65:
        return False
    axis /= separation
    if abs(hands[0, 0]-hands[1, 0]) > arm*1.35 or abs(float((hands[0]-hands[1])@axis)) > arm*1.30:
        return False
    if abs(feet[0, 0]-feet[1, 0]) > leg*.95 or abs(float((feet[0]-feet[1])@axis)) > leg*.72:
        return False
    return abs(hand_mid[0]-foot_mid[0]) < leg*.65


def _round(value):
    if isinstance(value, dict): return {k: _round(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_round(v) for v in value]
    if isinstance(value, (float, np.floating)): return round(float(value), 5)
    return value


def orientation_support(context, contacts, moving_limb):
    """Describe support geometry; deliberately do not claim force equilibrium.

    The midpoint between hand and foot centroids is a nominal trunk location,
    not an IK centre of mass. A hand's declared pull is compared to its vector
    toward that location. The moving hand is excluded from retained support.
    """
    hands = [context[contacts[l]["placement_id"]] for l in ("LH", "RH")]
    feet = [context[contacts[l]["placement_id"]] for l in ("LF", "RF")]
    hand_mid = np.mean([p["position"] for p in hands], axis=0)
    foot_mid = np.mean([p["position"] for p in feet], axis=0)
    trunk = (hand_mid + foot_mid)/2
    alignments = {}
    lateral_pulls = []
    for limb in ("LH", "RH"):
        if limb == moving_limb: continue
        p = context[contacts[limb]["placement_id"]]
        direction = trunk-p["position"]
        denominator = float(np.linalg.norm(direction)*np.linalg.norm(p["pull"]))
        alignment = float(np.dot(direction, p["pull"])/denominator) if denominator > 1e-9 else 0.
        alignments[limb] = max(-1., min(1., alignment))
        norm = max(float(np.linalg.norm(p["pull"])), 1e-9)
        lateral_pulls.append(float(p["pull"][0])/norm)
    mismatch = sum((1-a)/2 for a in alignments.values())/max(1, len(alignments))
    # Trunk uses the pre-release nominal pose, but the support interval may
    # contain only retained feet. The moving foot cannot support its own step.
    footprint = [context[contacts[l]["placement_id"]]["position"][0] for l in ("LF", "RF") if l != moving_limb]
    outside = max(min(footprint)-trunk[0], trunk[0]-max(footprint), 0.)
    support_offset = min(1., float(outside)/.6)
    # Positive means two retained hand pulls have lateral opposition. A single
    # retained hand cannot receive an artificial opposition bonus.
    opposition = max(0., -lateral_pulls[0]*lateral_pulls[1]) if len(lateral_pulls) == 2 else 0.
    penalty = 12*mismatch+8*support_offset
    return {"retained_hand_pull_alignment": alignments, "pull_mismatch": mismatch,
            "retained_foot_count": len(footprint),
            "trunk_outside_foot_interval": support_offset, "lateral_opposition": opposition,
            "proxy_penalty": penalty, "basis": "nominal_trunk_and_declared_pull; not_force_equilibrium"}


def _step(request, context, before, limb, target, previous):
    after = dict(before, **{limb: _ref(target)})
    metrics = _metrics(request, context, before, limb, target)
    load, rest, recovery, burden = _history(previous, metrics, context, after)
    # Support before release matters even if the destination is an easy jug.
    support = orientation_support(context, before, limb)
    return after, load, metrics, rest, recovery, burden, support


def analyze_beta(request, candidate):
    context = _audit_context(request, candidate["placements"])
    states = {s["id"]: s for s in candidate["states"]}
    moves, load, hand_index = [], 0., 0
    for index, event in enumerate(candidate["events"]):
        limb = event["limb"]
        before = states[event["from_state"]]["contacts"]
        target = states[event["to_state"]]["contacts"][limb]["placement_id"]
        prior = load
        _, load, metrics, rest, recovery, burden, support = _step(request, context, before, limb, target, prior)
        moves.append({"event_index": index, "hand_move_index": hand_index, "phase_id": "independent-sequence", "phase_kind": "observed",
                      "limb": limb, "from_placement_id": before[limb]["placement_id"], "to_placement_id": target,
                      **metrics, "prior_load": prior, "accumulated_load": load, "rest_opportunity": rest,
                      "recovery_proxy": recovery, "fresh_burden": metrics["load"], "effective_burden": burden,
                      "burden": burden, "proxy_effort": burden+support["proxy_penalty"], "orientation_support": support})
        if limb.endswith("H"): hand_index += 1
    hands = [m for m in moves if m["limb"].endswith("H")]
    if not hands: raise ValueError("beta requires hand transfers")
    analysis = {"source": "synthetic_assumption", "model_version": MODEL_VERSION, "program": "independent_beta",
                "style_goal": "technical", "rhythm": "observed", "dimensions": {k: sum(m[k] for m in hands)/len(hands) for k in DIMS},
                "moves": moves, "phases": [], "summary": {"hand_moves": len(hands), "foot_moves": len(moves)-len(hands),
                "installed_holds": len(candidate["placements"]), "peak_strength": max(m["strength"] for m in hands),
                "peak_power": max(m["power"] for m in hands), "mean_technical": sum(m["technical"] for m in hands)/len(hands),
                "total_load": sum(m["load"] for m in moves), "peak_burden": max(m["burden"] for m in hands),
                "crux_event_index": max(hands, key=lambda m: m["burden"])["event_index"],
                "objective": sum(m["proxy_effort"] for m in moves), "load_variability": float(np.std([m["load"] for m in hands]))},
                "search": {"scope": "installed_geometry_without_phase_or_count_targets"}, "limitations": LIMITATIONS,
                "load_basis": "unvalidated_relative_proxy; orientation_support_is_not_force_equilibrium"}
    summary = {"hand_moves": len(hands), "foot_moves": len(moves)-len(hands), "transfers": len(moves),
               "total_proxy_effort": sum(m["proxy_effort"] for m in moves), "peak_proxy_burden": max(m["burden"] for m in hands), "final_load": load}
    return _round(analysis), _round(summary)


def _make_candidate(original, steps, objective):
    candidate = {k: copy.deepcopy(v) for k, v in original.items() if k not in ("search_metadata", "setting_report")}
    candidate.update(id=f"beta-{objective}-{original['id']}"[:120], name="更少换点" if objective == "fewer_transfers" else "较低模型负担",
                     parent_id=original["id"], revision=1, generator="rules", design_notes=LIMITATIONS)
    states = [{"id": "b0", "label": "相同起点", "contacts": copy.deepcopy(original["states"][0]["contacts"])}]
    events = []
    for index, (limb, pid) in enumerate(steps):
        before = states[-1]
        released = copy.deepcopy(before["contacts"]); released[limb] = None
        after = dict(released, **{limb: _ref(pid)})
        rid, tid = f"b{2*index+1}", f"b{2*index+2}"
        states.extend([{"id": rid, "label": f"{limb} 释放", "contacts": released}, {"id": tid, "label": f"{limb} → {pid}", "contacts": after}])
        events.append({"limb": limb, "from_state": before["id"], "release_state": rid, "to_state": tid})
    candidate.update(states=states, events=events)
    return candidate


def _used(candidate):
    return {ref["placement_id"] for state in candidate["states"] for ref in state["contacts"].values() if ref}


def _deletion_challenges(request, original, *, deadline=None):
    """A local counterexample search complements, never replaces, the beam."""
    context = _audit_context(request, original["placements"])
    sequence = [(event["limb"], original["states"][2*i+2]["contacts"][event["limb"]]["placement_id"]) for i, event in enumerate(original["events"])]
    original_analysis, _ = analyze_beta(request, original)
    crux_index = original_analysis["summary"]["crux_event_index"]
    candidates, rejected = [], Counter()
    for omitted in range(len(sequence)):
        if deadline is not None and time.perf_counter() >= deadline: break
        steps = sequence[:omitted]+sequence[omitted+1:]
        current = copy.deepcopy(original["states"][0]["contacts"])
        valid = True
        for limb, pid in steps:
            if current[limb]["placement_id"] == pid:
                rejected["no_op"] += 1; valid = False; break
            current[limb] = _ref(pid)
            occupancy = _occupancy_error(context, _key(current))
            if occupancy or not _valid_contact_geometry(context, current, request["body"], request["solver"]):
                rejected[occupancy or "necessary_contact_span"] += 1; valid = False; break
        if not valid: continue
        if any(ref is not None and current[limb] != ref for limb, ref in request["end_contacts"].items()):
            rejected["required_finish_contact"] += 1; continue
        alternate = _make_candidate(original, steps, "fewer_transfers")
        _, summary = analyze_beta(request, alternate)
        candidates.append((summary["total_proxy_effort"], omitted, steps))
    # Challenge the supposed crux directly, then the earliest removable move.
    # This makes the two-attempt scope explicit instead of hiding it as an
    # optimization result. Both still require independent full-path IK.
    candidates.sort(key=lambda entry: (entry[1] != crux_index, entry[1]))
    return [steps for _, _, steps in candidates[:2]], {"source": "bounded_single_transfer_deletion", "generated": len(candidates),
            "ordering": "original_crux_first_then_temporal", "challenged_crux_event_index": crux_index,
            "max_ik_candidates": 2, "ik_checked": 0, "rejected": dict(rejected), "time_budget_exhausted": deadline is not None and time.perf_counter() >= deadline}


def _search(request, original, objective, options, *, deadline=None):
    restrictions = constraint_errors(request, original["placements"], states=original["states"][:1])
    if restrictions:
        raise ValueError("; ".join(restrictions))
    context = _audit_context(request, original["placements"])
    start = _key(original["states"][0]["contacts"])
    goal = request["end_contacts"]["LH"]["placement_id"]
    top_y = context[goal]["uv"][1]
    arm = request["body"]["upper_arm"]+request["body"]["forearm"]
    leg = request["body"]["thigh"]+request["body"]["shin"]
    ordered = sorted(context, key=lambda p: (context[p]["key"], p))
    allowed = allowed_contact_ids(request, original["placements"])
    targets = {limb: [p for p in ordered if p in allowed[limb]] for limb in LIMBS}
    rejected = Counter()
    def remaining(key):
        # Ranking only, not an admissible optimality proof. Both hands must
        # reach TOP; feet need only remain compatible with the hand contacts.
        h = sum(max(0., top_y-context[key[i]]["uv"][1])/(arm*1.2) for i in (0, 1))
        f = sum(max(0., top_y-1.5-context[key[i]]["uv"][1])/(leg*.8) for i in (2, 3))
        return h+f
    beam = [(0., (), start, [], 0.)]
    seen = {start: [(0., 0.)]}
    completed, signatures = [], set()
    expanded = 0
    exhausted = False
    termination = "transfer_depth_limit"
    for depth in range(options["max_transfers"]):
        next_beam = []
        for cost, tie, key, steps, previous in beam:
            before = _contacts(key)
            for i, limb in enumerate(LIMBS):
                old = context[key[i]]
                for pid in targets[limb]:
                    if pid == key[i]: continue
                    dest = context[pid]
                    # Backtracking exists but stays within the declared local
                    # neighbourhood. The bound is a search limit, not physics.
                    if dest["uv"][1] < old["uv"][1]-(.35 if i < 2 else .25): continue
                    if np.linalg.norm(dest["position"]-old["position"]) > (arm*(2.8 if request.get("profile") == "setting" else 2.1) if i < 2 else leg*1.35): continue
                    if deadline is not None and time.perf_counter() >= deadline:
                        exhausted = True; termination = "shared_audit_time_budget"; break
                    if expanded >= options["max_expansions"]: exhausted = True; break
                    expanded += 1
                    changed = list(key); changed[i] = pid; changed = tuple(changed)
                    occupancy_error = _occupancy_error(context, changed)
                    if occupancy_error:
                        rejected[occupancy_error] += 1; continue
                    after = _contacts(changed)
                    if not _valid_contact_geometry(context, after, request["body"], request["solver"]):
                        rejected["necessary_contact_span"] += 1; continue
                    if request.get("profile") == "setting":
                        if not _setting_contact_corridor(context, after, request["body"], request["solver"]):
                            rejected["local_contact_corridor_search_assumption"] += 1; continue
                    _, load, metrics, rest, recovery, burden, support = _step(request, context, before, limb, pid, previous)
                    effort = burden+support["proxy_penalty"]
                    step_cost = 1.+effort*.0001 if objective == "fewer_transfers" else effort
                    next_cost = cost+step_cost
                    labels = seen.get(changed, [])
                    if any(c <= next_cost+1e-9 and l <= load+1e-9 for c, l in labels):
                        rejected["dominated_contacts_and_load"] += 1; continue
                    labels = [(c, l) for c, l in labels if not (next_cost <= c+1e-9 and load <= l+1e-9)]
                    labels.append((next_cost, load)); labels.sort()
                    seen[changed] = labels[:3]
                    new_steps = steps+[(limb, pid)]
                    new_tie = tie+((limb, context[pid]["key"], pid),)
                    entry = (next_cost, new_tie, changed, new_steps, load)
                    if changed[0] == goal and changed[1] == goal:
                        signature = tuple(new_steps)
                        if signature not in signatures:
                            completed.append(entry); signatures.add(signature)
                        continue
                    priority = next_cost+remaining(changed)*(1.3 if objective == "fewer_transfers" else 43.)
                    next_beam.append((priority, entry))
                if exhausted: break
            if exhausted: break
        next_beam.sort(key=lambda e: (round(e[0], 8), e[1][1]))
        rejected["beam_pruned"] += max(0, len(next_beam)-options["beam_width"])
        beam = [entry for _, entry in next_beam[:options["beam_width"]]]
        if exhausted:
            if termination != "shared_audit_time_budget": termination = "expansion_limit"
            break
        if not beam:
            termination = "frontier_empty"; break
        if objective == "fewer_transfers" and completed:
            termination = "first_complete_beam_depth"; break
        # Additional layers may find lower-effort longer paths, but have no
        # nonnegative-cost advantage once every frontier cost exceeds the best.
        if completed and min(e[0] for e in beam) >= min(e[0] for e in completed):
            termination = "retained_frontier_cost_bound"; break
    completed.sort(key=lambda e: (e[0], e[1]))
    return [e[3] for e in completed[:options["max_ik_candidates"]]], {
        "objective": objective, "expanded": expanded, "complete_sequences": len(completed),
        "budget_exhausted": exhausted or termination == "transfer_depth_limit", "termination_reason": termination,
        "rejected": dict(rejected), "depth_reached": depth+1}


def audit_beta(request, candidate, *, search_options=None):
    # Imported lazily to keep this module independent of the generator's import
    # graph. The standard evaluator, including its real IK budget, is reused.
    from .engine import canonical_hash, code_hash, evaluate, fingerprint, validate_request, _schema
    validate_request(request); _schema(candidate, "candidate")
    if request.get("profile") not in ("route", "setting"): raise ValueError("beta audit requires route or setting profile")
    if not all(request["start_contacts"].values()): raise ValueError("beta audit requires four starting contacts")
    state_map = {state["id"]: state for state in candidate["states"]}
    for event in candidate["events"]:
        before, after = state_map.get(event["from_state"]), state_map.get(event["to_state"])
        if before and after and before["contacts"][event["limb"]] == after["contacts"][event["limb"]]:
            raise ValueError("no-op release/regrab is not supported by beta audit")
    started = time.perf_counter()
    options = {"max_expansions": 26000, "beam_width": 48, "max_transfers": 30, "max_ik_candidates": 2, "timeout_seconds": 45}
    if search_options:
        if set(search_options)-set(options): raise ValueError("unknown beta search option")
        options.update(search_options)
    bounds = {"max_expansions": (1, 60000), "beam_width": (1, 128), "max_transfers": (1, 36), "max_ik_candidates": (1, 6), "timeout_seconds": (1, 45)}
    for name, (lo, hi) in bounds.items():
        if type(options[name]) is not int or not lo <= options[name] <= hi: raise ValueError(f"invalid beta search {name}")
    deadline = started+options["timeout_seconds"]
    original_eval = evaluate(request, candidate, deadline=deadline, include_design_analysis=False)
    invalid = [c for c in original_eval["checks"] if c["status"] == "fail"]
    if invalid: raise ValueError("original route failed structural/geometry checks: "+"; ".join(c["id"] for c in invalid))
    analysis, summary = analyze_beta(request, candidate)
    crux = max((m for m in analysis["moves"] if m["limb"].endswith("H")), key=lambda m: m["burden"])
    original_used = _used(candidate)
    report = {"schema_version": "beta-audit/1", "source": {"fingerprint": fingerprint(request, candidate),
              "candidate_id": candidate["id"], "revision": candidate["revision"], "code_hash": code_hash(), "audit_code_hash": audit_code_hash(),
              "geometry_hash": canonical_hash({"scene": request["scene"], "placements": candidate["placements"]})},
              "original": {"candidate": copy.deepcopy(candidate), "evaluation": original_eval, "analysis": analysis, "summary": summary,
                           "crux": {"event_index": crux["event_index"], "placement_id": crux["to_placement_id"], "from_placement_id": crux["from_placement_id"], "limb": crux["limb"], "burden": crux["burden"]}},
              "alternatives": [], "unverified_alternatives": [], "search": {"algorithm": "independent_installed_contact_beam_v1", **options,
              "expansion_limit": options["max_expansions"]*2, "expanded": 0, "complete_sequences": 0, "ik_checked": 0,
              "verified_alternatives": 0, "distinct_sequences": 0, "unverified_count": 0, "budget_exhausted": False, "objectives": [],
              "scope": "fixed_installed_geometry; no_phase_or_transfer_count_requirement; selected_surface_permissions",
              "matching_policy": {**MATCHING_POLICY, "allowed_hold_ids": sorted(pid for pid, point in _audit_context(request, candidate["placements"]).items() if point["hand_match_allowed"]) }}, "limitations": LIMITATIONS}
    old_sequence = [(event["limb"], candidate["states"][2*i+2]["contacts"][event["limb"]]["placement_id"]) for i, event in enumerate(candidate["events"])]
    def checked_entry(steps, objective, source):
        alternate = _make_candidate(candidate, steps, objective)
        alt_analysis, alt_summary = analyze_beta(request, alternate)
        improves = (alt_summary["transfers"] < summary["transfers"]) if objective == "fewer_transfers" else (alt_summary["total_proxy_effort"] < summary["total_proxy_effort"]-1e-6)
        if not improves: return None
        evaluation = evaluate(request, alternate, sequence_policy="independent_beta", deadline=deadline)
        report["search"]["ik_checked"] += 1
        alt_used = _used(alternate)
        entry = {"id": objective, "label": "更少换点" if objective == "fewer_transfers" else "较低模型负担", "objective": objective,
                 "search_source": source, "candidate": alternate, "evaluation": evaluation, "analysis": alt_analysis, "summary": alt_summary,
                 "skipped_hold_ids": sorted(original_used-alt_used),
                 "crux_bypass": {"original_hold_id": crux["to_placement_id"], "contacted": crux["to_placement_id"] in alt_used,
                                 "contacted_as_hand": any(s["contacts"][l] and s["contacts"][l]["placement_id"] == crux["to_placement_id"] for s in alternate["states"] for l in ("LH", "RH")),
                                 "original_transition_used": any(m["limb"] == crux["limb"] and m["from_placement_id"] == crux["from_placement_id"] and m["to_placement_id"] == crux["to_placement_id"] for m in alt_analysis["moves"]),
                                 "peak_reduced": alt_summary["peak_proxy_burden"] < summary["peak_proxy_burden"],
                                 "peak_delta": alt_summary["peak_proxy_burden"]-summary["peak_proxy_burden"]},
                 "comparison": {"transfers_delta": alt_summary["transfers"]-summary["transfers"], "hand_moves_delta": alt_summary["hand_moves"]-summary["hand_moves"],
                                "proxy_effort_delta": alt_summary["total_proxy_effort"]-summary["total_proxy_effort"],
                                "peak_burden_delta": alt_summary["peak_proxy_burden"]-summary["peak_proxy_burden"]}}
        return entry

    def retain(checked):
        if not checked: return
        selected = next((entry for entry in checked if entry["evaluation"]["summary"]["status"] == "pass"), checked[0])
        if selected["evaluation"]["summary"]["status"] == "pass":
            report["alternatives"].append(selected)
            report["search"]["verified_alternatives"] += 1
        report["unverified_alternatives"].extend(entry for entry in checked if entry["evaluation"]["summary"]["status"] != "pass")
        report["search"]["unverified_count"] = len(report["unverified_alternatives"])

    for objective in ("fewer_transfers", "lower_proxy_effort"):
        sequences, stats = _search(request, candidate, objective, options, deadline=deadline)
        report["search"]["objectives"].append(stats)
        for field in ("expanded", "complete_sequences"): report["search"][field] += stats[field]
        report["search"]["budget_exhausted"] |= stats["budget_exhausted"]
        checked = []
        for steps in sequences:
            if steps == old_sequence: continue
            entry = checked_entry(steps, objective, "independent_contact_beam")
            if entry is None: continue
            checked.append(entry)
            if entry["evaluation"]["summary"]["status"] == "pass": break
        retain(checked)
    if not report["alternatives"] and time.perf_counter() < deadline:
        sequences, stats = _deletion_challenges(request, candidate, deadline=deadline)
        report["search"]["deletion_challenge"] = stats
        checked = []
        for steps in sequences:
            entry = checked_entry(steps, "fewer_transfers", "bounded_single_transfer_deletion")
            if entry is None: continue
            stats["ik_checked"] += 1
            checked.append(entry)
            if entry["evaluation"]["summary"]["status"] == "pass": break
        retain(checked)
    report["status"] = "alternatives_found" if report["search"]["verified_alternatives"] else "no_verified_alternative"
    report["search"]["elapsed_ms"] = round((time.perf_counter()-started)*1000, 2)
    report["search"]["time_budget_exhausted"] = time.perf_counter() >= deadline
    report["search"]["budget_exhausted"] |= report["search"]["time_budget_exhausted"]
    report["search"]["distinct_sequences"] = len({tuple((event["limb"], entry["candidate"]["states"][2*i+2]["contacts"][event["limb"]]["placement_id"]) for i, event in enumerate(entry["candidate"]["events"])) for entry in report["alternatives"]})
    report["id"] = "beta-audit-"+canonical_hash({"source": report["source"], "options": options})[-16:]
    return _round(report)
