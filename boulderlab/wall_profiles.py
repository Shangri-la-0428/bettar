"""Developed setting seeds on continuous structural wall panels.

These are explicit demonstration structures, not surveyed gym architecture.
Local contact coordinates and normals inherit the real panel transforms.
"""
from __future__ import annotations

import math
import numpy as np

from .geometry import rotation_xyz, selected_contact, placement_frames, panel_fit, obb_separation

PROFILES = {
    "default": "原场景墙形",
    "overhang": "25°仰角",
    "roof": "立面—水平屋檐—出口",
    "dihedral": "凹角 · 110°内角",
    "arete": "凸角 · 外棱",
}
LIMITATIONS = [
    "这是同一空间种子在声明墙形上的适配实验，尚未经定线员现场试攀。墙板位置、安装点和法向参与实际计算。",
    "墙形角度是相对基础墙坐标的角度；scene.angle_deg 会整体旋转所有墙板。整体倾角为0°时屋檐段水平。",
    "墙板为无厚度结构面；未验证墙体强度、完整人体与墙面碰撞、屋檐跨角连续运动。",
    "当前走法搜索采用投影高度与窄接触走廊剪枝，屋檐、转角上的合理解可能被排除；无完整序列不等于线路不可攀。",
]


def panels_for(profile):
    if profile not in PROFILES or profile == "default":
        raise ValueError("explicit wall profile required")
    if profile == "overhang":
        return [{"id": "overhang", "label": "25°仰角面", "origin": [0, 0, 0],
                 "rotation_deg": [25, 0, 0], "width": 4.8, "height": 4.2}]
    if profile == "roof":
        return [
            {"id": "lower-wall", "label": "屋檐前立面", "origin": [0, 0, 0],
             "rotation_deg": [0, 0, 0], "width": 4.8, "height": 2.1},
            {"id": "roof", "label": "水平屋檐 · 深0.80m", "origin": [0, 2.1, 0],
             "rotation_deg": [90, 0, 0], "width": 4.8, "height": .8},
            {"id": "upper-wall", "label": "屋檐出口立面", "origin": [0, 2.1, .8],
             "rotation_deg": [0, 0, 0], "width": 4.8, "height": 1.3},
        ]
    width = 2.4; tilt = 35 if profile == "dihedral" else -35
    # Move the convex apex out so the entire wall remains within positive
    # world depth at the default angle; this avoids an irrelevant root-z bound.
    seam = np.array([0., 0., 0. if profile == "dihedral" else width*math.sin(math.radians(35))])
    left_rotation = [0, tilt, 0]; right_rotation = [0, -tilt, 0]
    left_origin = seam-rotation_xyz(left_rotation) @ [width/2, 0, 0]
    right_origin = seam+rotation_xyz(right_rotation) @ [width/2, 0, 0]
    return [
        {"id": "left-wall", "label": "左侧结构面", "origin": left_origin.tolist(),
         "rotation_deg": left_rotation, "width": width, "height": 4.2},
        {"id": "right-wall", "label": "右侧结构面", "origin": right_origin.tolist(),
         "rotation_deg": right_rotation, "width": width, "height": 4.2},
    ]


def fit_installed_footprints(request, reason="keep complete footprint inside assigned panel margin"):
    """Retain the panel choice; move any complete footprint away from its edge."""
    panels = {p["id"]: p for p in request["scene"]["wall_panels"]}
    inventory = {h["id"]: h for h in request["scene"]["inventory"]}
    margin = request["scene"]["margin"]; changes = []
    for placement in request["reference_layout"]:
        if "mount" in placement:
            continue
        panel = panels[placement["wall_panel_id"]]; item = inventory[placement["inventory_id"]]
        angle = math.radians(placement["rotation_deg"])
        c, s = abs(math.cos(angle)), abs(math.sin(angle))
        half_u = (c*item["width"]+s*item["height"])/2
        half_v = (s*item["width"]+c*item["height"])/2
        bounds = [[-panel["width"]/2+margin+half_u, panel["width"]/2-margin-half_u],
                  [margin+half_v, panel["height"]-margin-half_v]]
        if any(lo > hi for lo, hi in bounds):
            raise ValueError(f"{placement['id']}: complete hold footprint cannot fit assigned wall panel")
        before = {k: placement[k] for k in ("u", "v", "wall_panel_id")}
        placement["u"] = float(np.clip(placement["u"], *bounds[0]))
        placement["v"] = float(np.clip(placement["v"], *bounds[1]))
        after = {k: placement[k] for k in ("u", "v", "wall_panel_id")}
        if before != after:
            changes.append({"placement_id": placement["id"], "before": before, "after": after, "reason": reason})
    return changes


def apply_profile(request, profile):
    if profile not in PROFILES or profile == "default":
        raise ValueError("unknown or default wall profile cannot replace seed panels")
    request["scene"]["wall_panels"] = panels_for(profile)
    # Input coordinates are the original, unfolded setting seed. The roof
    # folds its 4.2 m developed height; corners fold the 4.8 m developed width.
    for placement in request["reference_layout"]:
        if profile == "overhang":
            placement["wall_panel_id"] = "overhang"
        elif profile == "roof":
            v = placement["v"]
            if v <= 2.1:
                placement["wall_panel_id"] = "lower-wall"
            elif v <= 2.9:
                placement["wall_panel_id"] = "roof"; placement["v"] = v-2.1
            else:
                placement["wall_panel_id"] = "upper-wall"; placement["v"] = v-2.9
        else:
            u = placement["u"]
            placement["wall_panel_id"] = "left-wall" if u < 0 else "right-wall"
            placement["u"] = u+1.2 if u < 0 else u-1.2
    request["setting_design"]["wall_application"] = {
        "profile": profile, "label": PROFILES[profile], "source": "synthetic_assumption",
        "mapping": "fold original seed along developed coordinates, retaining full installation margins",
        "adjustments": fit_installed_footprints(request), "limitations": LIMITATIONS,
    }
    return request


def repair_panel_spacing(request):
    """Resolve fold-induced OBB overlaps without moving the four start anchors.

    Panel folding is an explicit layout adaptation, so its 25-cm bound is
    separate from the existing 7-cm external-mesh foot-only repair. Both leave
    unsolved overlaps visible rather than altering boxes or physical rules.
    """
    scene = request["scene"]; points = request["reference_layout"]
    inventory = {h["id"]: h for h in scene["inventory"]}
    start = {ref["placement_id"] for ref in request["start_contacts"].values() if ref}
    eligible = [p for p in points if p["id"] not in start and "mount" not in p]
    feet = [p for p in eligible if set(selected_contact(p, inventory[p["inventory_id"]])["limbs"]) <= {"LF", "RF"}]
    hands = [p for p in reversed(eligible) if p not in feet]
    changes = []; epsilon = request["solver"]["epsilon_geometry_m"]
    def frames():
        return placement_frames(points, inventory, scene["angle_deg"], scene["wall_panels"])
    def gap(a, b, f):
        return obb_separation(inventory[a["inventory_id"]], f[a["id"]], inventory[b["inventory_id"]], f[b["id"]])
    for point in feet+hands:
        others = [p for p in points if p is not point]; f = frames()
        colliders = [p["id"] for p in others if gap(point, p, f) <= epsilon]
        if not colliders:
            continue
        before = {k: point[k] for k in ("u", "v", "wall_panel_id")}; chosen = None
        for step in range(1, 51):
            d = step*.005
            for du, dv in ((0, d), (-d, 0), (d, 0), (0, -d)):
                point.update(u=before["u"]+du, v=before["v"]+dv)
                if any(e["placement_id"] == point["id"] for e in panel_fit(points, inventory, scene)):
                    continue
                f = frames()
                if all(gap(point, p, f) > .005 for p in others):
                    chosen = {k: point[k] for k in ("u", "v", "wall_panel_id")}; break
            if chosen is not None:
                break
        if chosen is None:
            point.update(before)
        else:
            changes.append({"placement_id": point["id"], "before": before, "after": chosen,
                            "collided_with": colliders, "reason": "bounded panel-fold installation spacing; independent movement search still required"})
    f = frames()
    unresolved = [{"placements": [a["id"], b["id"]], "separation_m": gap(a, b, f)}
                  for i, a in enumerate(points) for b in points[i+1:] if gap(a, b, f) <= epsilon]
    return {"method": "nonstart_contact_axis_spacing_after_panel_fold", "max_displacement_m": .25,
            "grid_step_m": .005, "clearance_m": .005, "changes": changes, "unresolved_collisions": unresolved}
