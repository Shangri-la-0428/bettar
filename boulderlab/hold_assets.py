"""Versioned external meshes and draft annotated contact patches.

Mesh provenance and geometry are bound independently from synthetic force or
friction parameters. A backplate is not a volume face for mounting children.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from .geometry import (frame_axes, rotation_z, selected_contact, placement_frames,
                       panel_fit, obb_separation)

LIBRARY_PATH = Path(__file__).resolve().parent.parent / "assets/holds/library.json"
FAMILIES = {"jug", "crimp", "pinch", "sloper", "pocket"}
ASSET_FIELDS = {"asset_id", "asset_geometry_sha256", "asset_record_sha256", "asset_scale", "asset_source"}


def _canonical(value):
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return int(value) if isinstance(value, float) and value.is_integer() else value


def asset_hash(value):
    raw = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _vector(value, name, size=3):
    try:
        vector = np.asarray(value, float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"asset {name}: invalid numeric vector") from exc
    if vector.shape != (size,) or not np.isfinite(vector).all():
        raise ValueError(f"asset {name}: expected finite {size}-vector")
    return vector


def _text(record, name):
    if not isinstance(record.get(name), str) or not record[name].strip():
        raise ValueError(f"asset {name}: nonempty text required")


def validate_asset(asset):
    try:
        return _validate_asset(asset)
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("malformed external asset record") from exc


def _validate_asset(asset):
    """Reject bad anchors even if the caller recomputes the record digest."""
    if not isinstance(asset, dict):
        raise ValueError("asset must be an object")
    for name in ("id", "family", "label", "geometry_sha256", "asset_record_sha256"):
        _text(asset, name)
    if asset["family"] not in FAMILIES:
        raise ValueError("unsupported external asset family")
    if asset_hash({key: value for key, value in asset.items() if key != "asset_record_sha256"}) != asset["asset_record_sha256"]:
        raise ValueError("asset record hash mismatch")
    geometry = asset.get("geometry")
    if not isinstance(geometry, dict) or set(geometry) != {"positions", "triangles"}:
        raise ValueError("asset geometry requires positions and triangles only")
    if asset_hash(geometry) != asset["geometry_sha256"]:
        raise ValueError("asset geometry hash mismatch")
    try:
        vertices = np.asarray(geometry["positions"], float)
        faces = np.asarray(geometry["triangles"])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid asset mesh arrays") from exc
    if vertices.ndim != 2 or vertices.shape[1:] != (3,) or not 4 <= len(vertices) <= 250000 or not np.isfinite(vertices).all():
        raise ValueError("asset positions must be finite XYZ vertices")
    if faces.ndim != 2 or faces.shape[1:] != (3,) or not 1 <= len(faces) <= 500000 or faces.dtype.kind not in "iu" or np.any(faces < 0) or np.any(faces >= len(vertices)):
        raise ValueError("asset triangles must contain valid integer vertex indices")
    bounds = np.array([vertices.min(axis=0), vertices.max(axis=0)])
    dims = _vector([asset.get(k) for k in ("width", "height", "depth")], "dimensions")
    if np.any(dims <= 0) or not np.allclose(bounds[1]-bounds[0], dims, atol=1e-8, rtol=0):
        raise ValueError("asset dimensions must equal mesh bounds")
    if not np.allclose((bounds[0]+bounds[1])[:2], 0, atol=1e-8, rtol=0) or abs(bounds[0, 2]) > 1e-8:
        raise ValueError("asset origin must be XY bounds center and back z=0")
    triangles = vertices[faces]
    crosses = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    areas = np.linalg.norm(crosses, axis=1)
    if np.any(areas < 1e-14):
        raise ValueError("asset has degenerate triangles")
    source = asset.get("source")
    if not isinstance(source, dict):
        raise ValueError("asset source metadata required")
    for name in ("url", "author", "license", "license_url", "original_sha256"):
        _text(source, name)
    if not source["original_sha256"].startswith("sha256:") or len(source["original_sha256"]) != 71 or any(c not in "0123456789abcdef" for c in source["original_sha256"][7:]):
        raise ValueError("asset original_sha256 must identify original bytes")
    scale = asset.get("scale")
    installation = asset.get("installation")
    for name, data in (("scale", scale), ("installation", installation)):
        if not isinstance(data, dict) or not isinstance(data.get("verified"), bool):
            raise ValueError(f"asset {name} requires explicit verified flag")
        _text(data, "basis")
    if installation.get("kind") != "backplate" or not np.allclose(_vector(installation.get("origin"), "installation origin"), [0, 0, 0], atol=1e-8, rtol=0) or not np.allclose(_vector(installation.get("normal"), "installation normal"), [0, 0, -1], atol=1e-8, rtol=0):
        raise ValueError("asset installation must declare the normalized backplate")
    surfaces = asset.get("grip_surfaces")
    if not isinstance(surfaces, list) or not 1 <= len(surfaces) <= 8:
        raise ValueError("asset requires annotated grip surfaces")
    ids = set()
    for surface in surfaces:
        if not isinstance(surface, dict):
            raise ValueError("asset grip surface must be an object")
        for name in ("id", "label"):
            _text(surface, name)
        if surface["id"] in ids:
            raise ValueError("asset duplicate grip surface id")
        ids.add(surface["id"])
        frame_axes(surface)
        position = _vector(surface.get("position"), "surface position")
        radii = _vector(surface.get("radii"), "surface radii", 2)
        if np.any(radii <= 0) or np.any(radii > max(dims)):
            raise ValueError("asset grip radii must be positive bounded annotations")
        pull = _vector(surface.get("pull_direction"), "pull direction")
        if np.linalg.norm(pull) < 1e-10:
            raise ValueError("asset pull direction must be nonzero")
        limbs = surface.get("limbs")
        if not isinstance(limbs, list) or not limbs or len(set(limbs)) != len(limbs) or not set(limbs) <= {"LH", "RH", "LF", "RF"}:
            raise ValueError("asset surface limb permissions invalid")
        anchor = surface.get("mesh_anchor", {})
        index = anchor.get("triangle_index")
        if type(index) is not int or not 0 <= index < len(faces):
            raise ValueError("asset mesh anchor triangle index invalid")
        barycentric = _vector(anchor.get("barycentric"), "anchor barycentric")
        if np.any(barycentric < 0) or np.any(barycentric > 1) or not math.isclose(float(sum(barycentric)), 1, abs_tol=1e-8):
            raise ValueError("asset anchor barycentric outside triangle")
        if not np.allclose(position, barycentric @ triangles[index], atol=1e-8, rtol=0):
            raise ValueError("asset contact position is off mesh anchor")
        if not np.allclose(surface["normal"], crosses[index]/areas[index], atol=1e-7, rtol=0):
            raise ValueError("asset contact normal disagrees with anchor triangle winding")
        annotated = surface.get("annotations", {}).get("triangle_indices")
        if not isinstance(annotated, list) or index not in annotated or len(set(annotated)) != len(annotated) or any(type(i) is not int or not 0 <= i < len(faces) for i in annotated):
            raise ValueError("asset annotation triangle indices invalid")
    if "working" not in ids:
        raise ValueError("asset requires a working contact surface")
    return asset


@lru_cache(maxsize=3)
def _read_registry(encoded):
    data = json.loads(encoded)
    if not isinstance(data, dict) or data.get("schema_version") != "hold-assets/1" or not isinstance(data.get("assets"), list):
        raise ValueError("invalid hold asset registry")
    assets = {}
    for asset in data["assets"]:
        validate_asset(asset)
        if asset["id"] in assets:
            raise ValueError("duplicate hold asset id")
        assets[asset["id"]] = asset
    return assets


def load_registry(path=None):
    # Read on every boundary: mtime-only caching could accept changed source.
    try:
        encoded = Path(path or LIBRARY_PATH).read_text()
    except FileNotFoundError as exc:
        raise ValueError("external hold registry is unavailable") from exc
    return copy.deepcopy(_read_registry(encoded))


def resolve_hold_source(source):
    if source not in {"auto", "templates", "assets"}:
        raise ValueError("hold_source must be auto, templates or assets")
    return ("assets" if LIBRARY_PATH.exists() else "templates") if source == "auto" else source


def materialize_item(item, asset, scale):
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not math.isfinite(scale) or scale <= 0:
        raise ValueError("asset_scale must be positive and finite")
    if item["type"] != asset["family"]:
        raise ValueError("asset family does not match inventory type")
    result = copy.deepcopy(item)
    for key in ("width", "height", "depth"):
        result[key] = asset[key]*scale
    result.update(asset_id=asset["id"], asset_geometry_sha256=asset["geometry_sha256"],
                  asset_record_sha256=asset["asset_record_sha256"], asset_scale=scale,
                  asset_source="external_mesh", template_id="asset:"+asset["id"], template_name=asset["label"])
    result.pop("asset_fallback_reason", None)
    result.pop("mounting_faces", None)
    result["grip_surfaces"] = copy.deepcopy(asset["grip_surfaces"])
    for surface in result["grip_surfaces"]:
        for key in ("position", "radii"):
            surface[key] = [value*scale for value in surface[key]]
    working = next(surface for surface in result["grip_surfaces"] if surface["id"] == "working")
    result["contact"] = {"id": "main", "position": copy.deepcopy(working["position"]),
                         "radius": min(working["radii"]), "limbs": copy.deepcopy(working["limbs"])}
    result["pull_direction"] = copy.deepcopy(working["pull_direction"])
    return result


def validate_inventory_assets(inventory):
    # Triangle annotations and the reserved asset template namespace also
    # declare an external mesh. Dropping every asset_* key must not silently
    # convert its real-mesh contact coordinates into a procedural template.
    referenced = [item for item in inventory if ASSET_FIELDS.intersection(item)
                  or str(item.get("template_id", "")).startswith("asset:")
                  or any("mesh_anchor" in surface or "annotations" in surface
                         for surface in item.get("grip_surfaces", []))]
    if not referenced:
        return
    assets = load_registry()
    for item in referenced:
        if not ASSET_FIELDS <= set(item):
            raise ValueError("incomplete external asset inventory binding")
        asset = assets.get(item["asset_id"])
        if asset is None:
            raise ValueError("unknown external hold asset")
        if item["asset_geometry_sha256"] != asset["geometry_sha256"] or item["asset_record_sha256"] != asset["asset_record_sha256"]:
            raise ValueError("external asset hash mismatch; regenerate inventory")
        if item.get("mounting_faces") or "asset_fallback_reason" in item:
            raise ValueError("external hold backplate is not a mountable volume or template fallback")
        expected = materialize_item(item, asset, item["asset_scale"])
        for key in ("width", "height", "depth", "grip_surfaces", "contact", "pull_direction", "asset_source", "template_id", "template_name"):
            if asset_hash(item.get(key)) != asset_hash(expected[key]):
                raise ValueError(f"external asset inventory {key} differs from registry")


def apply_setting_assets(request):
    """Use five exact families; preserve authored XY contact corridors on swap."""
    from .beta_audit import MATCHING_POLICY
    assets = load_registry()
    by_family = {}
    for asset in sorted(assets.values(), key=lambda value: value["id"]):
        by_family.setdefault(asset["family"], asset)
    placements = {p["inventory_id"]: p for p in request["reference_layout"]}
    top_ids = {ref["placement_id"] for ref in request["end_contacts"].values() if ref}
    mapped = []; fallbacks = []
    for index, item in enumerate(request["scene"]["inventory"]):
        if item["type"] not in FAMILIES:
            continue
        asset = by_family.get(item["type"])
        reason = "no registered external mesh for this family" if asset is None else None
        if asset is not None:
            # Original mesh proportions are preserved. Width is an explicit
            # unmeasured demo choice, not a fabricated physical measurement.
            scale = item["width"]/asset["width"]
            replacement = materialize_item(item, asset, scale)
            working = next(surface for surface in replacement["grip_surfaces"] if surface["id"] == "working")
            if not {"LH", "RH"} <= set(working["limbs"]):
                reason = "registered working patch lacks hand permissions"
            if placements[item["id"]]["id"] in top_ids:
                diameters = sorted([2*radius for radius in working["radii"]], reverse=True)
                if replacement["width"] < MATCHING_POLICY["min_hold_width_m"] or replacement["height"] < MATCHING_POLICY["min_hold_height_m"] or diameters[0] < MATCHING_POLICY["min_selected_patch_major_diameter_m"] or diameters[1] < MATCHING_POLICY["min_selected_patch_minor_diameter_m"]:
                    reason = "uniform mesh size / annotated patch does not satisfy unchanged TOP matching policy"
        if reason:
            item["asset_fallback_reason"] = reason
            fallbacks.append({"inventory_id": item["id"], "reason": reason})
            continue
        placement = placements[item["id"]]
        old = selected_contact(placement, item)
        new = selected_contact(placement, replacement)
        shift = rotation_z(placement["rotation_deg"]) @ (np.asarray(old["position"])-new["position"])
        placement["u"] += float(shift[0]); placement["v"] += float(shift[1])
        request["scene"]["inventory"][index] = replacement
        mapped.append(item["id"])
    if not mapped:
        raise ValueError("asset mode requires at least one usable registered hold")
    repairs = _clear_footprint_collisions(request)
    request["setting_design"]["asset_application"] = {
        "mapped_instances": mapped, "fallbacks": fallbacks,
        "scale_policy": "uniform_to_template_width_unmeasured_demo_size",
        "placement_policy": "preserve selected contact XY in local mounting plane; depth follows mesh",
        "footprint_adjustment": repairs,
        "limitations": ["外部三角网格来自列明来源；演示尺寸未经实测，使用同比缩放。", "抓握面及椭圆范围为AI草稿标注，代表点和法向绑定三角面；抓握能力、摩擦及可抓握范围未经实测。", "碰撞仍用覆盖网格的保守包围盒；安装背板不属于可安装子岩点的体积块斜面。"],
    }
    return request


def _clear_footprint_collisions(request):
    """Small deterministic installation repair, followed by normal beta search.

    This uses the same conservative world OBB check as P0. It does not treat
    separated boxes as proof that the resulting moves can be climbed.
    """
    scene = request["scene"]; placements = request["reference_layout"]
    inventory = {item["id"]: item for item in scene["inventory"]}
    anchors = {ref["placement_id"] for key in ("start_contacts", "end_contacts")
               for ref in request[key].values() if ref}
    epsilon = request["solver"]["epsilon_geometry_m"]
    changes = []; clearance = .005; bound = .07

    def frames():
        return placement_frames(placements, inventory, scene["angle_deg"], scene.get("wall_panels"))

    def gap(a, b, current):
        return obb_separation(inventory[a["inventory_id"]], current[a["id"]],
                              inventory[b["inventory_id"]], current[b["id"]])

    for placement in placements:
        surface = selected_contact(placement, inventory[placement["inventory_id"]])
        if placement["id"] in anchors or not set(surface["limbs"]) <= {"LF", "RF"}:
            continue
        original = {key: placement[key] for key in ("u", "v")}
        others = [other for other in placements if other["id"] != placement["id"]]
        current = frames()
        collisions = [other["id"] for other in others if gap(placement, other, current) <= epsilon]
        if not collisions:
            continue
        # Search a 5-mm axis grid in increasing displacement, never resize a
        # real mesh, move anchor feet, or relax the collision threshold.
        chosen = None
        for step in range(1, 15):
            amount = step*.005
            for du, dv in ((-amount, 0), (amount, 0), (0, amount), (0, -amount)):
                placement.update(u=original["u"]+du, v=original["v"]+dv)
                if any(error["placement_id"] == placement["id"] for error in panel_fit(placements, inventory, scene)):
                    continue
                current = frames()
                if all(gap(placement, other, current) > clearance for other in others):
                    chosen = {key: placement[key] for key in ("u", "v")}
                    break
            if chosen is not None:
                break
        if chosen is None:
            placement.update(original)
        else:
            changes.append({"placement_id": placement["id"], "before": original, "after": chosen,
                            "collided_with": collisions, "reason": "smallest tested axis translation separating conservative mesh OBBs; beta/IK still required"})
    current = frames()
    unresolved = [{"placements": [a["id"], b["id"]], "separation_m": gap(a, b, current)}
                  for i, a in enumerate(placements) for b in placements[i+1:]
                  if gap(a, b, current) <= epsilon]
    return {"method": "bounded_axis_translation_of_nonanchor_feet", "max_displacement_m": bound,
            "grid_step_m": .005, "clearance_m": clearance, "changes": changes,
            "unresolved_collisions": unresolved}
