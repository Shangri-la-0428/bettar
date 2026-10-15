// Read-only verification of registered asset geometry used by scene, preview and
// thumbnails. Fixtures and source asset registration are prepared separately.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';
import { registerHoldAssetLibrary, resolveHoldAsset } from '../src/hold-assets.ts';
import { createHoldModel, createGripOverlay, disposeObject } from '../src/hold-models.ts';

const library = JSON.parse(fs.readFileSync(new URL('../../assets/holds/library.json', import.meta.url), 'utf8'));
registerHoldAssetLibrary(library);
const families = [...new Set(library.assets.map(asset => asset.family))], missingFamilies = ['jug', 'crimp', 'pinch', 'sloper', 'pocket'].filter(family => !families.includes(family));
assert.ok(library.assets.length > 0, 'registered assets required');
// Current contract: four licensed, prepared mesh families; pocket is an
// explicitly declared procedural fallback. Missing any other family remains
// a failure, including when the historical --allow-partial flag is supplied.
assert.deepEqual(missingFamilies.filter(family => family !== 'pocket'), [], 'jug, crimp, pinch and sloper must have registered meshes');
let models = 0, surfaces = 0, sampledPatchVertices = 0, maxVertexError = 0, maxAnchorError = 0, maxPatchError = 0;
let fixtureAssetInstances = 0, explicitTemplateFallbacks = 0;
const results = [];
function verifyFallback(hold, family, label) {
  assert.equal(hold.type, family);
  assert.ok(typeof hold.asset_fallback_reason === 'string' && hold.asset_fallback_reason.trim(), `${label}: missing mesh has an explicit reason`);
  for (const key of ['asset_id', 'asset_geometry_sha256', 'asset_record_sha256', 'asset_scale', 'asset_source']) assert.ok(!(key in hold), `${label}: fallback must not claim ${key}`);
  assert.ok(hold.grip_surfaces.every(surface => !surface.mesh_anchor), `${label}: no fabricated source-triangle anchors`);
  assert.equal(resolveHoldAsset(hold).kind, 'template', `${label}: renderer recognises original template`);
  const model = createHoldModel(hold);
  assert.equal(model.userData.modelSource, 'original_procedural_synthetic', `${label}: template cannot be reported as external geometry`);
  assert.ok(model.children.some(object => object.isMesh && object.userData.resin), `${label}: explicit fallback renders geometry`);
  disposeObject(model); explicitTemplateFallbacks++;
}
function inventoryHold(asset, scale) {
  const grips = asset.grip_surfaces.map(surface => ({ ...surface, position: surface.position.map(value => value * scale), radii: surface.radii.map(value => value * scale) }));
  return { id: `verification-${asset.id}-${scale}`, type: asset.family, width: asset.width * scale, height: asset.height * scale, depth: asset.depth * scale,
    asset_id: asset.id, asset_geometry_sha256: asset.geometry_sha256, asset_record_sha256: asset.asset_record_sha256, asset_scale: scale, asset_source: 'external_mesh',
    contact: { id: 'main', position: grips[0].position, radius: Math.min(...grips[0].radii), limbs: grips[0].limbs }, grip_surfaces: grips };
}
for (const asset of library.assets) for (const scale of [1, .65]) {
  const hold = inventoryHold(asset, scale), model = createHoldModel(hold, { id: 'asset-placement' });
  assert.equal(resolveHoldAsset(hold).kind, 'asset');
  assert.equal(model.userData.modelSource, 'external_mesh');
  const body = model.children.find(object => object.userData.resin);
  assert.ok(body?.isMesh, 'registered mesh exists');
  const positions = body.geometry.getAttribute('position');
  assert.equal(positions.count, asset.geometry.positions.length, 'original vertices retained');
  assert.deepEqual(Array.from(body.geometry.index.array), asset.geometry.triangles.flat(), 'original triangle topology retained');
  for (let index = 0; index < positions.count; index++) {
    const actual = new THREE.Vector3().fromBufferAttribute(positions, index), expected = new THREE.Vector3(...asset.geometry.positions[index]).multiplyScalar(scale);
    maxVertexError = Math.max(maxVertexError, actual.distanceTo(expected));
    assert.ok(actual.distanceTo(expected) < 1e-6, 'registered vertex only receives uniform scaling');
  }
  model.traverse(object => { assert.ok(!object.userData.fasteningRadius, 'no invented bolts added to external mesh'); if (object.isMesh) assert.equal(object.userData.id, 'asset-placement'); });
  const ghost = createHoldModel(hold, { ghost: true }), ghostBody = ghost.children.find(object => object.userData.resin);
  assert.deepEqual(Array.from(ghostBody.geometry.getAttribute('position').array), Array.from(positions.array), 'comparison mesh geometry parity');
  const triangles = asset.geometry.triangles.map(indices => new THREE.Triangle(...indices.map(index => new THREE.Vector3(...asset.geometry.positions[index]).multiplyScalar(scale))));
  for (const surface of hold.grip_surfaces) {
    assert.ok(surface.mesh_anchor, 'external contact has mesh anchor');
    const anchor = surface.mesh_anchor, triangle = triangles[anchor.triangle_index];
    assert.ok(triangle, 'anchor names existing triangle');
    const reconstructed = triangle.a.clone().multiplyScalar(anchor.barycentric[0]).addScaledVector(triangle.b, anchor.barycentric[1]).addScaledVector(triangle.c, anchor.barycentric[2]);
    const point = new THREE.Vector3(...surface.position), error = point.distanceTo(reconstructed);
    maxAnchorError = Math.max(maxAnchorError, error);
    assert.ok(error < 1e-6, 'anchor reconstructed on displayed mesh');
    const normal = new THREE.Vector3(...surface.normal), faceNormal = triangle.getNormal(new THREE.Vector3());
    assert.ok(normal.distanceTo(faceNormal) < 1e-5, 'declared normal matches oriented source triangle');
    body.updateMatrixWorld(true);
    const ray = new THREE.Raycaster(point.clone().addScaledVector(normal, .0005), normal.clone().negate());
    assert.ok(ray.intersectObject(body).some(hit => hit.point.distanceTo(point) < 1e-5), 'actual mesh ray picking reaches representative contact');
    const overlay = createGripOverlay(hold, surface.id, { all: false, id: 'asset-placement' });
    const patch = overlay.children.find(object => object.userData.gripSurface);
    assert.ok(patch?.geometry.getAttribute('position').count > 0, 'declared mesh patch is visible');
    const patchPositions = patch.geometry.getAttribute('position'), closest = new THREE.Vector3();
    const patchTriangles = surface.annotations?.triangle_indices?.map(index => triangles[index]) || triangles;
    for (let i = 0; i < patchPositions.count; i += Math.max(1, Math.floor(patchPositions.count / 100))) {
      const p = new THREE.Vector3().fromBufferAttribute(patchPositions, i);
      let distance = Infinity;
      for (const face of patchTriangles) distance = Math.min(distance, face.closestPointToPoint(p, closest).distanceTo(p));
      maxPatchError = Math.max(maxPatchError, distance); sampledPatchVertices++;
      assert.ok(distance < 1e-6, 'grip patch remains on declared real triangles, including side and incut faces');
    }
    const normalArrow = overlay.children.find(object => object.userData.annotation === 'normal');
    assert.ok(normalArrow && normalArrow.position.clone().sub(point).cross(normal).length() < 1e-6, 'annotation starts at anchor rather than z-projected outer shell');
    disposeObject(overlay); surfaces++;
  }
  const stripped = { ...hold, template_id: `asset:${asset.id}` };
  for (const key of ['asset_id', 'asset_geometry_sha256', 'asset_record_sha256', 'asset_scale', 'asset_source']) delete stripped[key];
  const anchorOnly = { ...stripped }; delete anchorOnly.template_id;
  const templateMarkerOnly = { ...stripped, grip_surfaces: [] };
  for (const mismatch of [{ ...hold, asset_id: 'missing' }, { ...hold, asset_geometry_sha256: 'wrong' }, { ...hold, asset_record_sha256: 'wrong' }, { ...hold, asset_scale: 0 }, { ...hold, asset_source: undefined }, { ...hold, width: hold.width * 2 }, stripped, anchorOnly, templateMarkerOnly]) {
    assert.equal(resolveHoldAsset(mismatch).kind, 'unavailable');
    const missing = createHoldModel(mismatch), overlay = createGripOverlay(mismatch);
    assert.equal(missing.children.length, 0, 'invalid references cannot fabricate a template replacement');
    assert.equal(overlay.children.length, 0, 'invalid references cannot fabricate contact patches');
  }
  results.push({ asset: asset.id, family: asset.family, scale, vertices: positions.count, triangles: asset.geometry.triangles.length, surfaces: hold.grip_surfaces.length });
  disposeObject(model); disposeObject(ghost); models++;
}
// Inspect fresh runtime inventories: archived fixture metadata alone cannot
// prove that today's generation still labels absent mesh families honestly.
const root = fileURLToPath(new URL('../../', import.meta.url));
const localPython = fileURLToPath(new URL('../../.venv/bin/python', import.meta.url));
const currentInventories = JSON.parse(execFileSync(process.env.BETAR_PYTHON || (fs.existsSync(localPython) ? localPython : 'python3'), ['-c', String.raw`
import json
from boulderlab.engine import default_request
programs = ('diagonal_balance', 'opposing_sidepulls', 'roof_exit')
print(json.dumps({program: default_request(profile='setting', setting_program=program,
    wall_profile='roof' if program == 'roof_exit' else 'overhang', hold_source='assets', budget=1)['scene']['inventory']
    for program in programs}))
`], { cwd: root, encoding: 'utf8' }));
for (const [program, inventory] of Object.entries(currentInventories)) {
  const imported = inventory.filter(hold => hold.asset_id);
  assert.deepEqual(new Set(imported.map(hold => hold.type)), new Set(families), `${program}: current generator uses every registered external family`);
  for (const hold of imported) assert.equal(resolveHoldAsset(hold).kind, 'asset', `${program}/${hold.id}: current inventory resolves the actual source`);
  for (const family of missingFamilies) {
    const fallback = inventory.filter(hold => hold.type === family);
    assert.ok(fallback.length > 0, `${program}: absent ${family} remains an explicit usable template`);
    for (const hold of fallback) verifyFallback(hold, family, `${program}/${hold.id}`);
  }
}
if (process.argv.includes('--fixtures')) for (const program of ['diagonal_balance', 'opposing_sidepulls', 'roof_exit']) {
  const bundle = JSON.parse(fs.readFileSync(new URL(`../../fixtures/setting-${program}-bundle.json`, import.meta.url), 'utf8'));
  assert.equal(bundle.request.setting_design.hold_source, 'assets', `${program}: fresh asset example required`);
  const imported = bundle.request.scene.inventory.filter(hold => hold.asset_id);
  assert.ok(imported.length > 0, `${program}: has imported inventory`);
  assert.deepEqual(new Set(imported.map(hold => hold.type)), new Set(families), `${program}: registered external families browseable`);
  for (const family of missingFamilies) {
    const fallback = bundle.request.scene.inventory.filter(hold => hold.type === family);
    assert.ok(fallback.length > 0 && fallback.every(hold => !hold.asset_id && hold.asset_fallback_reason), `${program}: missing ${family} explicitly retained as template`);
  }
  for (const hold of imported) {
    const resolved = resolveHoldAsset(hold);
    assert.equal(resolved.kind, 'asset', `${program}/${hold.id}: reference and scale resolve`);
    for (const surface of hold.grip_surfaces) {
      const source = resolved.asset.grip_surfaces.find(item => item.id === surface.id);
      assert.ok(source, 'contact surface belongs to registered record');
      assert.deepEqual(surface.mesh_anchor, source.mesh_anchor, 'same immutable contact anchor');
      for (const key of ['normal', 'u_axis', 'v_axis', 'pull_direction']) surface[key].forEach((value, index) => assert.ok(Math.abs(value - source[key][index]) < 1e-7, `uniform scaling preserves ${key}`));
      for (const key of ['position', 'radii']) surface[key].forEach((value, index) => assert.ok(Math.abs(value - source[key][index] * resolved.scale) < 1e-7, `actual inventory ${key} follows rendered scale`));
    }
    fixtureAssetInstances++;
  }
}
console.log(JSON.stringify({ status: 'pass', scope: missingFamilies.length ? 'four external mesh families plus explicitly synthetic pocket' : 'five-family registry', missing_families: missingFamilies, assets: library.assets.length, models, surfaces, fixture_asset_instances: fixtureAssetInstances, current_inventories: Object.keys(currentInventories).length, explicit_template_fallbacks: explicitTemplateFallbacks, sampled_patch_vertices: sampledPatchVertices, max_vertex_error_m: maxVertexError, max_anchor_error_m: maxAnchorError, max_patch_error_m: maxPatchError, checks: ['registered mesh topology and uniform scale', 'real mesh contact anchors and ray picking', 'grip patches stay on source triangles', 'side and incut annotations do not project to outer shell', 'comparison geometry parity', 'missing, hash-mismatched and distorted assets omitted', 'stripped references with retained mesh markers cannot become templates', 'three fresh inventories bind current asset registry', 'missing pocket mesh is explicitly synthetic without external references or triangle anchors', ...(fixtureAssetInstances ? ['all three asset inventories bind geometry and grip annotations'] : [])], results }, null, 2));
