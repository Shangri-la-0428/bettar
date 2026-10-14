"""Bounded geometry / independent-beta co-design; no force or dynamics claim.

The search never takes a phase, an ordered list of required holds, or an exact
hand count. Authored seeds are spatial arrangements, not prescribed betas.
"""
from __future__ import annotations
import copy
import json
import math
import time
from functools import lru_cache
import numpy as np
from .catalog import hold_taxonomy
from .geometry import grip_surfaces
from .route_design import AFFORDANCES, _ref

MODEL_VERSION = "geometry-beta-statics-codesign-3"
PROGRAMS = [
 {"id":"diagonal_balance", "label":"斜向移重", "description":"斜向手点与错开的脚点，引出横向移重和换脚。"},
 {"id":"opposing_sidepulls", "label":"对向侧拉", "description":"两侧朝内的抓握方向与支撑脚联动，允许不同换手顺序。"},
 {"id":"roof_exit", "label":"仰角转出", "description":"较差中段抓握连接较好上段，把出角前的脚点选择纳入搜索。"},
]
LIMITATIONS = [
 "本轮排名是静态支撑导向的研究选择，不是通用定线评分；不可行不作为动态线路的不可攀结论，仍需定线员修改与现场试爬。",
 "三个布局是合成定线研究，尚未经真人试攀；按当前求得姿态的准静态反力、摩擦/抓握包络与容量检查比较修订。参数及整体手部抓握包络未标定。",
 "先给空间和动作意图，再在同一布局上自由搜索手脚接触，依据反例提议位置、朝向及脚点调整，再重新搜索；不要求使用每个岩点。",
 "搜索以窄接触走廊剪枝；屋檐结构用实际三维手脚中心轴，其他结构沿用竖墙投影。阈值是搜索假设，仍可能漏掉高抬脚、大跨度等真人走法。",
 "有限束搜索并非穷举；未找到捷径不能证明难点不可绕过，搜索出的较低负担也不等于真人更省力。",
 "侧拉、横向移重、脚点转换仅为可观测几何标签；准静态可行不验证连续运动、足部旋转、挂脚、摆荡、动态飞行与落点。",
 "姿态 IK 验证离散接触及有限墙板骨架穿越；无皮肤厚度和连续动作扫掠，不能证明动作可连续完成。关节力矩与真人可攀性仍未验证。",
]


def make_request(base, program="diagonal_balance", hold_source="auto", wall_profile="default"):
    if program not in {p["id"] for p in PROGRAMS}: raise ValueError("unknown setting program")
    from .hold_assets import resolve_hold_source, apply_setting_assets
    from .wall_profiles import PROFILES as WALL_PROFILES, apply_profile, fit_installed_footprints, repair_panel_spacing
    if wall_profile not in WALL_PROFILES: raise ValueError("unknown wall_profile")
    hold_source = resolve_hold_source(hold_source)
    req=copy.deepcopy(base); inventory=[]; placements=[]
    from .statics import DEFAULT_PARAMETERS
    req["mechanics_parameters"]=copy.deepcopy(DEFAULT_PARAMETERS)
    # Sparse, non-grid hand corridors. Small extra foot options deliberately
    # remain installed even when a selected beta does not use them.
    hands={
      "diagonal_balance":[(-1.00,1.10,"jug"),(-.64,1.14,"jug"),(-.75,1.62,"crimp"),(-.13,1.92,"pinch"),(.22,2.30,"sloper"),(.02,2.67,"rail"),(.56,2.96,"jug"),(.66,3.34,"jug")],
      "opposing_sidepulls":[(-.66,1.10,"jug"),(-.27,1.10,"jug"),(-.80,1.62,"pinch"),(-.17,1.80,"directional_edge"),(-.61,2.15,"pinch"),(-.03,2.46,"sloper"),(-.36,2.85,"rail"),(.04,3.25,"jug")],
      "roof_exit":[(-.79,1.10,"jug"),(-.42,1.10,"jug"),(-.92,1.61,"pinch"),(-.25,1.93,"crimp"),(-.59,2.27,"sloper"),(.01,2.57,"rail"),(.39,2.90,"jug"),(.28,3.29,"jug")],
    }[program]
    foot_specs={
      "diagonal_balance":[(-1.01,.36),(-.65,.36),(-.86,.78),(-.43,.95),(-.11,1.26),(-.40,1.57),(.20,1.80),(.04,2.12),(.54,2.28),(.30,2.48)],
      "opposing_sidepulls":[(-.67,.36),(-.27,.36),(-.67,.78),(-.22,.97),(-.77,1.25),(-.23,1.51),(-.64,1.78),(-.12,2.04),(-.46,2.26),(.40,2.44)],
      "roof_exit":[(-.80,.36),(-.42,.36),(-.78,.79),(-.29,.98),(-.74,1.27),(-.20,1.53),(-.51,1.81),(.04,2.05),(-.16,2.29),(.42,2.45)],
    }[program]
    attrs_by_kind=dict(AFFORDANCES,crimp=(.40,.89,.78,.34),pocket=(.57,.85,.58,.29))
    def add(pid,kind,x,y,rotation=0,top=False):
        w,h,d={"jug":(.23,.14,.085),"crimp":(.15,.07,.05),"pinch":(.17,.23,.10),"sloper":(.30,.24,.15),"directional_edge":(.22,.09,.075),"rail":(.30,.10,.09),"pocket":(.24,.14,.09),"foothold":(.10,.06,.045)}[kind]
        if top:w,h=.36,.17
        attrs=dict(zip(("grip_accessibility","precision","force_demand","friction_dependence"),attrs_by_kind[kind]))
        item={"id":pid,"type":kind,"width":w,"height":h,"depth":d,"source":"synthetic_assumption","template_id":f"setting-{kind}","template_name":f"共设计模板 · {kind}","pull_direction":[0,-1,0],"contact":{"id":"main","position":[0,0,d],"radius":.015,"limbs":["LF","RF"] if kind=="foothold" else ["LH","RH"]},"design_attributes":{"source":"synthetic_assumption",**attrs},"taxonomy":hold_taxonomy(kind)}
        item["grip_surfaces"]=grip_surfaces(item);inventory.append(item)
        placements.append({"id":pid,"inventory_id":pid,"u":x,"v":y,"rotation_deg":rotation,"contact_surface_id":"working"})
    for i,(x,y,k) in enumerate(hands):
        if hold_source == "assets": k = {"rail":"pocket", "directional_edge":"crimp"}.get(k, k)
        add("start-left" if i==0 else "start-right" if i==1 else "top" if i==len(hands)-1 else f"hand-{i-1}",k,x,y,top=i==len(hands)-1)
    # The upper tread is ~12 mm higher in projected contact coordinates than
    # the previously selected underside. Keep the roof seed's support corridor
    # by moving the physical foot holds down 15 mm; do not alter friction.
    for i,(x,y) in enumerate(foot_specs):add("start-foot-left" if i==0 else "start-foot-right" if i==1 else f"foot-{i-1}","foothold",x,y-(.015 if program=="roof_exit" else 0))
    req.update(id=f"request-setting-{program}-{req['body']['id']}",profile="setting",scenario="setting_search",mode="free",hand_moves=10,reference_layout=placements,
      setting_design={"program":program,"source":"synthetic_assumption","hold_source":hold_source,"wall_profile":wall_profile,"intent":next(p["description"] for p in PROGRAMS if p["id"]==program),"search":{"geometry_trials":3,"beam_width":22,"max_expansions":16000}})
    req["scene"].update(width=4.8,height=4.2,inventory=inventory)
    # Structural wall facets, distinct from movable volumes. Local coordinates
    # are installed on each real plane; search reads transformed world contacts.
    if wall_profile != "default":
        apply_profile(req, wall_profile)
    elif program == "roof_exit":
        join = 2.85
        tilt = math.radians(18)
        req["scene"]["wall_panels"] = [
            {"id": "lower-overhang", "label": "下段仰角 18°", "origin": [0, 0, 0],
             "rotation_deg": [18, 0, 0], "width": 4.8, "height": join},
            {"id": "upper-exit", "label": "上段转出 4°", "origin": [0, join*math.cos(tilt), join*math.sin(tilt)],
             "rotation_deg": [4, 0, 0], "width": 4.8, "height": 1.35},
        ]
        for p in placements:
            if p["v"] > join:
                p["wall_panel_id"] = "upper-exit"
                p["v"] = round(p["v"] - 2.6, 4)
            else:
                p["wall_panel_id"] = "lower-overhang"
    else:
        tilt = 0 if program == "diagonal_balance" else 10
        req["scene"]["wall_panels"] = [{"id": "main-panel", "label": f"主墙面 {tilt}°",
            "origin": [0, 0, 0], "rotation_deg": [tilt, 0, 0], "width": 4.8, "height": 4.2}]
        for p in placements:
            p["wall_panel_id"] = "main-panel"
    req["start_contacts"]=dict(zip(("LH","RH","LF","RF"),map(_ref,("start-left","start-right","start-foot-left","start-foot-right"))))
    req["end_contacts"]={"LH":_ref("top"),"RH":_ref("top"),"LF":None,"RF":None}
    req["solver"]["root_bounds"]=[[-2.2,2.2],[.30,3.75],[.05,3.2]]
    if hold_source == "assets": apply_setting_assets(req)
    if wall_profile != "default":
        req["setting_design"]["wall_application"]["adjustments"].extend(fit_installed_footprints(req, "fit actual uniformly scaled asset footprint after contact alignment"))
        from .hold_assets import _clear_footprint_collisions
        repairs = _clear_footprint_collisions(req)
        req["setting_design"]["wall_application"]["footprint_adjustment"] = repairs
        req["setting_design"]["wall_application"]["spacing_adjustment"] = repair_panel_spacing(req)
    return req


def _shell(request,placements):
    return {"id":f"setting-{request['setting_design']['program']}","name":next(p["label"] for p in PROGRAMS if p["id"]==request["setting_design"]["program"]),"revision":1,"parent_id":None,"generator":"rules","placements":copy.deepcopy(placements),"states":[{"id":"s0","label":"起始","contacts":copy.deepcopy(request["start_contacts"])}],"events":[],"design_notes":LIMITATIONS}


def _sequence_search(request,placements,deadline=None):
    from .beta_audit import _search,_make_candidate,analyze_beta
    shell=_shell(request,placements); records=[];stats=[]
    options={**request["setting_design"]["search"],"max_transfers":26,"max_ik_candidates":3}
    for objective in ("fewer_transfers","lower_proxy_effort"):
        sequences,stat=_search(request,shell,objective,options,deadline=deadline);stats.append(stat)
        for steps in sequences:
            if any(tuple(steps)==r["signature"] for r in records):continue
            candidate=_make_candidate(shell,steps,objective);candidate["parent_id"]=None
            analysis,summary=analyze_beta(request,candidate)
            records.append({"candidate":candidate,"analysis":analysis,"summary":summary,"signature":tuple(steps),"objective":objective})
    return records,stats


def _character(request,record):
    """Geometry evidence only; no reward for touching a designated crux hold."""
    from .beta_audit import _audit_context
    c=record["candidate"];ctx=_audit_context(request,c["placements"]);hands=[m for m in record["analysis"]["moves"] if m["limb"].endswith("H")]
    horizontal=sum(abs(float(ctx[m["to_placement_id"]]["uv"][0]-ctx[m["from_placement_id"]]["uv"][0])) for m in hands)
    direction=sum(m["attributes"]["directional_demand"] for m in hands)/len(hands)
    foot_transfer=sum(m["limb"].endswith("F") for m in record["analysis"]["moves"])/len(hands)
    # A bounded tradeoff, not maximizing difficulty or enforcing a sequence.
    score=.45*min(horizontal/2.2,1)+.30*min(direction/.30,1)+.25*min(foot_transfer/.9,1)
    return {"score":round(score,5),"hand_lateral_travel_m":round(horizontal,4),"mean_directional_demand":round(direction,4),"foot_hand_transfer_ratio":round(foot_transfer,4),"basis":"observed_contact_geometry_not_force_or_technique_proof"}


def _proposal(request,original,record,strength):
    from .beta_audit import _audit_context
    points=copy.deepcopy(original);ctx=_audit_context(request,original);byid={p["id"]:p for p in points}
    program=request["setting_design"]["program"]
    # The baseline beta supplies which feet support each transfer. Orient the
    # contacted hand toward its actual support corridor; shift its support
    # feet and the next hand laterally together instead of adding unused points.
    moves=record["analysis"]["moves"]
    anchors={ref["placement_id"] for key in ("start_contacts","end_contacts") for ref in request[key].values() if ref}
    hands=[p for p in points if {"LH","RH"} & set(ctx[p["id"]]["limbs"])]
    for m in moves:
        if not m["limb"].endswith("H"):continue
        pid=m["to_placement_id"]
        if pid in anchors:continue
        p=byid[pid];side=-1 if p["u"]<np.mean([q["u"] for q in hands]) else 1
        rotation=(-side*35 if program=="opposing_sidepulls" else -side*28 if program=="diagonal_balance" else -side*20)*strength
        p["rotation_deg"]=round(rotation,2)
        p["u"]=round(p["u"]+side*.018*strength*(-1 if program=="roof_exit" else 1),4)
        before=candidate_state(record["candidate"],m["event_index"])
        for limb in ("LF","RF"):
            fid=before[limb]["placement_id"]
            if fid in anchors:continue
            f=byid[fid]
            # Opposite-side support for a sidepull; modest lateral offsets keep
            # the proposal inside local reach. Independent search may ignore it.
            f["u"]=round(f["u"]-side*.012*strength,4)
            f["rotation_deg"]=round(side*12*strength,2)
            if program=="roof_exit": f["v"]=round(f["v"]-.012*abs(strength),4)
    return points


def candidate_state(candidate,index):return candidate["states"][index*2]["contacts"]


def _placement_change_fields(placement):
    return {k: placement[k] for k in ("u", "v", "rotation_deg", "wall_panel_id") if k in placement}


def analyze_setting(request,candidate):
    from .beta_audit import analyze_beta
    return analyze_beta(request,candidate)[0]


def search_settings(request):
    return copy.deepcopy(_search_cached(json.dumps(request,sort_keys=True,ensure_ascii=False)))


@lru_cache(maxsize=12)
def _search_cached(encoded):
    from .engine import evaluate,canonical_hash
    request=json.loads(encoded);original=request["reference_layout"];trials=[];baseline=None
    started=time.perf_counter();deadline=started+60.
    for trial in range(request["setting_design"]["search"]["geometry_trials"]):
        if trial and baseline is None: break
        placements=original if trial==0 else _mechanical_proposal(request,original,baseline,.65 if trial==1 else -.65)
        records,stats=_sequence_search(request,placements,deadline=deadline)
        if not records:
            trials.append({"index":trial,"search":stats,"status":"no_sequence","records":[]});continue
        # Every shortlisted beta is evaluated honestly. Preserve unsuccessful
        # probes in the report, but do not call them viable alternatives.
        for i,r in enumerate(records):
            r["candidate"]["id"]=f"setting-{request['setting_design']['program']}-trial{trial}-beta{i}"
            r["candidate"]["name"]=_shell(request,placements)["name"]
            probe=evaluate(request,r["candidate"],deadline=time.perf_counter()-1)
            r["evaluation"]=probe if probe["summary"]["status"]=="fail" else evaluate(request,r["candidate"],deadline=deadline)
            r["character"]=_character(request,r)
        records.sort(key=_mechanical_rank)
        chosen=records[0]
        if trial==0:baseline=chosen
        valid=[r for r in records if r["evaluation"]["summary"]["status"]=="pass"]
        robust=min((r["character"]["score"] for r in valid),default=0)
        trials.append({"index":trial,"search":stats,"status":chosen["evaluation"]["summary"]["status"],"records":records,"character_score":robust,"mechanical_rank":list(_mechanical_rank(chosen))})
    if baseline is None:
        if request["setting_design"].get("wall_profile", "default") != "default":
            from .wall_profiles import LIMITATIONS as WALL_LIMITATIONS
            candidate = _shell(request, original)
            candidate["name"] += " · 墙形适配布局（未找到完整走法）"
            candidate["layout_report"] = {"status": "no_sequence", "wall_profile": request["setting_design"]["wall_profile"],
                "reason": "bounded independent search found no complete contact sequence; installed layout only",
                "search": trials[0]["search"] if trials else [], "limitations": WALL_LIMITATIONS}
            return [candidate]
        raise ValueError("bounded setting search found no complete sequence; enlarge search budget or revise geometry")
    feasible=[t for t in trials if t["status"]=="pass"]
    selected=min(feasible or [t for t in trials if t["records"]],key=lambda t:(_mechanical_rank(t["records"][0]),t["index"]))
    def exported(selected, best, role):
        candidate=copy.deepcopy(best["candidate"])
        changes=[]
        old={p["id"]:p for p in original}
        for p in candidate["placements"]:
            if p!=old[p["id"]]:changes.append({"placement_id":p["id"],"before":_placement_change_fields(old[p["id"]]),"after":_placement_change_fields(p),"reason":"依据当前释放态的准静态反力/重心及墙面支撑方向，调整手点朝向与脚点安装位置；调整后重新搜索、求姿态并检查平衡。"})
        alternatives=[]
        for r in selected["records"]:
            if r is best:continue
            if r["evaluation"]["summary"]["status"]=="pass":alternatives.append({k:copy.deepcopy(r[k]) for k in ("candidate","summary","evaluation","analysis")})
        tags=[{"id":"lateral-transfer","label":"横向手脚转换","evidence":best["character"]}, {"id":"directional-contact","label":"朝向与支撑配合（几何代理）","evidence":{"mean_directional_demand":best["character"]["mean_directional_demand"]}}]
        candidate["setting_report"]={"model_version":MODEL_VERSION,"program":request["setting_design"]["program"],"intent":request["setting_design"]["intent"],"baseline_candidate":copy.deepcopy(baseline["candidate"]),"baseline_evaluation":copy.deepcopy(baseline["evaluation"]),"baseline_analysis":copy.deepcopy(baseline["analysis"]),
          "baseline":{"mechanics_summary":baseline["evaluation"].get("mechanics_report",{}).get("summary"),"summary":baseline["summary"],"character":baseline["character"],"search":trials[0]["search"],"geometry_hash":canonical_hash(original)},"result":{"mechanics_summary":best["evaluation"].get("mechanics_report",{}).get("summary"),"summary":best["summary"],"character":best["character"],"search":selected["search"],"geometry_hash":canonical_hash(candidate["placements"])},"changes":changes,"observed_movement_tags":tags,"allowed_alternatives":alternatives,"limitations":LIMITATIONS,
          "search":{"timeout_seconds":60,"elapsed_ms":round((time.perf_counter()-started)*1000,2),"time_budget_exhausted":time.perf_counter()>=deadline,"geometry_trials":len(trials),"selected_trial":selected["index"],"hand_count_policy":"free; only start/TOP required","coverage_policy":"unused installed holds allowed","ranking":"P0 first; maximize current-pose release equilibrium fraction, then all-state equilibrium fraction, then lower required axial capacity utilization; geometry character does not select layouts","trials":[{k:v for k,v in t.items() if k!="records"}|{"evaluations":[{"summary":r["summary"],"status":r["evaluation"]["summary"]["status"],"character":r["character"],"mechanics_summary":r["evaluation"].get("mechanics_report",{}).get("summary")} for r in t["records"]]} for t in trials]}}
        if request["setting_design"].get("wall_profile") == "roof":
            report = candidate["setting_report"]
            report["selection_role"] = role
            report["baseline"]["exit_support"] = roof_exit_support(baseline["candidate"], baseline["evaluation"])
            report["result"]["exit_support"] = roof_exit_support(candidate, best["evaluation"])
            if role == "exit_support_tradeoff":
                candidate["name"] = "屋檐 · 转换调整方案（增加动作）"
                report["search"]["ranking"] = "P0 first; optional design prioritizes exit release equilibrium then exit all-state equilibrium; full-route support and added transfers remain visible, not a global improvement claim"
            else:
                candidate["name"] = "屋檐 · 全程支撑排序保留方案"
        return candidate
    best = selected["records"][0]
    candidates = [exported(selected, best, "whole_route_support")]
    if request["setting_design"].get("wall_profile") == "roof":
        def exit_rank(record):
            support = roof_exit_support(record["candidate"], record["evaluation"])
            return (-support["release_feasible_fraction"], -support["feasible_fraction"], _mechanical_rank(record))
        choices = [(trial, record) for trial in trials for record in trial["records"]
                   if record["evaluation"]["summary"]["status"] == "pass"
                   and canonical_hash(record["candidate"]["placements"]) != canonical_hash(best["candidate"]["placements"])]
        if choices:
            trial, alternate = min(choices, key=lambda pair: exit_rank(pair[1]))
            if exit_rank(alternate)[:2] < exit_rank(best)[:2]:
                candidates.append(exported(trial, alternate, "exit_support_tradeoff"))
    return candidates


def roof_exit_support(candidate, evaluation):
    """Observed exit contact window, derived only after independent search.

    Includes the release *before* the first hand reaches the exit face, so the
    awkward roof-to-exit handoff cannot disappear from the local comparison.
    """
    panels = {p["id"]: p.get("wall_panel_id") for p in candidate["placements"]}
    by_state = {s["id"]: s for s in candidate["states"]}
    first = next((i for i, event in enumerate(candidate["events"])
                  if event["limb"].endswith("H") and
                  panels[by_state[event["to_state"]]["contacts"][event["limb"]]["placement_id"]] == "upper-wall"), None)
    ordered_states = candidate["states"][2*first+1:] if first is not None else []
    state_ids = [s["id"] for s in ordered_states]
    states = [s for s in evaluation.get("mechanics_report", {}).get("states", []) if s["state_id"] in state_ids]
    release = [s for s in states if s["is_release"]]
    count = lambda rows, status: sum(s["status"] == status for s in rows)
    return {"first_exit_event_index": first, "state_ids": state_ids,
            "states": len(states), "feasible_states": count(states, "feasible"), "infeasible_states": count(states, "infeasible"), "unknown_states": count(states, "unknown"),
            "release_states": len(release), "release_feasible_states": count(release, "feasible"), "release_unknown_states": count(release, "unknown"),
            "feasible_fraction": count(states, "feasible")/max(1, len(states)),
            "release_feasible_fraction": count(release, "feasible")/max(1, len(release)),
            "finish_status": states[-1]["status"] if states else "unknown",
            "basis": "first exit hand-transfer release through matched TOP; current synthetic static model"}


def validate_setting_report(request,candidate,current_evaluation=None):
    """Treat embedded evidence like the main evaluation, never trusted prose."""
    from .engine import _schema,_validate_evaluation,canonical_hash
    from .beta_audit import analyze_beta
    report=candidate.get("setting_report")
    if report is None:return
    if not isinstance(report,dict):raise ValueError("setting report must be an object")
    for field in ("baseline","result","baseline_candidate","baseline_evaluation","baseline_analysis","search"):
        if not isinstance(report.get(field),dict):raise ValueError(f"setting report {field} must be an object")
    for field in ("changes","allowed_alternatives","observed_movement_tags","limitations"):
        if not isinstance(report.get(field),list):raise ValueError(f"setting report {field} must be an array")
    if any(not isinstance(value,str) for value in report["limitations"]):raise ValueError("setting limitations must contain strings")
    if any(not isinstance(value,dict) for field in ("changes","allowed_alternatives","observed_movement_tags") for value in report[field]):raise ValueError("setting report entries must be objects")
    if request.get("profile")!="setting":raise ValueError("setting report requires setting profile")
    if report.get("model_version")!=MODEL_VERSION or report.get("program")!=request["setting_design"]["program"]:
        raise ValueError("stale setting report version/program")
    if request["setting_design"].get("wall_profile") == "roof" and report.get("selection_role") not in ("whole_route_support", "exit_support_tradeoff"):
        raise ValueError("roof setting report requires explicit selection tradeoff")
    baseline=report.get("baseline_candidate")
    if not isinstance(baseline,dict) or "setting_report" in baseline:raise ValueError("invalid nested setting baseline")
    _schema(baseline,"candidate")
    if canonical_hash(baseline["placements"])!=canonical_hash(request["reference_layout"]):raise ValueError("setting baseline differs from reference geometry")
    entries=[("baseline",baseline,report.get("baseline_evaluation"),report.get("baseline_analysis")),("result",candidate,None,None)]
    for key,current,evaluation,analysis in entries:
        expected_analysis,summary=analyze_beta(request,current)
        actual=report.get(key,{})
        character = _character(request,{"candidate":current,"analysis":expected_analysis})
        if actual.get("geometry_hash")!=canonical_hash(current["placements"]) or actual.get("summary")!=summary or actual.get("character")!=character:
            raise ValueError("setting report geometry/summary/character mismatch")
        mechanical_evaluation=evaluation if key=="baseline" else current_evaluation
        if mechanical_evaluation is not None and actual.get("mechanics_summary")!=mechanical_evaluation.get("mechanics_report",{}).get("summary"):
            raise ValueError("setting mechanics summary mismatch")
        if request["setting_design"].get("wall_profile") == "roof" and mechanical_evaluation is not None:
            if actual.get("exit_support") != roof_exit_support(current, mechanical_evaluation):
                raise ValueError("setting roof exit support mismatch")
        if evaluation is not None:_validate_evaluation(request,current,evaluation)
        if key=="baseline" and analysis!=expected_analysis:raise ValueError("setting baseline analysis mismatch")
    character=report["result"]["character"]
    expected_tags=[{"id":"lateral-transfer","label":"横向手脚转换","evidence":character}, {"id":"directional-contact","label":"朝向与支撑配合（几何代理）","evidence":{"mean_directional_demand":character["mean_directional_demand"]}}]
    if report.get("observed_movement_tags")!=expected_tags:raise ValueError("setting movement evidence mismatch")
    old={p["id"]:p for p in baseline["placements"]};new={p["id"]:p for p in candidate["placements"]}
    if old.keys()!=new.keys():raise ValueError("setting refinement must retain installed inventory")
    expected={pid:(_placement_change_fields(old[pid]),_placement_change_fields(new[pid])) for pid in old if old[pid]!=new[pid]}
    actual={}
    for change in report.get("changes",[]):
        if change["placement_id"] in actual:raise ValueError("duplicate setting change")
        actual[change["placement_id"]]=(change.get("before"),change.get("after"))
    if actual!=expected:raise ValueError("setting change evidence mismatch")
    for entry in report.get("allowed_alternatives",[]):
        alternate=entry.get("candidate")
        if not isinstance(alternate,dict) or "setting_report" in alternate:raise ValueError("invalid nested setting alternative")
        _schema(alternate,"candidate")
        if canonical_hash(alternate["placements"])!=canonical_hash(candidate["placements"]):raise ValueError("setting alternative changed installed geometry")
        _validate_evaluation(request,alternate,entry.get("evaluation"))
        if entry["evaluation"]["summary"]["status"]!="pass":raise ValueError("setting alternative lacks verified pose sequence")
        analysis,summary=analyze_beta(request,alternate)
        if entry.get("analysis")!=analysis or entry.get("summary")!=summary:raise ValueError("setting alternative evidence mismatch")


def _mechanical_rank(record):
    report=record["evaluation"].get("mechanics_report",{})
    s=report.get("summary",{})
    release=s.get("release_states",0)
    release_feasible=(release-s.get("release_infeasible_states",release)-s.get("release_unknown_states",0))/max(1,release)
    total=sum(s.get(f"{k}_states",0) for k in ("feasible","infeasible","unknown"))
    ratio=s.get("feasible_states",0)/max(1,total)
    utilization=s.get("max_capacity_utilization")
    return (record["evaluation"]["summary"]["status"]!="pass",-release_feasible,-ratio,utilization if utilization is not None else 1e6,record["summary"]["total_proxy_effort"])


def _mechanical_proposal(request,original,record,strength):
    """Current failed/overloaded release poses suggest orientation/support edits.

    These are proposals, never a claim that rotating a hold resolves equilibrium.
    Every proposal goes through a new independent beta, IK and equilibrium check.
    """
    from .geometry import placement_frames
    points=copy.deepcopy(original);byid={p["id"]:p for p in points};inventory={i["id"]:i for i in request["scene"]["inventory"]}
    frames=placement_frames(points,inventory,request["scene"]["angle_deg"],request["scene"].get("wall_panels"))
    top={r["placement_id"] for r in request["end_contacts"].values() if r}
    proposals={}
    for state in record["evaluation"].get("mechanics_report",{}).get("states",[]):
        if not state["is_release"] or state["com_world_m"] is None:continue
        if state["status"]=="feasible" and (state["capacity_utilization"] or 0)<.75:continue
        com=np.asarray(state["com_world_m"])
        weight=2. if state["status"]=="infeasible" else 1.
        for contact in state["contacts"]:
            pid=contact["placement_id"]
            if pid in top:continue
            rot=frames[pid][1];position=np.asarray(contact["point_world_m"]);entry=proposals.setdefault(pid,{"turn":[],"u":[],"v":[]})
            if contact["limb"].endswith("H"):
                required=contact.get("required_force_world_n")
                desired=np.asarray(required) if required is not None and np.linalg.norm(required)>1 else position-com
                local=rot.T @ desired;axis=rot.T @ np.asarray(contact["axial_direction_world"])
                delta=math.degrees(math.atan2(local[1],local[0])-math.atan2(axis[1],axis[0]))
                delta=(delta+180)%360-180
                entry["turn"].append((max(-25.,min(25.,delta)),weight))
            else:
                # Bring support closer to the pose's projected COM. Modest
                # offsets change actual moment arms; the solver decides benefit.
                local=rot.T @ (com-position)
                entry["u"].append((max(-.05,min(.05,float(local[0])*.2)),weight))
                entry["v"].append((max(-.025,min(.025,float(local[1])*.025)),weight))
    for pid,values in proposals.items():
        p=byid[pid]
        for field,key in (("turn","rotation_deg"),("u","u"),("v","v")):
            if values[field]:p[key]=round(p[key]+strength*sum(v*w for v,w in values[field])/sum(w for _,w in values[field]),4)
    if request["setting_design"].get("wall_profile") == "roof":
        # Do not turn a border hold into a physically un-installable footprint.
        # Reject that orientation proposal rather than moving the TOP to make
        # room; the rest of the independently re-searched revision can proceed.
        from .geometry import panel_fit
        original_by_id = {p["id"]: p for p in original}
        for error in panel_fit(points, inventory, request["scene"]):
            pid = error["placement_id"]
            byid[pid]["rotation_deg"] = original_by_id[pid]["rotation_deg"]
        # A roof tread facing down cannot provide standing support at exit.
        # Propose re-installing one *used* ceiling foot on the exit face. The
        # search remains free to ignore it, match/skip hands, or reject the
        # geometry; this is a spatial proposal, never a required move order.
        roof_feet = [p for p in points if p.get("wall_panel_id") == "roof"
                     and inventory[p["inventory_id"]]["type"] == "foothold"
                     and any(p["id"] == ref["placement_id"] for s in record["candidate"]["states"]
                             for ref in s["contacts"].values() if ref)]
        if roof_feet:
            p = max(roof_feet, key=lambda p: (p["v"], p["u"]))
            exit_panel = next(panel for panel in request["scene"]["wall_panels"] if panel["id"] == "upper-wall")
            item = inventory[p["inventory_id"]]
            p.update(wall_panel_id=exit_panel["id"], v=request["scene"]["margin"]+item["height"]/2+.015,
                     rotation_deg=0.)
        # Rotations change the actual footprint. Re-fit and space the proposal
        # before spending IK time, retaining the same start and TOP positions.
        from .wall_profiles import fit_installed_footprints, repair_panel_spacing
        proposed_request = copy.deepcopy(request)
        proposed_request["reference_layout"] = points
        fit_installed_footprints(proposed_request)
        repair_panel_spacing(proposed_request, protected_ids=top)
    return points
