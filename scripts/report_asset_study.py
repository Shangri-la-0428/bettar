"""Summarize actual validated saved results; never infer human climbability."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from boulderlab.engine import validate_bundle, code_hash
from boulderlab.hold_assets import load_registry


def summarize(path):
    bundle = validate_bundle(json.loads(path.read_text()))
    request = bundle["request"]
    candidate = bundle["candidates"][0]
    evaluation = next(e for e in bundle["evaluations"] if e["candidate_id"] == candidate["id"])
    report = candidate.get("setting_report", {})
    inventory = request["scene"]["inventory"]
    used = {ref["placement_id"] for state in candidate["states"]
            for ref in state["contacts"].values() if ref}
    return {
        "file": str(path.relative_to(ROOT)),
        "bundle_digest": bundle["manifest"]["bundle_digest"],
        "candidate_id": candidate["id"],
        "hold_source": request.get("setting_design", {}).get("hold_source"),
        "wall_profile": request.get("setting_design", {}).get("wall_profile", "default"),
        "p0": evaluation["summary"],
        "mechanics": evaluation.get("mechanics_report", {}).get("summary"),
        "baseline_mechanics": report.get("baseline", {}).get("mechanics_summary"),
        "moves": len(candidate["events"]),
        "states": len(candidate["states"]),
        "installed": len(candidate["placements"]),
        "used": len(used),
        "unused": sorted(p["id"] for p in candidate["placements"] if p["id"] not in used),
        "imported_instances": [{"id": h["id"], "asset_id": h["asset_id"], "family": h["type"],
            "scale": h["asset_scale"], "dimensions_m": [h[k] for k in ("width", "height", "depth")]}
            for h in inventory if h.get("asset_id")],
        "fallbacks": [{"id": h["id"], "family": h["type"], "reason": h["asset_fallback_reason"]}
            for h in inventory if h.get("asset_fallback_reason")],
        "asset_application": request.get("setting_design", {}).get("asset_application"),
        "wall_application": request.get("setting_design", {}).get("wall_application"),
        "geometry_changes": len(report.get("changes", [])),
        "verified_alternatives": len(report.get("allowed_alternatives", [])),
        "search": report.get("search"),
    }


def main():
    assets = load_registry()
    out = ROOT / "outputs/asset-study"
    out.mkdir(parents=True, exist_ok=True)
    comparison = {
        "code_hash": code_hash(),
        "coverage": {"external_families": sorted({a["family"] for a in assets.values()}),
            "missing_external_families": sorted({"jug", "crimp", "pinch", "sloper", "pocket"} - {a["family"] for a in assets.values()}),
            "assets": len(assets), "scale_verified": False, "annotation_review": "AI draft; human routesetter review pending"},
        "comparison_basis": "Three shared spatial briefs, independently searched. Assets preserve proportions at unmeasured demo widths; family substitutions, footprint repairs and contact surfaces also differ. This is not a controlled test of mesh fidelity alone.",
        "limits": ["P0 passes only implemented geometry and discrete pose checks.",
            "Static diagnostics use synthetic force/friction assumptions; failures do not rule out dynamic climbing.",
            "Mesh realism does not establish route quality, real grade or forerun success."],
        "programs": {},
    }
    for program in ("diagonal_balance", "opposing_sidepulls", "roof_exit"):
        comparison["programs"][program] = {
            "assets": summarize(ROOT / "fixtures" / f"setting-{program}-bundle.json"),
            "templates": summarize(ROOT / "fixtures" / f"setting-templates-{program}-bundle.json"),
        }
    (out / "comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({p: {s: {k: r[k] for k in ("p0", "mechanics", "geometry_changes", "verified_alternatives")}
        for s, r in sides.items()} for p, sides in comparison["programs"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
