"""A spent shared audit budget must never manufacture verified poses."""
import json
from pathlib import Path
import time

from boulderlab import engine
from boulderlab.beta_audit import _audit_context, orientation_support


def test_expired_audit_deadline_does_not_invoke_ik_or_publish_skeletons(monkeypatch):
    bundle = json.loads((Path(__file__).resolve().parents[1] / "fixtures/route-mixed_flow-bundle.json").read_text())
    def forbidden(*args, **kwargs):
        raise AssertionError("the shared deadline expired before IK")
    monkeypatch.setattr(engine, "solve_pose", forbidden)
    result = engine.evaluate(bundle["request"], bundle["candidates"][0],
                             sequence_policy="independent_beta", deadline=time.perf_counter()-1)
    assert result["summary"]["status"] == "unknown"
    assert result["sequence_policy"] == "independent_beta"
    assert len(result["poses"]) == len(bundle["candidates"][0]["states"])
    for pose in result["poses"]:
        assert pose["status"] == "unknown"
        assert pose["evidence"]["reason"] == "shared_audit_time_budget"
        assert "joints" not in pose and "q" not in pose
    assert all(check["status"] == "not_checked" for check in result["checks"] if check.get("scope") == "P1")


def test_released_foot_cannot_widen_its_own_support_interval():
    bundle = json.loads((Path(__file__).resolve().parents[1] / "fixtures/route-mixed_flow-bundle.json").read_text())
    candidate = bundle["candidates"][0]
    context = _audit_context(bundle["request"], candidate["placements"])
    contacts = candidate["states"][0]["contacts"]
    two_feet = orientation_support(context, contacts, "LH")
    one_foot = orientation_support(context, contacts, "LF")
    assert two_feet["retained_foot_count"] == 2
    assert two_feet["trunk_outside_foot_interval"] == 0
    assert one_foot["retained_foot_count"] == 1
    assert one_foot["trunk_outside_foot_interval"] > 0
