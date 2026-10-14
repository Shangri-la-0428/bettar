"""Shared synthetic contact geometry, mounting frames and conservative 3-D OBBs.

Frames use column vectors (u, v, outward normal), metres, and right-handed axes.
The height fields match web/src/hold-models.ts; they are not scanned hold geometry.
"""
from __future__ import annotations

import itertools
import math
import copy
import numpy as np


def unit(vector):
    value = np.asarray(vector, float)
    length = float(np.linalg.norm(value))
    if value.shape != (3,) or not np.isfinite(value).all() or length < 1e-10:
        raise ValueError("invalid geometry direction")
    return value / length


def wall_basis(angle_deg):
    a = math.radians(angle_deg)
    return np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])


def rotation_z(angle_deg):
    a = math.radians(angle_deg)
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])


def rotation_xyz(rotation_deg):
    """Extrinsic Euler rotations, consistently composed as Rz @ Ry @ Rx."""
    rx, ry, rz = rotation_deg
    y = math.radians(ry)
    rotate_y = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0],
                         [-math.sin(y), 0, math.cos(y)]])
    return rotation_z(rz) @ rotate_y @ wall_basis(rx)


def panel_frame(panel, angle_deg):
    base = wall_basis(angle_deg)
    return base @ np.asarray(panel["origin"], float), base @ rotation_xyz(panel["rotation_deg"])


def panel_fit(placements, inventory, scene, epsilon=1e-8):
    """Check root hold footprints against their actual rectangular mounting panel.

    The same edge margin as the legacy wall is retained. Mounted children are
    checked against their parent volume face by mounting_fit instead.
    """
    panels = {panel["id"]: panel for panel in scene.get("wall_panels", [])}
    errors = []
    margin = scene.get("margin", .2)
    for p in placements:
        if "mount" in p:
            continue
        panel = panels.get(p.get("wall_panel_id"))
        if panel is None:
            errors.append({"placement_id": p["id"], "reason": "missing or unknown wall_panel_id"})
            continue
        item = inventory[p["inventory_id"]]
        corners = np.array([rotation_z(p["rotation_deg"]) @ [x*item["width"]/2, y*item["height"]/2, 0]
                            + [p["u"], p["v"], 0] for x, y in itertools.product((-1, 1), repeat=2)])[:, :2]
        lower = np.array([-panel["width"]/2+margin, margin])
        upper = np.array([panel["width"]/2-margin, panel["height"]-margin])
        if np.any(corners < lower-epsilon) or np.any(corners > upper+epsilon):
            errors.append({"placement_id": p["id"], "wall_panel_id": panel["id"],
                           "reason": "hold footprint extends beyond panel edge margin"})
    return errors


def height_at(item, x, y):
    if "asset_id" in item:
        raise ValueError("external mesh is not a single-valued template height field")
    w, h, d = item["width"], item["height"], item["depth"]
    if item["type"] == "volume":
        skirt = min(.008, d * .06)
        outline = [(-.49*w, -.45*h), (.49*w, -.32*h), (-.23*w, .49*h)]
        planes = []
        for i, (ax, ay) in enumerate(outline):
            bx, by = outline[(i+1) % 3]
            det = ax*by-bx*ay
            planes.append(d+(skirt-d)*(by-ay)/det*x+(skirt-d)*(ax-bx)/det*y)
        return max(0, min(planes))
    x, y = 2*x/w, 2*y/h
    r = min(1, math.hypot(x, y))
    body = math.sqrt(max(0, 1-r*r))
    kind = item["type"]
    if kind == "jug":
        lip = math.exp(-((y+.055+.09*x*x)/.21)**2)*(1-.35*x*x)
        cavity = math.exp(-x*x/.28-((y-.39)/.21)**2)
        center = .46+.65*math.exp(-(.055/.21)**2)-.35*math.exp(-(.39/.21)**2)
        z = (.11+.35*body+.65*lip-.35*cavity)/center
    elif kind == "sloper":
        q = min(1, x*x*.93+y*y*1.08)
        z = .055+.945*(1-q)**.60*(1-.13*y*r-.055*x*r)
    elif kind == "pinch":
        z = .075+.925*math.exp(-(abs(x)/.59)**1.45)*max(0, 1-y*y)**.36
    elif kind == "rail":
        ridge = math.exp(y*1.10) if y <= 0 else math.exp(-y*5.4)
        z = (.085+.915*ridge)*(1-.40*abs(x)**3)
    elif kind == "pocket":
        # A recessed, closed finger well with an actual inner wall and floor.
        # This height field deliberately models no invisible undercut.
        q = (x/.43)**2+((y-.12)/.43)**2
        shoulder = .12+.88*max(0, 1-r*r)**.48
        well = .76*math.exp(-q*q*1.8)
        z = shoulder-well
    elif kind == "crimp":
        # A short, low-profile ledge. Millimetre-scale edge depth comes from
        # its declared dimensions, not from a universal difficulty number.
        ramp = math.exp((y-.10)*1.35) if y <= .10 else math.exp(-(y-.10)*8.8)
        z = (.08+.92*ramp)*max(.03, 1-x*x)**.16
    elif kind == "directional_edge":
        ridge = math.exp(y*1.15) if y <= 0 else math.exp(-y*5.0)
        z = (.10+.90*ridge)*max(.04, 1-x*x)**.22
    else:
        ridge = max(.05, 1+y*.94) if y <= 0 else math.exp(-y*3.7)
        z = .09+.91*ridge*max(.02, 1-x*x)**.3
    return min(1, max(.045, z))*d


def mounting_faces(item):
    if "asset_id" in item:
        raise ValueError("external hold backplate is not a volume mounting face")
    w, h, d = item["width"], item["height"], item["depth"]
    skirt = min(.008, d*.06)
    apex = np.array([0, 0, d])
    rim = [np.array(p) for p in [(-.49*w, -.45*h, skirt), (.49*w, -.32*h, skirt), (-.23*w, .49*h, skirt)]]
    faces = []
    for i, a in enumerate(rim):
        b = rim[(i+1) % 3]
        origin = (apex+a+b)/3
        u = unit(b-a)
        normal = unit(np.cross(a-apex, b-apex))
        v = np.cross(normal, u)
        faces.append({"id": f"face_{i+1}", "label": f"安装斜面 {i+1}", "origin": origin.tolist(),
                      "u_axis": u.tolist(), "v_axis": v.tolist(), "normal": normal.tolist(),
                      "polygon": [[float((p-origin) @ u), float((p-origin) @ v)] for p in (apex, a, b)]})
    return faces


def grip_surfaces(item):
    if "asset_id" in item:
        if not item.get("grip_surfaces"):
            raise ValueError("external mesh requires registry-derived contact annotations")
        return copy.deepcopy(item["grip_surfaces"])
    kind = item["type"]
    if kind == "volume":
        return [{"id": face["id"]+"_grip", "label": f"斜面接触 {i+1}", "position": face["origin"],
                 "normal": face["normal"], "u_axis": face["u_axis"], "v_axis": face["v_axis"],
                 "radii": [.06, .05], "limbs": ["LF", "RF"], "pull_direction": (-np.asarray(face["v_axis"])).tolist()}
                for i, face in enumerate(mounting_faces(item))]
    samples = {"jug": [(0, -.08), (0, .28)], "directional_edge": [(0, -.06), (0, .18)],
               "foothold": [(0, .18), (0, -.06)], "rail": [(0, -.08), (0, .18)],
               "sloper": [(-.20, .12), (.22, .12)], "pinch": [(-.36, 0), (.36, 0)],
               "crimp": [(0, .22), (.24, .22)], "pocket": [(0, .40), (.29, .18), (0, .70)]}[kind]
    surfaces = []
    for i, (nx, ny) in enumerate(samples):
        x, y = nx*item["width"]/2, ny*item["height"]/2
        eps = min(.0002, min(item["width"], item["height"])*.002)
        dx = (height_at(item, x+eps, y)-height_at(item, x-eps, y))/(2*eps)
        dy = (height_at(item, x, y+eps)-height_at(item, x, y-eps))/(2*eps)
        normal = unit([-dx, -dy, 1])
        u = unit([1, 0, dx])
        v = np.cross(normal, u)
        surface_id = "standing" if kind == "pocket" and i == 2 else "working" if i == 0 else "alternate"
        labels = {"pocket": ("洞口内上缘", "洞口内侧缘", "洞外上缘踩面"),
                  "crimp": ("浅扣抓边", "侧段抓边"),
                  "foothold": ("主要踩踏面", "备选踩踏面")}
        label = labels.get(kind, ("主要抓握面", "备选抓握面"))[i]
        if kind == "foothold" or surface_id == "standing":
            limbs = ["LF", "RF"]
        else:
            limbs = ["LH", "RH", "LF", "RF"] if kind == "crimp" else ["LH", "RH"]
        if kind == "crimp":
            radii = [.014, .005]
        elif kind == "pocket":
            radii = [.011, .008] if i < 2 else [.018, .009]
        else:
            radii = [.14*item["width"], .14*item["height"]]
        surfaces.append({"id": surface_id, "label": label,
                         "position": [x, y, height_at(item, x, y)], "normal": normal.tolist(),
                         "u_axis": u.tolist(), "v_axis": v.tolist(),
                         "radii": radii, "limbs": limbs,
                         "pull_direction": (-v).tolist()})
    return surfaces


def frame_axes(record):
    axes = np.column_stack([record[k] for k in ("u_axis", "v_axis", "normal")]).astype(float)
    if axes.shape != (3, 3) or not np.isfinite(axes).all() or not np.allclose(axes.T @ axes, np.eye(3), atol=1e-7, rtol=0) or not math.isclose(float(np.linalg.det(axes)), 1, abs_tol=1e-7):
        raise ValueError("surface/face frame must be right-handed orthonormal")
    return axes


def selected_contact(placement, item):
    surface_id = placement.get("contact_surface_id")
    if surface_id is None:
        return item["contact"]
    for surface in item.get("grip_surfaces", []):
        if surface["id"] == surface_id:
            return surface
    raise ValueError(f"{placement['id']}: unknown contact_surface_id {surface_id}")


def placement_frames(placements, inventory, angle_deg, wall_panels=None):
    by_id = {p["id"]: p for p in placements}
    panels = {panel["id"]: panel for panel in wall_panels or []}
    if len(panels) != len(wall_panels or []):
        raise ValueError("wall panel ids must be unique")
    frames = {}
    for p in placements:
        item = inventory[p["inventory_id"]]
        selected_contact(p, item)
        if "mount" in p and "wall_panel_id" in p:
            raise ValueError(f"{p['id']}: mounted child inherits its parent's wall panel")
        if "mount" not in p:
            if panels or "wall_panel_id" in p:
                panel = panels.get(p.get("wall_panel_id"))
                if panel is None:
                    raise ValueError(f"{p['id']}: missing or unknown wall_panel_id")
                origin, base = panel_frame(panel, angle_deg)
            else:
                origin, base = np.zeros(3), wall_basis(angle_deg)
            frames[p["id"]] = (origin + base @ [p["u"], p["v"], 0], base @ rotation_z(p["rotation_deg"]))
    for p in placements:
        if "mount" not in p:
            continue
        m = p["mount"]
        parent = by_id.get(m["parent_id"])
        if not parent or parent["id"] == p["id"] or "mount" in parent:
            raise ValueError(f"{p['id']}: mount requires an existing unmounted parent; nested mounts/cycles rejected")
        parent_item = inventory[parent["inventory_id"]]
        if parent_item["type"] != "volume" or inventory[p["inventory_id"]]["type"] == "volume":
            raise ValueError(f"{p['id']}: only one-level volume to non-volume mounting is supported")
        face = next((f for f in parent_item.get("mounting_faces", []) if f["id"] == m["face_id"]), None)
        if face is None:
            raise ValueError(f"{p['id']}: unknown parent mounting face")
        parent_origin, parent_axes = frames[parent["id"]]
        face_axes = frame_axes(face)
        axes = parent_axes @ face_axes
        origin = parent_origin + parent_axes @ np.asarray(face["origin"]) + axes @ [p["u"], p["v"], 0]
        frames[p["id"]] = (origin, axes @ rotation_z(p["rotation_deg"]))
    return frames


def contact_world(request, placement, item, placements=None, frames=None):
    placements = placements if placements is not None else request["reference_layout"]
    # A caller may pass an independently edited root placement, as old tests do.
    if frames is None:
        items = {h["id"]: h for h in request["scene"]["inventory"]}
        layout = [p for p in placements if p["id"] != placement["id"]] + [placement]
        frames = placement_frames(layout, items, request["scene"]["angle_deg"], request["scene"].get("wall_panels"))
    origin, axes = frames[placement["id"]]
    return origin + axes @ np.asarray(selected_contact(placement, item)["position"])


def box_corners(item, frame):
    origin, axes = frame
    return np.asarray([origin+axes @ [x*item["width"]/2, y*item["height"]/2, z*item["depth"]]
                       for x, y, z in itertools.product((-1, 1), (-1, 1), (0, 1))])


def contains_polygon(polygon, points, epsilon):
    poly = np.asarray(polygon, float)
    signs = []
    for i, a in enumerate(poly):
        b = poly[(i+1) % len(poly)]
        edge = b-a
        if np.linalg.norm(edge) < epsilon:
            raise ValueError("degenerate mounting face polygon")
        signs.append((edge[0]*(points[:, 1]-a[1])-edge[1]*(points[:, 0]-a[0]))/np.linalg.norm(edge))
    signs = np.asarray(signs)
    return bool(np.all(signs >= -epsilon) or np.all(signs <= epsilon))


def mounting_fit(placements, inventory, epsilon):
    by_id = {p["id"]: p for p in placements}
    errors, valid_pairs = [], set()
    for p in placements:
        if "mount" not in p:
            continue
        parent = by_id[p["mount"]["parent_id"]]
        parent_item = inventory[parent["inventory_id"]]
        face = next(f for f in parent_item["mounting_faces"] if f["id"] == p["mount"]["face_id"])
        item = inventory[p["inventory_id"]]
        corners = np.array([rotation_z(p["rotation_deg"]) @ [x*item["width"]/2, y*item["height"]/2, 0] + [p["u"], p["v"], 0]
                            for x, y in itertools.product((-1, 1), repeat=2)])[:, :2]
        if not contains_polygon(face["polygon"], corners, epsilon):
            errors.append({"placement_id": p["id"], "reason": "child footprint extends beyond parent face polygon"})
        else:
            valid_pairs.add(frozenset((p["id"], parent["id"])))
    return errors, valid_pairs


def obb_separation(item_a, frame_a, item_b, frame_b):
    oa, a = frame_a
    ob, b = frame_b
    half_a = np.array([item_a["width"], item_a["height"], item_a["depth"]])/2
    half_b = np.array([item_b["width"], item_b["height"], item_b["depth"]])/2
    delta = ob+b[:, 2]*half_b[2]-oa-a[:, 2]*half_a[2]
    axes = [a[:, i] for i in range(3)] + [b[:, i] for i in range(3)]
    axes += [np.cross(a[:, i], b[:, j]) for i in range(3) for j in range(3)]
    separation = -float("inf")
    for axis in axes:
        norm = float(np.linalg.norm(axis))
        if norm < 1e-10:
            continue
        axis = axis/norm
        distance = abs(float(delta @ axis))-float(half_a @ np.abs(a.T @ axis))-float(half_b @ np.abs(b.T @ axis))
        separation = max(separation, distance)
    return separation
