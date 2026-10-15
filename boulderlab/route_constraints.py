"""Route contact selection is separate from installed, collidable geometry."""
from __future__ import annotations

import math

from .geometry import selected_contact

LIMBS = ("LH", "RH", "LF", "RF")


def allowed_contact_refs(request, placements):
    """Enumerate explicit usable surfaces, intersecting the placement route mask.

    Main is the existing selected-surface alias. Other declared surfaces have
    their own contact IDs; the selected surface is not duplicated. These lists
    are for contact search only. Callers must retain every
    placement in the geometry context, including holds unavailable to the route.
    """
    inventory = {item["id"]: item for item in request["scene"]["inventory"]}
    mask = request.get("route_constraints", {}).get("allowed_contacts")
    region = request.get("route_constraints", {}).get("installation_region")
    editable = set(region["editable_placement_ids"]) if region else None
    allowed = {limb: [] for limb in LIMBS}
    for placement in placements:
        if editable is not None and placement["id"] not in editable:
            continue
        item = inventory[placement["inventory_id"]]
        primary = selected_contact(placement, item)
        surfaces = [("main", primary)] + [(surface["id"], surface)
                    for surface in item.get("grip_surfaces", []) if surface is not primary]
        for contact_id, contact in surfaces:
            for limb in contact["limbs"]:
                if mask is None or placement["id"] in mask[limb]:
                    allowed[limb].append({"placement_id": placement["id"], "contact_id": contact_id})
    return allowed


def allowed_contact_ids(request, placements):
    """Compatibility view of placements with at least one permitted surface."""
    return {limb: {ref["placement_id"] for ref in refs}
            for limb, refs in allowed_contact_refs(request, placements).items()}


def constraint_errors(request, placements=None, *, states=None):
    """Check mask references and required contacts without modifying geometry.

    Reference geometry may be unavailable during request-only validation;
    candidate validation must supply its complete installed placements.
    """
    mask = request.get("route_constraints", {}).get("allowed_contacts")
    allowed = {limb: set(mask[limb]) for limb in LIMBS} if mask is not None else None
    errors = installation_errors(request, placements)
    if placements is not None:
        ids = {p["id"] for p in placements}
        for limb in LIMBS if mask is not None else ():
            unknown = allowed[limb] - ids
            if unknown:
                errors.append(f"route_constraints {limb}: unknown placement IDs {', '.join(sorted(unknown))}")
        try:
            if mask is not None:
                allowed = allowed_contact_ids(request, placements)
        except (KeyError, ValueError) as exc:
            errors.append(f"route_constraints: invalid installed contact: {exc}")
    contacts = [(name, request[name]) for name in ("start_contacts", "end_contacts")]
    contacts.extend((state["id"], state["contacts"]) for state in states or [])
    for name, refs in contacts:
        for limb, ref in refs.items():
            if ref is not None and allowed is not None and ref["placement_id"] not in allowed[limb]:
                errors.append(f"{name}: {limb} contact {ref['placement_id']} excluded by route_constraints or surface permissions")
            elif ref is not None and placements is not None:
                installed = {p["id"]: p for p in placements}
                inventory = {item["id"]: item for item in request["scene"]["inventory"]}
                # Legacy basic generators retain failed main-target attempts
                # outside a supplied custom layout. The evaluator marks those
                # invalid; keep that historical failure record importable.
                # New explicit surfaces and any mask remain strict.
                if mask is None and ref["contact_id"] == "main" and ref["placement_id"] not in installed:
                    continue
                try:
                    placement = installed[ref["placement_id"]]
                    surface = selected_contact(placement, inventory[placement["inventory_id"]], ref["contact_id"])
                    if limb not in surface["limbs"]:
                        errors.append(f"{name}: {limb} contact {ref['placement_id']} excluded by surface permissions")
                except (KeyError, ValueError) as exc:
                    errors.append(f"{name}: invalid {limb} contact: {exc}")
    return errors


def installation_errors(request, placements=None):
    """Enforce the same real footprint/frozen-neighbour contract everywhere.

    This runs at request, search, evaluation and bundle-import boundaries via
    constraint_errors. A route mask can narrow permissions, never unlock a
    neighbouring installed hold. Full physical geometry remains present.
    """
    region = request.get("route_constraints", {}).get("installation_region")
    if region is None:
        return []
    errors = []
    editable = set(region["editable_placement_ids"])
    fixed = {p["id"]: p for p in region["fixed_placements"]}
    panels = {p["id"]: p for p in request["scene"].get("wall_panels", [])}
    patches = {p["wall_panel_id"]: p for p in region["patches"]}
    if len(patches) != len(region["patches"]):
        errors.append("installation_region: duplicate panel patches")
    if len(fixed) != len(region["fixed_placements"]) or editable & set(fixed):
        errors.append("installation_region: fixed and editable placement IDs must be unique and disjoint")
    for patch in region["patches"]:
        panel = panels.get(patch["wall_panel_id"])
        if panel is None or not (-panel["width"]/2 <= patch["u_min"] < patch["u_max"] <= panel["width"]/2 and
                0 <= patch["v_min"] < patch["v_max"] <= panel["height"]):
            errors.append(f"installation_region: invalid patch {patch['wall_panel_id']}")
    for limb, ids in request.get("route_constraints", {}).get("allowed_contacts", {}).items():
        if set(ids)-editable:
            errors.append(f"installation_region: {limb} cannot use neighbouring placements")
    if placements is None:
        return errors
    by_id = {p["id"]: p for p in placements}
    if set(by_id) != editable | set(fixed):
        errors.append("installation_region: all editable and fixed placements must remain installed; no undeclared placements")
    for pid, original in fixed.items():
        if by_id.get(pid) != original:
            errors.append(f"installation_region: neighbouring placement {pid} is read-only")
    inventory = {i["id"]: i for i in request["scene"]["inventory"]}
    for pid in editable & set(by_id):
        point = by_id[pid]
        patch = patches.get(point.get("wall_panel_id"))
        item = inventory.get(point["inventory_id"])
        if "mount" in point or patch is None or item is None:
            errors.append(f"installation_region: {pid} mounting is outside the selected area")
            continue
        angle = math.radians(point["rotation_deg"])
        c, s = abs(math.cos(angle)), abs(math.sin(angle))
        hu, hv = (c*item["width"]+s*item["height"])/2, (s*item["width"]+c*item["height"])/2
        eps = 1e-8
        if not (patch["u_min"]-eps <= point["u"]-hu and point["u"]+hu <= patch["u_max"]+eps and
                patch["v_min"]-eps <= point["v"]-hv and point["v"]+hv <= patch["v_max"]+eps):
            errors.append(f"installation_region: {pid} complete footprint is outside the selected area")
    return errors
