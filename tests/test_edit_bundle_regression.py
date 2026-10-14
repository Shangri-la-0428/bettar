"""An edited route may fail geometry checks and must still serialize its evidence."""
from copy import deepcopy
import json

import pytest

from boulderlab.engine import (canonical_hash, default_request, evaluate,
                              make_bundle, propose, validate_bundle)


@pytest.mark.parametrize("edit", ["browser_drag", "exact_overlap"])
def test_ten_degree_manual_edit_collision_survives_evaluate_bundle_validate(edit):
    request = default_request(profile="competition", angle_deg=10)
    original = propose(request)
    candidate = deepcopy(original)
    candidate.update(id=f"manual-{edit}", parent_id=original["id"], revision=2, generator="manual")
    pinch = next(p for p in candidate["placements"] if p["id"] == "pinch_01")
    rail = next(p for p in candidate["placements"] if p["id"] == "rail_01")
    if edit == "browser_drag":
        pinch["u"] = -1.123492398396589
    else:
        pinch.update(u=rail["u"], v=rail["v"])
    report = evaluate(request, candidate)
    collision = next(c for c in report["checks"] if c["id"] == "hold_collision")
    assert collision["status"] == "fail"
    assert {"pinch_01", "rail_01"} <= set(collision["placement_ids"])
    pairs = [c["placements"] for c in collision["evidence"]["conflicts"]]
    assert ["pinch_01", "rail_01"] in pairs
    assert report["summary"]["status"] == "fail"
    bundle = make_bundle(request, [candidate], [report])
    decoded = json.loads(json.dumps(bundle, allow_nan=False))
    assert validate_bundle(decoded) == decoded
    assert decoded["evaluations"][0] == report
    assert original["placements"][0]["u"] == -1.25


@pytest.mark.parametrize("payload", [
    {"placements": ["p2", "p1"]},
    {"evidence": {"placements": ["p2", "p1"]}},
    {"evidence": {"placements": [{"id": "p2"}, {"id": "p1"}]}},
    {"candidate": {"states": [{"id": "s2"}, {"id": "s1"}]}},
    {"candidate": {"events": [{"limb": "LH"}, {"limb": "RH"}]}},
])
def test_canonical_hash_preserves_evidence_and_sequence_order(payload):
    reversed_payload = deepcopy(payload)
    value = reversed_payload
    while isinstance(value, dict):
        value = next(iter(value.values()))
    value.reverse()
    assert canonical_hash(payload) != canonical_hash(reversed_payload)


@pytest.mark.parametrize("payload", [
    {"scene": {"inventory": [{"id": "h2"}, {"id": "h1"}]}},
    {"reference_layout": [{"id": "p2"}, {"id": "p1"}]},
    {"placements": [{"id": "p2"}, {"id": "p1"}]},
    {"request": {"scene": {"inventory": [{"id": "h2"}, {"id": "h1"}]}}},
    {"request": {"reference_layout": [{"id": "p2"}, {"id": "p1"}]}},
    {"candidate": {"placements": [{"id": "p2"}, {"id": "p1"}]}},
    {"candidates": [{"placements": [{"id": "p2"}, {"id": "p1"}]}]},
])
def test_canonical_hash_still_normalizes_declared_id_collections(payload):
    reordered = deepcopy(payload)
    value = reordered
    while not (isinstance(value, list) and "id" in value[0]):
        value = next(iter(value.values())) if isinstance(value, dict) else value[0]
    value.reverse()
    assert canonical_hash(payload) == canonical_hash(reordered)
