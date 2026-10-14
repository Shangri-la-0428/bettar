from copy import deepcopy
import json

import pytest

from boulderlab.engine import (canonical_hash, evaluate, fingerprint, generate,
                              make_bundle, validate_bundle)


def test_ac11_hash_ignores_dictionary_order():
    assert canonical_hash({"a": 1, "b": {"x": 2, "y": 3}}) == canonical_hash({"b": {"y": 3, "x": 2}, "a": 1})


def test_ac11_inventory_order_does_not_change_fingerprint(example):
    request, candidate = example
    before = fingerprint(request, candidate)
    request["scene"]["inventory"].reverse()
    candidate["placements"].reverse()
    assert fingerprint(request, candidate) == before


def test_ac14_serialized_bundle_roundtrip(example):
    request, candidate = example
    bundle = make_bundle(request, [candidate])
    decoded = json.loads(json.dumps(bundle, allow_nan=False))
    assert validate_bundle(decoded) == decoded
    assert decoded["evaluations"][0]["fingerprint"] == fingerprint(request, candidate)


def test_ac14_bundle_is_an_immutable_input_snapshot(example):
    request, candidate = example
    bundle = make_bundle(request, [candidate])
    original = deepcopy(bundle)
    request["body"]["upper_arm"] += 0.1
    candidate["placements"][0]["u"] += 0.1
    assert bundle == original


@pytest.mark.parametrize("kind", ["body", "angle", "rotation", "inventory", "solver"])
def test_ac10_changed_dependencies_invalidate_old_evaluation(example, kind):
    request, candidate = example
    old = evaluate(request, candidate)
    if kind == "body":
        request["body"]["forearm"] += 0.02
    elif kind == "angle":
        request["scene"]["angle_deg"] = 10
    elif kind == "rotation":
        candidate["placements"][0]["rotation_deg"] = 20
    elif kind == "inventory":
        request["scene"]["inventory"][0]["width"] += 0.01
    else:
        request["solver"]["contact_tolerance_m"] += 0.001
    assert fingerprint(request, candidate) != old["fingerprint"]
    with pytest.raises(ValueError):
        validate_bundle(make_bundle(request, [candidate], evaluations=[old]))


@pytest.mark.parametrize("kind", ["schema", "missing_request", "position", "evaluation_status", "evaluation_version", "manifest"])
def test_ac12_ac14_tampered_bundles_are_rejected(example, kind):
    request, candidate = example
    bundle = make_bundle(request, [candidate])
    if kind == "schema":
        bundle["schema_version"] = "99.0"
    elif kind == "missing_request":
        bundle.pop("request")
    elif kind == "position":
        bundle["candidates"][0]["placements"][0]["u"] += 0.05
    elif kind == "evaluation_status":
        bundle["evaluations"][0]["checks"][0]["status"] = "unknown"
    elif kind == "evaluation_version":
        bundle["evaluations"][0]["version"] = "obsolete-version"
    else:
        bundle["manifest"] = {}
    with pytest.raises(ValueError):
        validate_bundle(bundle)


def test_ac09_generation_retains_budget_and_seed(example):
    request, _ = example
    request["budget"] = 2
    first = generate(request)
    second = generate(deepcopy(request))
    assert len(first["candidates"]) == len(first["evaluations"]) == 2
    assert len(second["candidates"]) == 2
    for a, b in zip(first["candidates"], second["candidates"]):
        assert a["placements"] == b["placements"]
        assert a["states"] == b["states"]
        assert a["events"] == b["events"]
    assert all(e["summary"]["status"] != "pass" for e in first["evaluations"])
    # No hidden filtering: zero IK budget still yields failed/unknown attempts.
    assert first["request"]["seed"] == request["seed"]
    validate_bundle(first)


@pytest.mark.parametrize("kind", ["missing_poses", "missing_summary", "unknown_with_joints",
                                     "joint_wrong_length", "joint_not_number", "summary_status", "summary_count"])
def test_ac12_structural_evaluation_errors_with_fresh_digest(example, kind):
    request, candidate = example
    report = evaluate(request, candidate)
    if kind == "missing_poses":
        report.pop("poses")
    elif kind == "missing_summary":
        report.pop("summary")
    elif kind == "unknown_with_joints":
        report["poses"][0]["joints"] = {"pelvis": [0, 1, 0.3]}
    elif kind in {"joint_wrong_length", "joint_not_number"}:
        # Construct all required joints so a wrong endpoint is not hidden by an
        # absent-joint error. A pose's shape must be checked before UI rendering.
        from boulderlab.kinematics import forward_kinematics
        q = [0.0] * 22
        q[:3] = [0, 1.1, 0.4]
        pose = report["poses"][0]
        pose.update(status="pass", q=q, residual_m=0,
                    joints={k: v.tolist() for k, v in forward_kinematics(request["body"], q).items()})
        pose["joints"]["left_wrist"] = [0, 1] if kind == "joint_wrong_length" else [0, "bad", 0]
    elif kind == "summary_status":
        report["summary"]["status"] = "pass"  # IK is unknown in this fixture.
    else:
        report["summary"]["passed"] += 1
    # Rebuild through the public constructor to get a matching digest. These
    # tests must detect malformed data, not merely a stale checksum.
    with pytest.raises(ValueError):
        validate_bundle(make_bundle(request, [candidate], evaluations=[report]))


def test_ac12_review_entries_must_be_objects(example):
    request, candidate = example
    bundle = make_bundle(request, [candidate])
    bundle["reviews"] = [None]
    # Reviews are intentionally outside the computational content digest.
    with pytest.raises(ValueError):
        validate_bundle(bundle)


def test_ac12_unevaluated_draft_is_accepted_without_a_pass_claim(example):
    request, candidate = example
    bundle = make_bundle(request, [candidate], evaluations=[])
    accepted = validate_bundle(bundle)
    assert accepted["evaluations"] == []
