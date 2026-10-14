// Verify declared catalog surfaces against the actual rendered triangles, without WebGL.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as THREE from 'three';
import { createHoldModel, createGripOverlay, sampleHoldSurface, disposeObject } from '../src/hold-models.ts';

const templates = JSON.parse(fs.readFileSync(new URL('../../fixtures/catalog-templates.json', import.meta.url), 'utf8'));
assert.equal(new Set(templates.map(item => item.type)).size, 9, 'catalog covers nine templates with canonical grip families');
const results = [];
for (const template of templates) {
  const main = template.grip_surfaces[0];
  const hold = { ...template, id: `${template.template_id}-instance-a`, contact: { id: main.id, position: main.position, radius: Math.min(...main.radii), limbs: main.limbs } };
  const model = createHoldModel(hold, { id: 'placement-a' }), resin = model.children.find(item => item.userData.resin);
  model.updateMatrixWorld(true);
  const clone = createHoldModel({ ...hold, id: `${template.template_id}-instance-b` });
  const twin = clone.children.find(item => item.userData.resin);
  for (const name of ['position', 'normal', 'uv']) assert.deepEqual(resin.geometry.attributes[name].array, twin.geometry.attributes[name].array, `${hold.type}: same template, different instance, identical ${name}`);
  assert.equal(resin.material.color.getHex(), twin.material.color.getHex(), `${hold.type}: consistent template color`);
  const bounds = new THREE.Box3().setFromObject(model), tolerance = 1e-6;
  assert.ok(bounds.min.x >= -hold.width / 2 - tolerance && bounds.max.x <= hold.width / 2 + tolerance, `${hold.type}: patch width envelope`);
  assert.ok(bounds.min.y >= -hold.height / 2 - tolerance && bounds.max.y <= hold.height / 2 + tolerance, `${hold.type}: patch height envelope`);
  assert.ok(bounds.min.z >= -tolerance && bounds.max.z <= hold.depth + tolerance, `${hold.type}: patch depth envelope`);
  const invalid = createGripOverlay(hold, 'does-not-exist', { all: true });
  assert.equal(invalid.userData.selectedSurfaceId, null, `${hold.type}: invalid selection has no substitute`);
  assert.ok(invalid.children.filter(item => item.userData.gripSurface).every(item => !item.userData.selected), `${hold.type}: invalid selection highlights no patch`);
  disposeObject(invalid);
  const empty = createGripOverlay({ ...hold, grip_surfaces: [] });
  assert.equal(empty.children.length, 0, `${hold.type}: empty declaration shows no invented region`); disposeObject(empty);
  for (const surface of hold.grip_surfaces) {
    const center = sampleHoldSurface(hold, surface.position[0], surface.position[1]);
    assert.ok(center, `${hold.type}/${surface.id}: declared contact lies on model`);
    const centerError = center.position.distanceTo(new THREE.Vector3(...surface.position));
    assert.ok(centerError < .001, `${hold.type}/${surface.id}: declared center differs from display surface by ${centerError} m`);
    const declaredNormal = new THREE.Vector3(...surface.normal);
    assert.ok(center.normal.dot(declaredNormal) > .99, `${hold.type}/${surface.id}: declared normal agrees with rendered normal`);
    const overlay = createGripOverlay(hold, surface.id, { id: 'placement-a', all: false, arrows: false }); overlay.updateMatrixWorld(true);
    const patch = overlay.children.find(item => item.userData.gripSurface);
    assert.ok(patch?.geometry.attributes.position.count > 0, `${hold.type}/${surface.id}: nonempty clipped patch`);
    assert.equal(patch.userData.id, 'placement-a'); assert.equal(patch.userData.surfaceId, surface.id);
    const p = patch.geometry.getAttribute('position'), u = new THREE.Vector3(...surface.u_axis), v = new THREE.Vector3(...surface.v_axis);
    const origin = new THREE.Vector3(...surface.position), ray = new THREE.Raycaster(), direction = new THREE.Vector3(0, 0, -1);
    let maxSurfaceError = 0;
    for (const attribute of Object.values(patch.geometry.attributes)) assert.ok(Array.from(attribute.array).every(Number.isFinite), `${hold.type}/${surface.id}: finite patch geometry`);
    for (let i = 0; i < p.count; i++) {
      const point = new THREE.Vector3().fromBufferAttribute(p, i), relative = point.clone().sub(origin);
      assert.ok((relative.dot(u) / surface.radii[0]) ** 2 + (relative.dot(v) / surface.radii[1]) ** 2 <= 1.00001, `${hold.type}/${surface.id}: patch stays within declared ellipse`);
      ray.set(new THREE.Vector3(point.x, point.y, hold.depth + 1), direction);
      const hit = ray.intersectObject(resin)[0];
      assert.ok(hit, `${hold.type}/${surface.id}: clipped vertex remains within model silhouette`);
      const error = hit.point.distanceTo(point); maxSurfaceError = Math.max(maxSurfaceError, error);
      assert.ok(error < 2e-6, `${hold.type}/${surface.id}: patch must remain on source mesh; error ${error} m`);
    }
    ray.set(new THREE.Vector3(center.position.x, center.position.y, hold.depth + 1), direction);
    assert.equal(ray.intersectObject(patch)[0]?.object.userData.surfaceId, surface.id, `${hold.type}/${surface.id}: region can be picked at declared contact`);
    const annotated = createGripOverlay(hold, surface.id, { all: true });
    const arrows = annotated.children.filter(item => item.userData.annotation && item.userData.surfaceId === surface.id);
    assert.deepEqual(arrows.map(item => item.userData.annotation).sort(), ['normal', 'pull']);
    for (const arrow of arrows) {
      const expected = new THREE.Vector3(...(arrow.userData.annotation === 'normal' ? surface.normal : surface.pull_direction)).normalize();
      assert.ok(new THREE.Vector3(0, 1, 0).applyQuaternion(arrow.quaternion).dot(expected) > .999999, `${hold.type}/${surface.id}: ${arrow.userData.annotation} arrow follows its own declared vector`);
    }
    results.push({ family: hold.type, surface: surface.id, vertices: p.count, center_error_m: centerError, max_patch_error_m: maxSurfaceError });
    disposeObject(overlay); disposeObject(annotated);
  }
  for (const face of hold.mounting_faces ?? []) {
    const center = sampleHoldSurface(hold, face.origin[0], face.origin[1]);
    assert.ok(center.position.distanceTo(new THREE.Vector3(...face.origin)) < 2e-7, `${face.id}: mount origin matches actual volume face`);
    assert.ok(center.normal.dot(new THREE.Vector3(...face.normal)) > .999999, `${face.id}: mount normal matches actual volume face`);
    const vertices = resin.geometry.getAttribute('position');
    for (const [u, v] of face.polygon) {
      const corner = new THREE.Vector3(...face.origin).addScaledVector(new THREE.Vector3(...face.u_axis), u).addScaledVector(new THREE.Vector3(...face.v_axis), v);
      let closest = Infinity;
      for (let i = 0; i < vertices.count; i++) closest = Math.min(closest, corner.distanceTo(new THREE.Vector3().fromBufferAttribute(vertices, i)));
      assert.ok(closest < 2e-7, `${face.id}: mounting polygon corner matches volume mesh vertex`);
    }
  }
  disposeObject(model); disposeObject(clone);
}
console.log(JSON.stringify({ status: 'pass', templates: templates.length, surfaces: results.length, checks: ['same-template geometry', 'surface center and normal alignment', 'all patch vertices on actual triangles', 'patches clipped to silhouette and declared ellipse', 'surface picking', 'separate normal and pull arrows', 'invalid and empty selections', 'volume mounting faces match display mesh'], results }, null, 2));
