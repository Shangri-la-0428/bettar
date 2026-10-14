"""Quasi-static equilibrium of one solved pose, under explicit synthetic contacts.

Feet and slopers are unilateral frictional points. Other hand holds use an
explicit *aggregate grasp envelope*, not an invented tensile surface normal.
No contact carries a free moment. No dynamics, joint torque, or human pass claim.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
from .geometry import selected_contact, placement_frames, contact_world

MODEL_VERSION="quasistatic-contact-lp-1"
DEFAULT_PARAMETERS={"source":"synthetic_assumption","mass_kg":70.,"gravity_m_s2":9.80665,
 "friction_coefficient_foot":.65,"friction_coefficient_hand":.60,
 "foot_normal_capacity_n":900.,"hand_normal_capacity_n":400.,
 "grasp_axial_capacity_n":{"jug":650.,"crimp":350.,"pinch":450.,"rail":550.,"directional_edge":400.,"pocket":400.},
 "grasp_cone_slope":.65,"grasp_inward_bias":.55,"cone_sides":8,"com_model":"synthetic_segments_v1"}
LIMITATIONS=[
 "只检查当前 IK 求得的离散姿态；不满足不代表该接触组合没有其它可平衡姿态，也不代表线路不可攀。",
 "质量、分段质心、摩擦系数与手脚容量均为显式合成假设，未经测量或真人标定。容量是法向/抓握轴向上限，不是合力或肌肉力上限。",
 "脚点与 Sloper 使用可压、不可拉的单侧摩擦点；其它手点采用声明的合成整体抓握包络。倒扣、多指与挤压接触并未由当前高度场几何验证。",
 "八边内接锥保守近似圆锥，并复核平衡及圆锥；每个点无自由力矩。抓握包络与摩擦锥分开标注，二者不是同一物理接触模型。",
 "包含每个释放态的三接触平衡，但未验证连续轨迹、动态动量、肌肉/关节力矩、人体碰撞和握力持续时间。双手同点仍共用一个代表位置；容量按每肢声明，同一抓握片的共享承载与独立手掌位置未建模。",
 "准静态可行只表示这些姿态与假设下找到受限反力分配，不是难度、安全性或真人可攀证明。",
]


def _round(value):
    if isinstance(value,dict):return {k:_round(v) for k,v in value.items()}
    if isinstance(value,(list,tuple,np.ndarray)):return [_round(v) for v in value]
    if isinstance(value,(np.floating,float)):return round(float(value),7)
    if isinstance(value,np.integer):return int(value)
    return value


def validate_parameters(p):
    if not isinstance(p,dict) or set(p)!=set(DEFAULT_PARAMETERS):raise ValueError("mechanics_parameters keys do not match the declared model")
    if p["source"]!="synthetic_assumption" or p["com_model"]!="synthetic_segments_v1" or p["cone_sides"]!=8:raise ValueError("unsupported mechanics model")
    bounds={"mass_kg":(20,200),"gravity_m_s2":(1,20),"friction_coefficient_foot":(.05,2),"friction_coefficient_hand":(.05,2),"foot_normal_capacity_n":(1,3000),"hand_normal_capacity_n":(1,3000),"grasp_cone_slope":(.05,2),"grasp_inward_bias":(0,2)}
    for key,(lo,hi) in bounds.items():
        if isinstance(p[key],bool) or not isinstance(p[key],(int,float)) or not math.isfinite(p[key]) or not lo<=p[key]<=hi:raise ValueError(f"invalid mechanics {key}")
    if not isinstance(p["grasp_axial_capacity_n"],dict) or set(p["grasp_axial_capacity_n"])!=set(DEFAULT_PARAMETERS["grasp_axial_capacity_n"]):raise ValueError("missing grasp capacity declaration")
    for v in p["grasp_axial_capacity_n"].values():
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 1<=v<=3000:raise ValueError("invalid grasp capacity")


def segment_com(joints):
    """Uncalibrated segment fractions sum to one; head is lumped into torso."""
    groups=[(.50,"pelvis","neck",.55)]
    for side in ("left","right"):
        groups +=[(.03,f"{side}_shoulder",f"{side}_elbow",.5),(.025,f"{side}_elbow",f"{side}_wrist",.5),(.11,f"{side}_hip",f"{side}_knee",.5),(.085,f"{side}_knee",f"{side}_ankle",.5)]
    centers=[]
    for weight,a,b,f in groups:
        pa,pb=np.asarray(joints[a],float),np.asarray(joints[b],float)
        if pa.shape!=(3,) or pb.shape!=(3,) or not np.isfinite(pa).all() or not np.isfinite(pb).all():raise ValueError("missing segment coordinates")
        centers.append(weight*((1-f)*pa+f*pb))
    return np.sum(centers,axis=0)


def _basis(axis):
    axis=np.asarray(axis,float);n=float(np.linalg.norm(axis))
    if axis.shape!=(3,) or not np.isfinite(axis).all() or n<1e-10:raise ValueError("missing contact direction")
    axis=axis/n;seed=np.array([1.,0,0]) if abs(axis[0])<.8 else np.array([0.,1.,0])
    tangent=np.cross(axis,seed);tangent/=np.linalg.norm(tangent)
    return axis,tangent,np.cross(axis,tangent)


def solve_equilibrium(contacts,com,gravity_force,cone_sides=8):
    """Minimize common axial capacity utilization over inner polygonal cones.

    Contacts require position, axis, slope, capacity_n. A nonnegative coefficient
    per ray contributes unit axial force. sum(ray coefficients) is axial load.
    This public helper also supports analytical fixture tests, independent of IK.
    """
    if not contacts:return {"status":"unknown","reason":"missing_contacts","capacity_utilization":None,"forces":[]}
    com=np.asarray(com,float);gravity=np.asarray(gravity_force,float)
    if com.shape!=(3,) or gravity.shape!=(3,) or not np.isfinite(com).all() or not np.isfinite(gravity).all():raise ValueError("invalid gravity or COM")
    count=len(contacts);columns=[];bases=[]
    for contact in contacts:
        axis,t1,t2=_basis(contact["axis"]);bases.append((axis,t1,t2))
        p=np.asarray(contact["position"],float);slope=float(contact["slope"]);capacity=float(contact["capacity_n"])
        if p.shape!=(3,) or not np.isfinite(p).all() or not math.isfinite(slope) or slope<0 or not math.isfinite(capacity) or capacity<=0:raise ValueError("invalid contact envelope")
        for k in range(cone_sides):
            theta=2*math.pi*k/cone_sides
            ray=axis+slope*(math.cos(theta)*t1+math.sin(theta)*t2)
            columns.append(np.r_[ray,np.cross(p-com,ray)])
    matrix=np.column_stack(columns);aeq=np.column_stack([matrix,np.zeros(6)])
    beq=np.r_[-gravity,[0.,0.,0.]];aub=np.zeros((count,count*cone_sides+1))
    for i,c in enumerate(contacts):aub[i,i*cone_sides:(i+1)*cone_sides]=1; aub[i,-1]=-float(c["capacity_n"])
    objective=np.zeros(count*cone_sides+1);objective[-1]=1
    solved=linprog(objective,A_ub=aub,b_ub=np.zeros(count),A_eq=aeq,b_eq=beq,bounds=[(0,None)]*(count*cone_sides+1),method="highs",options={"time_limit":2.})
    if not solved.success:
        reason="no_equilibrium_with_declared_contact_cones" if solved.status==2 else "lp_solver_unknown"
        return {"status":"infeasible" if solved.status==2 else "unknown","reason":reason,"capacity_utilization":None,"forces":[],"solver_status":int(solved.status)}
    utilization=float(solved.x[-1]);forces=[]
    for i,contact in enumerate(contacts):
        weights=solved.x[i*cone_sides:(i+1)*cone_sides]
        force=matrix[:3,i*cone_sides:(i+1)*cone_sides] @ weights
        axis=bases[i][0];axial=float(np.dot(force,axis));tangent=float(np.linalg.norm(force-axial*axis))
        margin=float(contact["slope"])*axial-tangent
        forces.append({"force":force,"axial_force_n":axial,"tangent_force_n":tangent,"cone_margin_n":margin,"capacity_margin_n":float(contact["capacity_n"])-axial})
    force_residual=float(np.linalg.norm(sum((f["force"] for f in forces),np.zeros(3))+gravity))
    torque_residual=float(np.linalg.norm(sum((np.cross(np.asarray(c["position"])-com,f["force"]) for c,f in zip(contacts,forces)),np.zeros(3))))
    if force_residual>1e-4 or torque_residual>1e-4 or any(f["cone_margin_n"]< -1e-5 or f["axial_force_n"]< -1e-5 for f in forces):
        return {"status":"unknown","reason":"independent_residual_check_failed","capacity_utilization":utilization,"forces":[],"force_residual_n":force_residual,"torque_residual_nm":torque_residual}
    return {"status":"feasible" if utilization<=1+1e-7 else "infeasible","reason":"equilibrium_within_declared_envelopes" if utilization<=1+1e-7 else "declared_axial_capacity_exceeded","capacity_utilization":utilization,"forces":forces,"force_residual_n":force_residual,"torque_residual_nm":torque_residual}


def _contact_model(request,placement,item,limb,frames,parameters,placements,contact_id="main"):
    surface=selected_contact(placement,item,contact_id)
    if limb not in surface["limbs"]:raise ValueError("contact_surface_limb_disallowed")
    if any(key not in surface for key in ("normal","u_axis","v_axis","pull_direction")):raise ValueError("contact_surface_frame_missing")
    rot=frames[placement["id"]][1];normal=rot @ np.asarray(surface["normal"],float)
    passive=limb.endswith("F") or item["type"]=="sloper"
    if passive:
        axis=normal;slope=parameters["friction_coefficient_foot" if limb.endswith("F") else "friction_coefficient_hand"]
        capacity=parameters["foot_normal_capacity_n" if limb.endswith("F") else "hand_normal_capacity_n"]
        mode="unilateral_friction"
    else:
        if item["type"] not in parameters["grasp_axial_capacity_n"]:raise ValueError("grasp_envelope_not_declared")
        # Aggregate force direction toward the hand: opposite declared pull,
        # plus an explicitly synthetic inward grasp bias in hold coordinates.
        axis=rot @ (-np.asarray(surface["pull_direction"],float)-np.array([0.,0.,parameters["grasp_inward_bias"]]))
        slope=parameters["grasp_cone_slope"];capacity=parameters["grasp_axial_capacity_n"][item["type"]];mode="synthetic_grasp_envelope"
    axis=_basis(axis)[0]
    return {"limb":limb,"placement_id":placement["id"],"contact_id":contact_id,"position":contact_world(request,placement,item,placements,frames,contact_id),"axis":axis,"normal":normal,"slope":slope,"capacity_n":capacity,"mode":mode}


def mechanics_report(request,candidate,evaluation):
    if "mechanics_parameters" not in request:return None
    validate_parameters(request["mechanics_parameters"])
    payload={"request":request,"candidate":{k:candidate[k] for k in ("placements","states","events")},"evaluation":{"fingerprint":evaluation.get("fingerprint"),"poses":evaluation.get("poses",[])},"code_hash":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return copy.deepcopy(_report_cached(json.dumps(payload,sort_keys=True,ensure_ascii=False)))


@lru_cache(maxsize=96)
def _report_cached(encoded):
    from .engine import canonical_hash
    payload=json.loads(encoded);request=payload["request"];candidate=payload["candidate"];evaluation=payload["evaluation"];params=request["mechanics_parameters"]
    inventory={i["id"]:i for i in request["scene"]["inventory"]};placements={p["id"]:p for p in candidate["placements"]}
    try: frames=placement_frames(candidate["placements"],inventory,request["scene"]["angle_deg"],request["scene"].get("wall_panels"))
    except (ValueError,KeyError,TypeError): frames=None
    poses={p["state_id"]:p for p in evaluation["poses"]};release={e["release_state"] for e in candidate["events"]};states=[]
    gravity=np.array([0.,-params["mass_kg"]*params["gravity_m_s2"],0.])
    for state in candidate["states"]:
        active=[limb for limb,ref in state["contacts"].items() if ref]
        entry={"state_id":state["id"],"is_release":state["id"] in release,"active_contacts":active,"status":"unknown","reason":"ik_pose_unavailable","com_world_m":None,"gravity_force_n":gravity,"capacity_utilization":None,"force_residual_n":None,"torque_residual_nm":None,"contacts":[]}
        if frames is None:entry["reason"]="contact_geometry_unavailable";states.append(entry);continue
        pose=poses.get(state["id"])
        if not pose or pose.get("status")!="pass":states.append(entry);continue
        try:
            com=segment_com(pose["joints"]);entry["com_world_m"]=com
            models=[_contact_model(request,placements[state["contacts"][limb]["placement_id"]],inventory[placements[state["contacts"][limb]["placement_id"]]["inventory_id"]],limb,frames,params,candidate["placements"],state["contacts"][limb]["contact_id"]) for limb in active]
            result=solve_equilibrium(models,com,gravity,params["cone_sides"])
            entry.update({k:result.get(k) for k in ("status","reason","capacity_utilization","force_residual_n","torque_residual_nm")})
            for i,model in enumerate(models):
                solved=result["forces"][i] if result["forces"] else None
                entry["contacts"].append({"limb":model["limb"],"placement_id":model["placement_id"],"contact_id":model["contact_id"],"point_world_m":model["position"],"mode":model["mode"],"normal_world":model["normal"],"axial_direction_world":model["axis"],"force_world_n":solved["force"] if solved and result["status"]=="feasible" else None,"required_force_world_n":solved["force"] if solved else None,"normal_force_n":float(np.dot(solved["force"],model["normal"])) if solved else None,"axial_force_n":solved["axial_force_n"] if solved else None,"tangent_force_n":solved["tangent_force_n"] if solved else None,"friction_margin_n":solved["cone_margin_n"] if solved and model["mode"]=="unilateral_friction" else None,"envelope_margin_n":solved["cone_margin_n"] if solved and model["mode"]=="synthetic_grasp_envelope" else None,"capacity_n":model["capacity_n"],"capacity_margin_n":solved["capacity_margin_n"] if solved else None,"cone_slope":model["slope"]})
        except (ValueError,KeyError,TypeError) as exc:entry["reason"]="contact_or_pose_model_missing: "+str(exc)
        states.append(entry)
    counts={status:sum(s["status"]==status for s in states) for status in ("feasible","infeasible","unknown")}
    releases=[s for s in states if s["is_release"]];known=[s for s in states if s["capacity_utilization"] is not None]
    no_equilibrium=[s for s in states if s["status"]=="infeasible" and s["capacity_utilization"] is None]
    failed=[s for s in known if s["status"]=="infeasible"]
    worst=no_equilibrium[0] if no_equilibrium else max(failed or known,key=lambda s:s["capacity_utilization"]) if (failed or known) else next((s for s in states if s["status"]=="unknown"),None)
    summary={"status":"infeasible" if counts["infeasible"] else "unknown" if counts["unknown"] else "feasible",**{f"{k}_states":v for k,v in counts.items()},"release_states":len(releases),"release_infeasible_states":sum(s["status"]=="infeasible" for s in releases),"release_unknown_states":sum(s["status"]=="unknown" for s in releases),"max_capacity_utilization":max((s["capacity_utilization"] for s in known),default=None),"worst_state_id":worst["state_id"] if worst else None}
    return _round({"model_version":MODEL_VERSION,"model_fingerprint":canonical_hash(payload),"parameters":params,"limitations":LIMITATIONS,"summary":summary,"states":states,"sources":{"equilibrium_and_cone":"https://modernrobotics.northwestern.edu/nu-gm-book-resource/12-2-3-force-closure/","parameters":"synthetic_unvalidated_declarations","com":"synthetic_segments_v1; torso/head .50, each upper arm .03, forearm/hand .025, thigh .11, shin/foot .085"}})
