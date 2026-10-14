"""Route contact selection is separate from installed, collidable geometry."""
from __future__ import annotations

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
    allowed = {limb: [] for limb in LIMBS}
    for placement in placements:
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
    errors = []
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
