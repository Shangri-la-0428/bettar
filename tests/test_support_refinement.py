"""Support repair proposals change installation, not physical assumptions."""
from copy import deepcopy
import math

import numpy as np
import pytest

from boulderlab.draft_generation import build_request
from boulderlab.geometry import placement_frames, rotation_z, panel_fit
from boulderlab.statics import _contact_model
from boulderlab.support_refinement import support_proposals, _mount_basis, _turn_toward, MAX_DISPLACEMENT_M


def request(wall="overhang"):
    return build_request({"wall_profile": wall, "style": "sustained" if wall == "roof" else "balance",
                          "difficulty": "medium", "seed": 42, "variant": 0})


def failed_record(req, contacts):
    placements = req["reference_layout"]
    byid = {p["id"]: p for p in placements}
    inv = {i["id"]: i for i in req["scene"]["inventory"]}
    frames = placement_frames(placements, inv, req["scene"]["angle_deg"], req["scene"]["wall_panels"])
    models = [_contact_model(req, byid[pid], inv[byid[pid]["inventory_id"]], limb, frames,
                req["mechanics_parameters"], placements) for limb, pid in contacts]
    com = np.mean([c["position"] for c in models], axis=0) + [0.10, -.70, .2]
    state = {"state_id": "failed-release", "status": "infeasible", "is_release": True,
             "com_world_m": com.tolist(), "capacity_utilization": None,
             "contacts": [{"limb": c["limb"], "placement_id": c["placement_id"], "contact_id": "main",
                "point_world_m": c["position"].tolist(), "axial_direction_world": c["axis"].tolist(),
                "normal_world": c["normal"].tolist(), "required_force_world_n": None} for c in models]}
    return {"candidate": {"placements": deepcopy(placements)},
            "evaluation": {"mechanics_report": {"states": [state]}}}


def test_uv_displacement_uses_mount_axes_before_hold_rotation():
    req = request("dihedral")
    p = req["reference_layout"][2]
    inv = {i["id"]: i for i in req["scene"]["inventory"]}
    p["rotation_deg"] = 80
    frame = placement_frames(req["reference_layout"], inv, req["scene"]["angle_deg"], req["scene"]["wall_panels"])[p["id"]]
    basis = _mount_basis(p, frame)
    world = basis @ np.array([.08, -.02, .10])
    assert np.allclose(basis.T @ world, [.08, -.02, .10])
    assert not np.allclose(frame[1].T @ world, [.08, -.02, .10])
    assert np.allclose(basis @ rotation_z(80), frame[1])


def test_foot_turn_rotates_actual_normal_toward_required_reaction():
    req = request()
    foot = next(p for p in req["reference_layout"] if p["id"] == "foot-1")
    foot["rotation_deg"] = 70
    record = failed_record(req, [("LF", "foot-1")])
    state = record["evaluation"]["mechanics_report"]["states"][0]
    state["contacts"][0]["required_force_world_n"] = [0., 600., 0.]
    proposals = support_proposals(req, record)
    assert proposals
    points = proposals[0]["placements"]
    inv = {i["id"]: i for i in req["scene"]["inventory"]}
    before = placement_frames(req["reference_layout"], inv, req["scene"]["angle_deg"], req["scene"]["wall_panels"])
    after = placement_frames(points, inv, req["scene"]["angle_deg"], req["scene"]["wall_panels"])
    local_normal = before["foot-1"][1].T @ state["contacts"][0]["normal_world"]
    assert (after["foot-1"][1] @ local_normal)[1] > (before["foot-1"][1] @ local_normal)[1]
    assert next(p for p in points if p["id"] == "foot-1")["rotation_deg"] < 70


def test_proposals_preserve_physics_and_anchor_positions_and_record_failed_evidence():
    req = request()
    record = failed_record(req, [("RH", "start-right"), ("LH", "hand-2"), ("LF", "foot-3")])
    original_request, original_record = deepcopy(req), deepcopy(record)
    proposals = support_proposals(req, record)
    assert proposals
    assert req == original_request and record == original_record
    anchors = {r["placement_id"] for field in ("start_contacts", "end_contacts") for r in req[field].values() if r}
    byid = {p["id"]: p for p in req["reference_layout"]}
    inv = {i["id"]: i for i in req["scene"]["inventory"]}
    for proposal in proposals:
        assert proposal["rationale"]["source_state_ids"] == ["failed-release"]
        assert {"hand-2", "foot-3"} <= {c["placement_id"] for c in proposal["changes"]}
        assert not panel_fit(proposal["placements"], inv, req["scene"])
        for p in proposal["placements"]:
            old = byid[p["id"]]
            assert math.hypot(p["u"]-old["u"], p["v"]-old["v"]) <= MAX_DISPLACEMENT_M + 1e-8
            assert abs(p["rotation_deg"]-old["rotation_deg"]) <= 40 + 1e-8
            if p["id"] in anchors:
                assert (p["u"], p["v"], p.get("wall_panel_id")) == (old["u"], old["v"], old.get("wall_panel_id"))


def test_roof_proposes_declared_pocket_face_and_real_exit_installation():
    req = request("roof")
    record = failed_record(req, [("LH", "hand-3"), ("RH", "hand-4"), ("LF", "foot-6")])
    proposals = support_proposals(req, record)
    alternate = next(p for p in proposals if p["label"] == "declared-grip-and-support")
    pocket = next(p for p in alternate["placements"] if p["id"] == "hand-4")
    assert pocket["contact_surface_id"] == "alternate"
    item = next(i for i in req["scene"]["inventory"] if i["id"] == pocket["inventory_id"])
    assert any(s["id"] == "alternate" and set(s["limbs"]) == {"LH", "RH"} for s in item["grip_surfaces"])
    exit_option = next(p for p in proposals if p["label"] == "roof-exit-support")
    assert "hand-3" in exit_option["rationale"]["panel_migrations"]
    assert next(p for p in exit_option["placements"] if p["id"] == "hand-3")["wall_panel_id"] == "upper-wall"
    assert all(c["panel_migration"] for c in exit_option["changes"] if c["before"].get("wall_panel_id") != c["after"].get("wall_panel_id"))


def test_unknown_or_unfailed_states_do_not_create_evidence_free_edits():
    req = request()
    record = failed_record(req, [("LH", "hand-1")])
    state = record["evaluation"]["mechanics_report"]["states"][0]
    state.update(status="feasible", capacity_utilization=.5)
    assert support_proposals(req, record) == []
    state.update(status="unknown", capacity_utilization=None)
    assert support_proposals(req, record) == []


def test_turn_rejects_rotation_without_an_in_plane_axis():
    assert _turn_toward([0., 0., 1.], [0., 1., 0.], np.eye(3)) == 0
