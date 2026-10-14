import type { Hold, Placement, Vec3, WallPanel } from './types';

/** Metres, right-handed orthonormal axes. No renderer objects: shared by UI and numeric checks. */
export interface Frame { origin: Vec3; u: Vec3; v: Vec3; normal: Vec3 }
export interface PlacementContext { angleDeg: number; placements: readonly Placement[]; inventory: readonly Hold[]; wallPanels?: readonly WallPanel[] }
export interface ContactFrame extends Frame { surfaceId: string; pullDirection?: Vec3 }

const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scale = (a: Vec3, s: number): Vec3 => [a[0] * s, a[1] * s, a[2] * s];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

export function wallFrame(angleDeg: number): Frame {
  const a = angleDeg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
  return { origin: [0, 0, 0], u: [1, 0, 0], v: [0, c, s], normal: [0, -s, c] };
}
export function transformDirection(frame: Frame, vector: Vec3): Vec3 {
  return add(add(scale(frame.u, vector[0]), scale(frame.v, vector[1])), scale(frame.normal, vector[2]));
}
export function transformPoint(frame: Frame, point: Vec3): Vec3 { return add(frame.origin, transformDirection(frame, point)); }
export function inversePoint(frame: Frame, point: Vec3): Vec3 {
  const relative: Vec3 = [point[0] - frame.origin[0], point[1] - frame.origin[1], point[2] - frame.origin[2]];
  return [dot(relative, frame.u), dot(relative, frame.v), dot(relative, frame.normal)];
}
function compose(parent: Frame, local: Frame): Frame {
  return { origin: transformPoint(parent, local.origin), u: transformDirection(parent, local.u), v: transformDirection(parent, local.v), normal: transformDirection(parent, local.normal) };
}

/** Rz @ Ry @ Rx in the base-wall frame; panel origin is the bottom centre. */
export function panelFrame(angleDeg: number, panel: WallPanel): Frame {
  const [rx, ry, rz] = panel.rotation_deg.map(value => value * Math.PI / 180);
  const cx = Math.cos(rx), sx = Math.sin(rx), cy = Math.cos(ry), sy = Math.sin(ry), cz = Math.cos(rz), sz = Math.sin(rz);
  return compose(wallFrame(angleDeg), { origin: panel.origin,
    u: [cz * cy, sz * cy, -sy],
    v: [cz * sy * sx - sz * cx, sz * sy * sx + cz * cx, cy * sx],
    normal: [cz * sy * cx + sz * sx, sz * sy * cx - cz * sx, cy * cx] });
}

/** The unrotated plane in which Placement.u/v are measured: wall or a parent volume face. */
export function installationFrame(placement: Placement, context: PlacementContext): Frame {
  if (placement.mount && placement.wall_panel_id) throw new Error(`Mounted child cannot select a wall panel: ${placement.id}`);
  if (!placement.mount) {
    if (!placement.wall_panel_id) {
      if (context.wallPanels?.length) throw new Error(`Wall panel required for ${placement.id}`);
      return wallFrame(context.angleDeg);
    }
    const panel = context.wallPanels?.find(item => item.id === placement.wall_panel_id);
    if (!panel) throw new Error(`Unknown wall panel ${placement.wall_panel_id} on ${placement.id}`);
    return panelFrame(context.angleDeg, panel);
  }
  if (context.inventory.find(hold => hold.id === placement.inventory_id)?.type === 'volume') throw new Error(`A volume cannot be mounted on another volume: ${placement.id}`);
  const parent = context.placements.find(item => item.id === placement.mount!.parent_id);
  if (!parent || parent.mount) throw new Error(`Invalid mounting parent for ${placement.id}`);
  const parentHold = context.inventory.find(hold => hold.id === parent.inventory_id);
  const face = parentHold?.mounting_faces?.find(item => item.id === placement.mount!.face_id);
  if (!parentHold || parentHold.type !== 'volume' || !face) throw new Error(`Invalid mounting face for ${placement.id}`);
  return compose(placementFrame(parent, context), { origin: face.origin, u: face.u_axis, v: face.v_axis, normal: face.normal });
}

/** Rotation is around the installation normal, after translation in that plane. */
export function placementFrame(placement: Placement, context: PlacementContext): Frame {
  const base = installationFrame(placement, context), a = placement.rotation_deg * Math.PI / 180;
  const c = Math.cos(a), s = Math.sin(a);
  return { origin: transformPoint(base, [placement.u, placement.v, 0]), u: transformDirection(base, [c, s, 0]), v: transformDirection(base, [-s, c, 0]), normal: base.normal };
}

/** `main` is the legacy alias for the placement's selected surface, never a second patch. */
export function selectedGripSurface(placement: Placement, hold: Hold, contactId?: string) {
  const id = contactId && contactId !== 'main' && contactId !== hold.contact.id ? contactId : placement.contact_surface_id;
  if (!id) return undefined;
  const surface = hold.grip_surfaces?.find(item => item.id === id);
  if (!surface) throw new Error(`Unknown grip surface ${id} on ${placement.id}`);
  return surface;
}

export function contactFrame(placement: Placement, hold: Hold, context: PlacementContext, contactId?: string): ContactFrame {
  const frame = placementFrame(placement, context), surface = selectedGripSurface(placement, hold, contactId);
  const contact = surface ?? { id: hold.contact.id, position: hold.contact.position, normal: [0, 0, 1] as Vec3, u_axis: [1, 0, 0] as Vec3, v_axis: [0, 1, 0] as Vec3, pull_direction: hold.pull_direction };
  return { ...compose(frame, { origin: contact.position, u: contact.u_axis, v: contact.v_axis, normal: contact.normal }), surfaceId: contact.id, pullDirection: contact.pull_direction ? transformDirection(frame, contact.pull_direction) : undefined };
}

/** Failed candidates remain reviewable. Missing/invalid frames are omitted, never moved to the wall. */
function displayFrame<T extends Frame>(resolve: () => T): T | undefined {
  try {
    const frame = resolve(), axes = [frame.u, frame.v, frame.normal];
    if (![frame.origin, ...axes].every(vector => vector.length === 3 && vector.every(Number.isFinite))) return undefined;
    if (axes.some(axis => Math.abs(dot(axis, axis) - 1) > 1e-7) || Math.abs(dot(frame.u, frame.v)) > 1e-7 || Math.abs(dot(frame.u, frame.normal)) > 1e-7 || Math.abs(dot(frame.v, frame.normal)) > 1e-7) return undefined;
    const cross: Vec3 = [frame.u[1] * frame.v[2] - frame.u[2] * frame.v[1], frame.u[2] * frame.v[0] - frame.u[0] * frame.v[2], frame.u[0] * frame.v[1] - frame.u[1] * frame.v[0]];
    return dot(cross, frame.normal) > 0 ? frame : undefined;
  } catch { return undefined; }
}
export function tryInstallationFrame(placement: Placement, context: PlacementContext): Frame | undefined { return displayFrame(() => installationFrame(placement, context)); }
export function tryPlacementFrame(placement: Placement, context: PlacementContext): Frame | undefined { return displayFrame(() => placementFrame(placement, context)); }
export function tryContactFrame(placement: Placement, hold: Hold, context: PlacementContext, contactId?: string): ContactFrame | undefined { return displayFrame(() => contactFrame(placement, hold, context, contactId)); }

/** Layout height and vertical elevation are distinct on inclined/folded walls.
 * Vertical elevation uses the front panel corners above the scene floor y = 0;
 * slab thickness and hold depth are intentionally excluded from wall height.
 */
export function wallHeightMeasures(scene: { height: number; angle_deg: number; wall_panels?: readonly WallPanel[] }) {
  const elevations = scene.wall_panels?.length
    ? scene.wall_panels.flatMap(panel => {
      const frame = panelFrame(scene.angle_deg, panel);
      return [-panel.width / 2, panel.width / 2].flatMap(u => [0, panel.height].map(v => transformPoint(frame, [u, v, 0])[1]));
    })
    : [transformPoint(wallFrame(scene.angle_deg), [0, scene.height, 0])[1]];
  return { unfolded: scene.height, vertical: Math.max(0, ...elevations) };
}
