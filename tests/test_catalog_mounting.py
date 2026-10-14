"""Finite stock, actual sampled contacts and one-level sloped-face installation."""
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from boulderlab.engine import (catalog_metadata, contact_world, default_request, evaluate,
                              fingerprint, make_bundle, propose, validate_bundle, validate_request)
from boulderlab.geometry import box_corners, frame_axes, height_at, obb_separation, placement_frames


def setup(**kwargs):
    request = default_request(profile="catalog", **kwargs)
    request["solver"]["max_nfev"] = 0
    candidate = propose(request)
    return request, candidate


def check(report, identifier):
    return next(c for c in report["checks"] if c["id"] == identifier)


def placement(candidate, pid):
    return next(p for p in candidate["placements"] if p["id"] == pid)


def test_default_stock_and_identical_template_instances_are_explicit():
    request, candidate = setup()
    inventory = request["scene"]["inventory"]
    assert len(inventory) == 34 and len({h["id"] for h in inventory}) == 34
    assert Counter(h["type"] for h in inventory) == dict(jug=6, directional_edge=4, crimp=6, pocket=2, foothold=8, sloper=2, pinch=2, rail=2, volume=2)
    assert len(catalog_metadata()) == len(request["scene"]["catalog_stock"]) == 9
    for item in inventory:
        siblings = [h for h in inventory if h["template_id"] == item["template_id"]]
        shape = {k: v for k, v in item.items() if k != "id"}
        assert all({k: v for k, v in h.items() if k != "id"} == shape for h in siblings)
    assert len(candidate["placements"]) < len(inventory)
    assert placement(candidate, "foothold_03")["mount"] == {"parent_id": "volume_01", "face_id": "face_1"}
    assert placement(candidate, "directional_edge_03")["mount"]["face_id"] == "face_2"
    assert any(s["contacts"]["LF"] and s["contacts"]["LF"]["placement_id"] == "foothold_03" for s in candidate["states"])


@pytest.mark.parametrize("scenario", ["foot_first", "sidepull", "foot_reposition"])
@pytest.mark.parametrize("moves", [2, 3, 4])
def test_existing_scenarios_and_hand_counts_use_real_stock(scenario, moves):
    request, candidate = setup(scenario=scenario, hand_moves=moves)
    report = evaluate(request, candidate)
    assert check(report, "request_conformance")["status"] == "pass"
    assert check(report, "request_conformance")["evidence"]["hand_moves"] == moves
    for key in ("inventory", "boundary", "hold_collision", "mounting"):
        assert check(report, key)["status"] == "pass", check(report, key)


@pytest.mark.parametrize("counts", [{"jug": 3}, {"foothold": 3}, {"volume": 0}, {"jug": 21}, {"jug": -1}, {"jug": True}, {"unknown": 1}])
def test_insufficient_or_invalid_stock_is_rejected_without_fabrication(counts):
    with pytest.raises(ValueError):
        default_request(profile="catalog", catalog_counts=counts)


def test_zero_optional_stock_and_maximum_stock_have_exact_counts():
    request, candidate = setup(catalog_counts={"directional_edge": 0, "sloper": 0, "pinch": 0, "rail": 0})
    assert all(h["type"] not in {"directional_edge", "sloper", "pinch", "rail"} for h in request["scene"]["inventory"])
    assert not any(p["id"] == "directional_edge_03" for p in candidate["placements"])
    full = default_request(profile="catalog", catalog_counts={t["type"]: 20 for t in catalog_metadata()})
    assert len(full["scene"]["inventory"]) == 180
    validate_request(full)


@pytest.mark.parametrize("kind", ["duplicate_id", "wrong_count", "changed_size", "changed_surface", "left_handed", "off_plane"])
def test_inventory_and_declared_geometry_tampering_is_rejected(kind):
    request, _ = setup()
    inventory = request["scene"]["inventory"]
    if kind == "duplicate_id":
        inventory[1]["id"] = inventory[0]["id"]
    elif kind == "wrong_count":
        request["scene"]["catalog_stock"][0]["count"] -= 1
    elif kind == "changed_size":
        inventory[0]["width"] += .01
    elif kind == "changed_surface":
        inventory[0]["grip_surfaces"][0]["position"][2] += .01
    elif kind == "left_handed":
        inventory[0]["grip_surfaces"][0]["normal"] = [-x for x in inventory[0]["grip_surfaces"][0]["normal"]]
    else:
        volume = next(h for h in inventory if h["type"] == "volume")
        volume["mounting_faces"][0]["origin"][2] += .02
    with pytest.raises(ValueError):
        validate_request(request)


def test_template_contacts_are_on_profile_with_right_handed_surface_frames():
    for item in catalog_metadata():
        for surface in item["grip_surfaces"]:
            x, y, z = surface["position"]
            assert z == pytest.approx(height_at(item, x, y), abs=1e-10)
            axes = frame_axes(surface)
            assert np.allclose(np.cross(axes[:, 0], axes[:, 1]), axes[:, 2])
        for face in item.get("mounting_faces", []):
            axes = frame_axes(face)
            for uv in face["polygon"]:
                vertex = np.asarray(face["origin"])+axes @ [uv[0], uv[1], 0]
                assert vertex[2] == pytest.approx(height_at(item, *vertex[:2]), abs=1e-10)


@pytest.mark.parametrize("angle", [0, 10])
def test_all_default_variants_have_valid_mounts_and_no_collision(angle):
    request, _ = setup(angle_deg=angle)
    for i in range(3):
        candidate = propose(request, i)
        report = evaluate(request, candidate)
        for key in ("boundary", "hold_collision", "mounting"):
            assert check(report, key)["status"] == "pass"
        assert check(report, "hold_collision")["evidence"]["parent_child_exemptions"] == [["directional_edge_03", "volume_01"], ["foothold_03", "volume_01"]]
        assert all(c["status"] == "not_checked" for c in report["checks"] if c.get("scope") == "P1")


@pytest.mark.parametrize("kind", ["missing_parent", "self_cycle", "nested", "wrong_parent", "missing_face", "unknown_surface", "duplicate_install", "off_face", "normal_offset", "wrong_limb"])
def test_invalid_mounts_surfaces_and_installations_have_explicit_failures(kind):
    request, candidate = setup()
    child = placement(candidate, "foothold_03")
    parent = placement(candidate, "volume_01")
    if kind == "missing_parent":
        child["mount"]["parent_id"] = "missing"
    elif kind == "self_cycle":
        child["mount"]["parent_id"] = child["id"]
    elif kind == "nested":
        parent["mount"] = {"parent_id": child["id"], "face_id": "face_1"}
    elif kind == "wrong_parent":
        child["mount"]["parent_id"] = "jug_01"
    elif kind == "missing_face":
        child["mount"]["face_id"] = "missing"
    elif kind == "unknown_surface":
        child["contact_surface_id"] = "missing"
    elif kind == "duplicate_install":
        duplicate = deepcopy(child); duplicate["id"] = "duplicate"; candidate["placements"].append(duplicate)
    elif kind == "off_face":
        child["u"] = .7
    elif kind == "normal_offset":
        child["mount"]["offset"] = .1  # The contract permits no hidden normal offset.
    else:
        candidate["states"][0]["contacts"]["LH"] = {"placement_id": "foothold_03", "contact_id": "main"}
    report = evaluate(request, candidate)
    assert report["summary"]["status"] == "fail"
    assert any(c["status"] == "fail" for c in report["checks"] if c["id"] in {"schema", "inventory", "mounting", "request_conformance"})
    assert not any(p.get("joints") for p in report["poses"])


def test_invalid_footprint_is_not_granted_parent_child_collision_exemption():
    request, candidate = setup()
    child = placement(candidate, "foothold_03")
    child["v"] = .18
    report = evaluate(request, candidate)
    assert check(report, "mounting")["status"] == "fail"
    assert ["foothold_03", "volume_01"] not in check(report, "hold_collision")["evidence"]["parent_child_exemptions"]


def test_siblings_and_unrelated_overlapping_volume_are_not_exempt():
    request, candidate = setup()
    sibling = deepcopy(placement(candidate, "directional_edge_03"))
    sibling.update(id="directional_edge_04", inventory_id="directional_edge_04")
    candidate["placements"].append(sibling)
    report = evaluate(request, candidate)
    assert check(report, "mounting")["status"] == "pass"
    pairs = check(report, "hold_collision")["evidence"]["conflicts"]
    assert any(set(pair["placements"]) == {"directional_edge_03", "directional_edge_04"} for pair in pairs)
    second = deepcopy(placement(candidate, "volume_01")); second.update(id="volume_02", inventory_id="volume_02")
    candidate["placements"].append(second)
    report = evaluate(request, candidate)
    assert any(set(pair["placements"]) == {"volume_01", "volume_02"} for pair in check(report, "hold_collision")["evidence"]["conflicts"])
    validate_bundle(make_bundle(request, [candidate], [report]))


def test_parent_rotation_wall_tilt_and_surface_changes_affect_actual_targets():
    request, candidate = setup(angle_deg=10)
    inventory = {h["id"]: h for h in request["scene"]["inventory"]}
    parent = placement(candidate, "volume_01"); parent["rotation_deg"] = 37
    child = placement(candidate, "foothold_03"); child.update(u=.01, v=.015, rotation_deg=-23)
    item = inventory[child["inventory_id"]]
    face = inventory[parent["inventory_id"]]["mounting_faces"][0]
    a, b, c = map(math.radians, [10, 37, -23])
    wall = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    rz = lambda t: np.array([[math.cos(t), -math.sin(t), 0], [math.sin(t), math.cos(t), 0], [0, 0, 1]])
    face_frame = np.column_stack([face[k] for k in ("u_axis", "v_axis", "normal")])
    expected = wall @ (np.array([parent["u"], parent["v"], 0])+rz(b) @ (np.asarray(face["origin"])+face_frame @ (np.array([child["u"], child["v"], 0])+rz(c) @ item["grip_surfaces"][0]["position"])))
    target = contact_world(request, child, item, candidate["placements"])
    assert np.allclose(target, expected, atol=1e-12)
    before = fingerprint(request, candidate)
    child["contact_surface_id"] = "alternate"
    assert fingerprint(request, candidate) != before
    alternate = contact_world(request, child, item, candidate["placements"])
    assert np.linalg.norm(alternate-target) > .001
    before = fingerprint(request, candidate)
    parent["u"] += .08
    assert fingerprint(request, candidate) != before
    moved = contact_world(request, child, item, candidate["placements"])
    assert np.allclose(moved-alternate, [.08, 0, 0])


def test_sat_detects_overlap_and_separation_along_out_of_wall_axis():
    item = {"width": .2, "height": .2, "depth": .1}
    a = (np.zeros(3), np.eye(3))
    b = (np.array([0, 0, .101]), np.eye(3))
    assert obb_separation(item, a, item, b) == pytest.approx(.001)
    b = (np.array([0, 0, .09]), np.eye(3))
    assert obb_separation(item, a, item, b) == pytest.approx(-.01)
    assert box_corners(item, a).shape == (8, 3)


def test_catalog_fixed_layout_locks_surface_and_mount_as_well_as_coordinates():
    request, candidate = setup(mode="fixed")
    assert all(propose(request, i)["placements"] == request["reference_layout"] for i in range(3))
    placement(candidate, "foothold_03")["contact_surface_id"] = "alternate"
    assert check(evaluate(request, candidate), "fixed_layout")["status"] == "fail"


def test_catalog_demo_is_current_and_contains_solved_mounted_contacts():
    bundle = json.loads((Path(__file__).resolve().parents[1]/"fixtures/catalog-demo-bundle.json").read_text())
    validate_bundle(bundle)
    assert bundle["request"]["profile"] == "catalog"
    assert len(bundle["candidates"]) == len(bundle["evaluations"]) == 3
