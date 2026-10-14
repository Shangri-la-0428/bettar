// Read-only acceptance: compare UI metrics/contact labels with every saved rule route.
// Run after scripts/run_own_routes_study.py has published the study.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { actualRouteMetrics, contactPresentation, ownRouteChoicesHTML, ownRouteDetailHTML, readOwnRouteBundle } from '../src/own-route-study.ts';

// Isolated batch-consistency regression; does not read or modify generated outputs.
const oldDigest = `sha256:${'a'.repeat(64)}`, newDigest = `sha256:${'b'.repeat(64)}`;
const oldRoute = { id: 'lateral-balance', bundle_digest: oldDigest };
const oldBundle = { manifest: { bundle_digest: oldDigest } }, newBundle = { manifest: { bundle_digest: newDigest } };
const emptyCache = new Map();
await assert.rejects(readOwnRouteBundle(oldRoute, emptyCache, async () => newBundle), /刷新页面.*整组规则线路/, 'old index cannot accept a newly published bundle');
assert.equal(emptyCache.size, 0, 'rejected bundle must not enter cache');
const mismatchedCache = new Map([[oldRoute.id, newBundle]]);
await assert.rejects(readOwnRouteBundle(oldRoute, mismatchedCache, async () => { throw new Error('cache should be used'); }), /同一批次/, 'cached bundle must pass the same batch check');
await assert.rejects(readOwnRouteBundle({ id: oldRoute.id }, new Map(), async () => oldBundle), /同一批次/, 'missing index digest cannot bypass batch checking');
assert.equal(await readOwnRouteBundle(oldRoute, emptyCache, async () => oldBundle), oldBundle, 'matching batch can be opened');
assert.equal(await readOwnRouteBundle(oldRoute, emptyCache, async () => { throw new Error('matching cache should be reused'); }), oldBundle, 'matching cached batch can be opened');
if (process.argv.includes('--integrity-only')) {
  console.log(JSON.stringify({ status: 'pass', batch_consistency: 'network, cache, missing digest, matching batch' }));
  process.exit(0);
}

const index = new URL('../../outputs/own-routes-study/study.json', import.meta.url);
const study = JSON.parse(fs.readFileSync(index, 'utf8'));
assert.equal(study.schema_version, 'own-routes-study-v1');
assert.equal(study.routes.length, 3);
const choices = ownRouteChoicesHTML(study, study.routes[0].id, false);
assert.equal((choices.match(/data-action="own-route"/g) || []).length, 3);
assert.equal((choices.match(/aria-pressed="true"/g) || []).length, 1);
let contacts = 0, standingContacts = 0, handToFootMoments = 0;
const routes = [];
for (const route of study.routes) {
  const raw = fs.readFileSync(new URL(route.bundle_file, index));
  const bundle = JSON.parse((route.bundle_file.endsWith('.gz') ? gunzipSync(raw) : raw).toString('utf8'));
  const candidate = bundle.candidates[0], evaluation = bundle.evaluations.find(item => item.candidate_id === candidate.id);
  const metrics = actualRouteMetrics(bundle, candidate, evaluation);
  assert.equal(metrics.handTransfers, route.metrics.hand_moves, `${route.id}: hand movements`);
  assert.equal(metrics.footTransfers, route.metrics.foot_moves, `${route.id}: foot movements`);
  assert.equal(metrics.used, route.metrics.used_hold_ids.length, `${route.id}: actually used hold count`);
  const uiHandToFoot = [...new Set(metrics.handToFoot.map(item => item.placementId))].sort();
  assert.deepEqual(uiHandToFoot, [...route.metrics.hand_then_foot_ids].sort(), `${route.id}: hand-to-foot proof`);
  for (const item of metrics.handToFoot) {
    assert.equal(candidate.states[item.stateIndex].contacts[item.limb].placement_id, item.placementId, 'jump link lands on actual contact');
    handToFootMoments++;
  }
  for (const state of candidate.states) for (const [limb, contact] of Object.entries(state.contacts)) {
    if (!contact) continue;
    const placement = candidate.placements.find(item => item.id === contact.placement_id);
    const hold = bundle.request.scene.inventory.find(item => item.id === placement.inventory_id);
    const display = contactPresentation(contact, limb, placement, hold);
    const selected = hold.grip_surfaces.find(item => item.id === (contact.contact_id === 'main' ? placement.contact_surface_id : contact.contact_id));
    if (selected) assert.equal(display.surfaceLabel, selected.label, `${route.id}/${state.id}/${limb}: concrete surface label`);
    if (limb.endsWith('F') && contact.contact_id !== 'main') {
      assert.ok(selected.limbs.includes(limb), 'foot label references an explicitly foot-compatible surface');
      assert.equal(display.action, '踩踏');
      standingContacts++;
    }
    contacts++;
  }
  const html = ownRouteDetailHTML(route, bundle, candidate, evaluation, false);
  const mislabeledStage = { ...route, completion: { ...route.completion, before: { ...route.completion.before, status: 'complete' } } };
  assert.ok(ownRouteDetailHTML(mislabeledStage, bundle, candidate, evaluation, false).includes('补全前预算内未找到完整走法'), 'stage label cannot overrule validated incomplete evidence');
  assert.ok(html.includes(route.label), 'actual route label shown');
  assert.ok(html.includes('几何通过不代表静态支撑全部通过'), 'geometric and mechanical checks remain distinct');
  assert.equal((html.match(/data-action="phase"/g) || []).length, metrics.handToFoot.length, 'every hand-to-foot moment is locatable');
  const stale = ownRouteDetailHTML(route, bundle, candidate, undefined, true);
  assert.ok(stale.includes('修订待检查') && stale.includes('待重算'), 'stale detail cannot show previous check status');
  routes.push({ id: route.id, movements: candidate.events.length, stepped_handholds: metrics.steppedHandholds, hand_to_foot: uiHandToFoot });
}
assert.ok(standingContacts > 0 && handToFootMoments > 0, 'saved examples exercise concrete foot surfaces and hand-to-foot transitions');
const escaped = ownRouteChoicesHTML({ ...study, routes: [{ ...study.routes[0], label: '<img onerror=alert(1)>', intent: '<script>unsafe</script>' }] }, '', false);
assert.ok(!escaped.includes('<img ') && !escaped.includes('<script>'), 'saved text is escaped');
console.log(JSON.stringify({ status: 'pass', routes, contacts, standing_contacts: standingContacts, hand_to_foot_moments: handToFootMoments }, null, 2));
