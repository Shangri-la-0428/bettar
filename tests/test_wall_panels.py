"""Panel geometry must affect contacts, mounting and collisions, not just rendering."""
from copy import deepcopy
import math

import numpy as np
import pytest

from boulderlab.engine import catalog_metadata, fingerprint
from boulderlab.geometry import contact_world, frame_axes, obb_separation, panel_fit, placement_frames


def scene_setup():
    items = {h["type"]: deepcopy(h) for h in catalog_metadata()}
    for key, item in items.items():
        item["id"] = key
    panel = {"id": "corner", "label": "转角", "origin": [.4, .2, .3],
             "rotation_deg": [0, 90, 0], "width": 3, "height": 4.2}
    scene = {"angle_deg": 10, "margin": .2, "inventory": list(items.values()), "wall_panels": [panel]}
    hold = {"id": "hand", "inventory_id": "jug", "wall_panel_id": "corner",
            "u": .25, "v": 1.2, "rotation_deg": 30, "contact_surface_id": "working"}
    return items, scene, hold


def test_panel_yaw_wall_tilt_and_hold_rotation_compose_in_declared_order():
    items, scene, hold = scene_setup()
    a, b = math.radians(10), math.radians(30)
    base = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    yaw = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]])
    rz = np.array([[math.cos(b), -math.sin(b), 0], [math.sin(b), math.cos(b), 0], [0, 0, 1]])
    expected = base @ (np.array([.4, .2, .3])+yaw @ (np.array([.25, 1.2, 0])+rz @ items["jug"]["grip_surfaces"][0]["position"]))
    request = {"scene": scene, "reference_layout": [hold]}
    assert np.allclose(contact_world(request, hold, items["jug"]), expected, atol=1e-12)


def test_child_volume_contact_inherits_panel_and_parent_rotation():
    items, scene, parent = scene_setup()
    parent.update(id="volume", inventory_id="volume", contact_surface_id="face_1_grip")
    child = {"id": "foot", "inventory_id": "foothold", "u": .01, "v": -.01, "rotation_deg": -20,
             "contact_surface_id": "working", "mount": {"parent_id": "volume", "face_id": "face_1"}}
    frames = placement_frames([parent, child], items, scene["angle_deg"], scene["wall_panels"])
    po, pa = frames["volume"]
    face = items["volume"]["mounting_faces"][0]
    angle = math.radians(-20)
    rz = np.array([[math.cos(angle), -math.sin(angle), 0], [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
    expected = po+pa @ (np.asarray(face["origin"])+frame_axes(face) @ (np.array([.01, -.01, 0])+rz @ items["foothold"]["grip_surfaces"][0]["position"]))
    request = {"scene": scene, "reference_layout": [parent, child]}
    assert np.allclose(contact_world(request, child, items["foothold"]), expected, atol=1e-12)


@pytest.mark.parametrize("mutation", ["missing", "unknown", "duplicate", "both"])
def test_invalid_panel_reference_never_silently_falls_back_to_flat_wall(mutation):
    items, scene, hold = scene_setup()
    if mutation == "missing":
        del hold["wall_panel_id"]
    elif mutation == "unknown":
        hold["wall_panel_id"] = "absent"
    elif mutation == "duplicate":
        scene["wall_panels"].append(deepcopy(scene["wall_panels"][0]))
    else:
        hold["mount"] = {"parent_id": "volume", "face_id": "face_1"}
    with pytest.raises(ValueError):
        placement_frames([hold], items, scene["angle_deg"], scene["wall_panels"])


def test_panel_boundary_uses_local_rotated_footprint_and_margin():
    items, scene, hold = scene_setup()
    assert panel_fit([hold], items, scene) == []
    hold["u"] = 1.3
    errors = panel_fit([hold], items, scene)
    assert errors[0]["placement_id"] == "hand" and errors[0]["wall_panel_id"] == "corner"


def test_different_panel_frames_affect_world_collision_even_at_equal_local_coordinates():
    items, scene, hold = scene_setup()
    scene["angle_deg"] = 0
    scene["wall_panels"][0].update(origin=[0, 0, 0], rotation_deg=[0, 0, 0])
    second = deepcopy(scene["wall_panels"][0]); second.update(id="second", origin=[0, 0, 2])
    scene["wall_panels"].append(second)
    other = deepcopy(hold); other.update(id="other", wall_panel_id="second")
    frames = placement_frames([hold, other], items, 0, scene["wall_panels"])
    assert obb_separation(items["jug"], frames["hand"], items["jug"], frames["other"]) > 1
    second["origin"] = [0, 0, .01]
    frames = placement_frames([hold, other], items, 0, scene["wall_panels"])
    assert obb_separation(items["jug"], frames["hand"], items["jug"], frames["other"]) < 0


def test_panel_geometry_changes_evidence_fingerprint():
    items, scene, hold = scene_setup()
    request = {"scene": scene}
    candidate = {"placements": [hold]}
    before = fingerprint(request, candidate)
    scene["wall_panels"][0]["rotation_deg"][1] += 5
    assert fingerprint(request, candidate) != before
