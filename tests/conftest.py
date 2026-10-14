"""Hand-built acceptance fixtures; do not treat generator output as ground truth."""

from copy import deepcopy

import pytest


@pytest.fixture
def example():
    from boulderlab.engine import default_request

    request = default_request(budget=2)
    request["solver"]["max_nfev"] = 0
    request["solver"]["restarts"] = 1
    # Simple known 12 cm boxes keep geometry examples independent of asset art.
    for hold in request["scene"]["inventory"]:
        hold.update(width=0.12, height=0.12, depth=0.08)
        hold["contact"].update(position=[0, 0, 0.08], radius=0.02)
    hands = [h["id"] for h in request["scene"]["inventory"] if h["type"] == "jug"]
    feet = [h["id"] for h in request["scene"]["inventory"] if h["type"] == "foothold"]
    locations = [
        ("h1", hands[0], -0.22, 1.6), ("h2", hands[1], 0.22, 1.6),
        ("h3", hands[2], 0.42, 1.95), ("h4", hands[3], -0.12, 2.15),
        ("f1", feet[0], -0.25, 0.45), ("f2", feet[1], 0.25, 0.45),
        ("f3", feet[2], -0.45, 0.78),
    ]
    placements = [dict(id=i, inventory_id=h, u=u, v=v, rotation_deg=0)
                  for i, h, u, v in locations]

    def contact(placement):
        return {"placement_id": placement, "contact_id": "main"}

    contacts = dict(LH=contact("h1"), RH=contact("h2"),
                    LF=contact("f1"), RF=contact("f2"))
    states = [dict(id="s0", label="initial", contacts=deepcopy(contacts))]
    events = []
    for index, (limb, target) in enumerate([("LF", "f3"), ("RH", "h3"), ("LH", "h4")]):
        from_state = states[-1]["id"]
        contacts[limb] = None
        release = dict(id=f"s{2 * index + 1}", label="release", contacts=deepcopy(contacts))
        contacts[limb] = contact(target)
        arrival = dict(id=f"s{2 * index + 2}", label="arrival", contacts=deepcopy(contacts))
        states.extend([release, arrival])
        events.append(dict(limb=limb, from_state=from_state,
                           release_state=release["id"], to_state=arrival["id"]))
    candidate = dict(id="acceptance-manual", name="Independent fixture", revision=1,
                     parent_id=None, generator="manual", placements=placements,
                     states=states, events=events, design_notes=["Synthetic test fixture"])
    request["start_contacts"] = deepcopy(states[0]["contacts"])
    request["end_contacts"] = deepcopy(states[-1]["contacts"])
    request["reference_layout"] = deepcopy(placements)
    return request, candidate


def checks(evaluation, identifier):
    selected = [c for c in evaluation["checks"] if c["id"] == identifier]
    assert selected, f"Missing required check {identifier}: {evaluation}"
    return selected


def assert_status(evaluation, identifier, expected):
    selected = checks(evaluation, identifier)
    assert {c["status"] for c in selected} == {expected}, selected
    return selected
