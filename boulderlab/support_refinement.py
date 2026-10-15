"""Small, evidence-driven installation proposals, never support certifications.

Only failed/overloaded contacts from the checked beta suggest edits. The caller
must independently search each proposal and re-run IK and static checks. Contact
materials, body dimensions, capacities and solver tolerances remain unchanged.
"""
from __future__ import annotations

import copy
import math
import numpy as np

from .geometry import placement_frames, rotation_z, selected_contact, panel_fit
from .wall_profiles import fit_installed_footprints, repair_panel_spacing

MAX_DISPLACEMENT_M = .12
MAX_ROTATION_DEG = 40.


def _mount_basis(placement, frame):
    """u/v belong to the mounting plane, not the already-rotated hold frame."""
    return frame[1] @ rotation_z(-placement["rotation_deg"])


def _unit(vector):
    value = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(value))
    return value / norm if norm > 1e-9 else None


def _turn_toward(axis, desired, mount_basis):
    a, d = mount_basis.T @ np.asarray(axis), mount_basis.T @ np.asarray(desired)
    if np.linalg.norm(a[:2]) < 1e-8 or np.linalg.norm(d[:2]) < 1e-8:
        return 0.
    delta = math.degrees(math.atan2(d[1], d[0]) - math.atan2(a[1], a[0]))
    return max(-MAX_ROTATION_DEG, min(MAX_ROTATION_DEG, (delta + 180.) % 360. - 180.))


def _axis(request, item, surface, rotation, limb):
    parameters = request["mechanics_parameters"]
    passive = limb.endswith("F") or item["type"] == "sloper"
    local = np.asarray(surface["normal"], float) if passive else (
        -np.asarray(surface["pull_direction"], float)
        - np.array([0., 0., parameters["grasp_inward_bias"]]))
    return _unit(rotation @ local)


def _failed_contacts(record):
    evidence = []
    for state in record["evaluation"].get("mechanics_report", {}).get("states", []):
        if state.get("com_world_m") is None or state.get("status") == "unknown":
            continue
        if state["status"] == "feasible" and (state.get("capacity_utilization") or 0) < .85:
            continue
        for contact in state.get("contacts", []):
            evidence.append((state, contact))
    return evidence


def _finish(request, original, points, evidence, label, policy, migrations=()):
    """Fit actual footprints while retaining anchors and the local edit bound."""
    proposal = copy.deepcopy(request)
    proposal["reference_layout"] = points
    before = {p["id"]: p for p in original}
    anchors = {r["placement_id"] for key in ("start_contacts", "end_contacts")
               for r in request[key].values() if r}
    inv = {i["id"]: i for i in request["scene"]["inventory"]}
    # An anchor's new orientation may not fit its existing location. Reject
    # that turn, rather than moving the start/TOP to make room for it.
    bad = {e["placement_id"] for e in panel_fit(points, inv, request["scene"])}
    for p in points:
        if p["id"] in anchors & bad:
            p["rotation_deg"] = before[p["id"]]["rotation_deg"]
    try:
        fitted = fit_installed_footprints(proposal, "fit support-guided installation proposal")
        spacing = repair_panel_spacing(proposal, protected_ids=anchors)
    except (ValueError, KeyError):
        return None
    migrated = set(migrations)
    for p in points:
        old = before[p["id"]]
        if p["id"] in anchors and any(p.get(k) != old.get(k) for k in ("u", "v", "wall_panel_id", "mount")):
            return None
        if p["id"] not in migrated and (
            p.get("wall_panel_id") != old.get("wall_panel_id")
            or math.hypot(p["u"] - old["u"], p["v"] - old["v"]) > MAX_DISPLACEMENT_M + 1e-8):
            return None
    fields = ("u", "v", "rotation_deg", "wall_panel_id", "contact_surface_id")
    evidence_ids = {c["placement_id"] for _, c in evidence}
    changes = [{"placement_id": p["id"],
                "before": {k: before[p["id"]][k] for k in fields if k in before[p["id"]]},
                "after": {k: p[k] for k in fields if k in p},
                "reason": "failed_contact_support" if p["id"] in evidence_ids else "installation_spacing",
                "panel_migration": p["id"] in migrated}
               for p in points if p != before[p["id"]]]
    if not changes:
        return None
    return {"label": label, "placements": points, "changes": changes,
            "rationale": {"policy": policy,
                "source_state_ids": sorted({s["state_id"] for s, _ in evidence}),
                "source_contact_ids": sorted(evidence_ids),
                "rotation_limit_deg": MAX_ROTATION_DEG, "local_displacement_limit_m": MAX_DISPLACEMENT_M,
                "panel_migrations": sorted(migrated), "panel_fit": fitted, "spacing": spacing,
                "limitations": ["Edits are proposals from current-pose failures, not a force-equilibrium proof.",
                    "Changing the main face uses an already declared surface; no new contact capability is invented.",
                    "A different layout requires a fresh independent beta, IK and mechanics evaluation."]}}


def support_proposals(request, record):
    """Return up to three coherent support repairs without mutating inputs."""
    original = record["candidate"]["placements"]
    inventory = {i["id"]: i for i in request["scene"]["inventory"]}
    frames = placement_frames(original, inventory, request["scene"]["angle_deg"], request["scene"].get("wall_panels"))
    byid = {p["id"]: p for p in original}
    anchors = {r["placement_id"] for key in ("start_contacts", "end_contacts")
               for r in request[key].values() if r}
    evidence = _failed_contacts(record)
    if not evidence:
        return []
    edits = {}
    for state, contact in evidence:
        pid = contact["placement_id"]
        if pid not in byid:
            continue
        p = byid[pid]
        basis = _mount_basis(p, frames[pid])
        com, position = np.asarray(state["com_world_m"]), np.asarray(contact["point_world_m"])
        weight = 2. if state["is_release"] else 1.
        hand = contact["limb"].endswith("H")
        required = contact.get("required_force_world_n")
        # A no-equilibrium LP has no valid reaction vector. Feet then aim their
        # declared normal toward gravity's opposite; hands toward the body-to-
        # contact direction. These heuristics are explicitly rechecked later.
        desired = _unit(required) if required is not None else None
        if desired is None:
            desired = _unit(position - com) if hand else np.array([0., 1., 0.])
        if desired is None:
            continue
        turn = _turn_toward(contact["axial_direction_world"], desired, basis)
        local_delta = basis.T @ (com - position)
        scale = .20 if hand else .35
        max_shift = .10
        move = local_delta[:2] * scale
        # Vertical foot movement is more conservative than lateral support.
        move[1] *= .35
        length = float(np.linalg.norm(move))
        if length > max_shift:
            move *= max_shift / length
        entry = edits.setdefault(pid, {"turn": [], "move": [], "desired": [], "limbs": set()})
        entry["turn"].append((turn, weight))
        entry["move"].append((move, weight))
        entry["desired"].append((desired, weight))
        entry["limbs"].add(contact["limb"])

    def edited(strength, alternate_faces=False):
        points = copy.deepcopy(original)
        for p in points:
            info = edits.get(p["id"])
            if not info:
                continue
            item = inventory[p["inventory_id"]]
            turn = sum(v * w for v, w in info["turn"]) / sum(w for _, w in info["turn"])
            p["rotation_deg"] = round(p["rotation_deg"] + strength * turn, 4)
            if p["id"] not in anchors:
                move = sum((v * w for v, w in info["move"]), np.zeros(2)) / sum(w for _, w in info["move"])
                p["u"] = round(p["u"] + strength * float(move[0]), 5)
                p["v"] = round(p["v"] + strength * float(move[1]), 5)
            if alternate_faces and p["id"] not in anchors and item["type"] == "pocket":
                # Some imported pocket main faces point the aggregate reaction
                # out of the wall. Consider only real, declared hand surfaces.
                desired = _unit(sum((v * w for v, w in info["desired"]), np.zeros(3)))
                if desired is None:
                    continue
                rotation = _mount_basis(byid[p["id"]], frames[p["id"]]) @ rotation_z(p["rotation_deg"])
                current = selected_contact(p, item)
                choices = [s for s in item.get("grip_surfaces", []) if {"LH", "RH"} <= set(s["limbs"])]
                score = lambda surface: float(np.dot(_axis(request, item, surface, rotation, "LH"), desired))
                chosen = max(choices, key=score, default=current)
                if score(chosen) > score(current) + .15:
                    p["contact_surface_id"] = chosen["id"]
        return points

    proposals = []
    for strength, alternate, label in ((.65, False, "support-position-and-orientation"),
                                       (1., True, "declared-grip-and-support")):
        result = _finish(request, original, edited(strength, alternate), evidence, label,
            "weighted failed/loaded contact reactions; actual foot normals and mounting-plane moment arms; declared pocket face option")
        if result:
            proposals.append(result)

    if request.get("setting_design", {}).get("wall_profile") == "roof":
        upper = next((p for p in request["scene"].get("wall_panels", []) if p["id"] == "upper-wall"), None)
        if upper is not None:
            points = edited(1., True)
            migrated = []
            exit_foot = max((p for p in original if p["id"] in edits and p["id"] not in anchors
                and p.get("wall_panel_id") == "roof" and inventory[p["inventory_id"]]["type"] == "foothold"),
                key=lambda p: p["v"], default=None)
            for p in points:
                if p["id"] in anchors or p["id"] not in edits or p.get("wall_panel_id") != "roof":
                    continue
                item = inventory[p["inventory_id"]]
                # A passive tread/sloper on the underside cannot become an
                # upward support merely by an in-plane turn. Reinstall the
                # actually used offending hold on the adjacent exit face.
                if item["type"] not in ("foothold", "sloper"):
                    continue
                normal = frames[p["id"]][1] @ np.asarray(selected_contact(p, item)["normal"])
                mu = request["mechanics_parameters"]["friction_coefficient_foot" if item["type"] == "foothold" else "friction_coefficient_hand"]
                max_upward = normal[1] + mu * math.sqrt(max(0., 1. - normal[1] ** 2))
                if max_upward >= 0 and (exit_foot is None or p["id"] != exit_foot["id"]):
                    continue
                p.update(wall_panel_id=upper["id"], v=request["scene"]["margin"] + item["height"] / 2 + .025,
                         rotation_deg=byid[p["id"]]["rotation_deg"])
                migrated.append(p["id"])
            if migrated:
                result = _finish(request, original, points, evidence, "roof-exit-support",
                    "reinstall actually used downward-only passive contacts and the nearest used roof foot on the adjacent exit face; retain all original material/contact limits", migrated)
                if result:
                    proposals.append(result)
    return proposals
