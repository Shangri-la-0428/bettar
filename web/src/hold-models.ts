import * as THREE from 'three';
import type { Hold, GripSurface } from './types';
import { resolveHoldAsset } from './hold-assets.ts';

export const holdColors: Record<string, number> = {
  jug: 0xb86d4e, crimp: 0x587985, pocket: 0x936c9f, directional_edge: 0x587985, foothold: 0x858853,
  sloper: 0x3762b8, pinch: 0xe37c43, rail: 0x3762b8, volume: 0x515861,
};
let resinTexture: THREE.DataTexture | undefined;
/** Original, deterministic resin grain. Shared for the lifetime of the page. */
export function grainTexture(): THREE.DataTexture {
  if (resinTexture) return resinTexture;
  const size = 128, bytes = new Uint8Array(size * size * 4);
  let seed = 8173;
  for (let i = 0; i < size * size; i++) {
    seed = (Math.imul(seed, 1664525) + 1013904223) | 0;
    const v = 130 + ((seed >>> 24) % 110);
    bytes.set([v, v, v, 255], i * 4);
  }
  resinTexture = new THREE.DataTexture(bytes, size, size, THREE.RGBAFormat);
  resinTexture.wrapS = resinTexture.wrapT = THREE.RepeatWrapping;
  resinTexture.magFilter = THREE.LinearFilter; resinTexture.minFilter = THREE.LinearMipmapLinearFilter;
  resinTexture.generateMipmaps = true; resinTexture.needsUpdate = true;
  return resinTexture;
}
function hash(id: string) { let n = 2166136261; for (const c of id) n = Math.imul(n ^ c.charCodeAt(0), 16777619); return (n >>> 0) / 4294967295; }
const modelSeed = (hold: Hold) => typeof hold.template_id === 'string' ? hold.template_id : hold.id;
export type GripSurfaceSpec = GripSurface;
export function gripSurfaces(hold: Hold): GripSurfaceSpec[] {
  return Array.isArray(hold.grip_surfaces) ? hold.grip_surfaces as GripSurfaceSpec[] : [];
}
interface Shell { geometry: THREE.BufferGeometry; surface: (x: number, y: number) => number }
const signedPower = (value: number, power: number) => Math.sign(value) * Math.pow(Math.abs(value), power);

/** Three planar working faces, a triangular footprint, and a closed wall-facing back.
 * The central apex is the current synthetic contact target, not a validated grip. */
function volumeShell(hold: Hold): Shell {
  const { width: w, height: h, depth: d } = hold;
  const outline = [[-.49 * w, -.45 * h], [.49 * w, -.32 * h], [-.23 * w, .49 * h]];
  const skirt = Math.min(.008, d * .06), positions = [0, 0, d];
  for (const [x, y] of outline) positions.push(x, y, skirt);
  for (const [x, y] of outline) positions.push(x, y, 0);
  const indices = [0, 1, 2, 0, 2, 3, 0, 3, 1, 1, 4, 2, 2, 4, 5, 2, 5, 3, 3, 5, 6, 3, 6, 1, 1, 6, 4, 4, 6, 5];
  const indexed = new THREE.BufferGeometry();
  indexed.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3)); indexed.setIndex(indices);
  const geometry = indexed.toNonIndexed(); indexed.dispose();
  const uvs: number[] = [];
  const p = geometry.getAttribute('position');
  for (let i = 0; i < p.count; i++) uvs.push(p.getX(i) * 14, p.getY(i) * 14);
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2)); geometry.computeVertexNormals();
  // Height on the pyramid is the minimum of the three face planes.
  const planes = outline.map((a, i) => {
    const b = outline[(i + 1) % outline.length], determinant = a[0] * b[1] - a[1] * b[0];
    return [(skirt - d) * (b[1] - a[1]) / determinant, (skirt - d) * (a[0] - b[0]) / determinant];
  });
  return { geometry, surface: (x, y) => Math.max(0, Math.min(...planes.map(([a, b]) => d + a * x + b * y))) };
}

/** Original closed height-field shells, all inside the declared box.
 * Width/height/depth are metres. Display form does not replace collision proxies,
 * add secondary contact patches, or establish friction and force feasibility. */
function shell(hold: Hold): Shell {
  const resolved = resolveHoldAsset(hold);
  if (resolved.kind === 'unavailable') return { geometry: new THREE.BufferGeometry(), surface: () => 0 };
  if (resolved.kind === 'asset') {
    const { asset, scale } = resolved, geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(asset.geometry.positions.flatMap(point => point.map(value => value * scale)), 3));
    geometry.setIndex(asset.geometry.triangles.flat());
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(asset.geometry.positions.flatMap(([x, y]) => [x * scale * 14, y * scale * 14]), 2));
    geometry.computeVertexNormals();
    // An arbitrary mesh is not a height field. No analytic surface or synthetic
    // bolt is added; picking and contact patches use the registered triangles.
    return { geometry, surface: () => 0 };
  }
  if (hold.type === 'volume') return volumeShell(hold);
  const phase = hash(modelSeed(hold)) * Math.PI * 2;
  const { width: w, height: h, depth: d } = hold;
  const profile = (x: number, y: number) => {
    const r = Math.min(1, Math.hypot(x, y));
    const body = Math.sqrt(Math.max(0, 1 - r * r));
    let z: number;
    if (hold.type === 'jug') {
      const lip = Math.exp(-Math.pow((y + .055 + .09 * x * x) / .21, 2)) * (1 - .35 * x * x);
      const cavity = Math.exp(-x * x / .28 - Math.pow((y - .39) / .21, 2));
      z = .11 + .35 * body + .65 * lip - .35 * cavity;
      const center = .46 + .65 * Math.exp(-Math.pow(.055 / .21, 2)) - .35 * Math.exp(-Math.pow(.39 / .21, 2));
      z /= center;
    } else if (hold.type === 'sloper') {
      // Broad asymmetric convex macro; no invented incut or positive gripping lip.
      const q = Math.min(1, x * x * .93 + y * y * 1.08);
      z = .055 + .945 * Math.pow(1 - q, .60) * (1 - .13 * y * r - .055 * x * r);
    } else if (hold.type === 'pinch') {
      // A tall tapered rib with opposed side faces and a narrow rounded crest.
      z = .075 + .925 * Math.exp(-Math.pow(Math.abs(x) / .59, 1.45)) * Math.pow(Math.max(0, 1 - y * y), .36);
    } else if (hold.type === 'rail') {
      // Long directional lip: broad lower ramp, abrupt upper fall-away, rounded ends.
      const ridge = y <= 0 ? Math.exp(y * 1.10) : Math.exp(-y * 5.4);
      z = (.085 + .915 * ridge) * (1 - .40 * Math.pow(Math.abs(x), 3));
    } else if (hold.type === 'pocket') {
      // The depression is part of the mesh, including a floor and rounded inner
      // wall. A dark circle painted onto a jug would not provide this geometry.
      const q = (x / .43) ** 2 + ((y - .12) / .43) ** 2;
      const shoulder = .12 + .88 * Math.pow(Math.max(0, 1 - r * r), .48);
      z = shoulder - .76 * Math.exp(-q * q * 1.8);
    } else if (hold.type === 'crimp') {
      const ramp = y <= .10 ? Math.exp((y - .10) * 1.35) : Math.exp(-(y - .10) * 8.8);
      z = (.08 + .92 * ramp) * Math.pow(Math.max(.03, 1 - x * x), .16);
    } else if (hold.type === 'directional_edge') {
      const ridge = y <= 0 ? Math.exp(y * 1.15) : Math.exp(-y * 5.0);
      z = (.10 + .90 * ridge) * Math.pow(Math.max(.04, 1 - x * x), .22);
    } else {
      const ridge = y <= 0 ? Math.max(.05, 1 + y * .94) : Math.exp(-y * 3.7);
      z = .09 + .91 * ridge * Math.pow(Math.max(.02, 1 - x * x), .3);
    }
    return Math.min(1, Math.max(.045, z)) * d;
  };
  const outline = (a: number): [number, number] => {
    const c = Math.cos(a), s = Math.sin(a);
    if (hold.type === 'sloper') {
      const organic = .90 + .055 * Math.sin(3 * a + phase) + .025 * Math.cos(2 * a);
      return [signedPower(c, .86) * organic, signedPower(s, .91) * organic];
    }
    if (hold.type === 'pinch') {
      const y = signedPower(s, .56) * .97;
      return [signedPower(c, .72) * (.97 - .42 * Math.pow(Math.abs(y), 1.5)), y];
    }
    if (hold.type === 'crimp') {
      return [signedPower(c, .58) * .97, signedPower(s, .72) * .91];
    }
    if (hold.type === 'pocket') {
      return [signedPower(c, .83) * .95, signedPower(s, .88) * .95];
    }
    if (hold.type === 'rail') {
      const x = signedPower(c, .52) * .98;
      return [x, signedPower(s, .82) * .78 + .12 * x * x];
    }
    const organic = .94 + .035 * Math.sin(a * 3 + phase) + .02 * Math.cos(a * 5 - phase);
    return [c * organic, s * organic];
  };
  const detailed = hold.type === 'pocket' || hold.type === 'crimp';
  const segments = detailed ? 120 : 80, rings = detailed ? 48 : 24, positions: number[] = [], uvs: number[] = [], indices: number[] = [];
  const add = (x: number, y: number, z: number) => {
    positions.push(x * w / 2, y * h / 2, z);
    // Physical grain spacing stays constant as a hold scales up to a macro.
    uvs.push(x * w * 7, y * h * 7);
  };
  add(0, 0, profile(0, 0));
  for (let ring = 1; ring <= rings; ring++) for (let j = 0; j < segments; j++) {
    const [ox, oy] = outline(j / segments * Math.PI * 2), r = ring / rings;
    const x = ox * r, y = oy * r; add(x, y, profile(x, y));
  }
  for (let j = 0; j < segments; j++) indices.push(0, 1 + j, 1 + (j + 1) % segments);
  for (let ring = 1; ring < rings; ring++) for (let j = 0; j < segments; j++) {
    const a = 1 + (ring - 1) * segments + j, b = 1 + (ring - 1) * segments + (j + 1) % segments;
    const c = a + segments, e = b + segments; indices.push(a, c, b, b, c, e);
  }
  const backStart = positions.length / 3;
  for (let j = 0; j < segments; j++) {
    const front = 1 + (rings - 1) * segments + j;
    positions.push(positions[front * 3], positions[front * 3 + 1], 0); uvs.push(0, 0);
  }
  const centerBack = positions.length / 3; positions.push(0, 0, 0); uvs.push(0, 0);
  for (let j = 0; j < segments; j++) {
    const a = 1 + (rings - 1) * segments + j, b = 1 + (rings - 1) * segments + (j + 1) % segments;
    const c = backStart + j, e = backStart + (j + 1) % segments;
    indices.push(a, c, b, b, c, e, centerBack, e, c);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2)); geometry.setIndex(indices); geometry.computeVertexNormals();
  return { geometry, surface: (x, y) => profile(x * 2 / w, y * 2 / h) };
}

function sampleGeometrySurface(geometry: THREE.BufferGeometry, hold: Hold, x: number, y: number) {
  const material = new THREE.MeshBasicMaterial();
  const mesh = new THREE.Mesh(geometry, material);
  mesh.updateMatrixWorld(true);
  const ray = new THREE.Raycaster(new THREE.Vector3(x, y, hold.depth + 1), new THREE.Vector3(0, 0, -1));
  const hit = ray.intersectObject(mesh)[0]; material.dispose();
  if (!hit) return undefined;
  return { position: hit.point.clone(), normal: (hit.normal ?? hit.face!.normal).clone().normalize() };
}

/** Samples the actual front mesh (not its analytic approximation), in model metres. */
export function sampleHoldSurface(hold: Hold, x: number, y: number) {
  if (resolveHoldAsset(hold).kind === 'unavailable') return undefined;
  const { geometry } = shell(hold);
  const hit = sampleGeometrySurface(geometry, hold, x, y); geometry.dispose(); return hit;
}

interface PatchVertex { position: THREE.Vector3; normal: THREE.Vector3; u: number; v: number }
function clipPatchPolygon(vertices: PatchVertex[], distance: (point: PatchVertex) => number): PatchVertex[] {
  const result: PatchVertex[] = [];
  for (let j = 0; j < vertices.length; j++) {
    const p = vertices[j], q = vertices[(j + 1) % vertices.length], dp = distance(p), dq = distance(q);
    if (dp >= -1e-10) result.push(p);
    if ((dp >= 0) !== (dq >= 0)) {
      const t = dp / (dp - dq);
      result.push({ position: p.position.clone().lerp(q.position, t), normal: p.normal.clone().lerp(q.normal, t), u: p.u + (q.u - p.u) * t, v: p.v + (q.v - p.v) * t });
    }
  }
  return result;
}
/** Clip existing resin triangles in the declared tangent ellipse. Every generated
 * vertex remains on its source triangle, so the region cannot float or bridge a rim. */
function gripPatchGeometry(geometry: THREE.BufferGeometry, surface: GripSurfaceSpec, external: boolean): THREE.BufferGeometry {
  const point = new THREE.Vector3(...surface.position), uAxis = new THREE.Vector3(...surface.u_axis).normalize();
  const vAxis = new THREE.Vector3(...surface.v_axis).normalize(), normal = new THREE.Vector3(...surface.normal).normalize();
  const positions: number[] = [], normals: number[] = [], uvs: number[] = [];
  const position = geometry.getAttribute('position'), vertexNormal = geometry.getAttribute('normal');
  const index = geometry.index, count = index?.count ?? position.count;
  const selectedTriangles = surface.annotations?.triangle_indices ? new Set(surface.annotations.triangle_indices) : undefined;
  const depthLimit = Math.max(...surface.radii) * .70;
  const normalDistance = (p: PatchVertex) => p.position.clone().sub(point).dot(normal);
  const polygon = Array.from({ length: 40 }, (_, i) => [Math.cos(i * Math.PI / 20), Math.sin(i * Math.PI / 20)]);
  const vertex = (i: number): PatchVertex => {
    const p = new THREE.Vector3().fromBufferAttribute(position, i), relative = p.clone().sub(point);
    return { position: p, normal: new THREE.Vector3().fromBufferAttribute(vertexNormal, i), u: relative.dot(uAxis) / surface.radii[0], v: relative.dot(vAxis) / surface.radii[1] };
  };
  const append = (entry: PatchVertex) => {
    positions.push(...entry.position.toArray()); normals.push(...entry.normal.clone().normalize().toArray());
    uvs.push(entry.position.x * 14, entry.position.y * 14);
  };
  for (let i = 0; i < count; i += 3) {
    if (selectedTriangles && !selectedTriangles.has(i / 3)) continue;
    let clipped = [vertex(index ? index.getX(i) : i), vertex(index ? index.getX(i + 1) : i + 1), vertex(index ? index.getX(i + 2) : i + 2)];
    const faceNormal = clipped[1].position.clone().sub(clipped[0].position).cross(clipped[2].position.clone().sub(clipped[0].position)).normalize();
    // Imported incuts may face sideways or back toward the wall. Restrict their
    // patch by the declared neighbourhood and face direction, not global z.
    if ((!external && faceNormal.z < .015) || faceNormal.dot(normal) < .15) continue;
    if (Math.min(...clipped.map(p => p.u)) > 1 || Math.max(...clipped.map(p => p.u)) < -1 || Math.min(...clipped.map(p => p.v)) > 1 || Math.max(...clipped.map(p => p.v)) < -1) continue;
    // A tangent projection alone can accidentally select a remote surface behind
    // a lip. Keep the patch local to its declared contact neighbourhood.
    clipped = clipPatchPolygon(clipped, p => depthLimit - normalDistance(p));
    clipped = clipPatchPolygon(clipped, p => depthLimit + normalDistance(p));
    if (!clipped.every(p => p.u * p.u + p.v * p.v < .993)) {
      for (let edge = 0; edge < polygon.length && clipped.length; edge++) {
        const a = polygon[edge], b = polygon[(edge + 1) % polygon.length];
        const distance = (p: PatchVertex) => (b[0] - a[0]) * (p.v - a[1]) - (b[1] - a[1]) * (p.u - a[0]);
        clipped = clipPatchPolygon(clipped, distance);
      }
    }
    for (let j = 1; j < clipped.length - 1; j++) { append(clipped[0]); append(clipped[j]); append(clipped[j + 1]); }
  }
  const patch = new THREE.BufferGeometry();
  patch.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  patch.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  patch.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  return patch;
}

function surfaceMesh(geometry: THREE.BufferGeometry, surface: GripSurfaceSpec, tint: THREE.Color, selected: boolean, base: boolean, external = false) {
  const material = new THREE.MeshStandardMaterial({
    color: tint.clone().lerp(new THREE.Color(0xf4f1df), base ? .13 : selected ? .42 : .18),
    roughness: .98, metalness: 0, bumpMap: grainTexture(), bumpScale: .00035,
    transparent: !base, opacity: base ? 1 : selected ? .72 : .27,
    polygonOffset: true, polygonOffsetFactor: base ? -1 : -2, polygonOffsetUnits: base ? -1 : -2,
    depthWrite: base, side: THREE.FrontSide,
  });
  const mesh = new THREE.Mesh(gripPatchGeometry(geometry, surface, external), material);
  mesh.receiveShadow = true;
  mesh.userData.surfaceId = surface.id; mesh.userData.gripSurface = true; mesh.userData.selected = selected;
  mesh.userData.gripBase = base;
  mesh.renderOrder = base ? 1 : 3; return mesh;
}

function holdTint(hold: Hold) {
  const custom = typeof hold.color === 'string' && /^#[0-9a-f]{6}$/i.test(hold.color) ? hold.color : undefined;
  const tint = new THREE.Color(custom ?? holdColors[hold.type] ?? 0x8c806e);
  if (!custom) tint.offsetHSL((hash(modelSeed(hold)) - .5) * .018, 0, (hash(modelSeed(hold)) - .5) * .025);
  return tint;
}

/** Scene/preview helper. Local coordinates only: the caller supplies installation
 * transforms. Teal = outward surface normal; warm ivory = declared pull direction. */
export function createGripOverlay(hold: Hold, surfaceId?: string, options: { id?: string; arrows?: boolean; all?: boolean } = {}): THREE.Group {
  const group = new THREE.Group(), surfaces = gripSurfaces(hold);
  const resolved = resolveHoldAsset(hold), external = resolved.kind === 'asset';
  group.userData.gripOverlay = true; group.userData.selectedSurfaceId = null;
  if (!surfaces.length || resolved.kind === 'unavailable') return group;
  const selectedId = surfaceId ?? surfaces[0].id, { geometry } = shell(hold), tint = holdTint(hold);
  if (surfaces.some(surface => surface.id === selectedId)) group.userData.selectedSurfaceId = selectedId;
  for (const surface of surfaces) {
    const selected = surface.id === selectedId;
    if (options.all === false && !selected) continue;
    const mesh = surfaceMesh(geometry, surface, tint, selected, false, external);
    mesh.userData.id = options.id ?? hold.id; group.add(mesh);
    if (options.arrows === false || (!selected && options.all !== true)) continue;
    const hit = external ? undefined : sampleGeometrySurface(geometry, hold, surface.position[0], surface.position[1]);
    const point = hit?.position ?? new THREE.Vector3(...surface.position), normal = new THREE.Vector3(...surface.normal).normalize();
    const length = Math.max(.025, Math.min(.11, Math.max(...surface.radii) * 1.25)) * (selected ? 1 : .82);
    const origin = point.clone().addScaledVector(normal, Math.min(.003, length * .07));
    for (const [direction, color, kind] of [[normal, 0x45c1c4, 'normal'], [new THREE.Vector3(...surface.pull_direction).normalize(), 0xf5db9e, 'pull']] as const) {
      if (direction.lengthSq() < 1e-10) continue;
      const arrow = new THREE.ArrowHelper(direction, origin, length, color, length * .24, length * .13);
      arrow.userData.surfaceId = surface.id; arrow.userData.annotation = kind;
      arrow.traverse(object => {
        object.userData.id = options.id ?? hold.id; object.userData.surfaceId = surface.id; object.userData.annotation = kind;
        if (!selected && (object instanceof THREE.Mesh || object instanceof THREE.Line)) {
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          for (const material of materials) { material.transparent = true; material.opacity = .30; }
        }
      });
      group.add(arrow);
    }
  }
  geometry.dispose(); return group;
}

/** Small tangent-aligned metal details, capped in metres rather than scaled with macros. */
function addFastening(group: THREE.Group, hold: Hold, surface: Shell['surface'], x: number, y: number, screw = false) {
  const radius = Math.min(screw ? .0035 : .0075, Math.min(hold.width, hold.height) * .055, hold.depth * .09);
  const epsilon = Math.min(.0002, Math.min(hold.width, hold.height) * .002);
  const dx = (surface(x + epsilon, y) - surface(x - epsilon, y)) / (2 * epsilon);
  const dy = (surface(x, y + epsilon) - surface(x, y - epsilon)) / (2 * epsilon);
  const normal = new THREE.Vector3(-dx, -dy, 1).normalize();
  const fixture = new THREE.Group(); fixture.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
  fixture.position.set(x, y, surface(x, y));
  const socket = new THREE.Mesh(new THREE.CircleGeometry(radius, 24), new THREE.MeshStandardMaterial({ color: 0x232a30, roughness: .96 }));
  socket.position.z = .00015; fixture.add(socket);
  const rim = new THREE.Mesh(new THREE.RingGeometry(radius * .56, radius * .88, 24), new THREE.MeshStandardMaterial({ color: 0x777d80, metalness: .65, roughness: .52 }));
  rim.position.z = .00025; fixture.add(rim);
  const hex = new THREE.Mesh(new THREE.CircleGeometry(radius * .40, 6), new THREE.MeshBasicMaterial({ color: 0x242a2d }));
  hex.rotation.z = .24; hex.position.z = .00035; fixture.add(hex);
  fixture.userData.fasteningRadius = radius; group.add(fixture);
}

export function createHoldModel(hold: Hold, options: { id?: string; ghost?: boolean } = {}): THREE.Group {
  const group = new THREE.Group(), ghost = !!options.ghost;
  const resolved = resolveHoldAsset(hold);
  group.userData.modelSource = resolved.kind === 'template' ? 'original_procedural_synthetic' : resolved.kind === 'asset' ? 'external_mesh' : 'unavailable_asset';
  group.userData.holdType = hold.type;
  if (resolved.kind === 'unavailable') { group.userData.assetError = resolved.reason; return group; }
  const { geometry, surface } = shell(hold);
  const tint = holdTint(hold), surfaces = gripSurfaces(hold);
  const resin = new THREE.MeshStandardMaterial({ color: tint, roughness: resolved.kind === 'asset' ? .80 : hold.type === 'volume' ? .83 : surfaces.length ? .52 : .87, metalness: 0, bumpMap: grainTexture(), bumpScale: Math.min(surfaces.length ? .00004 : .0003, Math.min(hold.width, hold.height) * .003), roughnessMap: surfaces.length ? null : grainTexture(), transparent: ghost, opacity: ghost ? .23 : 1, wireframe: ghost });
  const body = new THREE.Mesh(geometry, resin); body.castShadow = !ghost; body.receiveShadow = true; body.userData.resin = true; group.add(body);
  if (!ghost) {
    for (const grip of surfaces) group.add(surfaceMesh(geometry, grip, tint, false, true, resolved.kind === 'asset'));
    if (resolved.kind === 'asset') {
      group.userData.assetId = resolved.asset.id; group.userData.assetGeometrySha256 = resolved.asset.geometry_sha256;
    } else if (hold.type === 'volume') {
      // Screw-on volume: perimeter fastenings are deliberately small, no giant central bolt.
      for (const [x, y] of [[-.29, -.27], [.28, -.18], [-.15, .30]]) addFastening(group, hold, surface, x * hold.width, y * hold.height, true);
    } else {
      const bx = hold.type === 'pinch' ? -.18 * hold.width : .025 * hold.width;
      const by = hold.type === 'pinch' ? -.13 * hold.height : hold.type === 'pocket' ? -.32 * hold.height : -.25 * hold.height;
      addFastening(group, hold, surface, bx, by);
      if (Math.max(hold.width, hold.height) > .30) addFastening(group, hold, surface, -.25 * hold.width, -.18 * hold.height, true);
    }
  }
  group.traverse((object) => { if (object instanceof THREE.Mesh) { object.userData.id = options.id || hold.id; object.userData.baseOpacity = object.material instanceof THREE.Material ? object.material.opacity : 1; } });
  return group;
}
export function disposeObject(root: THREE.Object3D) {
  root.traverse((object) => {
    if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
      object.geometry.dispose(); const materials = Array.isArray(object.material) ? object.material : [object.material]; materials.forEach((material) => material.dispose());
    }
  });
}
