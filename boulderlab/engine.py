"""Local, auditable geometric experiment engine. No model API or climbability claim."""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import time
from datetime import datetime, timezone

import jsonschema
import numpy as np
import scipy

from .kinematics import LIMBS, contact_distance_bound, contact_endpoints, forward_kinematics, joint_bounds, solve_pose
from .catalog import catalog_metadata, make_inventory, validate_catalog
from .route_constraints import constraint_errors
from .setting import PROGRAMS as SETTING_PROGRAMS, make_request as make_setting_request, search_settings, analyze_setting
from .full_route import PROGRAMS, make_request as make_full_request, search_routes as search_full_routes, analyze_route as analyze_full_route
from .route_design import STYLE_GOALS, RHYTHMS, make_request as make_style_request, search_routes, analyze_route
from .geometry import (box_corners, contact_world as geometry_contact_world, frame_axes,
                       mounting_faces, mounting_fit, obb_separation, placement_frames,
                       selected_contact, wall_basis, panel_fit)

ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.1.0"
SCENARIOS = [
    {"id": "foot_first", "label": "脚先移动再抬手", "description": "先重定位脚点，再完成交替手移动。"},
    {"id": "sidepull", "label": "侧拉横移", "description": "用方向岩点组织横移；受力效果尚未检查。"},
    {"id": "foot_reposition", "label": "脚点重定位", "description": "先调整两脚接触，再进行手部换点。"},
    {"id": "competition_sequence", "label": "对向 → 移重 → 收尾", "description": "竞赛启发的四次手移动研究；动作、摩擦与平衡仅为设计意图。"},
]
PROFILES = [
    {"id": "setting", "label": "空间与动作共设计", "description": "固定岩壁上的稀疏布局、独立走法和有界几何修订。"},
    {"id": "basic", "label": "基础几何实验", "description": "3 × 3 m 单平面，保留原有测试模板。"},
    {"id": "competition", "label": "竞赛启发研究", "description": "4.8 × 4.2 m 合成单平面，12 个安装件与四次手移动。"},
    {"id": "route", "label": "完整线路", "description": "8–12 次移手，混合阶段与历史负荷参与搜索。"},
    {"id": "style", "label": "风格与节奏搜索", "description": "同一固定训练墙上按风格和阶段目标搜索手脚接触序列。"},
    {"id": "catalog", "label": "标准库存工作台", "description": "七款有限库存、抓握面选择与体积块斜面安装。"},
]
P1_CHECKS = [("force", "抓握、摩擦与受力"), ("balance", "平衡与稳定性"),
             ("body_collision", "完整人体碰撞"), ("transition", "连续动作转换"),
             ("grade_experience", "真实难度与体验")]


def body_profiles():
    profiles = []
    for name, lengths in [("A", [.28, .25, .40, .38, .34, .26, .43]),
                          ("B", [.32, .28, .45, .43, .40, .30, .49])]:
        body = dict(zip(["upper_arm", "forearm", "thigh", "shin", "shoulder_width", "hip_width", "torso"], lengths))
        body.update(id=name, source="synthetic_assumption", endpoint_offsets={l: [0, 0, 0] for l in LIMBS},
                    joint_limits_deg={"shoulder": [[-170, 170]]*3, "hip": [[-110, 110], [-90, 90], [-70, 70]],
                                      "elbow": [0, 140], "knee": [0, 140]})
        profiles.append(body)
    return profiles


def _finite(value, path="$"):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path}: non-finite number")
    if isinstance(value, dict):
        for k, v in value.items():
            _finite(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _finite(v, f"{path}[{i}]")


def _canonical(value, path=()):
    if isinstance(value, dict):
        return {k: _canonical(v, path + (k,)) for k, v in sorted(value.items())}
    if isinstance(value, list):
        values = [_canonical(v, path + (i,)) for i, v in enumerate(value)]
        # Only schema-defined ID collections are order-insensitive. In particular,
        # collision evidence also uses "placements", but contains an ordered pair
        # of ID strings; field names alone cannot determine canonical semantics.
        id_collection = path in {
            ("scene", "inventory"), ("reference_layout",), ("placements",),
            ("request", "scene", "inventory"), ("request", "reference_layout"),
            ("candidate", "placements"),
        } or (len(path) == 3 and path[0] == "candidates" and isinstance(path[1], int) and path[2] == "placements")
        if id_collection and all(isinstance(v, dict) and isinstance(v.get("id"), str) for v in values):
            values.sort(key=lambda v: v["id"])
        if len(path) >= 3 and path[-3:-1] == ("route_constraints", "allowed_contacts") and path[-1] in LIMBS:
            values.sort()
        return values
    # Normalize integral floats so equivalent JSON roundtrips have the same digest.
    return int(value) if isinstance(value, float) and value.is_integer() else value


def canonical_hash(value):
    _finite(value)
    raw = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def code_hash():
    paths = [Path(__file__), Path(__file__).with_name("kinematics.py"),
             Path(__file__).with_name("geometry.py"), Path(__file__).with_name("catalog.py"), Path(__file__).with_name("route_design.py"), Path(__file__).with_name("full_route.py"),
             Path(__file__).with_name("statics.py"), Path(__file__).with_name("setting.py"), Path(__file__).with_name("hold_assets.py"), Path(__file__).with_name("wall_profiles.py"), Path(__file__).with_name("wall_clearance.py"), Path(__file__).with_name("beta_audit.py"), Path(__file__).with_name("route_constraints.py"), ROOT / "schemas/request.schema.json", ROOT / "schemas/candidate.schema.json"]
    return "sha256:" + hashlib.sha256(b"".join(p.read_bytes() for p in paths)).hexdigest()


def fingerprint(request, candidate):
    r = {k: v for k, v in request.items() if k not in {"name", "notes", "revision", "id"}}
    c = {"placements": candidate.get("placements", []),
         "states": [{k: v for k, v in s.items() if k != "label"} for s in candidate.get("states", [])],
         "events": candidate.get("events", [])}
    return canonical_hash({"request": r, "candidate": c, "engine": VERSION, "code": code_hash()})


def _schema(value, name):
    _finite(value)
    schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_text())
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(value), key=lambda e: str(list(e.path)))
    if errors:
        first = errors[0]
        raise ValueError(f"{name}.{'.'.join(map(str, first.path))}: {first.message}")


def validate_request(request):
    _schema(request, "request")
    joint_bounds(request["body"], request["solver"])
    from .hold_assets import validate_inventory_assets
    validate_inventory_assets(request["scene"]["inventory"])
    if "mechanics_parameters" in request:
        from .statics import validate_parameters
        validate_parameters(request["mechanics_parameters"])
    if not any(request["start_contacts"].values()) or not any(request["end_contacts"].values()):
        raise ValueError("request start_contacts/end_contacts must not be empty")
    restrictions = constraint_errors(request, request["reference_layout"] or None)
    if restrictions:
        raise ValueError("; ".join(restrictions))
    if request.get("profile") == "catalog":
        validate_catalog(request)
    for item in request["scene"]["inventory"]:
        for key in ("grip_surfaces", "mounting_faces"):
            records = item.get(key, [])
            if len({s["id"] for s in records}) != len(records):
                raise ValueError(f"{item['id']}: duplicate {key} id")
            for record in records:
                if key == "grip_surfaces" and record["id"] == "main":
                    raise ValueError("grip surface id main is reserved for the placement alias")
                frame_axes(record)
        if item.get("mounting_faces"):
            if item["type"] != "volume":
                raise ValueError("only volume templates may expose mounting faces")
            expected = {f["id"]: f for f in mounting_faces(item)}
            for face in item["mounting_faces"]:
                if face["id"] not in expected or any(not np.allclose(face[k], expected[face["id"]][k], atol=1e-8, rtol=0) for k in ("origin", "u_axis", "v_axis", "normal", "polygon")):
                    raise ValueError(f"{item['id']}: mounting face does not match the declared pyramid")
    if request["reference_layout"]:
        installed = {p["id"]: p for p in request["reference_layout"]}
        inventory = {item["id"]: item for item in request["scene"]["inventory"]}
        for name in ("start_contacts", "end_contacts"):
            for limb, ref in request[name].items():
                if ref is None:
                    continue
                placement = installed.get(ref["placement_id"])
                item = inventory.get(placement["inventory_id"]) if placement else None
                if item is None:
                    raise ValueError(f"{name}: unknown {limb} contact")
                if limb not in selected_contact(placement, item, ref["contact_id"])["limbs"]:
                    raise ValueError(f"{name}: {limb} violates surface permissions")
    if request.get("profile") == "style":
        design = request["route_design"]
        if [p["hand_move_index"] for p in design["phases"]] != list(range(4)) or len({p["id"] for p in design["phases"]}) != 4:
            raise ValueError("style phases must cover four ordered hand transfers")
        ids = {p["id"] for p in request["reference_layout"]}
        if any(not r or r["placement_id"] not in ids for key in ("start_contacts", "end_contacts") for r in request[key].values()):
            raise ValueError("style start/end contacts must reference installed holds")
    if request.get("profile") == "route":
        if not all(request["start_contacts"].values()):
            raise ValueError("完整线路需要四肢起始接触。")
        if any(request["end_contacts"][l] is not None for l in ("LF", "RF")):
            raise ValueError("完整线路终点脚点须留空，由搜索选择实际支撑。")
        design = request["route_design"]
        if [p["hand_move_index"] for p in design["phases"]] != list(range(request["hand_moves"])):
            raise ValueError("route phases must cover every ordered hand transfer")
        if len({p["id"] for p in design["phases"]}) != request["hand_moves"] or any("segment_id" not in p or "phase_kind" not in p for p in design["phases"]):
            raise ValueError("route phases require unique IDs and segment/kind")
        seen_segments, previous_segment, descriptions = set(), None, {}
        for phase in design["phases"]:
            segment = phase["segment_id"]
            if segment != previous_segment and segment in seen_segments:
                raise ValueError("route segments must be contiguous")
            description = (phase["label"], phase["phase_kind"])
            if segment in descriptions and descriptions[segment] != description:
                raise ValueError("route segment label/kind must be consistent")
            seen_segments.add(segment); descriptions[segment] = description; previous_segment = segment
        ids = {p["id"] for p in request["reference_layout"]}
        if any(r and r["placement_id"] not in ids for key in ("start_contacts", "end_contacts") for r in request[key].values()):
            raise ValueError("route anchor is absent from the placement pool")
        if request["end_contacts"]["LH"] != request["end_contacts"]["RH"] or not request["end_contacts"]["LH"]:
            raise ValueError("route finish requires both hands on the same TOP")
    if request.get("profile") == "setting":
        ids = {p["id"] for p in request["reference_layout"]}
        if not all(request["start_contacts"].values()) or any(r and r["placement_id"] not in ids for k in ("start_contacts", "end_contacts") for r in request[k].values()):
            raise ValueError("setting anchors require four installed start contacts")
        if any(request["end_contacts"][l] is not None for l in ("LF", "RF")) or not request["end_contacts"]["LH"] or request["end_contacts"]["LH"] != request["end_contacts"]["RH"]:
            raise ValueError("setting requires matched TOP with unconstrained finish feet")
    brief = request.get("design_brief")
    if brief:
        ids = {p["id"] for p in request["reference_layout"]}
        if any(pid not in ids for key in ("zone_placement_ids", "top_placement_ids") for pid in brief[key]):
            raise ValueError("design_brief references unknown reference placement")
        phases = brief["phases"]
        if len({p["id"] for p in phases}) != len(phases) or any(p["event_start"] > p["event_end"] for p in phases):
            raise ValueError("design_brief has invalid phases")
    return request


def _contact(placement_id):
    return {"placement_id": placement_id, "contact_id": "main"}


def _template(request, variant=0):
    if request["scenario"] == "competition_sequence":
        return [("LF", "volume_01"), ("RH", "sloper_01"),
                ("RF", "foothold_03"), ("LH", "pinch_02"),
                ("LF", "foothold_04"), ("RH", "sloper_02"),
                ("RF", "foothold_05"), ("LH", "rail_02")]
    n = request["hand_moves"]
    scenario = request["scenario"]
    hands = [("RH", "jug_03"), ("LH", "jug_04"), ("RH", "jug_05"), ("LH", "jug_06")][:n]
    feet = [("LF", "foothold_03"), ("RF", "foothold_04")]
    if scenario == "sidepull":
        hands = [("RH", "jug_02"), ("LH", "directional_edge_02"), ("RH", "jug_03"), ("LH", "jug_04")][:n]
    if variant % 2:
        feet = feet[::-1]
    if scenario == "foot_reposition":
        return feet + hands
    return [feet[0], hands[0], feet[1]] + hands[1:]


def default_request(body_id="A", scenario="foot_first", mode="free", angle_deg=0, hand_moves=None, seed=42, budget=3, profile="basic", catalog_counts=None, style_goal="power", rhythm=None, route_program="mixed_flow", setting_program="diagonal_balance", hold_source="auto", wall_profile="default"):
    if hold_source not in {"auto", "templates", "assets"}:
        raise ValueError("hold_source must be auto, templates or assets")
    if profile != "setting" and hold_source == "assets":
        raise ValueError("external hold assets currently require profile=setting")
    from .wall_profiles import PROFILES as WALL_PROFILES
    if wall_profile not in WALL_PROFILES:
        raise ValueError("unknown wall_profile")
    if profile != "setting" and wall_profile != "default":
        raise ValueError("wall_profile currently requires profile=setting")
    hand_moves = (10 if profile in ("route", "setting") else 2) if hand_moves is None else hand_moves
    bodies = {b["id"]: b for b in body_profiles()}
    if body_id not in bodies:
        raise ValueError("unknown body_id")
    if profile == "setting":
        if catalog_counts is not None:
            raise ValueError("catalog_counts requires profile=catalog")
        req = make_setting_request(default_request(body_id=body_id, angle_deg=min(angle_deg, 10), seed=seed, budget=budget), setting_program, hold_source, wall_profile)
        req["scene"]["angle_deg"] = angle_deg
        validate_request(req)
        return req
    if profile == "route":
        if catalog_counts is not None:
            raise ValueError("catalog_counts requires profile=catalog")
        moves = hand_moves
        req = make_full_request(default_request(body_id=body_id, angle_deg=min(angle_deg, 10), seed=seed, budget=budget), route_program, moves)
        req["scene"]["angle_deg"] = angle_deg
        validate_request(req)
        return req
    if profile == "style":
        if catalog_counts is not None:
            raise ValueError("catalog_counts requires profile=catalog")
        req = make_style_request(default_request(body_id=body_id, mode="fixed", angle_deg=min(angle_deg, 10), seed=seed, budget=budget), style_goal, rhythm or "late_crux")
        req["scene"]["angle_deg"] = angle_deg
        validate_request(req)
        return req
    if profile == "catalog":
        return _catalog_request(body_id, scenario, mode, angle_deg, hand_moves, seed, budget, catalog_counts)
    if catalog_counts is not None:
        raise ValueError("catalog_counts requires profile=catalog")
    if profile == "competition":
        return _competition_request(bodies[body_id], mode, angle_deg, seed, budget)
    if profile != "basic":
        raise ValueError("unknown profile")
    if scenario == "competition_sequence":
        raise ValueError("competition_sequence requires profile=competition")
    inventory = []
    for kind, count, size in [("jug", 6, (.17, .12, .09)), ("directional_edge", 4, (.16, .10, .07)),
                               ("foothold", 6, (.10, .07, .045))]:
        for i in range(count):
            inventory.append({"id": f"{kind}_{i+1:02d}", "type": kind, "width": size[0], "height": size[1], "depth": size[2],
                              "source": "synthetic_assumption", "pull_direction": [0, -1, 0],
                              "contact": {"id": "main", "position": [0, 0, size[2]], "radius": .015,
                                          "limbs": list(LIMBS[:2] if kind != "foothold" else LIMBS[2:])}})
    xy = [(-.28, 1.55), (.28, 1.55), (.45, 1.80), (-.12, 1.88), (.28, 2.10), (-.34, 2.17),
          (-.62, 1.63), (-.46, 1.92), (-.90, 2.10), (.90, 1.40),
          (-.22, .60), (.22, .60), (-.35, .86), (.12, .93), (.46, .84), (-.06, 1.05)]
    placements = [{"id": item["id"], "inventory_id": item["id"], "u": p[0], "v": p[1],
                   "rotation_deg": 65 if item["type"] == "directional_edge" else 0}
                  for item, p in zip(inventory, xy)]
    req = {"schema_version": "1.0", "id": f"request-{scenario}-{body_id}", "revision": 1, "source": "synthetic_assumption",
           "scene": {"width": 3, "height": 3, "angle_deg": angle_deg, "margin": .2, "inventory": inventory},
           "body": bodies[body_id], "scenario": scenario, "mode": mode, "hand_moves": hand_moves,
           "seed": seed, "budget": budget, "reference_layout": placements,
           "solver": {"max_nfev": 100, "restarts": 3, "contact_tolerance_m": .015, "epsilon_geometry_m": .000001,
                      "root_bounds": [[-1.6, 1.6], [.35, 2.6], [.08, 1.0]],
                      "root_rotation_deg": [[-35, 35], [-65, 65], [-35, 35]], "timeout_seconds": 12},
           "start_contacts": {"LH": _contact("directional_edge_01" if scenario == "sidepull" else "jug_01"),
                              "RH": _contact("jug_01" if scenario == "sidepull" else "jug_02"),
                              "LF": _contact("foothold_01"), "RF": _contact("foothold_02")}, "end_contacts": {}}
    req["end_contacts"] = copy.deepcopy(req["start_contacts"])
    for limb, hold in _template(req):
        req["end_contacts"][limb] = _contact(hold)
    validate_request(req)
    return req


def _catalog_request(body_id, scenario, mode, angle_deg, hand_moves, seed, budget, counts):
    req = default_request(body_id, scenario, mode, angle_deg, hand_moves, seed, budget)
    inventory, stock = make_inventory(counts)
    items = {h["id"]: h for h in inventory}
    required = {ref["placement_id"] for ref in req["start_contacts"].values() if ref}
    required.update(pid for _, pid in _template(req))
    required.add("volume_01")
    missing = sorted(required-set(items))
    if missing:
        raise ValueError("库存不足，所选接触序列及体积块安装需要："+", ".join(missing))
    placements = [copy.deepcopy(p) for p in req["reference_layout"] if p["id"] in required]
    placements.append({"id": "volume_01", "inventory_id": "volume_01", "u": -.62, "v": .88, "rotation_deg": 0})
    # An optional, unused directional handhold demonstrates a second mounting face
    # without manufacturing stock when the user reduced this template's count.
    if "directional_edge_03" in items:
        placements.append({"id": "directional_edge_03", "inventory_id": "directional_edge_03", "u": 0, "v": 0,
                           "rotation_deg": 0, "mount": {"parent_id": "volume_01", "face_id": "face_2"}})
    for p in placements:
        p["contact_surface_id"] = "face_1_grip" if items[p["inventory_id"]]["type"] == "volume" else "working"
        if p["id"] == "foothold_01":
            p.update(u=-.42, v=.39)
        if p["id"] == "foothold_03":
            p.update(u=0, v=0, rotation_deg=0, mount={"parent_id": "volume_01", "face_id": "face_1"})
    req.update(id=f"request-catalog-{scenario}-{body_id}", profile="catalog", reference_layout=placements)
    req["scene"].update(inventory=inventory, catalog_stock=stock)
    validate_request(req)
    return req


def _competition_request(body, mode, angle_deg, seed, budget):
    # Dimensions and contact locations are illustrative. A volume has one declared
    # foot contact here; no multi-face contact or surface/friction model is implied.
    specs = [
        ("pinch_01", "pinch", (.38, .52, .16), (-1.25, 1.50, -18), [1, -.7, 0]),
        ("rail_01", "rail", (.60, .16, .12), (-.67, 1.64, 28), [-1, -.7, 0]),
        ("sloper_01", "sloper", (.57, .43, .23), (-.22, 2.18, -12), [0, -1, 0]),
        ("pinch_02", "pinch", (.35, .54, .17), (.40, 2.61, -15), [-1, -.5, 0]),
        ("sloper_02", "sloper", (.63, .44, .22), (1.02, 3.20, 16), [0, -1, 0]),
        ("rail_02", "rail", (.62, .18, .13), (1.29, 3.73, -18), [0, -1, 0]),
        ("volume_01", "volume", (.82, .58, .28), (-.65, 1.00, 12), [0, -1, 0]),
        ("foothold_01", "foothold", (.10, .07, .045), (-1.35, .45, -8), [0, -1, 0]),
        ("foothold_02", "foothold", (.10, .07, .045), (-.67, .50, 8), [0, -1, 0]),
        ("foothold_03", "foothold", (.11, .075, .05), (-.10, 1.51, 12), [0, -1, 0]),
        ("foothold_04", "foothold", (.10, .07, .045), (.55, 2.08, -14), [0, -1, 0]),
        ("foothold_05", "foothold", (.12, .08, .05), (.98, 2.52, 6), [0, -1, 0]),
    ]
    inventory, placements = [], []
    for pid, kind, size, position, pull in specs:
        inventory.append({"id": pid, "type": kind, "width": size[0], "height": size[1], "depth": size[2],
                          "source": "synthetic_assumption", "pull_direction": pull,
                          "contact": {"id": "main", "position": [0, 0, size[2]], "radius": .015,
                                      "limbs": list(LIMBS[2:] if kind in {"foothold", "volume"} else LIMBS[:2])}})
        placements.append({"id": pid, "inventory_id": pid, "u": position[0], "v": position[1], "rotation_deg": position[2]})
    req = {"schema_version": "1.0", "id": f"request-competition-{body['id']}", "revision": 1,
           "source": "synthetic_assumption", "profile": "competition",
           "scene": {"width": 4.8, "height": 4.2, "angle_deg": angle_deg, "margin": .2, "inventory": inventory},
           "body": body, "scenario": "competition_sequence", "mode": mode, "hand_moves": 4,
           "seed": seed, "budget": budget, "reference_layout": placements,
           "solver": {"max_nfev": 100, "restarts": 3, "contact_tolerance_m": .015, "epsilon_geometry_m": .000001,
                      "root_bounds": [[-2.3, 2.3], [.35, 3.8], [.08, 1.8]],
                      "root_rotation_deg": [[-35, 35], [-65, 65], [-35, 35]], "timeout_seconds": 12},
           "start_contacts": {"LH": _contact("pinch_01"), "RH": _contact("rail_01"),
                              "LF": _contact("foothold_01"), "RF": _contact("foothold_02")},
           "design_brief": {"title": "对向建立 · 移重抬升 · 延伸收尾",
                            "intent": "沿左下至右上的稀疏线路研究四次手移动，利用不同体量与方向表达动作意图。",
                            "phases": [
                                {"id": "opposition", "label": "对向建立", "event_start": 0, "event_end": 1,
                                 "intent": "先抬左脚，再右手伸向斜面岩点；对向受力尚未验证。"},
                                {"id": "weight_shift", "label": "移重抬升", "event_start": 2, "event_end": 4,
                                 "intent": "右脚上移、左手换捏点、再抬左脚；重心移动尚未验证。"},
                                {"id": "finish", "label": "延伸收尾", "event_start": 5, "event_end": 7,
                                 "intent": "右手到高点，右脚补位后左手收尾；两只手使用分离接触目标。"}],
                            "zone_placement_ids": ["pinch_02"], "top_placement_ids": ["sloper_02", "rail_02"],
                            "source": "competition_inspired_synthetic",
                            "disclaimer": "从比赛影像提炼的合成研究，不是任何比赛线路复刻。尺寸、单点接触与方向均是假设；分离终点不是正式比赛判定模型。"}}
    req["end_contacts"] = copy.deepcopy(req["start_contacts"])
    for limb, hold in _template(req):
        req["end_contacts"][limb] = _contact(hold)
    validate_request(req)
    return req


def contact_world(request, placement, item, placements=None, frames=None, contact_id="main"):
    return geometry_contact_world(request, placement, item, placements, frames, contact_id)


def _corners(placement, item):
    a = math.radians(placement["rotation_deg"])
    r = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    base = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]]) * [item["width"]/2, item["height"]/2]
    return base @ r.T + [placement["u"], placement["v"]]


def _polygon_distance(a, b):
    # OBBs all share wall-normal intervals [0,depth], so their 3D distance is
    # precisely the distance between rotated footprint rectangles.
    separated = False
    for poly in (a, b):
        for i in range(2):
            edge = poly[i+1] - poly[i]
            axis = np.array([-edge[1], edge[0]]) / np.linalg.norm(edge)
            pa, pb = a @ axis, b @ axis
            if pa.max() < pb.min() or pb.max() < pa.min():
                separated = True
    if not separated:
        return 0.0
    best = float("inf")
    for points, edges in ((a, b), (b, a)):
        for p in points:
            for i in range(4):
                u, v = edges[i], edges[(i+1) % 4]
                d = v-u
                t = np.clip(np.dot(p-u, d)/np.dot(d, d), 0, 1)
                best = min(best, float(np.linalg.norm(p-(u+t*d))))
    return best


def _sequence_errors(request, candidate, placements, inventory, *, sequence_policy="request"):
    errors = constraint_errors(request, candidate["placements"], states=candidate["states"])
    states = candidate["states"]
    ids = [s["id"] for s in states]
    if len(set(ids)) != len(ids):
        errors.append("duplicate state id")
    for state in states:
        if not any(state["contacts"].values()):
            errors.append(f"{state['id']}: empty contact state")
        for limb, ref in state["contacts"].items():
            if ref is None:
                continue
            p = placements.get(ref["placement_id"])
            item = inventory.get(p["inventory_id"]) if p else None
            if not item:
                errors.append(f"{state['id']}: unknown {limb} contact")
            else:
                try:
                    if limb not in selected_contact(p, item, ref["contact_id"])["limbs"]:
                        errors.append(f"{state['id']}: disallowed limb {limb}")
                except ValueError as exc:
                    errors.append(str(exc))
    if states[0]["contacts"] != request["start_contacts"]:
        errors.append("start contacts do not match request")
    end = request["end_contacts"]
    if request.get("profile") in ("route", "setting"):
        if any(ref is not None and states[-1]["contacts"][limb] != ref for limb, ref in end.items()):
            errors.append("end contacts do not match request")
    elif states[-1]["contacts"] != end:
        errors.append("end contacts do not match request")
    if len(states) != 1 + 2*len(candidate["events"]):
        errors.append("event/state chain length mismatch")
    hand_moves = 0
    foot_moves = 0
    for i, event in enumerate(candidate["events"]):
        if 2*i+2 >= len(states):
            break
        before, release, after = states[2*i:2*i+3]
        if [event["from_state"], event["release_state"], event["to_state"]] != [before["id"], release["id"], after["id"]]:
            errors.append(f"event {i}: broken state references")
        limb = event["limb"]
        if before["contacts"][limb] is None or release["contacts"][limb] is not None or after["contacts"][limb] is None:
            errors.append(f"event {i}: expected contact -> null -> contact")
        for other in LIMBS:
            if other != limb and not before["contacts"][other] == release["contacts"][other] == after["contacts"][other]:
                errors.append(f"event {i}: changed undeclared limb {other}")
        if before["contacts"][limb] != after["contacts"][limb]:
            if limb.endswith("H"):
                hand_moves += 1
            else:
                foot_moves += 1
    if sequence_policy == "request" and request.get("profile") != "setting" and hand_moves != request["hand_moves"]:
        errors.append(f"hand_moves={hand_moves}, requested={request['hand_moves']}")
    events = candidate["events"]
    required_feet = 2 if request["scenario"] == "foot_reposition" else (1 if request["scenario"] == "foot_first" else 0)
    for i in range(required_feet):
        if i >= len(events) or 2*i+2 >= len(states):
            errors.append("scenario requires initial foot relocations")
            break
        limb = events[i]["limb"]
        if not limb.endswith("F") or states[2*i]["contacts"][limb] == states[2*i+2]["contacts"][limb]:
            errors.append(f"event {i}: scenario requires actual foot relocation, not release/regrab")
    if request["scenario"] == "competition_sequence":
        expected = _template(request)
        if len(events) != len(expected):
            errors.append("competition_sequence requires four hand transfers with four intervening foot relocations")
        for i, (limb, pid) in enumerate(expected):
            if i >= len(events) or 2*i+2 >= len(states):
                break
            if events[i]["limb"] != limb or states[2*i+2]["contacts"][limb] != _contact(pid):
                errors.append(f"event {i}: competition study phase/target does not match request")
    return errors, hand_moves, foot_moves


def _skeleton_wall_check(scene, pose):
    """Independent P0 evidence, separate from IK's optimization objective."""
    if not scene.get("wall_panels"):
        return None
    from .wall_clearance import wall_clearance_report
    if pose["status"] == "pass":
        evidence = wall_clearance_report(scene, pose["joints"])
        status = evidence["status"]
    else:
        status = "unknown" if pose["status"] == "unknown" else "not_checked"
        evidence = {"reason": "verified_skeleton_unavailable", "pose_status": pose["status"]}
    return {"id": "skeleton_wall", "status": status, "label": "骨架与有限墙板",
            "detail": "独立复核离散姿态的骨架中心线是否穿过墙板；不验证人体厚度、岩点碰撞或连续动作。",
            "state_id": pose["state_id"], "scope": "P0", "evidence": evidence}


def evaluate(request, candidate, *, sequence_policy="request", deadline=None, include_design_analysis=True):
    if sequence_policy not in ("request", "independent_beta"):
        raise ValueError("unknown sequence policy")
    if sequence_policy == "independent_beta" and request.get("profile") not in ("route", "setting"):
        raise ValueError("independent beta evaluation requires route or setting profile")
    if deadline is not None and (isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline)):
        raise ValueError("deadline must be a finite monotonic-clock timestamp")
    started = time.perf_counter()
    checks, poses = [], []

    def check(id, status, label, detail, **extra):
        checks.append(dict(id=id, status=status, label=label, detail=detail, **extra))

    try:
        validate_request(request)
        _schema(candidate, "candidate")
        fp = fingerprint(request, candidate)
    except (ValueError, TypeError, KeyError) as exc:
        check("schema", "fail", "数据结构", str(exc))
        fp = None
    if fp is not None:
        check("schema", "pass", "数据结构", "版本、有限数和必要字段符合契约。")
        inventory = {h["id"]: h for h in request["scene"]["inventory"]}
        placements = {p["id"]: p for p in candidate["placements"]}
        used = [p["inventory_id"] for p in candidate["placements"]]
        errors = []
        if len(inventory) != len(request["scene"]["inventory"]):
            errors.append("duplicate inventory id")
        if len(placements) != len(candidate["placements"]):
            errors.append("duplicate placement id")
        if len(used) != len(set(used)):
            errors.append("inventory instance installed more than once")
        if any(i not in inventory for i in used):
            errors.append("unknown inventory instance")
        frames, mount_errors, valid_mounts = {}, [], set()
        eps = request["solver"]["epsilon_geometry_m"]
        has_mounting = request.get("profile") == "catalog" or any("mount" in p for p in candidate["placements"])
        if not errors:
            try:
                frames = placement_frames(candidate["placements"], inventory, request["scene"]["angle_deg"], request["scene"].get("wall_panels"))
                mount_errors, valid_mounts = mounting_fit(candidate["placements"], inventory, eps)
            except ValueError as exc:
                errors.append(str(exc))
        check("inventory", "fail" if errors else "pass", "库存与引用", "; ".join(errors) or "每个实例最多安装一次。")
        seq_errors, hands, feet = _sequence_errors(request, candidate, placements, inventory, sequence_policy=sequence_policy)
        check("request_conformance", "fail" if seq_errors else "pass", "接触顺序与目标", "; ".join(seq_errors) or "释放、换点和起终点符合请求。",
              evidence={"hand_moves": hands, "foot_moves": feet})
        locked_ok = request["mode"] != "fixed" or canonical_hash({"placements": candidate["placements"]}) == canonical_hash({"placements": request["reference_layout"]})
        check("fixed_layout", "pass" if locked_ok else "fail", "布局模式", "自由变量允许修改。" if request["mode"] == "free" else ("固定布局未改变。" if locked_ok else "固定布局被修改。"))
        if has_mounting:
            check("mounting", "not_checked" if errors else ("fail" if mount_errors else "pass"), "体积块安装面",
                  "被无效安装引用阻断。" if errors else "子岩点完整底面必须落在父块三角斜面内；仅有效直接父子对豁免包围体碰撞。",
                  placement_ids=[e["placement_id"] for e in mount_errors], evidence={"errors": mount_errors, "valid_parent_child_pairs": [sorted(pair) for pair in sorted(valid_mounts, key=lambda p: sorted(p))]}, scope="P0")
        if not errors:
            scene = request["scene"]
            lower = np.array([-scene["width"]/2 + scene["margin"], scene["margin"]])
            upper = np.array([scene["width"]/2 - scene["margin"], scene["height"]-scene["margin"]])
            to_wall = wall_basis(scene["angle_deg"]).T
            footprints = {p["id"]: (box_corners(inventory[p["inventory_id"]], frames[p["id"]]) @ to_wall.T)[:, :2] for p in candidate["placements"]}
            if scene.get("wall_panels"):
                panel_errors = panel_fit(candidate["placements"], inventory, scene, eps)
                outside = [entry["placement_id"] for entry in panel_errors]
                check("boundary", "fail" if outside else "pass", "安装边界", "完整底面须位于所属墙板 0.2 m 边距内；体积块子点另验父安装面。", placement_ids=outside,
                      evidence={"panel_errors": panel_errors, "epsilon_m": eps, "basis": "own_wall_panel_local_coordinates"})
            else:
                outside = [pid for pid, corners in footprints.items() if np.any(corners < lower-eps) or np.any(corners > upper+eps)]
                check("boundary", "fail" if outside else "pass", "安装边界", "完整投影须在留出 0.2 m 边距的区域内。", placement_ids=outside,
                      evidence={"lower_uv": lower.tolist(), "upper_uv": upper.tolist(), "epsilon_m": eps})
            collisions = []
            for a, b in itertools.combinations(footprints, 2):
                if frozenset((a, b)) in valid_mounts:
                    continue
                separation = obb_separation(inventory[placements[a]["inventory_id"]], frames[a], inventory[placements[b]["inventory_id"]], frames[b])
                if separation <= eps:
                    collisions.append({"placements": [a, b], "separation_m": separation})
            check("hold_collision", "fail" if collisions else "pass", "岩点包围体", "接触或间距不大于容差按冲突处理。",
                  placement_ids=sorted({p for c in collisions for p in c["placements"]}), evidence={"conflicts": collisions, "epsilon_m": eps, "proxy": "full_3D_OBB_15_axis_SAT", "parent_child_exemptions": [sorted(pair) for pair in sorted(valid_mounts, key=lambda p: sorted(p))]})
        else:
            for id, label in [("boundary", "安装边界"), ("hold_collision", "岩点包围体")]:
                check(id, "not_checked", label, "被无效库存引用阻断。", scope="P0")
        if not errors and not seq_errors and not mount_errors:
            previous_q = None
            body = request["body"]
            for index, state in enumerate(candidate["states"]):
                targets = {l: contact_world(request, placements[r["placement_id"]], inventory[placements[r["placement_id"]]["inventory_id"]], candidate["placements"], frames, r["contact_id"])
                           for l, r in state["contacts"].items() if r is not None}
                span_fail = False
                if "LH" in targets and "RH" in targets:
                    d = float(np.linalg.norm(targets["LH"]-targets["RH"]))
                    offsets = sum(float(np.linalg.norm(body["endpoint_offsets"][l])) for l in ("LH", "RH"))
                    bound = contact_distance_bound(body, "LH", "RH", request["solver"]["contact_tolerance_m"])
                    span_fail = d > bound + eps
                    check("hand_span", "fail" if span_fail else "pass", "双手距离必要上界", "仅检查声明骨架的保守必要条件。", state_id=state["id"],
                          evidence={"distance_m": d, "bound_m": bound, "shoulder_width": body["shoulder_width"], "upper_arm": body["upper_arm"], "forearm": body["forearm"], "endpoint_offset_sum_m": offsets, "fingerprint": fp})
                if span_fail:
                    pose = {"state_id": state["id"], "status": "not_checked", "residual_m": None}
                    check("ik", "not_checked", "接触姿态 IK", "已由必要上界判定违反模型约束。", state_id=state["id"], scope="P0")
                else:
                    remaining = None if deadline is None else deadline-time.perf_counter()
                    if remaining is not None and remaining <= 0:
                        pose = {"status": "unknown", "residual_m": None, "evidence": {"reason": "shared_audit_time_budget", "attempts": 0}}
                    else:
                        solver = request["solver"] if remaining is None else dict(request["solver"], timeout_seconds=min(request["solver"].get("timeout_seconds", 15), remaining))
                        pose = solve_pose(body, targets, solver, seed=request["seed"]+index, initial=previous_q,
                                          scene=request["scene"])
                    pose["state_id"] = state["id"]
                    if pose["status"] == "pass":
                        previous_q = pose["q"]
                    check("ik", pose["status"], "接触姿态 IK", "同一骨架的离散接触姿态；动态转换未检查。", state_id=state["id"],
                          evidence={"residual_m": pose["residual_m"], **pose.get("evidence", {})})
                poses.append(pose)
                wall_check = _skeleton_wall_check(request["scene"], pose)
                if wall_check is not None:
                    checks.append(wall_check)
        else:
            check("ik", "not_checked", "接触姿态 IK", "被无效接触序列、库存引用或安装面约束阻断。", scope="P0")
    else:
        for id in ("inventory", "request_conformance", "fixed_layout", "boundary", "hold_collision", "ik"):
            check(id, "not_checked", id, "被无效输入阻断。", scope="P0")
    for id, label in P1_CHECKS:
        detail = "P0 未验证，不得据此判断真人可攀、难度或安全。"
        if "mechanics_parameters" in request and id in ("force", "balance"):
            label = "真实抓握与摩擦能力" if id == "force" else "真实稳定性与运动"
            detail = "真实抓握能力、摩擦与稳定性未测量/标定；当前姿态的合成准静态检查单列，不能代替真人试爬或动态分析。"
        check(id, "not_checked", label, detail, scope="P1")
    p0 = [c for c in checks if c.get("scope") != "P1"]
    summary = "fail" if any(c["status"] == "fail" for c in p0) else ("pass" if all(c["status"] == "pass" for c in p0) else "unknown")
    result = {"id": f"eval-{candidate.get('id', 'invalid')}-{(fp or 'invalid')[-10:]}", "candidate_id": candidate.get("id"),
            "fingerprint": fp, "version": VERSION, "checks": checks, "poses": poses,
            "summary": {"status": summary, "passed": sum(c["status"] == "pass" for c in p0), "total": len(p0)},
            "elapsed_ms": round((time.perf_counter()-started)*1000, 2)}
    if sequence_policy != "request":
        result["sequence_policy"] = sequence_policy
    if include_design_analysis and request.get("profile") in ("style", "route", "setting") and fp is not None and sequence_policy == "request":
        try:
            result["design_analysis"] = (analyze_setting if request.get("profile") == "setting" else analyze_full_route if request.get("profile") == "route" else analyze_route)(request, candidate)
        except (ValueError, TypeError, KeyError, IndexError):
            result["design_analysis"] = None
    if "mechanics_parameters" in request and fp is not None:
        from .statics import mechanics_report
        result["mechanics_report"] = mechanics_report(request, candidate, result)
    return result


def propose(request, index=0):
    validate_request(request)
    if request.get("profile") in ("style", "route", "setting"):
        candidates = (search_settings if request.get("profile") == "setting" else search_full_routes if request.get("profile") == "route" else search_routes)(request)
        if index >= len(candidates):
            raise ValueError("style search returned fewer distinct candidates than requested index")
        return candidates[index]
    rng = np.random.default_rng(request["seed"] + index)
    placements = copy.deepcopy(request["reference_layout"])
    if request["mode"] == "free" and index > 0:
        for p in placements:
            if request["scenario"] == "competition_sequence":
                # A bounded template search, not a learned routesetter or a
                # success-filtered search. Every attempted layout is evaluated.
                spread = [.0, -.04, .035][index % 3]
                p["u"] = round(p["u"] * (1 + spread) + rng.uniform(-.012, .012), 5)
                p["v"] = round(p["v"] + rng.uniform(-.012, .012), 5)
                p["rotation_deg"] = round(p["rotation_deg"] + rng.uniform(-3, 3), 3)
            else:
                p["u"] = round(p["u"] + rng.uniform(-.022, .022), 5)
                p["v"] = round(p["v"] + rng.uniform(-.018, .018), 5)
                p["rotation_deg"] = round(p["rotation_deg"] + rng.uniform(-7, 7), 3)
    states = [{"id": "s0", "label": "起始接触", "contacts": copy.deepcopy(request["start_contacts"])}]
    events = []
    for i, (limb, pid) in enumerate(_template(request, index)):
        before = states[-1]
        released = copy.deepcopy(before["contacts"])
        released[limb] = None
        after = copy.deepcopy(released)
        after[limb] = _contact(pid)
        rid, tid = f"s{2*i+1}", f"s{2*i+2}"
        states.extend([{"id": rid, "label": f"{limb} 释放", "contacts": released},
                       {"id": tid, "label": f"{limb} → {pid}", "contacts": after}])
        events.append({"limb": limb, "from_state": before["id"], "release_state": rid, "to_state": tid})
    competition = request["scenario"] == "competition_sequence"
    catalog = request.get("profile") == "catalog"
    variation = "固定参照" if request["mode"] == "fixed" else ["基准走向", "收紧横距", "展开横距"][index % 3]
    return {"id": f"candidate-{request['seed']}-{index+1}", "name": (f"研究 {index+1} · {variation}" if competition else f"方案 {index+1} · {'固定参照' if request['mode']=='fixed' else '自由布局'}"),
            "revision": 1, "parent_id": None, "generator": "rules", "placements": placements, "states": states, "events": events,
            "design_notes": (["七款标准模板按实际库存分配；未安装实例保留在岩点库中。",
                              "抓握/踩踏面来自程序表面的采样；方向为设计声明，不是接触力。",
                              "小岩点可安装到三角体积块的真实斜面；完整底面须在面内，其他物体仍做三维包围体检查。",
                              "合成接触与离散姿态不代表抓握、摩擦、平衡或真人可攀性。"] if catalog else
                             ["四次手移动：对向建立 → 换脚移重 → 分离接触收尾，均为设计意图。",
                              "宏型岩点与体积块采用外接矩形和单点接触；不代表真实可用抓握面。",
                              f"模板搜索：{variation}。所有尝试保留，相同预算与检查器评估，不按通过结果筛选。",
                              "摩擦、抓握、平衡、碰撞和连续动作尚未验证；未收敛只能记为未知。"] if competition else
                             ["合成模板：有限点位与接触序列变化。", "侧向箭头仅表示设计意图；受力、稳定性和连续动作仍未验证。"])}


def _bundle_digest(bundle):
    return canonical_hash({k: v for k, v in bundle.items() if k not in {"manifest", "reviews"}} | {
        "manifest": {k: v for k, v in bundle["manifest"].items() if k != "bundle_digest"}})


def make_bundle(request, candidates, evaluations=None):
    validate_request(request)
    candidates = copy.deepcopy(candidates)
    for candidate in candidates:
        _schema(candidate, "candidate")
    if len({c["id"] for c in candidates}) != len(candidates):
        raise ValueError("duplicate candidate ids")
    if evaluations is None:
        evaluations = [evaluate(request, c) for c in candidates]
    bundle = {"schema_version": "1.0", "id": "bundle-"+canonical_hash(request)[-10:]+f"-{time.time_ns()}",
              "created_at": datetime.now(timezone.utc).isoformat(), "request": copy.deepcopy(request),
              "candidates": candidates, "evaluations": copy.deepcopy(evaluations),
              "manifest": {"engine_version": VERSION, "code_hash": code_hash(), "source": "synthetic_assumption",
                           "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                           "attempted_candidates": len(candidates), "candidate_budget": request["budget"],
                           "evaluation_count": len(evaluations), "seed": request["seed"],
                           "limitations": [label for _, label in P1_CHECKS]}, "reviews": []}
    bundle["manifest"]["bundle_digest"] = _bundle_digest(bundle)
    return validate_bundle(bundle)


def generate(request, strategy="rules"):
    if strategy != "rules":
        raise ValueError("Only rules generation is implemented. Codex/manual proposals must be supplied explicitly to evaluate().")
    validate_request(request)
    candidates = search_settings(request) if request.get("profile") == "setting" else search_full_routes(request) if request.get("profile") == "route" else search_routes(request) if request.get("profile") == "style" else [propose(request, i) for i in range(request["budget"])]
    if request.get("profile") == "setting":
        deadline = time.perf_counter()+60
        return make_bundle(request, candidates, [evaluate(request, c, deadline=deadline) for c in candidates])
    return make_bundle(request, candidates)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_evaluation(request, candidate, evaluation):
    restrictions = constraint_errors(request, candidate["placements"], states=candidate["states"])
    if restrictions:
        raise ValueError("; ".join(restrictions))
    if "layout_report" in candidate:
        report = candidate["layout_report"]
        if request.get("profile") != "setting" or request["setting_design"].get("wall_profile", "default") == "default" or report["wall_profile"] != request["setting_design"]["wall_profile"]:
            raise ValueError("layout-only report requires the same nondefault setting wall profile")
    statuses = {"pass", "fail", "unknown", "not_checked"}
    if not isinstance(evaluation, dict) or not all(k in evaluation for k in ("id", "candidate_id", "fingerprint", "version", "checks", "poses", "summary", "elapsed_ms")):
        raise ValueError("evaluation missing required fields")
    if evaluation.get("sequence_policy", "request") != "request":
        raise ValueError("independent beta evaluation belongs to an audit report, not a generation bundle")
    if not isinstance(evaluation["id"], str) or not evaluation["id"] or evaluation["candidate_id"] != candidate["id"]:
        raise ValueError("invalid evaluation identity")
    if not _number(evaluation["elapsed_ms"]) or evaluation["elapsed_ms"] < 0:
        raise ValueError("invalid evaluation elapsed_ms")
    if evaluation["version"] != VERSION or evaluation["fingerprint"] != fingerprint(request, candidate):
        raise ValueError("stale evaluation fingerprint")
    if request.get("profile") in ("style", "route", "setting"):
        try:
            expected_analysis = (analyze_setting if request.get("profile") == "setting" else analyze_full_route if request.get("profile") == "route" else analyze_route)(request, candidate)
        except (ValueError, TypeError, KeyError, IndexError):
            expected_analysis = None
        if evaluation.get("design_analysis") != expected_analysis:
            raise ValueError("design analysis mismatch; recomputation required")
    elif "design_analysis" in evaluation:
        raise ValueError("design analysis requires style or route profile")
    if "mechanics_parameters" in request:
        from .statics import mechanics_report
        if evaluation.get("mechanics_report") != mechanics_report(request, candidate, evaluation):
            raise ValueError("mechanics report mismatch; recomputation required")
    elif "mechanics_report" in evaluation:
        raise ValueError("mechanics report requires explicit model parameters")
    if "setting_report" in candidate:
        from .setting import validate_setting_report
        validate_setting_report(request, candidate, evaluation)
    checks, poses = evaluation["checks"], evaluation["poses"]
    if not isinstance(checks, list) or not checks or not isinstance(poses, list):
        raise ValueError("checks/poses must be arrays")
    state_map = {s["id"]: s for s in candidate["states"]}
    placement_map = {p["id"]: p for p in candidate["placements"]}
    p1 = {id for id, _ in P1_CHECKS}
    allowed = p1 | {"schema", "inventory", "request_conformance", "fixed_layout", "boundary", "hold_collision", "hand_span", "ik", "mounting", "skeleton_wall"}
    seen = set()
    for c in checks:
        if not isinstance(c, dict) or any(not isinstance(c.get(k), str) for k in ("id", "status", "label", "detail")):
            raise ValueError("malformed check record")
        if c["id"] not in allowed or c["status"] not in statuses:
            raise ValueError("unknown check id/status")
        key = (c["id"], c.get("state_id"))
        if key in seen:
            raise ValueError("duplicate check record")
        seen.add(key)
        if "state_id" in c and c["state_id"] not in state_map:
            raise ValueError("check references unknown state")
        if "placement_ids" in c and (not isinstance(c["placement_ids"], list) or any(p not in placement_map for p in c["placement_ids"])):
            raise ValueError("check references unknown placement")
        if "evidence" in c and not isinstance(c["evidence"], dict):
            raise ValueError("check evidence must be a record")
        if c["id"] in p1:
            if c["status"] != "not_checked" or c.get("scope") != "P1":
                raise ValueError("unsupported P1 claim")
        elif c.get("scope") not in (None, "P0"):
            raise ValueError("P0 check cannot be excluded from summary")
    for id in p1 | {"schema", "inventory", "request_conformance", "fixed_layout", "boundary", "hold_collision"}:
        if (id, None) not in seen:
            raise ValueError(f"missing check {id}")
    if (request.get("profile") == "catalog" or any("mount" in p for p in candidate["placements"])) and ("mounting", None) not in seen:
        raise ValueError("missing mounting check")
    p0 = [c for c in checks if c["id"] not in p1]
    status = "fail" if any(c["status"] == "fail" for c in p0) else ("pass" if all(c["status"] == "pass" for c in p0) else "unknown")
    expected = {"status": status, "passed": sum(c["status"] == "pass" for c in p0), "total": len(p0)}
    if evaluation["summary"] != expected or any(isinstance(evaluation["summary"].get(k), bool) for k in ("passed", "total")):
        raise ValueError("summary inconsistent with P0 checks")
    lo, hi = joint_bounds(request["body"], request["solver"])
    inventory = {h["id"]: h for h in request["scene"]["inventory"]}
    pose_ids = set()
    for pose in poses:
        if not isinstance(pose, dict) or pose.get("state_id") not in state_map or pose.get("status") not in statuses:
            raise ValueError("malformed pose identity/status")
        sid = pose["state_id"]
        if sid in pose_ids:
            raise ValueError("duplicate pose state")
        pose_ids.add(sid)
        matching = [c for c in checks if c["id"] == "ik" and c.get("state_id") == sid]
        if len(matching) != 1 or matching[0]["status"] != pose["status"]:
            raise ValueError("pose and IK check disagree")
        expected_wall_check = _skeleton_wall_check(request["scene"], pose)
        wall_checks = [c for c in checks if c["id"] == "skeleton_wall" and c.get("state_id") == sid]
        if wall_checks != ([expected_wall_check] if expected_wall_check is not None else []):
            raise ValueError("skeleton-wall check missing or inconsistent with verified joints and finite panels")
        if pose["status"] != "pass":
            if "joints" in pose or "q" in pose:
                raise ValueError("unverified pose cannot contain rendered skeleton")
            if pose.get("residual_m") is not None and (not _number(pose["residual_m"]) or pose["residual_m"] < 0):
                raise ValueError("invalid pose residual")
            continue
        q = pose.get("q")
        if not isinstance(q, list) or len(q) != 22 or not all(_number(v) for v in q):
            raise ValueError("pass pose requires finite q[22]")
        if np.any(np.asarray(q) < lo-1e-9) or np.any(np.asarray(q) > hi+1e-9):
            raise ValueError("pose violates frozen joint/root bounds")
        expected_joints = forward_kinematics(request["body"], q)
        joints = pose.get("joints")
        if not isinstance(joints, dict) or set(joints) != set(expected_joints):
            raise ValueError("pass pose missing skeleton joints")
        for name, xyz in joints.items():
            if not isinstance(xyz, list) or len(xyz) != 3 or not all(_number(v) for v in xyz):
                raise ValueError("joint requires finite xyz[3]")
            if not np.allclose(xyz, expected_joints[name], atol=1e-8, rtol=0):
                raise ValueError("pose joints do not match forward kinematics")
        endpoints = contact_endpoints(request["body"], q)
        errors = []
        for limb, ref in state_map[sid]["contacts"].items():
            if ref is not None:
                p = placement_map[ref["placement_id"]]
                errors.append(float(np.linalg.norm(endpoints[limb]-contact_world(request, p, inventory[p["inventory_id"]], candidate["placements"], contact_id=ref["contact_id"]))))
        worst = max(errors, default=float("inf"))
        if not _number(pose.get("residual_m")) or abs(pose["residual_m"]-worst) > 1e-8 or worst > request["solver"]["contact_tolerance_m"]:
            raise ValueError("pass pose contacts/residual not verified")
    state_ik = {c["state_id"] for c in checks if c["id"] == "ik" and "state_id" in c}
    if state_ik != pose_ids:
        raise ValueError("IK checks and pose records do not correspond")
    wall_state_ids = {c.get("state_id") for c in checks if c["id"] == "skeleton_wall"}
    if wall_state_ids != (pose_ids if request["scene"].get("wall_panels") else set()):
        raise ValueError("skeleton-wall checks and pose records do not correspond")
    if status == "pass" and pose_ids != set(state_map):
        raise ValueError("all-pass evaluation must cover every state")


def _validate_reviews(bundle):
    reviews = bundle.get("reviews", [])
    if not isinstance(reviews, list) or len(reviews) > 10000:
        raise ValueError("reviews must be a bounded record array")
    candidates = {c["id"]: c for c in bundle["candidates"]}
    for review in reviews:
        if not isinstance(review, dict) or any(not isinstance(review.get(k), str) for k in ("id", "candidate_id", "kind", "text", "created_at")):
            raise ValueError("review requires string identity/text/date fields")
        if review["kind"] != "design_review" or review["candidate_id"] not in candidates:
            raise ValueError("review kind/candidate is invalid")
        if type(review.get("candidate_revision")) is not int or review["candidate_revision"] < 1:
            raise ValueError("review revision is invalid")
        for key in ("evaluation_id", "evaluation_fingerprint", "state_id", "placement_id"):
            if review.get(key) is not None and not isinstance(review[key], str):
                raise ValueError(f"review {key} must be string/null")


def validate_bundle(bundle):
    _finite(bundle)
    try:
        if bundle["schema_version"] != "1.0":
            raise ValueError("unknown bundle schema version")
        validate_request(bundle["request"])
        if bundle["manifest"]["engine_version"] != VERSION or bundle["manifest"]["code_hash"] != code_hash():
            raise ValueError("stale evaluator version/code hash; re-evaluation required")
        if bundle["manifest"]["bundle_digest"] != _bundle_digest(bundle):
            raise ValueError("bundle integrity mismatch; source or results changed")
        candidates = bundle["candidates"]
        evals = bundle["evaluations"]
        if not isinstance(candidates, list) or not candidates or len(candidates) > 100 or len(evals) > len(candidates):
            raise ValueError("invalid candidate/evaluation counts")
        if len({c["id"] for c in candidates}) != len(candidates) or len({e["candidate_id"] for e in evals}) != len(evals):
            raise ValueError("duplicate candidate/evaluation IDs")
        evaluation_map = {e["candidate_id"]: e for e in evals}
        if set(evaluation_map) - {c["id"] for c in candidates}:
            raise ValueError("evaluation references unknown candidate")
        for candidate in candidates:
            _schema(candidate, "candidate")
            restrictions = constraint_errors(bundle["request"], candidate["placements"], states=candidate["states"])
            if restrictions:
                raise ValueError("; ".join(restrictions))
            if candidate["id"] not in evaluation_map:
                continue
            evaluation = evaluation_map[candidate["id"]]
            _validate_evaluation(bundle["request"], candidate, evaluation)
        _validate_reviews(bundle)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"malformed bundle: {exc}") from exc
    return copy.deepcopy(bundle)
