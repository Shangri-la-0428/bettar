"""Route contact selection is separate from installed, collidable geometry."""
from __future__ import annotations

from .geometry import selected_contact

LIMBS = ("LH", "RH", "LF", "RF")


def allowed_contact_ids(request, placements):
    """Intersect an optional route mask with each selected surface's permissions.

    Returned sets are for contact search only. Callers must retain every
    placement in the geometry context, including holds unavailable to the route.
    """
    inventory = {item["id"]: item for item in request["scene"]["inventory"]}
    mask = request.get("route_constraints", {}).get("allowed_contacts")
    allowed = {limb: set() for limb in LIMBS}
    for placement in placements:
        contact = selected_contact(placement, inventory[placement["inventory_id"]])
        for limb in contact["limbs"]:
            if mask is None or placement["id"] in mask[limb]:
                allowed[limb].add(placement["id"])
    return allowed


def constraint_errors(request, placements=None, *, states=None):
    """Check mask references and required contacts without modifying geometry.

    Reference geometry may be unavailable during request-only validation;
    candidate validation must supply its complete installed placements.
    """
    mask = request.get("route_constraints", {}).get("allowed_contacts")
    if mask is None:
        return []
    allowed = {limb: set(mask[limb]) for limb in LIMBS}
    errors = []
    if placements is not None:
        ids = {p["id"] for p in placements}
        for limb in LIMBS:
            unknown = allowed[limb] - ids
            if unknown:
                errors.append(f"route_constraints {limb}: unknown placement IDs {', '.join(sorted(unknown))}")
        try:
            allowed = allowed_contact_ids(request, placements)
        except (KeyError, ValueError) as exc:
            errors.append(f"route_constraints: invalid installed contact: {exc}")
    contacts = [(name, request[name]) for name in ("start_contacts", "end_contacts")]
    contacts.extend((state["id"], state["contacts"]) for state in states or [])
    for name, refs in contacts:
        for limb, ref in refs.items():
            if ref is not None and ref["placement_id"] not in allowed[limb]:
                errors.append(f"{name}: {limb} contact {ref['placement_id']} excluded by route_constraints or surface permissions")
    return errors
