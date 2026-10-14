"""Record the actual searched roof beta, exit poses and history estimates."""
from pathlib import Path
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from boulderlab.engine import code_hash, validate_bundle
from boulderlab.geometry import panel_frame
from boulderlab.wall_clearance import wall_clearance_report
from boulderlab.setting import roof_exit_support


def summarize(request, candidate, evaluation):
    placements = {p["id"]: p for p in candidate["placements"]}
    states = {s["id"]: s for s in candidate["states"]}
    poses = {p["state_id"]: p for p in evaluation["poses"]}
    mechanics = {s["state_id"]: s for s in evaluation.get("mechanics_report", {}).get("states", [])}
    analysis = evaluation.get("design_analysis") or {}
    moves = {m["event_index"]: m for m in analysis.get("moves", [])}
    exit_panel = next(p for p in request["scene"]["wall_panels"] if p["id"] == "upper-wall")
    origin, axes = panel_frame(exit_panel, request["scene"]["angle_deg"])
    observations = []
    for state in candidate["states"]:
        pose = poses.get(state["id"], {})
        contacts = {limb: {"placement_id": ref["placement_id"],
                          "panel_id": placements[ref["placement_id"]]["wall_panel_id"]} if ref else None
                    for limb, ref in state["contacts"].items()}
        entry = {"state_id": state["id"], "contacts": contacts, "pose_status": pose.get("status"),
                 "mechanics_status": mechanics.get(state["id"], {}).get("status")}
        if pose.get("status") == "pass":
            joints = pose["joints"]
            shoulder = (np.array(joints["left_shoulder"])+joints["right_shoulder"])/2
            entry.update(pelvis_exit_frame_m=(axes.T @ (np.array(joints["pelvis"])-origin)).tolist(),
                         shoulders_exit_frame_m=(axes.T @ (shoulder-origin)).tolist(),
                         wall_clearance=wall_clearance_report(request["scene"], joints))
        observations.append(entry)
    events = []
    for index, event in enumerate(candidate["events"]):
        arrival = states[event["to_state"]]
        target = arrival["contacts"][event["limb"]]["placement_id"]
        event_panels = {placements[ref["placement_id"]]["wall_panel_id"]
                        for ref in arrival["contacts"].values() if ref}
        move = moves.get(index, {})
        events.append({"event_index": index, "limb": event["limb"], "target": target,
            "target_panel": placements[target]["wall_panel_id"],
            "from_state": event["from_state"], "release_state": event["release_state"], "to_state": event["to_state"],
            "spans_exit_and_lower_contacts": "upper-wall" in event_panels and len(event_panels) > 1,
            **{key: move.get(key) for key in ("prior_load", "fresh_burden", "effective_burden", "accumulated_load", "rest_opportunity", "recovery_proxy")}})
    exit_events = [e for e in events if e["spans_exit_and_lower_contacts"]]
    used = {ref["placement_id"] for state in candidate["states"] for ref in state["contacts"].values() if ref}
    return {"candidate_id": candidate["id"], "p0": evaluation["summary"],
            "moves": len(events), "hand_moves": sum(e["limb"].endswith("H") for e in events),
            "foot_moves": sum(e["limb"].endswith("F") for e in events),
            "installed": len(placements), "used": len(used), "unused": sorted(set(placements)-used),
            "first_exit_transfer": exit_events[0] if exit_events else None,
            "exit_peak": max(exit_events, key=lambda e: e["effective_burden"] or 0) if exit_events else None,
            "mechanics_summary": evaluation.get("mechanics_report", {}).get("summary"),
            "exit_support": roof_exit_support(candidate, evaluation),
            "load_summary": analysis.get("summary"),
            "skeleton_crossing_states": [s["state_id"] for s in observations if s.get("wall_clearance", {}).get("status") == "fail"],
            "unverified_pose_states": [s["state_id"] for s in observations if s["pose_status"] != "pass"],
            "states": observations, "events": events}


def main():
    out = ROOT / "outputs/roof-study"
    out.mkdir(parents=True, exist_ok=True)
    bundle = validate_bundle(json.loads((ROOT / "fixtures/wall-roof-bundle.json").read_text()))
    request = bundle["request"]
    comparisons = []
    for candidate in bundle["candidates"]:
        evaluation = next(e for e in bundle["evaluations"] if e["candidate_id"] == candidate["id"])
        assert candidate.get("layout_report") is None, "roof remains a layout-only draft"
        assert evaluation["summary"]["status"] == "pass", "current roof has unresolved geometry/pose checks"
        report = candidate["setting_report"]
        paths = {"before": summarize(request, report["baseline_candidate"], report["baseline_evaluation"]),
                 "after": summarize(request, candidate, evaluation),
                 "alternatives": [summarize(request, a["candidate"], a["evaluation"]) for a in report["allowed_alternatives"]]}
        for path in [paths["before"], paths["after"], *paths["alternatives"]]:
            assert not path["skeleton_crossing_states"] and not path["unverified_pose_states"]
        assert any(e["target_panel"] == "roof" and e["limb"].endswith("H") for e in paths["after"]["events"])
        assert paths["after"]["first_exit_transfer"] is not None
        comparisons.append({"candidate_id": candidate["id"], "name": candidate["name"],
                            "selection_role": report["selection_role"], "paths": paths,
                            "layout_changes": report["changes"], "search": report["search"],
                            "changed_but_unused": [c["placement_id"] for c in report["changes"]
                                                   if c["placement_id"] in paths["after"]["unused"]]})
    previous = json.loads((out / "before-folded-bundle.json").read_text())
    record = {"code_hash": code_hash(), "bundle_digest": bundle["manifest"]["bundle_digest"],
        "fixture": "fixtures/wall-roof-bundle.json", "wall_panels": request["scene"]["wall_panels"],
        "historical_failure": {"file": "outputs/roof-study/before-folded-bundle.json",
            "code_hash": previous["manifest"]["code_hash"], "status": previous["candidates"][0]["layout_report"]["status"],
            "note": "Historical evidence only; not a current-engine evaluation or controlled before/after experiment."},
        "comparison_basis": "Before and after use the same current solver, wall, inventory, body and synthetic mechanics parameters. Alternatives keep the selected installed geometry. Fresh/history values compare the same action sequence.",
        "comparisons": comparisons,
        "limits": ["P0 validates only the declared geometry, discrete contacts and zero-radius skeleton crossings.",
                   "No continuous trajectories, body volume, hook techniques or human forerunning were verified.",
                   "Load/recovery values are uncalibrated relative proxies, not energy, fatigue percentages or climbing grades.",
                   "Quasi-static failures remain visible; passing geometry does not establish real climbability."]}
    (out / "comparison.json").write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps([{"name": c["name"],
                       "after": {k: c["paths"]["after"][k] for k in ("p0", "moves", "exit_peak", "exit_support", "mechanics_summary")},
                       "alternatives": len(c["paths"]["alternatives"]),
                       "changed_placements": len(c["layout_changes"]),
                       "changed_but_unused": c["changed_but_unused"]} for c in comparisons], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
