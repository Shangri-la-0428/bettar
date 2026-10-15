import type { Candidate, Placement, Request, Vec3 } from './types';
import { panelFrame, transformPoint } from './placement-geometry.ts';

/** Bounds are in each physical panel's installation coordinates, in metres. */
export interface GymPatch {
  wall_panel_id: string;
  u_min: number; u_max: number; v_min: number; v_max: number;
}
export interface GymRegion {
  id: string; name: string; label: string;
  wall_profile: string; panel_ids: string[]; patches: GymPatch[];
}
export interface ExampleGym {
  id: string; name: string; version: string; revision: number; description: string;
  scene: Request['scene']; regions: GymRegion[];
  preview: { request: Request; candidate: Candidate };
}
export interface InstallationRegion {
  patches: GymPatch[];
  editable_placement_ids: string[];
  fixed_placements: Placement[];
}

/** The backend is authoritative: region membership cannot grant edit permission. */
export function gymEditableIds(request?: Request): Set<string> | undefined {
  const constraints = request?.route_constraints as (Request['route_constraints'] & { installation_region?: InstallationRegion }) | undefined;
  const region = constraints?.installation_region;
  return region ? new Set(region.editable_placement_ids) : undefined;
}

/** A quick editing guard; saved requests still undergo the server's same check. */
export function gymPlacementIssue(request: Request, placement: Placement): string | undefined {
  const constraints = request.route_constraints as (Request['route_constraints'] & { installation_region?: InstallationRegion }) | undefined;
  const region = constraints?.installation_region;
  if (!region) return;
  if (!region.editable_placement_ids.includes(placement.id)) return '周围岩点已保留，不能在本次定线中修改。';
  if (placement.mount) return '示例馆暂只支持直接安装在墙面的岩点。';
  const hold = request.scene.inventory.find(item => item.id === placement.inventory_id);
  if (!hold || ![placement.u, placement.v, placement.rotation_deg, hold.width, hold.height].every(Number.isFinite)) return '岩点安装信息不完整。';
  const angle = placement.rotation_deg * Math.PI / 180, c = Math.abs(Math.cos(angle)), s = Math.abs(Math.sin(angle));
  const hu = (c * hold.width + s * hold.height) / 2, hv = (s * hold.width + c * hold.height) / 2;
  const inside = region.patches.some(patch => patch.wall_panel_id === placement.wall_panel_id
    && placement.u - hu >= patch.u_min - 1e-8 && placement.u + hu <= patch.u_max + 1e-8
    && placement.v - hv >= patch.v_min - 1e-8 && placement.v + hv <= patch.v_max + 1e-8);
  if (!inside) return '岩点边缘超出了所选区域，请向区域内移一点。';
}

/** Exact panel transforms shared with holds; a folded region stays on every face. */
export function gymPatchPoints(scene: Request['scene'], patch: GymPatch, offset = 0): Vec3[] {
  const panel = scene.wall_panels?.find(item => item.id === patch.wall_panel_id);
  if (!panel || ![patch.u_min, patch.u_max, patch.v_min, patch.v_max, offset].every(Number.isFinite)
    || patch.u_min >= patch.u_max || patch.v_min >= patch.v_max
    || patch.u_min < -panel.width / 2 || patch.u_max > panel.width / 2
    || patch.v_min < 0 || patch.v_max > panel.height) return [];
  const frame = panelFrame(scene.angle_deg, panel);
  return [[patch.u_min, patch.v_min], [patch.u_max, patch.v_min], [patch.u_max, patch.v_max], [patch.u_min, patch.v_max]]
    .map(([u, v]) => transformPoint(frame, [u, v, offset]));
}

export function gymRegionPoints(gym: ExampleGym, regionId: string, offset = 0): Vec3[] {
  return gym.regions.find(region => region.id === regionId)?.patches.flatMap(patch => gymPatchPoints(gym.scene, patch, offset)) || [];
}
