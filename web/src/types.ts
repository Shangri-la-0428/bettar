export type Vec3 = [number, number, number];
export type Limb = 'LH' | 'RH' | 'LF' | 'RF';
export type Status = 'pass' | 'fail' | 'unknown' | 'not_checked';
export interface GripSurface {
  id: string; label: string; position: Vec3; normal: Vec3; u_axis: Vec3; v_axis: Vec3;
  radii: [number, number]; limbs: Limb[]; pull_direction: Vec3;
  mesh_anchor?: { triangle_index: number; barycentric: Vec3 };
  annotations?: { triangle_indices?: number[]; [key: string]: unknown };
}
export interface MountingFace {
  id: string; label: string; origin: Vec3; u_axis: Vec3; v_axis: Vec3; normal: Vec3;
  polygon: [number, number][];
}
export interface Hold {
  id: string; type: string; width: number; height: number; depth: number;
  pull_direction?: Vec3;
  contact: { id: string; position: Vec3; radius: number; limbs: Limb[] };
  template_id?: string; template_name?: string;
  asset_id?: string; asset_geometry_sha256?: string; asset_record_sha256?: string; asset_scale?: number; asset_source?: 'external_mesh';
  asset_fallback_reason?: string;
  taxonomy?: { family: 'jug' | 'crimp' | 'pinch' | 'sloper' | 'pocket' | 'foot_chip' | 'volume'; preferred_role: 'hand' | 'foot' | 'structure'; roles: ('hand' | 'foot' | 'structure')[]; form: string; legacy_alias?: string };
  grip_surfaces?: GripSurface[]; mounting_faces?: MountingFace[];
  design_attributes?: { source: string; grip_accessibility: number; precision: number; force_demand: number; friction_dependence: number };
  [key: string]: unknown;
}
export interface WallPanel { id: string; label: string; origin: Vec3; rotation_deg: Vec3; width: number; height: number }
export interface Body { id: string; [key: string]: unknown }
export interface Request {
  schema_version: string; id: string; revision: number; source: string;
  profile?: 'basic' | 'competition' | 'catalog' | 'style' | 'route' | 'setting';
  route_design?: RouteDesign;
  setting_design?: { program: string; source: string; intent: string; search: Record<string, unknown>; hold_source?: 'assets' | 'templates'; wall_profile?: 'default' | 'overhang' | 'roof' | 'dihedral' | 'arete'; wall_application?: Record<string, unknown>; asset_application?: Record<string, unknown> };
  design_brief?: { title: string; intent: string; source: string; disclaimer: string; phases: { id: string; label: string; event_start: number; event_end: number; intent: string }[]; zone_placement_ids: string[]; top_placement_ids: string[] };
  scene: { width: number; height: number; angle_deg: number; margin: number; inventory: Hold[]; wall_panels?: WallPanel[]; catalog_stock?: { template_id: string; template_name: string; type: string; count: number }[] };
  body: Body; scenario: string; mode: 'free' | 'fixed'; hand_moves: number; seed: number; budget: number;
  [key: string]: unknown;
}
export interface Placement { id: string; inventory_id: string; u: number; v: number; rotation_deg: number; contact_surface_id?: string; wall_panel_id?: string; mount?: { parent_id: string; face_id: string } }
export interface Contact { placement_id: string; contact_id: string }
export interface State { id: string; label: string; contacts: Record<Limb, Contact | null> }
export interface Event { limb: Limb; from_state: string; release_state: string; to_state: string }
export interface Candidate {
  id: string; name: string; revision: number; parent_id: string | null;
  generator: string; setting_report?: SettingReport; placements: Placement[]; states: State[]; events: Event[]; design_notes: string[];
  layout_report?: { status: 'no_sequence'; wall_profile: string; reason: string; search: Record<string, unknown>[]; limitations: string[] };
  [key: string]: unknown;
}
export interface Check {
  id: string; status: Status; label: string; detail: string;
  state_id?: string; placement_ids?: string[]; evidence?: Record<string, unknown>;
}
export interface Pose { state_id: string; status: Status; joints?: Record<string, Vec3>; residual_m?: number }
export interface Evaluation {
  id: string; candidate_id: string; fingerprint: string; version: string;
  checks: Check[]; poses: Pose[]; summary: { status: Status; passed: number; total: number }; elapsed_ms: number;
  design_analysis?: DesignAnalysis;
  mechanics_report?: MechanicsReport;
}
export type StyleGoal = 'power' | 'sustained' | 'technical';
export type RouteProgram = 'mixed_flow' | 'power_finish' | 'sustained_finish';
export type Rhythm = 'early_crux' | 'late_crux' | 'sustained';
export interface DemandDimensions { strength: number; power: number; technical: number; load: number }
export interface RouteDesign {
  style_goal: StyleGoal; rhythm: Rhythm; source: string; program?: RouteProgram;
  search: { beam_width: number; [key: string]: unknown };
  phases: { id: string; label: string; hand_move_index: number; segment_id?: string; phase_kind?: string; target: DemandDimensions }[];
}
export interface DesignMove extends DemandDimensions {
  event_index: number; hand_move_index: number; phase_id: string; limb: Limb;
  from_placement_id: string; to_placement_id: string;
  attributes: { span_ratio: number; grip_accessibility: number; precision: number; foot_support: number; inclination: number; directional_demand: number };
  accumulated_load: number; burden: number; phase_target: DemandDimensions;
  orientation_support?: { retained_hand_pull_alignment: Partial<Record<Limb, number>>; pull_mismatch: number; trunk_outside_foot_interval: number; lateral_opposition: number; proxy_penalty: number; basis: string };
  proxy_effort?: number;
  prior_load?: number; rest_opportunity?: number; fresh_burden?: number; effective_burden?: number;
}
export interface DesignAnalysis {
  source: string; model_version: string; style_goal: StyleGoal; rhythm: Rhythm; program?: RouteProgram;
  history_comparison?: { fresh_peak: number; with_history_peak: number; delta: number; late_move_delta: number; source: string };
  dimensions: DemandDimensions;
  moves: DesignMove[];
  phases: { id: string; label: string; event_start: number; event_end: number; target: DemandDimensions; estimate: DemandDimensions; phase_kind?: string; load_basis?: string }[];
  summary: { peak_strength: number; peak_power: number; mean_technical: number; total_load: number; load_variability: number; peak_burden: number; crux_event_index: number; objective: number };
  search: Record<string, unknown>;
  limitations: string[];
}
export interface StyleExample { id: string; label: string; bundle: Bundle }
export interface Review {
  id: string; candidate_id: string; candidate_revision: number; evaluation_id: string | null;
  evaluation_fingerprint: string | null; state_id: string | null; placement_id: string | null;
  kind: 'design_review'; text: string; created_at: string;
}
export interface Bundle {
  schema_version: string; id: string; created_at: string; request: Request;
  candidates: Candidate[]; evaluations: Evaluation[]; manifest: Record<string, unknown>;
  reviews?: Review[];
}
export interface CatalogTemplate extends Pick<Hold, 'id' | 'type' | 'width' | 'height' | 'depth' | 'grip_surfaces' | 'mounting_faces'> { template_id: string; template_name: string; default_count: number; min_count: number; max_count: number }
export interface Defaults { request: Request; body_profiles: Body[]; scenarios: { id: string; label: string; description: string }[]; catalog_templates?: CatalogTemplate[] }

export const limbs: Limb[] = ['LH', 'RH', 'LF', 'RF'];
export const limbNames: Record<Limb, string> = { LH: '左手', RH: '右手', LF: '左脚', RF: '右脚' };
export const statusLabels: Record<Status, string> = {
  pass: '通过', fail: '违反条件', unknown: '无法判断', not_checked: '未检查',
};
export const holdNames: Record<string, string> = { jug: '把手 · Jug', crimp: '抓边 · Crimp', directional_edge: '抓边 · Crimp', foothold: '小脚点', foot_chip: '小脚点', sloper: '摩擦点 · Sloper', pinch: '捏点 · Pinch', pocket: '指洞 · Pocket', rail: '长条抓边 · Crimp', volume: '体积块' };
export function holdFamily(hold: Hold): string { return hold.taxonomy?.family || ({ directional_edge: 'crimp', rail: 'crimp', foothold: 'foot_chip' } as Record<string, string>)[hold.type] || hold.type; }
export function holdRoleName(hold: Hold): string {
  const roles = hold.taxonomy?.roles || (hold.type === 'volume' ? ['structure', 'foot'] : hold.contact.limbs.some(limb => limb.endsWith('H')) ? ['hand', 'foot'] : ['foot']);
  return roles.includes('structure') ? '体积结构 / 可作脚面' : roles.includes('hand') ? '手点 / 也可踩踏' : '脚点';
}

export function holdDisplayName(hold: Hold): string {
  const name = holdNames[holdFamily(hold)] || holdNames[hold.type] || hold.type;
  return (hold.template_id?.startsWith('study-') || hold.template_id?.startsWith('route-')) ? `研究模板 · ${name}` : hold.template_name || name;
}

export function escape(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
}

export function shortHoldName(hold: Hold, inventory: Hold[]): string {
  const prefix = ({ jug: 'J', crimp: 'C', directional_edge: 'E', foothold: 'F', sloper: 'S', pinch: 'P', pocket: 'O', rail: 'R', volume: 'V' } as Record<string, string>)[hold.type] || 'H';
  const index = inventory.filter((item) => item.type === hold.type).findIndex((item) => item.id === hold.id) + 1;
  return `${prefix}${index}`;
}

export interface BetaSummary {
  hand_moves: number; foot_moves: number; transfers: number;
  total_proxy_effort: number; peak_proxy_burden: number; final_load: number;
}
export interface BetaAlternative {
  id: string; label: string; objective: 'fewer_transfers' | 'lower_proxy_effort';
  search_source?: 'independent_contact_beam' | 'bounded_single_transfer_deletion';
  candidate: Candidate; evaluation: Evaluation; analysis: DesignAnalysis; summary: BetaSummary;
  skipped_hold_ids: string[];
  crux_bypass: { original_hold_id: string; contacted: boolean; contacted_as_hand?: boolean; original_transition_used?: boolean; peak_reduced: boolean; peak_delta: number };
  comparison: { transfers_delta: number; hand_moves_delta: number; proxy_effort_delta: number; peak_burden_delta: number };
}
export interface BetaAudit {
  schema_version: 'beta-audit/1';
  source: { fingerprint: string; candidate_id: string; revision: number; code_hash: string; audit_code_hash: string; geometry_hash: string };
  original: { candidate: Candidate; evaluation: Evaluation; analysis: DesignAnalysis; summary: BetaSummary; crux: { event_index: number; placement_id: string; burden: number } };
  alternatives: BetaAlternative[];
  unverified_alternatives?: BetaAlternative[];
  search: { algorithm: string; expanded: number; expansion_limit: number; beam_width: number; budget_exhausted: boolean; time_budget_exhausted?: boolean; elapsed_ms?: number; complete_sequences: number; ik_checked: number; verified_alternatives: number; unverified_count?: number; scope: string };
  limitations: string[];
}

export interface SettingAlternative {
  candidate: Candidate; summary: BetaSummary; evaluation: Evaluation; analysis: DesignAnalysis;
  id?: string; label?: string;
}
export interface SettingReport {
  model_version: string; program: string; intent: string;
  baseline: { summary: BetaSummary; character?: Record<string, number | string>; mechanics_summary?: MechanicsSummary; search: Record<string, unknown>; geometry_hash: string };
  result: { summary: BetaSummary; character?: Record<string, number | string>; mechanics_summary?: MechanicsSummary; search: Record<string, unknown>; geometry_hash: string };
  baseline_candidate: Candidate; baseline_evaluation: Evaluation; baseline_analysis: DesignAnalysis;
  changes: { placement_id: string; before: { u: number; v: number; rotation_deg: number }; after: { u: number; v: number; rotation_deg: number }; reason: string }[];
  observed_movement_tags: { id: string; label: string; evidence: unknown }[];
  allowed_alternatives: SettingAlternative[];
  limitations: string[]; search: Record<string, unknown>;
}

export type MechanicsStatus = 'feasible' | 'infeasible' | 'unknown';
export interface MechanicsContact {
  limb: Limb; placement_id: string; point_world_m: Vec3;
  mode: 'unilateral_friction' | 'synthetic_grasp_envelope';
  force_world_n: Vec3 | null; required_force_world_n?: Vec3 | null; normal_world: Vec3;
  normal_force_n: number | null; axial_force_n?: number | null; tangent_force_n: number | null;
  axial_direction_world?: Vec3; cone_slope?: number;
  friction_margin_n: number | null; envelope_margin_n: number | null;
  capacity_n: number; capacity_margin_n: number | null;
}
export interface MechanicsState {
  state_id: string; is_release: boolean; active_contacts: Limb[]; status: MechanicsStatus; reason: string;
  com_world_m: Vec3 | null; gravity_force_n: Vec3 | null;
  capacity_utilization: number | null; force_residual_n: number | null; torque_residual_nm: number | null;
  contacts: MechanicsContact[];
}
export interface MechanicsSummary {
  status: MechanicsStatus; feasible_states: number; infeasible_states: number; unknown_states: number;
  release_states: number; release_infeasible_states: number; release_unknown_states?: number;
  max_capacity_utilization: number | null; worst_state_id: string | null;
}
export interface MechanicsReport {
  model_version: string; model_fingerprint: string;
  parameters: { source: string; mass_kg: number; gravity_m_s2: number;
    friction_coefficient_foot: number; friction_coefficient_hand: number;
    foot_normal_capacity_n: number; hand_normal_capacity_n: number;
    grasp_axial_capacity_n: Record<string, number>; grasp_cone_slope: number; grasp_inward_bias: number;
    cone_sides: number; com_model: string;
  };
  limitations: string[]; summary: MechanicsSummary; states: MechanicsState[];
}
