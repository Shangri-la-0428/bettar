"""Shape, contact role and direction are independent catalog properties."""
from copy import deepcopy

import numpy as np
import pytest

from boulderlab.catalog import catalog_metadata, hold_taxonomy, make_inventory, validate_catalog
from boulderlab.geometry import frame_axes, grip_surfaces, height_at, rotation_z


def template(kind):
    return next(item for item in catalog_metadata() if item["type"] == kind)


def test_canonical_families_are_separate_from_legacy_shape_labels():
    metadata = catalog_metadata()
    assert {item["taxonomy"]["family"] for item in metadata} == {
        "jug", "crimp", "pinch", "sloper", "pocket", "foot_chip", "volume"}
    assert hold_taxonomy("directional_edge")["family"] == "crimp"
    assert hold_taxonomy("rail")["family"] == "crimp"
    assert hold_taxonomy("rail")["form"] == "rail"
    assert hold_taxonomy("volume")["preferred_role"] == "structure"
    assert all(item["taxonomy"]["family"] not in {"sidepull", "undercling"} for item in metadata)


def test_pocket_has_recessed_floor_and_rim_and_contact_roles_are_explicit():
    pocket = template("pocket")
    floor = height_at(pocket, 0, pocket["height"]*.06)
    rim = height_at(pocket, 0, pocket["height"]*.32)
    assert rim-floor > .45*pocket["depth"]
    assert floor > 0  # A closed well, not an accidental hole through the wall.
    assert pocket["taxonomy"]["roles"] == ["hand", "foot"]
    internal = [s for s in pocket["grip_surfaces"] if s["id"] != "standing"]
    external = next(s for s in pocket["grip_surfaces"] if s["id"] == "standing")
    assert all(s["limbs"] == ["LH", "RH"] for s in internal)
    assert external["limbs"] == ["LF", "RF"]
    assert external["position"][1] > max(s["position"][1] for s in internal)


def test_crimp_is_a_shallow_edge_with_small_contact_region():
    crimp = template("crimp")
    assert crimp["depth"] < template("jug")["depth"]*.5
    assert crimp["width"] > crimp["height"]
    assert max(s["radii"][1] for s in crimp["grip_surfaces"]) <= .006
    assert height_at(crimp, 0, crimp["height"]*.05) > height_at(crimp, 0, crimp["height"]*.30)+.015
    assert all(set(s["limbs"]) == {"LH", "RH", "LF", "RF"} for s in crimp["grip_surfaces"])


@pytest.mark.parametrize("kind", ["crimp", "pocket"])
def test_new_surface_frames_match_actual_geometry_and_rotate_without_reclassification(kind):
    hold = template(kind)
    original = deepcopy(hold["taxonomy"])
    for surface in hold["grip_surfaces"]:
        x, y, z = surface["position"]
        assert height_at(hold, x, y) == pytest.approx(z)
        axes = frame_axes(surface)
        assert np.linalg.det(axes) == pytest.approx(1)
        transformed = rotation_z(90) @ axes
        assert np.allclose(transformed.T @ transformed, np.eye(3))
    assert hold["taxonomy"] == original


def test_new_stock_is_finite_and_classification_tampering_is_rejected():
    inventory, stock = make_inventory({"pocket": 0, "crimp": 3})
    assert len([item for item in inventory if item["type"] == "crimp"]) == 3
    assert not any(item["type"] == "pocket" for item in inventory)
    request = {"scene": {"inventory": inventory, "catalog_stock": stock}}
    validate_catalog(request)
    inventory[0]["taxonomy"]["family"] = "sloper"
    with pytest.raises(ValueError, match="taxonomy"):
        validate_catalog(request)
