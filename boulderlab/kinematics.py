"""Explicit synthetic rigid-torso skeleton and bounded, coupled IK.

q = root xyz, root XYZ angles, then LH/RH/LF/RF (XYZ, flexion), radians.
These bounds describe an experimental model, not physiological capability.
"""
from __future__ import annotations

import time
import numpy as np
from scipy.optimize import least_squares

LIMBS = ("LH", "RH", "LF", "RF")
ENDPOINTS = {"LH": "left_wrist", "RH": "right_wrist", "LF": "left_ankle", "RF": "right_ankle"}


def rotation_matrix(angles):
    x, y, z = angles
    sx, sy, sz = np.sin([x, y, z])
    cx, cy, cz = np.cos([x, y, z])
    return np.array([[cz*cy, cz*sy*sx-sz*cx, cz*sy*cx+sz*sx],
                     [sz*cy, sz*sy*sx+cz*cx, sz*sy*cx-cz*sx],
                     [-sy, cy*sx, cy*cx]])


def forward_kinematics(body, q):
    q = np.asarray(q, dtype=float)
    if q.shape != (22,) or not np.isfinite(q).all():
        raise ValueError("q must contain 22 finite values")
    root = q[:3]
    rot = rotation_matrix(q[3:6])
    joints = {"pelvis": root.copy(), "neck": root + rot @ [0, body["torso"], 0]}
    for i, limb in enumerate(LIMBS):
        hand = i < 2
        side = "left" if i % 2 == 0 else "right"
        sign = -1 if i % 2 == 0 else 1
        origin = np.array([sign * body["shoulder_width" if hand else "hip_width"] / 2,
                           body["torso"] if hand else 0, 0])
        upper, lower = (body["upper_arm"], body["forearm"]) if hand else (body["thigh"], body["shin"])
        a = q[6 + 4*i:10 + 4*i]
        r = rot @ rotation_matrix(a[:3])
        direction = 1 if hand else -1
        joint = root + rot @ origin
        middle = joint + r @ [0, direction * upper, 0]
        bend = rotation_matrix([(-1 if hand else 1) * a[3], 0, 0])
        end = middle + r @ bend @ [0, direction * lower, 0]
        joints[f"{side}_{'shoulder' if hand else 'hip'}"] = joint
        joints[f"{side}_{'elbow' if hand else 'knee'}"] = middle
        joints[ENDPOINTS[limb]] = end
    return joints


def contact_endpoints(body, q):
    joints = forward_kinematics(body, q)
    root_rotation = rotation_matrix(np.asarray(q)[3:6])
    out = {}
    for i, limb in enumerate(LIMBS):
        a = np.asarray(q)[6 + 4*i:10 + 4*i]
        bend = rotation_matrix([(-1 if i < 2 else 1) * a[3], 0, 0])
        offset = np.asarray(body.get("endpoint_offsets", {}).get(limb, [0, 0, 0]))
        out[limb] = joints[ENDPOINTS[limb]] + root_rotation @ rotation_matrix(a[:3]) @ bend @ offset
    return out


def contact_distance_bound(body, first, second, contact_tolerance_m=0.):
    """Conservative skeleton path bound shared by evaluator and search.

    Anchor separation is fixed by the rigid torso. Endpoint offsets may point
    independently, so add their norms; both contact residuals contribute.
    This is necessary only and does not establish an attainable joint pose.
    """
    if first not in LIMBS or second not in LIMBS:
        raise ValueError("unknown contact limb")
    if not np.isfinite(contact_tolerance_m) or contact_tolerance_m < 0:
        raise ValueError("invalid contact tolerance")
    def anchor(limb):
        hand=limb.endswith("H");side=-1 if limb.startswith("L") else 1
        return np.array([side*body["shoulder_width" if hand else "hip_width"]/2,body["torso"] if hand else 0,0])
    def reach(limb):
        return body["upper_arm"]+body["forearm"] if limb.endswith("H") else body["thigh"]+body["shin"]
    offsets=sum(float(np.linalg.norm(body.get("endpoint_offsets",{}).get(limb,[0,0,0]))) for limb in (first,second))
    return float(np.linalg.norm(anchor(first)-anchor(second)))+reach(first)+reach(second)+offsets+2*contact_tolerance_m


def joint_bounds(body, solver):
    bounds = list(solver["root_bounds"]) + np.deg2rad(solver["root_rotation_deg"]).tolist()
    limits = body["joint_limits_deg"]
    for limb in LIMBS:
        hand = limb.endswith("H")
        bounds.extend(np.deg2rad(limits["shoulder" if hand else "hip"]).tolist())
        bounds.append(np.deg2rad(limits["elbow" if hand else "knee"]).tolist())
    pairs = np.asarray(bounds, dtype=float)
    if pairs.shape != (22, 2) or not np.isfinite(pairs).all() or np.any(pairs[:, 0] >= pairs[:, 1]):
        raise ValueError("invalid skeleton/root joint bounds")
    return pairs[:, 0], pairs[:, 1]


def initial_pose(body, targets, solver):
    lo, hi = joint_bounds(body, solver)
    q = np.zeros(22)
    hands = [p for l, p in targets.items() if l.endswith("H")]
    feet = [p for l, p in targets.items() if l.endswith("F")]
    q[0] = np.mean([p[0] for p in targets.values()]) if targets else 0
    q[1] = np.mean([p[1] for p in hands]) - body["torso"] - .12 if hands else 1.1
    if feet:
        q[1] = (q[1] + np.mean([p[1] for p in feet]) + .55) / 2
    q[2] = np.mean([p[2] for p in targets.values()]) + .28 if targets else .3
    for i in range(4):
        q[6 + 4*i] = np.deg2rad(-30 if i < 2 else -15)
        q[9 + 4*i] = np.deg2rad(75 if i < 2 else 50)
    return np.clip(q, lo + 1e-8, hi - 1e-8)


def _wall_residual_function(scene):
    """Fixed-size, bounded-panel guidance for the nonlinear IK iterations.

    Samples guide optimization only. Acceptance independently checks complete
    bone segments against finite panels, so no sampled gap is called clear.
    The penetration penalty is capped by distance to a panel's finite edge:
    exiting around a roof lip is permitted; crossing its interior is not.
    """
    if not scene or not scene.get("wall_panels"):
        return None
    from .geometry import panel_frame
    from .wall_clearance import SEGMENTS
    panels = [(panel_frame(p, scene["angle_deg"]), p["width"], p["height"]) for p in scene["wall_panels"]]
    fractions = np.linspace(0., 1., 5)[None, :, None]

    def residual(joints):
        starts = np.array([joints[a] for a, b in SEGMENTS])
        ends = np.array([joints[b] for a, b in SEGMENTS])
        samples = (starts[:, None, :]+fractions*(ends-starts)[:, None, :]).reshape((-1, 3))
        result = []
        for (origin, rotation), width, height in panels:
            local = (samples-origin)@rotation
            inside = np.minimum.reduce([width/2-abs(local[:, 0]), local[:, 1], height-local[:, 1]])
            result.append(5.*np.maximum(0., np.minimum(-local[:, 2]+.002, inside)))
            # A short crossing next to a roof lip can fall between samples.
            # Guide the exact plane intersection toward the finite edge too.
            a, b = (starts-origin)@rotation, (ends-origin)@rotation
            denominator = b[:, 2]-a[:, 2]
            safe = np.where(abs(denominator) > 1e-10, denominator, 1.)
            t = -a[:, 2]/safe
            intersection = a+t[:, None]*(b-a)
            edge = np.minimum.reduce([width/2-abs(intersection[:, 0]), intersection[:, 1], height-intersection[:, 1]])
            crossing = (a[:, 2]*b[:, 2] < 0.) & (t > 0.) & (t < 1.)
            result.append(5.*np.where(crossing, np.maximum(0., np.minimum(edge+.002, np.minimum(abs(a[:, 2]), abs(b[:, 2])))), 0.))
        return np.concatenate(result)
    return residual


def solve_pose(body, targets, solver, seed=0, initial=None, *, scene=None):
    """Solve all declared contacts together; no convergence is *unknown*."""
    started = time.perf_counter()
    if not targets:
        return {"status": "unknown", "residual_m": None, "evidence": {"reason": "no_contacts", "attempts": 0}}
    if solver.get("max_nfev", 0) <= 0 or solver.get("restarts", 0) <= 0:
        return {"status": "unknown", "residual_m": None, "evidence": {"reason": "budget_exhausted", "attempts": 0}}
    lo, hi = joint_bounds(body, solver)
    targets = {l: np.asarray(p, float) for l, p in targets.items()}
    if any(l not in LIMBS or p.shape != (3,) or not np.isfinite(p).all() for l, p in targets.items()):
        raise ValueError("invalid contact targets")
    rng = np.random.default_rng(seed)
    base = initial_pose(body, targets, solver)
    if initial is not None:
        initial = np.asarray(initial, float)
        if initial.shape == (22,) and np.isfinite(initial).all():
            base = np.clip(initial, lo + 1e-8, hi - 1e-8)
    best = None
    attempts = []
    timeout = float(solver.get("timeout_seconds", 15))
    deadline = started + timeout
    wall_residual = _wall_residual_function(scene)
    for restart in range(solver["restarts"]):
        if time.perf_counter() >= deadline:
            attempts.append({"reason": "time_budget"})
            break
        x0 = base.copy() if restart == 0 else np.clip(base + rng.normal(0, .25, 22), lo + 1e-8, hi - 1e-8)

        def residual(q):
            if time.perf_counter() >= deadline:
                raise TimeoutError("IK time budget exhausted")
            points = contact_endpoints(body, q)
            contact_error = np.concatenate([points[l] - target for l, target in targets.items()])
            # Weak tie-break only. It never replaces independent contact checking.
            parts = [contact_error, .0005 * (q - base)]
            if wall_residual is not None:
                parts.append(wall_residual(forward_kinematics(body, q)))
            return np.concatenate(parts)

        try:
            result = least_squares(residual, x0, bounds=(lo, hi), max_nfev=solver["max_nfev"],
                                   ftol=1e-7, xtol=1e-7, gtol=1e-7)
            q = result.x
            points = contact_endpoints(body, q)
            errors = {l: float(np.linalg.norm(points[l] - target)) for l, target in targets.items()}
            worst = max(errors.values())
            attempts.append({"nfev": int(result.nfev), "solver_success": bool(result.success), "residual_m": worst})
            if best is None or worst < best[0]:
                best = (worst, q, errors)
            if worst <= solver["contact_tolerance_m"] and np.all(q >= lo) and np.all(q <= hi):
                joints = forward_kinematics(body, q)
                clearance = None
                if wall_residual is not None:
                    from .wall_clearance import wall_clearance_report
                    clearance = wall_clearance_report(scene, joints)
                    if clearance["status"] != "pass":
                        attempts[-1]["wall_clearance"] = clearance
                        continue
                return {"status": "pass", "joints": {k: v.tolist() for k, v in joints.items()},
                        "q": q.tolist(), "residual_m": worst,
                        "evidence": {"contact_errors_m": errors, "attempts": attempts, "joint_limits_pass": True,
                                     "body_id": body["id"], "elapsed_ms": round((time.perf_counter()-started)*1000, 2),
                                     **({"wall_clearance": clearance} if clearance is not None else {})}}
        except (ValueError, FloatingPointError, TimeoutError, np.linalg.LinAlgError) as exc:
            attempts.append({"reason": type(exc).__name__, "detail": str(exc)})
    return {"status": "unknown", "residual_m": best[0] if best else None,
            "evidence": {"reason": "no_verified_solution_within_budget", "attempts": attempts,
                         "elapsed_ms": round((time.perf_counter()-started)*1000, 2)}}
