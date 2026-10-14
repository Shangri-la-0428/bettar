import * as THREE from 'three';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

export const MAX_SCAN_BYTES = 15 * 1024 * 1024;
export const MAX_SCAN_TRIANGLES = 150_000;
export type ScanUnit = 'm' | 'cm' | 'mm';
export type ScanUp = 'Y' | 'Z';
export interface ScanTriangle {
  triangle_index: number; position_m: number[]; normal: number[];
  u_axis: number[]; v_axis: number[]; vertices_m: number[][]; area_m2: number;
}

/** Only local geometry is parsed: OBJ materials and external resources are never loaded. */
export function parseScan(data: ArrayBuffer, filename: string): THREE.BufferGeometry {
  if (data.byteLength > MAX_SCAN_BYTES) throw new Error('文件超过 15 MB，请先在扫描软件中减面。');
  let geometry: THREE.BufferGeometry;
  if (/\.stl$/i.test(filename)) geometry = new STLLoader().parse(data);
  else if (/\.obj$/i.test(filename)) {
    const object = new OBJLoader().parse(new TextDecoder().decode(data));
    const pieces: THREE.BufferGeometry[] = [];
    object.updateMatrixWorld(true);
    object.traverse(child => {
      if (!(child instanceof THREE.Mesh)) return;
      const piece = child.geometry.index ? child.geometry.toNonIndexed() : child.geometry.clone();
      for (const name of Object.keys(piece.attributes)) if (name !== 'position') piece.deleteAttribute(name);
      piece.clearGroups(); piece.applyMatrix4(child.matrixWorld); pieces.push(piece);
    });
    const merged = pieces.length ? mergeGeometries(pieces) : null;
    pieces.forEach(piece => piece.dispose());
    object.traverse(child => { if (child instanceof THREE.Mesh) { child.geometry.dispose(); for (const material of Array.isArray(child.material) ? child.material : [child.material]) material.dispose(); } });
    if (!merged) throw new Error('OBJ 没有可读取的三角网格。');
    geometry = merged;
  } else throw new Error('请选择 STL 或 OBJ 网格文件。');
  try { validateScan(geometry); } catch (error) { geometry.dispose(); throw error; }
  return geometry;
}

export function validateScan(geometry: THREE.BufferGeometry): void {
  const p = geometry.getAttribute('position');
  const count = geometry.index?.count || p?.count || 0;
  if (!p || p.itemSize !== 3 || count < 3 || count % 3) throw new Error('网格为空或三角形索引不完整。');
  if (count / 3 > MAX_SCAN_TRIANGLES) throw new Error('网格超过 15 万个三角形，请先减面。');
  for (let i = 0; i < p.count; i++) for (let j = 0; j < 3; j++) if (!Number.isFinite(p.array[i * 3 + j])) throw new Error('网格包含非有限坐标。');
  if (geometry.index) for (const i of geometry.index.array) if (i < 0 || i >= p.count) throw new Error('网格索引超出顶点范围。');
  geometry.computeBoundingBox();
  if (geometry.boundingBox!.getSize(new THREE.Vector3()).length() < 1e-9) throw new Error('网格没有可辨识的尺寸。');
}

/** Preserve the scan origin. Registration and a mat/ground datum remain separate work. */
export function normalizeScan(raw: THREE.BufferGeometry, unit: ScanUnit, up: ScanUp): THREE.BufferGeometry {
  const geometry = raw.index ? raw.toNonIndexed() : raw.clone();
  const scale = { m: 1, cm: .01, mm: .001 }[unit];
  geometry.scale(scale, scale, scale);
  if (up === 'Z') geometry.rotateX(-Math.PI / 2);
  geometry.computeBoundingBox();
  const extent = geometry.boundingBox!.getSize(new THREE.Vector3()).length();
  if (extent > 100 || extent < .001) { geometry.dispose(); throw new Error('换算后尺寸不在 1 mm–100 m 范围，请检查单位。'); }
  // Recompute geometric normals; a scan's declared normals are not trusted as contact evidence.
  geometry.computeVertexNormals();
  return geometry;
}

export function trianglePatch(geometry: THREE.BufferGeometry, index: number, flip = false): ScanTriangle {
  const p = geometry.getAttribute('position');
  const ids = [0, 1, 2].map(i => geometry.index ? geometry.index.getX(index * 3 + i) : index * 3 + i);
  if (!Number.isInteger(index) || index < 0 || ids.some(i => i >= p.count)) throw new Error('请选择有效的三角面。');
  const [a, b, c] = ids.map(i => new THREE.Vector3().fromBufferAttribute(p, i));
  const cross = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(c, a));
  const area = cross.length() / 2;
  if (area < 1e-12) throw new Error('这个三角面已退化，无法定义接触法向。');
  const normal = cross.normalize().multiplyScalar(flip ? -1 : 1);
  const u = new THREE.Vector3().subVectors(b, a).normalize();
  const v = new THREE.Vector3().crossVectors(normal, u).normalize();
  return { triangle_index: index, position_m: a.clone().add(b).add(c).divideScalar(3).toArray(),
    normal: normal.toArray(), u_axis: u.toArray(), v_axis: v.toArray(),
    vertices_m: [a, b, c].map(p => p.toArray()), area_m2: area };
}

/** Original full 3-D C-section: overhanging lip and recessed cavity are actual triangles. */
export function demoJug(): THREE.BufferGeometry {
  const section = new THREE.Shape();
  const yz = [[-.065, 0], [.065, 0], [.065, .024], [-.022, .025], [-.035, .05], [-.027, .092], [.018, .11], [.047, .095], [.061, .102], [.050, .124], [.005, .139], [-.048, .115], [-.070, .065]];
  yz.forEach(([y, z], i) => i ? section.lineTo(z, y) : section.moveTo(z, y)); section.closePath();
  const geometry = new THREE.ExtrudeGeometry(section, { depth: .24, bevelEnabled: true, bevelSegments: 4, steps: 1, bevelSize: .004, bevelThickness: .004, curveSegments: 8 });
  geometry.rotateY(-Math.PI / 2); geometry.translate(.12, 0, 0); return geometry;
}

/** An original multi-facet wall, not a recovered gym scan. */
export function demoWall(): THREE.BufferGeometry {
  const xs = [-2.4, -.8, .65, 2.4], ys = [0, 1.7, 3, 4.2];
  const depths = [[0, .2, .2, 0], [.3, .7, .9, .2], [.65, 1.15, .65, .1], [.48, .95, .44, -.05]];
  const vertices: number[] = [];
  for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
    const p = [[xs[col], ys[row], depths[row][col]], [xs[col + 1], ys[row], depths[row][col + 1]], [xs[col + 1], ys[row + 1], depths[row + 1][col + 1]], [xs[col], ys[row + 1], depths[row + 1][col]]];
    for (const i of [0, 1, 2, 0, 2, 3]) vertices.push(...p[i]);
  }
  const geometry = new THREE.BufferGeometry(); geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3)); geometry.computeVertexNormals(); return geometry;
}
