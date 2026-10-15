"""One synthetic gym in shared metres, with explicit editable installation areas.

The existing setting seeds remain local to their wall. Translating a bay shifts
both its actual panels and root bounds; other bays and installed neighbours stay
in the request as collision context, never as available route contacts.
"""
from __future__ import annotations

import copy
import math
from functools import lru_cache

from .wall_profiles import panels_for

GYM_ID = "bettar-demo"
GYM_VERSION = "demo-gym-1"
REGIONS = (
    {"id": "overhang-bay", "name": "左侧仰角", "wall_profile": "overhang", "offset_x": -5.,
     "panel_ids": ["overhang"]},
    {"id": "roof-exit", "name": "中部屋檐出口", "wall_profile": "roof", "offset_x": 0.,
     "panel_ids": ["lower-wall", "roof", "upper-wall"]},
    {"id": "corner-bay", "name": "右侧凹角", "wall_profile": "dihedral", "offset_x": 5.,
     "panel_ids": ["left-wall", "right-wall"]},
)


def get_region(gym_id, region_id):
    if gym_id != GYM_ID:
        raise ValueError("未知示例岩馆。")
    region = next((r for r in REGIONS if r["id"] == region_id), None)
    if region is None:
        raise ValueError("未知定线区域。")
    result = copy.deepcopy(region)
    result["label"] = result["name"]
    result["patches"] = [{"wall_panel_id": p["id"],
        "u_min": -1.55 if p["width"] > 3 else -p["width"]/2,
        "u_max": 1.15 if p["width"] > 3 else p["width"]/2,
        "v_min": .2, "v_max": min(p["height"]-.2, 3.8)}
        for p in panels_for(region["wall_profile"])]
    return result


def all_panels():
    result = []
    for region in REGIONS:
        panels = panels_for(region["wall_profile"])
        for panel in panels:
            panel["origin"][0] += region["offset_x"]
        result.extend(panels)
    return result


def fit_region(request):
    """Clamp complete ordinary hold footprints to the active installation patch."""
    region = request.get("route_constraints", {}).get("installation_region")
    if not region:
        return []
    patches = {p["wall_panel_id"]: p for p in region["patches"]}
    editable = set(region["editable_placement_ids"])
    inventory = {i["id"]: i for i in request["scene"]["inventory"]}
    changes = []
    for point in request["reference_layout"]:
        if point["id"] not in editable:
            continue
        if "mount" in point or point.get("wall_panel_id") not in patches:
            raise ValueError(f"{point['id']}: 安装面不在本次定线区域。")
        patch, item = patches[point["wall_panel_id"]], inventory[point["inventory_id"]]
        angle = math.radians(point["rotation_deg"])
        c, s = abs(math.cos(angle)), abs(math.sin(angle))
        hu, hv = (c*item["width"]+s*item["height"])/2, (s*item["width"]+c*item["height"])/2
        limits = ((patch["u_min"]+hu, patch["u_max"]-hu), (patch["v_min"]+hv, patch["v_max"]-hv))
        if any(lo > hi for lo, hi in limits):
            raise ValueError(f"{point['id']}: 岩点安装占地放不进所选区域。")
        before = copy.deepcopy(point)
        for key, (lo, hi) in zip(("u", "v"), limits):
            point[key] = max(lo, min(hi, point[key]))
        if point != before:
            changes.append({"placement_id": point["id"], "before": before, "after": copy.deepcopy(point),
                            "reason": "fit complete hold footprint inside the selected installation region"})
    return changes


@lru_cache(maxsize=1)
def _neighbour_stock():
    from .engine import default_request
    stock = {}
    # These are intentionally sparse, fixed demonstration installations. They
    # do not pretend to be checked neighbouring routes or real gym inventory.
    for region in REGIONS:
        request = default_request(profile="setting", setting_program="diagonal_balance",
            wall_profile=region["wall_profile"], hold_source="assets", seed=42, budget=1)
        selected = {"start-left", "hand-2", "hand-4", "top", "start-foot-left", "foot-3", "foot-6"}
        inventory = {i["id"]: i for i in request["scene"]["inventory"]}
        points, items = [], []
        for point in request["reference_layout"]:
            if point["id"] not in selected:
                continue
            point = copy.deepcopy(point)
            item = copy.deepcopy(inventory[point["inventory_id"]])
            prefix = f"context-{region['id']}-"
            point["id"] = prefix+point["id"]
            point["inventory_id"] = item["id"] = prefix+item["id"]
            points.append(point); items.append(item)
        stock[region["id"]] = {"placements": points, "inventory": items}
    return stock


def apply_gym(request, gym_id, region_id):
    """Attach frozen gym context to a generated, still region-local seed."""
    from .route_constraints import allowed_contact_ids
    region = get_region(gym_id, region_id)
    if request["setting_design"]["wall_profile"] != region["wall_profile"]:
        raise ValueError("所选墙形与定线区域不一致。")
    editable = [p["id"] for p in request["reference_layout"]]
    request["scene"]["wall_panels"] = all_panels()
    request["solver"]["root_bounds"][0] = [x+region["offset_x"] for x in request["solver"]["root_bounds"][0]]
    fixed = []
    for other, data in _neighbour_stock().items():
        if other == region_id:
            continue
        request["scene"]["inventory"].extend(copy.deepcopy(data["inventory"]))
        fixed.extend(copy.deepcopy(data["placements"]))
    request["reference_layout"].extend(copy.deepcopy(fixed))
    mask = {limb: sorted(ids & set(editable)) for limb, ids in allowed_contact_ids(request, request["reference_layout"]).items()}
    request["route_constraints"] = {"allowed_contacts": mask, "installation_region": {
        "gym_id": GYM_ID, "gym_version": GYM_VERSION, "region_id": region_id,
        "patches": copy.deepcopy(region["patches"]), "editable_placement_ids": editable,
        "fixed_placements": fixed}}
    return fit_region(request)


@lru_cache(maxsize=1)
def _metadata():
    from .engine import default_request, validate_request
    request = default_request(profile="setting", setting_program="diagonal_balance",
        wall_profile="overhang", hold_source="assets", seed=42, budget=1)
    apply_gym(request, GYM_ID, "overhang-bay")
    validate_request(request)
    # No solve, no evaluation, no invented path. The frontend renders only
    # structural context and installed preview geometry until generation.
    candidate = {"id": "gym-preview", "name": "示例岩馆", "revision": 1, "parent_id": None,
        "generator": "rules", "placements": copy.deepcopy(request["reference_layout"]),
        "states": [], "events": [], "read_only": True, "design_notes": ["只读场地预览，未生成线路、未检查走法。"]}
    return {"id": GYM_ID, "name": "bettar 示例岩馆", "version": GYM_VERSION, "revision": 1,
        "description": "演示场地与模拟库存；三处墙区共用真实比例坐标，尚未经实测或现场试攀。",
        "scene": copy.deepcopy(request["scene"]),
        "regions": [get_region(GYM_ID, r["id"]) for r in REGIONS],
        "preview": {"request": request, "candidate": candidate}}


def gym_metadata():
    return copy.deepcopy(_metadata())
