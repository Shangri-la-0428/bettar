// Shared UI region math and editing permissions, without constructing WebGL.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { gymEditableIds, gymPatchPoints, gymPlacementIssue, gymRegionPoints } from '../src/gym.ts';
import { panelFrame, transformPoint } from '../src/placement-geometry.ts';

const panels = [
  { id: 'lower', label: 'Lower', origin: [0, 0, 0], rotation_deg: [0, 0, 0], width: 3, height: 2 },
  { id: 'roof', label: 'Roof', origin: [0, 2, 0], rotation_deg: [90, 0, 0], width: 3, height: 1.2 },
  { id: 'exit', label: 'Exit', origin: [0, 2, 1.2], rotation_deg: [0, 0, 0], width: 3, height: 2 },
  { id: 'neighbour', label: 'Neighbour', origin: [4, 0, 0], rotation_deg: [25, -20, 0], width: 3, height: 4 },
];
const patches = panels.slice(0, 3).map(panel => ({ wall_panel_id: panel.id, u_min: -1.2, u_max: 1.2, v_min: .05, v_max: panel.height - .05 }));
const scene = { angle_deg: 0, width: 8, height: 4, margin: .05, inventory: [{ id: 'hold', width: .4, height: .2 }], wall_panels: panels };
const request = { scene, route_constraints: { installation_region: { patches, editable_placement_ids: ['editable'], fixed_placements: [] } } };
const gym = { scene, regions: [{ id: 'roof-exit', patches }] };
const snapshot = structuredClone({ request, gym });
const points = gymRegionPoints(gym, 'roof-exit');
assert.equal(points.length, 12, 'folded region includes all three physical faces');
assert.ok(points.some(point => point[2] > 1), 'region extends through roof depth');
assert.ok(points.some(point => point[1] > 3), 'region includes upper exit');
assert.ok(points.every(point => Math.abs(point[0]) <= 1.2), 'neighbour face is not part of selected region');
assert.deepEqual(gymPatchPoints(scene, patches[1], .006)[0], transformPoint(panelFrame(0, panels[1]), [-1.2, .05, .006]), 'outline follows the same transform as installed holds');
assert.deepEqual(gymPatchPoints(scene, { ...patches[0], wall_panel_id: 'missing' }), [], 'unknown face must not become a legacy wall');
assert.deepEqual(gymPatchPoints(scene, { ...patches[0], u_min: -9 }), [], 'invalid patch omitted instead of drawn outside panel');
assert.deepEqual(gymRegionPoints(gym, 'missing'), []);

const placement = { id: 'editable', inventory_id: 'hold', u: 0, v: 1, rotation_deg: 0, wall_panel_id: 'lower' };
assert.equal(gymPlacementIssue(request, placement), undefined);
assert.match(gymPlacementIssue(request, { ...placement, id: 'context-other' }), /周围岩点/);
assert.match(gymPlacementIssue(request, { ...placement, wall_panel_id: 'neighbour' }), /超出/);
assert.match(gymPlacementIssue(request, { ...placement, u: 1.05 }), /超出/, 'footprint edge, not just centre, obeys region');
assert.equal(gymPlacementIssue(request, { ...placement, u: 1.05, rotation_deg: 90 }), undefined, 'rotation uses actual rectangular footprint');
assert.match(gymPlacementIssue(request, { ...placement, mount: { parent_id: 'volume', face_id: 'front' } }), /直接安装/);
assert.equal(gymPlacementIssue({ scene }, placement), undefined, 'legacy requests retain existing editor behaviour');
assert.deepEqual([...gymEditableIds(request)], ['editable']);
assert.equal(gymEditableIds({ scene }), undefined, 'missing region is legacy, not empty permissions');
assert.equal(gymEditableIds({ scene, route_constraints: { installation_region: { editable_placement_ids: [] } } }).size, 0, 'preview allows no editable holds');
assert.deepEqual({ request, gym }, snapshot, 'display and editing checks do not modify scene or permissions');
const root = fileURLToPath(new URL('../../', import.meta.url));
const localPython = fileURLToPath(new URL('../../.venv/bin/python', import.meta.url));
const actual = JSON.parse(execFileSync(process.env.BETAR_PYTHON || (existsSync(localPython) ? localPython : 'python3'), ['-c', 'import json; from boulderlab.example_gym import gym_metadata; print(json.dumps(gym_metadata()))'], { cwd: root, encoding: 'utf8' }));
assert.equal(actual.scene.wall_panels.length, 6);
assert.equal(actual.regions.length, 3);
assert.equal(actual.preview.candidate.read_only, true, 'real first-open metadata is read-only');
assert.deepEqual(actual.preview.candidate.states, [], 'metadata does not invent a replay');
assert.deepEqual(actual.preview.request.scene.wall_panels, actual.scene.wall_panels, 'overview and local requests share the same wall');
for (const region of actual.regions) {
  assert.equal(gymRegionPoints(actual, region.id).length, region.patches.length * 4, `${region.id}: all declared patches fit their actual panel`);
}
assert.ok(gymRegionPoints(actual, 'overhang-bay').every(point => point[0] < -3));
assert.ok(gymRegionPoints(actual, 'corner-bay').every(point => point[0] > 2));
assert.equal(actual.regions.find(region => region.id === 'roof-exit').patches.length, 3, 'real roof region spans lower wall, roof and exit');
console.log(JSON.stringify({ status: 'pass', checks: ['folded panel coordinates', 'adjacent walls excluded from selection', 'malformed region does not fall back', 'editable ID allowlist', 'rotation-aware footprint boundaries', 'preview read-only', 'legacy preserved', 'no scene mutation', 'actual six-panel metadata and cross-roof region'] }));
