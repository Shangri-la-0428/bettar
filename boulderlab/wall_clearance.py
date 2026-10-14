"""Independent finite-panel / skeleton-segment crossing check.

The structure is an oriented, zero-thickness rectangle, not an infinite solid
half-space. Only strict crossings through its finite surface are rejected.
This deliberately does not imply capsule clearance or a continuous motion.
"""
from __future__ import annotations

import math
import numpy as np

from .geometry import panel_frame

MODEL_VERSION = "finite-panel-skeleton-crossing-1"
DEFAULT_TOLERANCE_M = .001
SEGMENTS = (
    ("pelvis", "neck"), ("left_shoulder", "right_shoulder"), ("left_hip", "right_hip"),
    ("neck", "left_shoulder"), ("neck", "right_shoulder"),
    ("pelvis", "left_hip"), ("pelvis", "right_hip"),
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
)
LIMITATIONS = [
    "只检查已求得的离散姿态中15条骨架中心线是否穿过真实有限墙板；不是完整人体碰撞检查。",
    "墙板无厚度，骨架线段无半径；擦碰、端点触面及在容差内的接近不判为穿透。",
    "不把板面背后的无限半空间视作实体；未验证实体墙厚度、岩点碰撞、自碰撞与连续动作扫掠。",
]


def wall_clearance_report(scene, joints, tolerance_m=DEFAULT_TOLERANCE_M):
    """Check all declared skeleton segments against actual finite panels.

    A hit needs endpoints on opposite sides beyond ``tolerance_m`` and an
    intersection inside the closed panel rectangle. The tolerance is normal
    to the wall only: it never grows the panel around its finite edges. Exactly
    touching an edge while crossing the plane is a hit; touching the plane at
    a segment endpoint is not. Missing/malformed joints give ``unknown``.
    """
    if isinstance(tolerance_m, bool) or not isinstance(tolerance_m, (int, float)) or not math.isfinite(tolerance_m) or tolerance_m < 0:
        raise ValueError("wall clearance tolerance must be finite and nonnegative")
    panels = scene.get("wall_panels", [])
    report = {"model_version": MODEL_VERSION, "status": "not_checked", "tolerance_m": float(tolerance_m),
              "scope": "discrete_zero_radius_skeleton_segments_vs_finite_zero_thickness_panels",
              "segments_checked": 0, "panel_count": len(panels), "violations": [], "limitations": LIMITATIONS.copy()}
    if not panels:
        report["reason"] = "no_explicit_wall_panels"
        return report
    required = sorted({joint for segment in SEGMENTS for joint in segment})
    try:
        points = {joint: np.asarray(joints[joint], dtype=float) for joint in required}
        if any(p.shape != (3,) or not np.isfinite(p).all() for p in points.values()):
            raise ValueError("invalid joint coordinates")
    except (KeyError, TypeError, ValueError):
        report.update(status="unknown", reason="complete_finite_skeleton_unavailable")
        return report
    report["segments_checked"] = len(SEGMENTS)
    for panel in panels:
        origin, rotation = panel_frame(panel, scene["angle_deg"])
        local = {joint: rotation.T @ (p-origin) for joint, p in points.items()}
        for first, second in SEGMENTS:
            a, b = local[first], local[second]
            if not ((a[2] < -tolerance_m and b[2] > tolerance_m) or
                    (b[2] < -tolerance_m and a[2] > tolerance_m)):
                continue
            t = float(-a[2]/(b[2]-a[2]))
            hit = a+t*(b-a)
            # Numerical edge tolerance is separate from normal clearance and
            # is just enough to retain exact seams under rotated coordinates.
            edge_epsilon = 1e-10
            if not (-panel["width"]/2-edge_epsilon <= hit[0] <= panel["width"]/2+edge_epsilon and
                    -edge_epsilon <= hit[1] <= panel["height"]+edge_epsilon):
                continue
            world = origin+rotation @ hit
            report["violations"].append({
                "panel_id": panel["id"], "segment": [first, second],
                "intersection_world_m": [round(float(v), 9) for v in world],
                "intersection_panel_uv_m": [round(float(v), 9) for v in hit[:2]],
                "endpoint_signed_distances_m": [round(float(a[2]), 9), round(float(b[2]), 9)],
            })
    report["status"] = "fail" if report["violations"] else "pass"
    report["reason"] = "skeleton_crosses_finite_wall_panel" if report["violations"] else "no_strict_skeleton_crossing_found"
    return report
