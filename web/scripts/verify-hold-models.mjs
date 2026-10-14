// Runs against the real display geometry; no WebGL, browser, or fixture re-solving.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as THREE from 'three';
import { createHoldModel, sampleHoldSurface, disposeObject } from '../src/hold-models.ts';

const fixture = JSON.parse(fs.readFileSync(new URL('../../fixtures/default-request.json', import.meta.url), 'utf8'));
const synthetic = (type, width, height, depth, color = '#3762b8') => ({
  id: `verification-${type}`, type, width, height, depth, color,
  contact: { id: 'main', position: [0, 0, depth], radius: .018, limbs: ['LH', 'RH'] },
});
const competition = [
  synthetic('sloper', .55, .43, .22), synthetic('pinch', .19, .48, .15, '#e37c43'),
  synthetic('rail', .64, .14, .09), synthetic('volume', .88, .72, .31, '#515861'),
];
const templates = JSON.parse(fs.readFileSync(new URL('../../fixtures/catalog-templates.json', import.meta.url), 'utf8'));
const newFamilies = templates.filter(item => ['crimp', 'pocket'].includes(item.type)).map(item => {
  const main = item.grip_surfaces[0];
  return { ...item, id: `verification-${item.type}`, contact: { id: 'main', position: main.position, radius: Math.min(...main.radii), limbs: main.limbs } };
});
const results = [];
for (const hold of [...fixture.scene.inventory, ...competition, ...newFamilies]) {
  const model = createHoldModel(hold, { id: 'test-placement' });
  model.updateMatrixWorld(true);
  const bounds = new THREE.Box3().setFromObject(model);
  const tolerance = 1e-6;
  assert.ok(bounds.min.x >= -hold.width / 2 - tolerance && bounds.max.x <= hold.width / 2 + tolerance, `${hold.id}: width`);
  assert.ok(bounds.min.y >= -hold.height / 2 - tolerance && bounds.max.y <= hold.height / 2 + tolerance, `${hold.id}: height`);
  assert.ok(bounds.min.z >= -tolerance && bounds.max.z <= hold.depth + tolerance, `${hold.id}: depth`);
  let triangles = 0;
  model.traverse(object => {
    if (object.userData.fasteningRadius) assert.ok(object.userData.fasteningRadius <= .0075, `${hold.id}: metric fastening scale`);
    if (!object.isMesh) return;
    assert.equal(object.userData.id, 'test-placement', `${hold.id}: child picking ID`);
    for (const attribute of Object.values(object.geometry.attributes)) {
      assert.ok(Array.from(attribute.array).every(Number.isFinite), `${hold.id}: finite geometry`);
    }
    if (object.geometry.index) {
      assert.ok(Array.from(object.geometry.index.array).every(index => index < object.geometry.attributes.position.count), `${hold.id}: valid vertex indices`);
    }
    triangles += (object.geometry.index?.count || object.geometry.attributes.position.count) / 3;
  });
  const origin = new THREE.Vector3(...hold.contact.position).add(new THREE.Vector3(0, 0, .5));
  const ray = new THREE.Raycaster(origin, new THREE.Vector3(0, 0, -1));
  const hit = ray.intersectObject(model, true).find(entry => entry.object.userData.resin);
  assert.ok(hit, `${hold.id}: contact ray hits resin`);
  assert.equal(hit.object.userData.id, 'test-placement', `${hold.id}: ray picking ID`);
  assert.ok(hit.point.distanceTo(new THREE.Vector3(...hold.contact.position)) < .001, `${hold.id}: display surface matches default contact within 1 mm`);
  const second = createHoldModel(hold);
  const vertices = root => {
    const arrays = [];
    root.traverse(object => { if (object.isMesh && object.userData.resin) arrays.push(Array.from(object.geometry.attributes.position.array)); });
    return arrays;
  };
  assert.deepEqual(vertices(model), vertices(second), `${hold.id}: deterministic geometry`);
  const ghost = createHoldModel(hold, { id: 'ghost-placement', ghost: true });
  assert.deepEqual(vertices(model), vertices(ghost), `${hold.id}: comparison uses same resin form`);
  if (hold.color) assert.equal(model.children[0].material.color.getHexString(), hold.color.slice(1).toLowerCase(), `${hold.id}: explicit route color`);
  results.push({ id: hold.id, type: hold.type, triangles, contact_error_m: hit.point.distanceTo(new THREE.Vector3(...hold.contact.position)) });
  disposeObject(model); disposeObject(second); disposeObject(ghost);
}
// Test the recessed pocket and low-profile edge against actual triangles.
const pocket = newFamilies.find(item => item.type === 'pocket');
const floor = sampleHoldSurface(pocket, 0, pocket.height * .06);
const rim = sampleHoldSurface(pocket, 0, pocket.height * .32);
assert.ok(floor && rim && rim.position.z - floor.position.z > pocket.depth * .45, 'pocket has a recessed well, not a painted circle');
const crimp = newFamilies.find(item => item.type === 'crimp');
const lip = sampleHoldSurface(crimp, 0, crimp.height * .05);
const shoulder = sampleHoldSurface(crimp, 0, crimp.height * .30);
assert.ok(lip && shoulder && lip.position.z - shoulder.position.z > .015, 'crimp has a narrow positive edge');
// At equal dimensions the new families still have different silhouettes, not just scale changes.
const silhouettes = competition.map(hold => {
  const model = createHoldModel(synthetic(hold.type, .5, .5, .2), { ghost: true });
  model.updateMatrixWorld(true);
  const ray = new THREE.Raycaster(), direction = new THREE.Vector3(0, 0, -1);
  let signature = '';
  for (let y = -10; y <= 10; y++) for (let x = -10; x <= 10; x++) {
    ray.set(new THREE.Vector3(x * .024, y * .024, .5), direction);
    signature += ray.intersectObject(model, true).length ? '1' : '0';
  }
  disposeObject(model); return signature;
});
assert.equal(new Set(silhouettes).size, competition.length, 'all competition families have distinct silhouettes at equal dimensions');
console.log(JSON.stringify({ status: 'pass', holds: results.length, checks: ['declared envelope', 'finite geometry', 'picking IDs', 'default contact alignment', 'deterministic geometry', 'comparison geometry parity', 'explicit route colors', 'metric fastenings', 'distinct competition silhouettes', 'pocket recessed geometry', 'crimp narrow edge'], results }, null, 2));
