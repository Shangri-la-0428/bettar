"""Bounded contact-sequence search with explicit, uncalibrated design proxies.

A hold has affordance assumptions, not a grade. Contextual movement demand and
history-dependent burden are distinct. Nothing here solves force or dynamics.
"""
from __future__ import annotations

import copy
import math
from collections import Counter
from itertools import combinations
from .kinematics import contact_distance_bound

import numpy as np

from .geometry import contact_world, grip_surfaces, placement_frames, selected_contact, wall_basis

MODEL_VERSION = "style-proxy-2"
STYLE_GOALS = [
    {"id": "power", "label": "力量与爆发倾向", "description": "偏向较长移手和较高握持要求，安排局部难点。"},
    {"id": "sustained", "label": "持续输出", "description": "偏向连续、相近的动作负荷，减少明显缓和段。"},
    {"id": "technical", "label": "精细与转换", "description": "偏向方向适配、精细接触和脚点选择。"},
]
RHYTHMS = [
    {"id": "early_crux", "label": "前段难点 → 缓和"},
    {"id": "late_crux", "label": "铺垫 → 后段难点"},
    {"id": "sustained", "label": "连续输出"},
]
DIMS = ("strength", "power", "technical", "load")
# Declarative affordance hypotheses; coefficients are deliberately not learned grades.
AFFORDANCES = {
    "jug": (.88, .18, .20, .20),
    "crimp": (.40, .89, .78, .34),
    "pocket": (.57, .85, .58, .29),
    "directional_edge": (.44, .88, .72, .38),
    "sloper": (.46, .45, .70, .92),
    "pinch": (.58, .60, .62, .55),
    "rail": (.71, .38, .42, .40),
    "foothold": (.70, .65, .15, .35),
    "volume": (.60, .48, .42, .65),
}
LIMITATIONS = [
    "0–100 为未标定的设计模型指数，不是岩点难度、真实力/功率或 V 等级。",
    "累积负荷是有序动作的相对状态量；缓和机会不等于实际恢复百分比。",
    "搜索限制为四次手移动、每次之前一次换脚；束剪枝会合并不同负荷历史，不是穷举或全局最优解。",
    "接触、受力、摩擦、平衡、动态转换、读线智力和真人体验仍未验证。",
]


def _ref(pid):
    return {"placement_id": pid, "contact_id": "main"}


def make_brief(goal="power", rhythm="late_crux"):
    if goal not in {s["id"] for s in STYLE_GOALS} or rhythm not in {r["id"] for r in RHYTHMS}:
        raise ValueError("unknown style_goal/rhythm")
    bases = {"power": (64, 60, 40, 55), "sustained": (52, 38, 38, 59), "technical": (48, 43, 72, 48)}
    factors = {"early_crux": (1.22, 1.08, .78, .64), "late_crux": (.68, .86, 1.12, 1.26), "sustained": (1, 1, 1, 1)}[rhythm]
    labels = {"early_crux": ("进入难点", "延续", "转换", "缓和收尾"), "late_crux": ("建立", "铺垫", "进入难点", "难点收尾"), "sustained": ("建立输出", "连续输出", "延续负荷", "持续收尾")}[rhythm]
    return {"style_goal": goal, "rhythm": rhythm, "source": "synthetic_assumption",
            "search": {"beam_width": 128, "max_expansions": 16000},
            "phases": [{"id": f"phase-{i+1}", "label": labels[i], "hand_move_index": i,
                        "target": {k: round(min(95, value*factors[i]), 2) for k, value in zip(DIMS, bases[goal])}}
                       for i in range(4)]}


def make_request(base_request, goal="power", rhythm="late_crux"):
    req = copy.deepcopy(base_request)
    # Coordinates specify the shared experiment wall, never a desired solution.
    specs = [("jug", -.28, 1.50, 0, .17, .12), ("jug", .28, 1.50, 0, .17, .12)]
    specs += [(kind, x, y, rotation, width, height) for y, row in [
        (1.76, [("jug", -.62, 0, .17, .12), ("directional_edge", -.20, 60, .13, .08), ("pinch", .20, -22, .14, .17), ("sloper", .62, 0, .23, .18)]),
        (1.98, [("sloper", -.62, 0, .23, .18), ("pinch", -.20, 28, .14, .17), ("directional_edge", .20, -65, .13, .08), ("jug", .62, 0, .17, .12)]),
    ] for kind, x, rotation, width, height in row]
    specs += [("rail", -.27, 2.24, -12, .22, .10), ("rail", .27, 2.24, 12, .22, .10)]
    specs += [("foothold", x, y, rotation, width, .065) for x, y, rotation, width in [
        (-.22, .52, 0, .10), (.22, .52, 0, .10),
        (-.52, .73, -30, .09), (-.17, .77, 0, .12), (.17, .77, 32, .07), (.52, .73, 0, .10),
        (-.42, .92, -38, .07), (-.06, .94, 0, .12), (.34, .94, 30, .08),
        (-.20, 1.10, 0, .10), (.23, 1.10, 0, .10),
    ]]
    inventory, placements = [], []
    for i, (kind, x, y, rotation, width, height) in enumerate(specs):
        pid = f"board-{i+1:02d}"
        depth = .045 if kind == "foothold" else {"sloper": .105, "pinch": .09}.get(kind, .07)
        values = AFFORDANCES[kind]
        attrs = dict(zip(("grip_accessibility", "precision", "force_demand", "friction_dependence"), values))
        if kind == "foothold":
            attrs["precision"] = round(1-width/.20, 3)
            attrs["grip_accessibility"] = round(width/.14, 3)
        item = {"id": pid, "type": kind, "width": width, "height": height, "depth": depth,
                "template_id": f"study-{kind}-{width}", "template_name": f"研究模板 · {kind}",
                "source": "synthetic_assumption", "pull_direction": [0, -1, 0],
                "contact": {"id": "main", "position": [0, 0, depth], "radius": .015,
                            "limbs": ["LF", "RF"] if kind == "foothold" else ["LH", "RH"]},
                "design_attributes": {"source": "synthetic_assumption", **attrs}}
        item["grip_surfaces"] = grip_surfaces(item)
        inventory.append(item)
        placements.append({"id": pid, "inventory_id": pid, "u": x, "v": y, "rotation_deg": rotation, "contact_surface_id": "working"})
    req.update(id=f"request-style-{goal}-{req['body']['id']}", profile="style", scenario="style_search", mode="fixed", hand_moves=4,
               reference_layout=placements, route_design=make_brief(goal, rhythm))
    req["scene"]["inventory"] = inventory
    req["start_contacts"] = dict(zip(("LH", "RH", "LF", "RF"), map(_ref, ("board-01", "board-02", "board-13", "board-14"))))
    req["end_contacts"] = dict(zip(("LH", "RH", "LF", "RF"), map(_ref, ("board-11", "board-12", "board-22", "board-23"))))
    # Roots still stay in front of the wall at 40 degrees; joint bounds unchanged.
    req["solver"]["root_bounds"][2] = [.08, 2.4]
    return req


def _clip(value):
    return max(0., min(1., float(value)))


def _context(request, placements):
    inventory = {h["id"]: h for h in request["scene"]["inventory"]}
    frames = placement_frames(placements, inventory, request["scene"]["angle_deg"], request["scene"].get("wall_panels"))
    out = {}
    for p in placements:
        item = inventory[p["inventory_id"]]
        contact = selected_contact(p, item)
        attrs = item.get("design_attributes", dict(zip(("grip_accessibility", "precision", "force_demand", "friction_dependence"), AFFORDANCES[item["type"]])))
        pull = np.asarray(contact.get("pull_direction", item.get("pull_direction", [0, -1, 0])), float)
        _, rot = frames[p["id"]]
        out[p["id"]] = {"position": contact_world(request, p, item, placements, frames), "uv": np.array([p["u"], p["v"]]),
                         "attrs": attrs, "limbs": contact["limbs"], "pull": rot @ pull,
                         "normal": rot @ np.asarray(contact.get("normal", [0., 0., 1.]), float),
                         "key": (p["v"], p["u"], p["rotation_deg"], item["type"], item["width"], item["height"], item["depth"])}
        if request["scene"].get("wall_panels"):
            out[p["id"]]["uv"] = (wall_basis(request["scene"]["angle_deg"]).T @ out[p["id"]]["position"])[:2]
            out[p["id"]]["inclination"] = max(0., min(1., -float(rot[1, 2])))
    return out


def _metrics(request, context, before, limb, target):
    source = before[limb]["placement_id"]
    old, dest = context[source], context[target]
    delta = dest["position"]-old["position"]
    arm = request["body"]["upper_arm"]+request["body"]["forearm"]
    span = float(np.linalg.norm(delta))/arm
    inclination = math.sin(math.radians(request["scene"]["angle_deg"]))
    if request["scene"].get("wall_panels"):
        contact_ids = [ref["placement_id"] for key, ref in before.items() if key.endswith("H") and ref and key != limb]
        if limb.endswith("H"): contact_ids.append(target)
        inclination = sum(context[pid]["inclination"] for pid in contact_ids)/max(1, len(contact_ids))
    others = {l: context[r["placement_id"]] for l, r in before.items() if r and l != limb}
    feet = [p for l, p in others.items() if l.endswith("F")]
    # A down-facing roof tread is not the same standing/recovery opportunity
    # as the same foothold facing upward. This is a gravity-aware proxy only;
    # the separate contact-cone solver still decides actual equilibrium.
    # Hand/foot hooks and active tension are outside this contact grammar.
    standing = [max(0., min(1., float(p["normal"][1]))) if "normal" in p else 1. for p in feet]
    foot_support = sum(p["attrs"]["grip_accessibility"]*factor for p, factor in zip(feet, standing))/2
    attrs = dest["attrs"]
    supporting_hands = [p for l, p in others.items() if l.endswith("H")]
    supporting_hand_demand = sum(p["attrs"]["force_demand"] for p in supporting_hands)/max(1, len(supporting_hands))
    support_precision = sum(p["attrs"]["precision"] for p in feet)/max(1, len(feet))
    # Declared pull orientation relative to gravity is a design descriptor,
    # never a solved contact force or opposition to the supporting hand.
    pull = dest["pull"]
    pull_norm = max(float(np.linalg.norm(pull)), 1e-8)
    vertical_pull = _clip(-pull[1]/pull_norm)
    direction = 1-vertical_pull
    hand = limb.endswith("H")
    foot_mid = np.mean([p["uv"] for p in feet], axis=0) if feet else old["uv"]
    lateral = _clip(abs(dest["uv"][0]-foot_mid[0])/.80)
    support = _clip(foot_support*(1-.32*lateral))
    strength = _clip(.30*attrs["force_demand"]+.17*(1-attrs["grip_accessibility"])+.17*inclination+.12*(1-support)+.09*direction+.15*supporting_hand_demand)
    power = _clip(.55*min(span/1.8, 1)+.18*inclination+.17*lateral+.10*direction)
    technical = _clip(.35*attrs["precision"]+.22*direction+.15*lateral+.13*(1-support)+.15*support_precision)
    load = _clip(.49*strength+.24*power+.17*technical+.10*inclination)
    if not hand:
        strength, power, technical, load = strength*.38, power*.45, technical*.85, load*.42
    return {"strength": strength*100, "power": power*100, "technical": technical*100, "load": load*100,
            "attributes": {"span_ratio": span, "grip_accessibility": attrs["grip_accessibility"], "precision": attrs["precision"],
                           "foot_support": support, "inclination": inclination, "directional_demand": direction,
                           "standing_foot_support": sum(standing)/2,
                           "friction_dependence": attrs["friction_dependence"], "supporting_hand_demand": supporting_hand_demand,
                           "support_precision": support_precision}}


def _advance_load(previous, metrics):
    # Retention is demand-sensitive; changing order changes later burden.
    retention = .72+.22*metrics["load"]/100
    return previous*retention+metrics["load"]


def _cost(metrics, target, goal, accumulated):
    weights = {"power": (.24, .42, .10, .24), "sustained": (.12, .13, .10, .65), "technical": (.12, .13, .60, .15)}[goal]
    # A later action is evaluated in its prior-load context, not an unordered sum.
    contextual = dict(metrics, load=min(100, metrics["load"]+.12*accumulated))
    return sum(weight*((contextual[key]-target[key])/100)**2 for key, weight in zip(DIMS, weights))


def _valid_contact_geometry(context, contacts, body, solver=None):
    points = {limb: context[ref["placement_id"]]["position"] for limb, ref in contacts.items() if ref}
    solver = solver or {}
    tolerance = solver.get("contact_tolerance_m", 0.)
    epsilon = solver.get("epsilon_geometry_m", 0.)
    return all(np.linalg.norm(points[a]-points[b]) <= contact_distance_bound(body,a,b,tolerance)+epsilon
               for a,b in combinations(points,2))


def _candidate(request, steps, index, metadata):
    states = [{"id": "s0", "label": "起始接触", "contacts": copy.deepcopy(request["start_contacts"])}]
    events = []
    for i, (limb, pid) in enumerate(steps):
        before = states[-1]
        release = copy.deepcopy(before["contacts"])
        release[limb] = None
        after = copy.deepcopy(release)
        after[limb] = _ref(pid)
        rid, tid = f"s{2*i+1}", f"s{2*i+2}"
        states.extend([{"id": rid, "label": f"{limb} 释放", "contacts": release}, {"id": tid, "label": f"{limb} → {pid}", "contacts": after}])
        events.append({"limb": limb, "from_state": before["id"], "release_state": rid, "to_state": tid})
    label = next(g["label"] for g in STYLE_GOALS if g["id"] == request["route_design"]["style_goal"])
    return {"id": f"candidate-style-{request['seed']}-{index+1}", "name": f"{label} · {index+1}", "revision": 1, "parent_id": None, "generator": "rules",
            "placements": copy.deepcopy(request["reference_layout"]), "states": states, "events": events,
            "search_metadata": copy.deepcopy(metadata), "design_notes": ["同一固定墙面、起终点和身材下搜索选点与换手换脚顺序。", *LIMITATIONS]}


def search_routes(request):
    """Deterministic beam search. No hold ID encodes movement role or priority."""
    brief = request["route_design"]
    context = _context(request, request["reference_layout"])
    ordered = sorted(context, key=lambda pid: (context[pid]["key"], pid))
    anchors = {r["placement_id"] for key in ("start_contacts", "end_contacts") for r in request[key].values() if r}
    # Beam entry: objective, canonical geometric tie key, contacts, counts, steps, accumulated load.
    beam = [(0., (), copy.deepcopy(request["start_contacts"]), Counter(), [], 0.)]
    expanded, rejected, truncated = 0, Counter(), False
    complete_count = 0
    limit = brief["search"]["max_expansions"]
    width = brief["search"]["beam_width"]
    for stage in range(4):
        next_beam = []
        for cost, tie, contacts, counts, steps, accumulated in beam:
            for hand in ("LH", "RH"):
                if counts[hand] >= 2:
                    continue
                hand_end = request["end_contacts"][hand]["placement_id"]
                hand_options = [hand_end] if counts[hand] == 1 else [p for p in ordered if hand in context[p]["limbs"] and p not in anchors]
                for hp in hand_options:
                    if hp not in context or context[hp]["uv"][1] <= context[contacts[hand]["placement_id"]]["uv"][1]+.015 or context[hp]["uv"][1] > context[hand_end]["uv"][1]+.01:
                        rejected["nonprogressing_hand"] += 1
                        continue
                    for foot in ("LF", "RF"):
                        if counts[foot] >= 2:
                            continue
                        foot_end = request["end_contacts"][foot]["placement_id"]
                        foot_options = [foot_end] if counts[foot] == 1 else [p for p in ordered if foot in context[p]["limbs"] and p not in anchors]
                        for fp in foot_options:
                            if expanded >= limit:
                                truncated = True
                                break
                            expanded += 1
                            if fp not in context or context[fp]["uv"][1] <= context[contacts[foot]["placement_id"]]["uv"][1]+.015 or context[fp]["uv"][1] > context[foot_end]["uv"][1]+.01:
                                rejected["nonprogressing_foot"] += 1
                                continue
                            after_foot = dict(contacts, **{foot: _ref(fp)})
                            after_hand = dict(after_foot, **{hand: _ref(hp)})
                            if any(len({r["placement_id"] for l, r in state.items() if l.endswith(pair)}) != 2 for state in (after_foot, after_hand) for pair in ("H", "F")):
                                rejected["duplicate_contact"] += 1
                                continue
                            if not _valid_contact_geometry(context, after_foot, request["body"], request["solver"]) or not _valid_contact_geometry(context, after_hand, request["body"], request["solver"]):
                                rejected["necessary_geometry"] += 1
                                continue
                            fm = _metrics(request, context, contacts, foot, fp)
                            middle_load = _advance_load(accumulated, fm)
                            hm = _metrics(request, context, after_foot, hand, hp)
                            next_load = _advance_load(middle_load, hm)
                            next_cost = cost+_cost(hm, brief["phases"][stage]["target"], brief["style_goal"], middle_load)
                            next_counts = counts.copy(); next_counts.update((hand, foot))
                            next_tie = tie+((foot, context[fp]["key"]), (hand, context[hp]["key"]))
                            next_beam.append((next_cost, next_tie, after_hand, next_counts, steps+[(foot, fp), (hand, hp)], next_load))
                        if truncated: break
                    if truncated: break
                if truncated: break
            if truncated: break
        next_beam.sort(key=lambda entry: (round(entry[0], 12), entry[1]))
        # Keep multiple contact selections, not 48 equivalent foot-order variants.
        signatures, diverse = set(), []
        for entry in next_beam:
            signature = (tuple(sorted((l, r["placement_id"]) for l, r in entry[2].items())), tuple(sorted(entry[3].items())))
            if signature in signatures:
                rejected["beam_duplicate_state"] += 1
                continue
            signatures.add(signature)
            diverse.append(entry)
        if stage == 3:
            # End contacts are identical by design; retain full distinct sequences.
            diverse = next_beam
            complete_count = len(diverse)
        rejected["beam_pruned"] += max(0, len(diverse)-width)
        beam = diverse[:width]
        if truncated or not beam:
            break
    solutions = [entry for entry in beam if len(entry[4]) == 8 and entry[2] == request["end_contacts"]]
    # Select genuinely different intermediate hand choices before feet-only variants.
    selected, hand_signatures = [], set()
    for entry in solutions:
        signature = tuple((limb, pid) for limb, pid in entry[4] if limb.endswith("H"))
        if signature in hand_signatures: continue
        selected.append(entry); hand_signatures.add(signature)
        if len(selected) >= request["budget"]: break
    for entry in solutions:
        if len(selected) >= request["budget"]: break
        if not any(entry is previous for previous in selected): selected.append(entry)
    if not selected:
        reason = "搜索预算耗尽，未找到完整候选；不能据此断言无线可攀。" if truncated else "当前四次移手与换脚语法内未找到完整候选；请调整起终点或可用岩点。"
        raise ValueError(reason)
    metadata = {"algorithm": "bounded_contact_beam_v1", "expanded": expanded, "expansion_limit": limit, "beam_width": width,
                "complete_sequences": complete_count, "returned_candidates": len(selected), "distinct_hand_sequences": len(hand_signatures),
                "rejected": dict(sorted(rejected.items())), "budget_exhausted": truncated,
                "scope": "cheap_geometry_and_design_objective; returned_candidates_get_independent_P0_checks",
                "seed_policy": "recorded_for_IK; design_search_order_is_deterministic"}
    return [_candidate(request, entry[4], i, metadata) for i, entry in enumerate(selected)]


def analyze_route(request, candidate):
    """Recompute all estimates from current geometry/sequence; ignore supplied scores."""
    if request.get("profile") != "style":
        return None
    brief = request["route_design"]
    context = _context(request, candidate["placements"])
    states = {state["id"]: state for state in candidate["states"]}
    accumulated, moves, hand_index = 0., [], 0
    objective = 0.
    for index, event in enumerate(candidate["events"]):
        before = states[event["from_state"]]["contacts"]
        after = states[event["to_state"]]["contacts"]
        limb = event["limb"]
        target = after[limb]["placement_id"]
        metrics = _metrics(request, context, before, limb, target)
        phase = brief["phases"][min(hand_index, 3)]
        previous_load = accumulated
        accumulated = _advance_load(accumulated, metrics)
        if limb.endswith("H"):
            objective += _cost(metrics, phase["target"], brief["style_goal"], previous_load)
        moves.append({"event_index": index, "hand_move_index": hand_index, "phase_id": phase["id"], "limb": limb,
                      "from_placement_id": before[limb]["placement_id"], "to_placement_id": target,
                      **metrics, "accumulated_load": accumulated, "phase_target": phase["target"],
                      "burden": metrics["load"]+.12*previous_load})
        if limb.endswith("H"): hand_index += 1
    hand_moves = [m for m in moves if m["limb"].endswith("H")]
    if not hand_moves: raise ValueError("style analysis needs hand transfers")
    phases = []
    for phase in brief["phases"]:
        group = [m for m in moves if m["phase_id"] == phase["id"]]
        if not group: continue
        hands = [m for m in group if m["limb"].endswith("H")] or group
        phases.append({"id": phase["id"], "label": phase["label"], "event_start": group[0]["event_index"], "event_end": group[-1]["event_index"],
                       "target": phase["target"], "estimate": {key: sum(min(100, m["burden"]) if key == "load" else m[key] for m in hands)/len(hands) for key in DIMS},
                       "load_basis": "contextual_burden_capped_100"})
    # Generation statistics are reproduced, never trusted from an imported candidate.
    search = {"scope": "current_route_not_reproduced_by_generator", "reproduced_for_current_route": False}
    try:
        generated = search_routes(request)
        same_placements = sorted(candidate["placements"], key=lambda p: p["id"]) == sorted(request["reference_layout"], key=lambda p: p["id"])
        contact_chain = [state["contacts"] for state in candidate["states"]]
        if same_placements and any(contact_chain == [state["contacts"] for state in c["states"]] for c in generated):
            search = dict(generated[0]["search_metadata"], reproduced_for_current_route=True)
    except (ValueError, KeyError, TypeError):
        pass
    # Scores remain target-independent; only objective measures agreement to intent.
    analysis = {"source": "synthetic_assumption", "model_version": MODEL_VERSION, "style_goal": brief["style_goal"], "rhythm": brief["rhythm"],
                "dimensions": {key: sum(m[key] for m in hand_moves)/len(hand_moves) for key in DIMS},
                "moves": moves, "phases": phases,
                "summary": {"peak_strength": max(m["strength"] for m in hand_moves), "peak_power": max(m["power"] for m in hand_moves),
                            "mean_technical": sum(m["technical"] for m in hand_moves)/len(hand_moves), "total_load": sum(m["load"] for m in moves),
                            "peak_burden": max(m["burden"] for m in moves), "crux_event_index": max(moves, key=lambda m: m["burden"])["event_index"],
                            "objective": objective, "load_variability": float(np.std([m["load"] for m in hand_moves]))}, "limitations": LIMITATIONS,
                "search": search, "load_basis": "dimensions_and_moves: single_move; phases: contextual_burden; accumulated_load: relative_state"}
    # JSON-stable rounding also keeps the UI honest about proxy precision.
    def rounded(value):
        if isinstance(value, dict): return {key: rounded(v) for key, v in value.items()}
        if isinstance(value, list): return [rounded(v) for v in value]
        if isinstance(value, (float, np.floating)): return round(float(value), 5)
        return value
    return rounded(analysis)
