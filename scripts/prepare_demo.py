"""Create shipped examples with actual solver results, never mocked poses."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from boulderlab.engine import default_request, generate, validate_bundle


def save_bundle(destination, bundle):
    validate_bundle(bundle)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        previous = json.loads(destination.read_text(encoding="utf-8"))
        if previous["manifest"]["code_hash"] != bundle["manifest"]["code_hash"]:
            history = ROOT / "fixtures" / "history"
            history.mkdir(exist_ok=True)
            suffix = previous["manifest"]["bundle_digest"].split(":")[-1][:12]
            (history / f"{destination.stem}-{suffix}.json").write_bytes(destination.read_bytes())
    destination.write_text(json.dumps(bundle, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    passed = sum(e["summary"]["status"] == "pass" for e in bundle["evaluations"])
    print(f"Saved {len(bundle['candidates'])} candidates, {passed} passed P0: {destination}", flush=True)


def prepare(profile):
    if profile == "wall":
        for wall_profile in ("overhang", "roof", "dihedral", "arete"):
            request = default_request(budget=3, profile="setting", setting_program="diagonal_balance", hold_source="assets", wall_profile=wall_profile)
            save_bundle(ROOT / "fixtures" / f"wall-{wall_profile}-bundle.json", generate(request))
        return
    if profile == "setting":
        for program in ("diagonal_balance", "opposing_sidepulls", "roof_exit"):
            request = default_request(budget=3, profile="setting", setting_program=program)
            bundle = generate(request)
            save_bundle(ROOT / "fixtures" / f"setting-{program}-bundle.json", bundle)
            if program == "diagonal_balance":
                save_bundle(ROOT / "fixtures" / "setting-demo-bundle.json", bundle)
                (ROOT / "fixtures" / "setting-request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        # Same spatial briefs using the retained parametric inventory. These are
        # independently searched baselines, not the same beta with new labels.
        for program in ("diagonal_balance", "opposing_sidepulls", "roof_exit"):
            request = default_request(budget=3, profile="setting", setting_program=program, hold_source="templates")
            save_bundle(ROOT / "fixtures" / f"setting-templates-{program}-bundle.json", generate(request))
        return
    if profile == "route":
        for program in ("mixed_flow", "power_finish", "sustained_finish"):
            request = default_request(budget=3, profile="route", route_program=program, hand_moves=10)
            bundle = generate(request)
            save_bundle(ROOT / "fixtures" / f"route-{program}-bundle.json", bundle)
            if program == "mixed_flow":
                save_bundle(ROOT / "fixtures" / "route-demo-bundle.json", bundle)
                (ROOT / "fixtures" / "route-request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if profile == "style":
        for goal in ("power", "sustained", "technical"):
            request = default_request(budget=3, profile="style", style_goal=goal, rhythm="late_crux")
            bundle = generate(request)
            save_bundle(ROOT / "fixtures" / f"style-{goal}-bundle.json", bundle)
            if goal == "power":
                save_bundle(ROOT / "fixtures" / "style-demo-bundle.json", bundle)
                (ROOT / "fixtures" / "style-request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    request = default_request(budget=3, profile=profile)
    bundle = generate(request)
    passed = sum(e["summary"]["status"] == "pass" for e in bundle["evaluations"])
    if profile == "basic" and passed < 2:
        raise SystemExit(f"Only {passed} checked candidates; demo was not replaced. Inspect solver diagnostics.")
    prefix = f"{profile}-" if profile != "basic" else ""
    save_bundle(ROOT / "fixtures" / f"{prefix}demo-bundle.json", bundle)
    request_name = f"{profile}-request.json" if profile != "basic" else "default-request.json"
    (ROOT / "fixtures" / request_name).write_text(json.dumps(request, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("basic", "competition", "catalog", "style", "route", "setting", "wall", "all"), default="all")
    args = parser.parse_args()
    for profile in (("basic", "competition", "catalog", "style", "route", "setting", "wall") if args.profile == "all" else (args.profile,)):
        prepare(profile)
    if args.profile == "all":
        for profile in ("competition", "catalog"):
            save_bundle(ROOT / "fixtures" / f"{profile}-10deg-bundle.json", generate(default_request(profile=profile, angle_deg=10)))


if __name__ == "__main__":
    main()
