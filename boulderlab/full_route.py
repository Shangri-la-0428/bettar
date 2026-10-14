"""Longer synthetic boulder design: contact search, phase intent and load history.

All demand coefficients are transparent hypotheses, not measured physiology.
The candidate contains only holds used by its contact sequence. The shared pool
is a collection of possible installation positions, not a densely set route.
"""
from __future__ import annotations

import copy
import json
import math
from collections import Counter
from functools import lru_cache

import numpy as np

from .geometry import grip_surfaces
from .catalog import hold_taxonomy
from .route_design import DIMS, AFFORDANCES, _context, _metrics, _ref, _valid_contact_geometry

PROGRAMS = [
    {"id": "mixed_flow", "label": "混合节奏", "description": "建立 → 技术转换 → 力量难点 → 缓和 → 收尾。"},
    {"id": "power_finish", "label": "后段力量", "description": "连续推进与转换后，保留后段力量难点。"},
    {"id": "sustained_finish", "label": "持续收尾", "description": "前段难点与缓和后，连接连续输出。"},
]
MODEL_VERSION = "full-route-proxy-1"
LIMITATIONS = [
    "岩点属性、动作需求和负荷递推系数均为合成假设；不是实际抓力、疲劳、功率或攀爬等级。",
    "历史负荷参与动作选择；缓和机会来自当前手脚接触条件，不由阶段名称直接给予恢复。",
    "束搜索允许每次移手前 0–2 次脚调整及最终双手匹配 TOP；不是完整动作学或全局最优搜索。",
    "只生成 8、10、12 次移手的合成抱石路线；连续动力学、摩擦、平衡与真人试攀未验证。",
]
PHASES = {
    "establish": ("建立", (26, 31, 29, 37), (.25, .20, .20, .35)),
    "power": ("力量难点", (47, 57, 42, 61), (.34, .36, .10, .20)),
    "technical": ("技术转换", (36, 37, 62, 51), (.10, .10, .63, .17)),
    "relief": ("缓和", (23, 27, 28, 38), (.18, .12, .15, .55)),
    "sustained": ("持续输出", (39, 43, 44, 64), (.12, .13, .15, .60)),
    "finish": ("终点匹配", (20, 32, 27, 45), (.20, .20, .10, .50)),
}


def make_brief(program="mixed_flow", hand_moves=10):
    if program not in {p["id"] for p in PROGRAMS} or hand_moves not in (8, 10, 12):
        raise ValueError("route requires a known program and 8, 10 or 12 hand transfers")
    sequence = {"mixed_flow": ("establish", "technical", "power", "relief", "sustained"),
                "power_finish": ("establish", "sustained", "technical", "relief", "power"),
                "sustained_finish": ("establish", "power", "relief", "technical", "sustained")}[program]
    # TOP approach and matching are their own finish, not a promised hard
    # segment on a deliberately positive final hold. Allocate more actions to
    # the requested late work before those two finish transfers.
    counts = [1]*5
    priorities = {"mixed_flow": (2, 1, 4, 0, 3), "power_finish": (4, 2, 4, 1, 0),
                  "sustained_finish": (4, 1, 4, 3, 0)}[program]
    for extra in range(hand_moves-7): counts[priorities[extra % len(priorities)]] += 1
    expanded = [(segment, kind) for segment, (kind, count) in enumerate(zip(sequence, counts)) for _ in range(count)]
    expanded += [(5, "finish"), (5, "finish")]
    phases = []
    for index, (segment, kind) in enumerate(expanded):
        label, target, _ = PHASES[kind]
        phases.append({"id": f"move-{index+1}", "segment_id": f"segment-{segment+1}", "phase_kind": kind,
                       "label": label, "hand_move_index": index, "target": dict(zip(DIMS, target))})
    return {"program": program, "style_goal": "power" if program == "power_finish" else "sustained" if program == "sustained_finish" else "technical",
            "rhythm": "late_crux", "source": "synthetic_assumption", "search": {"beam_width": 24, "max_expansions": 60000}, "phases": phases}


def make_request(base_request, program="mixed_flow", hand_moves=10):
    req = copy.deepcopy(base_request)
    inventory, placements = [], []
    family_attrs = dict(AFFORDANCES, crimp=(.40, .89, .78, .34), pocket=(.57, .85, .58, .29))
    def add(pid, kind, x, y, rotation=0, top=False):
        width, height, depth = {"jug": (.18, .12, .075), "crimp": (.13, .065, .048),
                               "pinch": (.13, .16, .09), "sloper": (.22, .17, .10),
                               "pocket": (.17, .13, .075), "foothold": (.09, .055, .042)}[kind]
        if top: width, height = .34, .15
        attrs = dict(zip(("grip_accessibility", "precision", "force_demand", "friction_dependence"), family_attrs[kind]))
        item = {"id": pid, "type": kind, "width": width, "height": height, "depth": depth,
                "source": "synthetic_assumption", "template_id": f"route-{kind}", "template_name": f"标准研究模板 · {kind}",
                "pull_direction": [0, -1, 0], "contact": {"id": "main", "position": [0, 0, depth], "radius": .015,
                "limbs": ["LF", "RF"] if kind == "foothold" else ["LH", "RH"]},
                "design_attributes": {"source": "synthetic_assumption", **attrs}, "taxonomy": hold_taxonomy(kind)}
        item["grip_surfaces"] = grip_surfaces(item)
        inventory.append(item)
        placements.append({"id": pid, "inventory_id": pid, "u": round(x, 4), "v": round(y, 4), "rotation_deg": rotation, "contact_surface_id": "working"})
    # A gentle line across the wall, with alternatives on either side. The pool
    # is identical for every program and length, including inventory quantities.
    def center(y): return -.62 + .90*(y-1.12)/2.52 + .15*math.sin((y-1.12)*2.1)
    add("start-left", "jug", -.85, 1.12)
    add("start-right", "jug", -.43, 1.12)
    add("start-foot-left", "foothold", -.83, .35)
    add("start-foot-right", "foothold", -.43, .35)
    kinds = ("jug", "crimp", "pinch", "sloper", "pocket")
    for row in range(10):
        y = 1.38 + row*.225
        for col in range(3):
            kind = kinds[(row+col*2) % len(kinds)]
            add(f"hand-{row+1:02d}-{col+1}", kind, center(y)+(col-1)*.34, y,
                (-35 if col == 0 else 35 if col == 2 else 0) if kind in ("crimp", "pinch", "pocket") else 0)
    # Foot alternatives are placed between hand rows, with a narrow support
    # corridor. Actual installed subsets are checked for collision separately.
    for row in range(11):
        y = .57 + row*.205
        for col in range(3):
            add(f"foot-{row+1:02d}-{col+1}", "foothold", center(y+.85)+(col-1)*.29, y,
                -15 if col == 0 else 15 if col == 2 else 0)
    add("top", "jug", center(3.67), 3.67, top=True)
    add("finish-foot-left", "foothold", center(3.57)-.20, 2.77)
    add("finish-foot-right", "foothold", center(3.57)+.20, 2.77)
    req.update(id=f"request-route-{program}-{req['body']['id']}", profile="route", scenario="route_search", mode="free", hand_moves=hand_moves,
               reference_layout=placements, route_design=make_brief(program, hand_moves))
    req["scene"].update(width=4.8, height=4.2, inventory=inventory)
    req["start_contacts"] = dict(zip(("LH", "RH", "LF", "RF"), map(_ref, ("start-left", "start-right", "start-foot-left", "start-foot-right"))))
    req["end_contacts"] = {"LH": _ref("top"), "RH": _ref("top"), "LF": None, "RF": None}
    req["solver"]["root_bounds"] = [[-2.2, 2.2], [.35, 3.65], [.08, 3.0]]
    return req


def _history(previous, metrics, context, after):
    hands = [context[after[l]["placement_id"]]["attrs"] for l in ("LH", "RH")]
    access = sum(a["grip_accessibility"] for a in hands)/2
    grip = sum(a["force_demand"] for a in hands)/2
    # Relative release of effort only when both current hands and feet permit
    # it; labels and requested phase targets never enter this calculation.
    rest = max(0., (access-.65)/.35) * metrics["attributes"]["foot_support"] * (1-metrics["attributes"]["inclination"]) * max(0., 1-grip)
    recovery = previous*.24*rest
    accumulated = max(0., previous*.91 + metrics["load"]*.70 - recovery)
    burden = metrics["load"] + previous*.17
    return accumulated, rest, recovery, burden


def _contact_valid(context, contacts, body, solver=None):
    if not _valid_contact_geometry(context, contacts, body, solver): return False
    h = [context[contacts[l]["placement_id"]]["uv"] for l in ("LH", "RH")]
    f = [context[contacts[l]["placement_id"]]["uv"] for l in ("LF", "RF")]
    arm = body["upper_arm"]+body["forearm"]
    leg = body["thigh"]+body["shin"]
    # Local shape constraints remove ladder-wide splits and high feet. These
    # are explicit search assumptions; independent IK still decides each pose.
    if abs(h[0][0]-h[1][0]) > arm*1.35 or abs(h[0][1]-h[1][1]) > arm*1.30: return False
    if abs(f[0][0]-f[1][0]) > leg*.95 or abs(f[0][1]-f[1][1]) > leg*.72: return False
    if any(np.linalg.norm(a-b) > (arm+body["torso"]+leg)*.95 for a in h for b in f): return False
    hm, fm = np.mean(h, axis=0), np.mean(f, axis=0)
    return .45 < hm[1]-fm[1] < body["torso"]+arm*.65+leg*.65 and abs(hm[0]-fm[0]) < leg*.65


def _cost(metrics, phase, previous, burden):
    values = dict(metrics, load=burden)
    weights = PHASES[phase["phase_kind"]][2]
    return sum(w*((values[k]-phase["target"][k])/100)**2 for k, w in zip(DIMS, weights))


def _candidate(request, steps, index, metadata):
    states = [{"id": "s0", "label": "起始接触", "contacts": copy.deepcopy(request["start_contacts"])}]
    events = []
    for i, (limb, pid) in enumerate(steps):
        before = states[-1]
        release = copy.deepcopy(before["contacts"]); release[limb] = None
        after = copy.deepcopy(release); after[limb] = _ref(pid)
        rid, tid = f"s{2*i+1}", f"s{2*i+2}"
        states.extend([{"id": rid, "label": f"{limb} 释放", "contacts": release}, {"id": tid, "label": f"{limb} → {pid}", "contacts": after}])
        events.append({"limb": limb, "from_state": before["id"], "release_state": rid, "to_state": tid})
    used = {r["placement_id"] for s in states for r in s["contacts"].values() if r}
    label = next(p["label"] for p in PROGRAMS if p["id"] == request["route_design"]["program"])
    return {"id": f"candidate-route-{request['seed']}-{index+1}", "name": f"{label} · {index+1}", "revision": 1, "parent_id": None, "generator": "rules",
            "placements": [copy.deepcopy(p) for p in request["reference_layout"] if p["id"] in used], "states": states, "events": events,
            "search_metadata": metadata, "design_notes": ["只安装接触序列实际使用的岩点；其余实例保留在候选库。", *LIMITATIONS]}


def search_routes(request):
    return copy.deepcopy(_search_cached(json.dumps(request, sort_keys=True, separators=(",", ":"))))


@lru_cache(maxsize=16)
def _search_cached(serialized):
    request = json.loads(serialized)
    if not all(request["start_contacts"].values()):
        raise ValueError("完整线路需要四肢起始接触。")
    if any(request["end_contacts"][l] is not None for l in ("LF", "RF")):
        raise ValueError("完整线路终点脚点须留空，由搜索选择实际支撑。")
    context = _context(request, request["reference_layout"])
    order = sorted(context, key=lambda pid: (context[pid]["key"], pid))
    inventory = {h["id"]: h for h in request["scene"]["inventory"]}
    placement = {p["id"]: p for p in request["reference_layout"]}
    # Conservative flat footprints account for rotations; final 3-D SAT remains
    # independent. Skipped alternatives do not become phantom installed holds.
    radii = {}
    for pid, p in placement.items():
        item = inventory[p["inventory_id"]]; a = math.radians(p["rotation_deg"])
        radii[pid] = np.array([abs(math.cos(a))*item["width"]+abs(math.sin(a))*item["height"], abs(math.sin(a))*item["width"]+abs(math.cos(a))*item["height"]])/2
    conflicts = {pid: {q for q in order if q != pid and np.all(np.abs(context[pid]["uv"]-context[q]["uv"]) <= radii[pid]+radii[q]+.005)} for pid in order}
    starts = {r["placement_id"] for r in request["start_contacts"].values()}
    top = request["end_contacts"]["LH"]["placement_id"]
    start_y = sum(context[request["start_contacts"][l]["placement_id"]]["uv"][1] for l in ("LH", "RH"))/2
    top_y = context[top]["uv"][1]
    for key in ("start_contacts", "end_contacts"):
        if any(ref and limb not in context[ref["placement_id"]]["limbs"] for limb, ref in request[key].items()):
            raise ValueError("线路起终点必须允许指定手脚接触。")
    n, brief = request["hand_moves"], request["route_design"]
    width, limit = brief["search"]["beam_width"], brief["search"]["max_expansions"]
    # cost, tie, contacts, steps, load, installed. Full load is retained in each
    # entry; dedup includes a fine load bin and installed set, not contacts alone.
    beam = [(0., (), copy.deepcopy(request["start_contacts"]), [], 0., frozenset(starts))]
    expanded, rejected, exhausted, complete = 0, Counter(), False, 0
    for stage in range(n):
        next_beam = []
        target_y = start_y+(top_y-start_y)*(stage+1)/(n-1)
        for cost, tie, contacts, steps, load, used in beam:
            for hand in ("LH", "RH"):
                source = contacts[hand]["placement_id"]
                other = contacts["RH" if hand == "LH" else "LH"]["placement_id"]
                if source == top: continue
                if stage >= n-2:
                    options = [top]
                else:
                    options = [pid for pid in order if hand in context[pid]["limbs"] and pid not in starts and pid != top and
                               pid not in used and abs(context[pid]["uv"][1]-target_y) < .36 and
                               context[pid]["uv"][1] >= context[source]["uv"][1]-.08 and
                               np.linalg.norm(context[pid]["position"]-context[source]["position"]) < (request["body"]["upper_arm"]+request["body"]["forearm"])*1.95]
                    options.sort(key=lambda pid: (abs(context[pid]["uv"][1]-target_y), context[pid]["key"]))
                    options = options[:7]
                for hp in options:
                    if hp not in context or (hp in conflicts and used & conflicts[hp]): rejected["installed_overlap"] += 1; continue
                    # Candidate supports are chosen around the forthcoming hand
                    # midpoint. Moving zero, one or both feet is a real branch.
                    hmid = (context[hp]["uv"]+context[other]["uv"])/2
                    support_y = hmid[1]-.96
                    per_foot = {}
                    for foot in ("LF", "RF"):
                        fp = contacts[foot]["placement_id"]
                        options_f = [p for p in order if foot in context[p]["limbs"] and p != fp and p not in starts and
                                     context[p]["uv"][1] >= context[fp]["uv"][1]-.10 and abs(context[p]["uv"][1]-support_y) < .40 and
                                     np.linalg.norm(context[p]["position"]-context[fp]["position"]) < (request["body"]["thigh"]+request["body"]["shin"])*1.10 and
                                     abs(context[p]["uv"][0]-(hmid[0]+(-.18 if foot == "LF" else .18))) < .40 and
                                     not ((used | {hp}) & conflicts[p])]
                        options_f.sort(key=lambda p: (abs(context[p]["uv"][1]-support_y)+abs(context[p]["uv"][0]-(hmid[0]+(-.18 if foot == "LF" else .18)))*.5, context[p]["key"]))
                        per_foot[foot] = options_f[:2]
                    foot_branches = [[]]+[[(l, p)] for l in ("LF", "RF") for p in per_foot[l]]
                    foot_branches += [[("LF", l), ("RF", r)] for l in per_foot["LF"] for r in per_foot["RF"] if l != r]
                    foot_branches += [[("RF", r), ("LF", l)] for l in per_foot["LF"][:1] for r in per_foot["RF"][:1] if l != r]
                    for foot_steps in foot_branches:
                        if expanded >= limit: exhausted = True; break
                        expanded += 1
                        current, previous, new_used, valid = copy.deepcopy(contacts), load, set(used), True
                        for limb, pid in [*foot_steps, (hand, hp)]:
                            if pid in conflicts and new_used & conflicts[pid]: valid = False; break
                            after = dict(current, **{limb: _ref(pid)})
                            if after["LF"] == after["RF"] or not _contact_valid(context, after, request["body"], request["solver"]): valid = False; break
                            metrics = _metrics(request, context, current, limb, pid)
                            next_load, _, _, burden = _history(previous, metrics, context, after)
                            if limb == hand: hand_cost = _cost(metrics, brief["phases"][stage], previous, burden)
                            previous, current = next_load, after
                            new_used.add(pid)
                        if not valid: rejected["contact_geometry_or_overlap"] += 1; continue
                        if min(context[current[l]["placement_id"]]["uv"][1] for l in ("LH", "RH")) < min(target_y, top_y)-.65:
                            rejected["lagging_hand_progress"] += 1; continue
                        if stage == n-1 and not all(current[l] == request["end_contacts"][l] for l in ("LH", "RH")): rejected["finish_contacts"] += 1; continue
                        # Small travel/order costs avoid gratuitous shuffling;
                        # they do not replace the phase/history objective.
                        progress_cost = .018*((context[hp]["uv"][1]-min(target_y, top_y))/.35)**2
                        new_cost = cost+hand_cost+progress_cost+.003*len(foot_steps)
                        new_steps = steps+foot_steps+[(hand, hp)]
                        new_tie = tie+tuple((l, context[p]["key"]) for l, p in foot_steps+[(hand, hp)])
                        next_beam.append((new_cost, new_tie, current, new_steps, previous, frozenset(new_used)))
                    if exhausted: break
                if exhausted: break
            if exhausted: break
        next_beam.sort(key=lambda e: (round(e[0], 12), e[1]))
        seen, diverse = set(), []
        for entry in next_beam:
            signature = (tuple((l, entry[2][l]["placement_id"]) for l in ("LH", "RH", "LF", "RF")), round(entry[4]/2), entry[5])
            if signature in seen: rejected["same_contacts_inventory_load_bin"] += 1; continue
            seen.add(signature); diverse.append(entry)
        rejected["beam_pruned"] += max(0, len(diverse)-width)
        if stage == n-1: complete = len(diverse)
        beam = diverse[:width]
        if not beam or exhausted: break
    solutions = [entry for entry in beam if sum(l.endswith("H") for l, _ in entry[3]) == n and all(entry[2][l] == request["end_contacts"][l] for l in ("LH", "RH"))]
    selected, sequences = [], set()
    for entry in solutions:
        seq = tuple((l, p) for l, p in entry[3] if l.endswith("H"))
        if seq not in sequences: selected.append(entry); sequences.add(seq)
        if len(selected) >= request["budget"]: break
    for entry in solutions:
        if len(selected) >= request["budget"]: break
        if not any(entry is e for e in selected): selected.append(entry)
    if not selected:
        raise ValueError("完整线路搜索预算耗尽，未找到完整候选。" if exhausted else "当前库存、身材和阶段约束下未找到完整线路；不能据此断言无人可攀。")
    metadata = {"algorithm": "history_contact_beam_v1", "expanded": expanded, "expansion_limit": limit, "beam_width": width,
                "complete_sequences": complete, "returned_candidates": len(selected), "distinct_hand_sequences": len(sequences),
                "rejected": dict(sorted(rejected.items())), "budget_exhausted": exhausted, "history_state": "relative_load_bin_2_and_installed_inventory",
                "scope": "synthetic_phase_and_history_search; candidates_get_independent_P0_checks", "pool_count": len(placement), "seed_policy": "deterministic_design_search; seed_used_for_IK"}
    return [_candidate(request, e[3], i, metadata) for i, e in enumerate(selected)]


def analyze_route(request, candidate, initial_load=0.):
    context = _context(request, candidate["placements"])
    states = {s["id"]: s for s in candidate["states"]}
    brief = request["route_design"]
    if not math.isfinite(initial_load) or initial_load < 0:
        raise ValueError("initial_load must be finite and nonnegative")
    moves, load, hand_index, objective = [], float(initial_load), 0, 0.
    for index, event in enumerate(candidate["events"]):
        before = states[event["from_state"]]["contacts"]
        after = states[event["to_state"]]["contacts"]
        limb, target = event["limb"], after[event["limb"]]["placement_id"]
        metrics = _metrics(request, context, before, limb, target)
        phase = brief["phases"][min(hand_index, len(brief["phases"])-1)]
        prior = load
        load, rest, recovery, burden = _history(prior, metrics, context, after)
        if limb.endswith("H"): objective += _cost(metrics, phase, prior, burden)
        moves.append({"event_index": index, "hand_move_index": hand_index, "phase_id": phase["segment_id"], "phase_kind": phase["phase_kind"],
                      "limb": limb, "from_placement_id": before[limb]["placement_id"], "to_placement_id": target,
                      **metrics, "prior_load": prior, "accumulated_load": load, "rest_opportunity": rest, "recovery_proxy": recovery,
                      "fresh_burden": metrics["load"], "effective_burden": burden, "burden": burden, "phase_target": phase["target"]})
        if limb.endswith("H"): hand_index += 1
    hands = [m for m in moves if m["limb"].endswith("H")]
    if not hands: raise ValueError("route analysis needs hand transfers")
    phases = []
    for phase in brief["phases"]:
        if any(p["id"] == phase["segment_id"] for p in phases): continue
        group = [m for m in moves if m["phase_id"] == phase["segment_id"]]
        gh = [m for m in group if m["limb"].endswith("H")]
        if not gh: continue
        phases.append({"id": phase["segment_id"], "label": phase["label"], "phase_kind": phase["phase_kind"], "event_start": group[0]["event_index"], "event_end": group[-1]["event_index"],
                       "hand_move_start": gh[0]["hand_move_index"], "hand_move_end": gh[-1]["hand_move_index"], "target": {k: sum(m["phase_target"][k] for m in gh)/len(gh) for k in DIMS},
                       "estimate": {key: sum(m["burden"] if key == "load" else m[key] for m in gh)/len(gh) for key in DIMS},
                       "entry_load": group[0]["prior_load"], "exit_load": group[-1]["accumulated_load"], "rest_opportunity": sum(m["rest_opportunity"] for m in group)/len(group), "load_basis": "contextual_burden"})
    search = {"reproduced_for_current_route": False, "scope": "current_route_not_reproduced_by_generator"}
    try:
        for generated in search_routes(request):
            if generated["placements"] == candidate["placements"] and [s["contacts"] for s in generated["states"]] == [s["contacts"] for s in candidate["states"]]:
                search = dict(generated["search_metadata"], reproduced_for_current_route=True); break
    except (ValueError, KeyError, TypeError): pass
    late = hands[-max(1, math.ceil(len(hands)/3)):]
    fresh_peak, loaded_peak = max(m["fresh_burden"] for m in hands), max(m["burden"] for m in hands)
    result = {"source": "synthetic_assumption", "model_version": MODEL_VERSION, "program": brief["program"], "style_goal": brief["style_goal"], "rhythm": brief["rhythm"],
              "dimensions": {k: sum(m[k] for m in hands)/len(hands) for k in DIMS}, "moves": moves, "phases": phases,
              "summary": {"peak_strength": max(m["strength"] for m in hands), "peak_power": max(m["power"] for m in hands), "mean_technical": sum(m["technical"] for m in hands)/len(hands),
                          "total_load": sum(m["load"] for m in moves), "peak_burden": loaded_peak, "crux_event_index": max(hands, key=lambda m: m["burden"])["event_index"], "objective": objective,
                          "load_variability": float(np.std([m["load"] for m in hands])), "hand_moves": len(hands), "foot_moves": len(moves)-len(hands), "installed_holds": len(candidate["placements"])},
              "history_comparison": {"fresh_peak": fresh_peak, "with_history_peak": loaded_peak, "delta": loaded_peak-fresh_peak, "late_move_delta": sum(m["burden"]-m["fresh_burden"] for m in late)/len(late),
                                     "initial_load": initial_load, "source": "same_sequence_counterfactual_zero_prior_load", "description": "同一动作序列：每次动作前负荷清零，对比保留真实前序模型状态；非真人实验。"},
              "search": search, "limitations": LIMITATIONS, "load_basis": "fresh_burden: isolated_action; effective_burden: action_plus_prior_load; accumulated_load: relative_state"}
    def rounded(value):
        if isinstance(value, dict): return {k: rounded(v) for k, v in value.items()}
        if isinstance(value, list): return [rounded(v) for v in value]
        if isinstance(value, (float, np.floating)): return round(float(value), 5)
        return value
    return rounded(result)
