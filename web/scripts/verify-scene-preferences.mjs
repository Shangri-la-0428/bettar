import assert from 'node:assert/strict';
import fs from 'node:fs';
import { scenePalettes, getScenePalette, presentationHold } from '../src/scene-palette.ts';
import { createHoldModel, disposeObject } from '../src/hold-models.ts';
import { registerHoldAssetLibrary } from '../src/hold-assets.ts';

const registry = JSON.parse(fs.readFileSync(new URL('../../assets/holds/library.json', import.meta.url), 'utf8'));
registerHoldAssetLibrary(registry);
const bundle = JSON.parse(fs.readFileSync(new URL('../../fixtures/setting-diagonal_balance-bundle.json', import.meta.url), 'utf8'));
const original = JSON.stringify(bundle), signatures = [], checks = [];
const geometry = model => model.children.filter(object => object.userData.resin).map(object => ({ positions: Array.from(object.geometry.getAttribute('position').array), index: object.geometry.index ? Array.from(object.geometry.index.array) : null }));
for (const hold of bundle.request.scene.inventory) {
  const base = createHoldModel(hold), expected = geometry(base); disposeObject(base);
  for (const palette of scenePalettes) {
    const display = presentationHold(hold, palette);
    assert.notEqual(display, hold, 'presentation creates a view-only copy');
    assert.equal(display.color, `#${(hold.type === 'volume' ? palette.volume : palette.route).toString(16).padStart(6, '0')}`, 'hands and feet share route colour; volumes use coordinated colour');
    const model = createHoldModel(display);
    assert.deepEqual(geometry(model), expected, 'palette never changes vertices or topology');
    disposeObject(model); checks.push(`${hold.id}/${palette.id}`);
  }
  signatures.push(hold.id);
}
assert.equal(JSON.stringify(bundle), original, 'request, placements, evaluations and fingerprints stay byte-for-byte unchanged');
assert.equal(getScenePalette('not-a-palette'), scenePalettes[0], 'unknown saved preference has a deterministic fallback');
console.log(JSON.stringify({ status: 'pass', palettes: scenePalettes.length, inventory_instances: signatures.length, geometry_comparisons: checks.length, checks: ['view-only copy', 'one route colour across hand and foot types', 'coordinated volumes', 'identical vertices and topology', 'original bundle and calculation fingerprints unmodified', 'saved preference fallback'] }, null, 2));
