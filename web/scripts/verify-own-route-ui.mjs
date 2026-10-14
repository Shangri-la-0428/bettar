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
assert.ok(!choices.includes('<table') && !choices.includes('<small') && !choices.includes('own-route-number'), 'route switching has no statistics, descriptions, or decorative numbering');
for (const route of study.routes) {
  assert.ok(choices.includes(route.label), 'route switch keeps the actual route name');
  assert.ok(!choices.includes(route.intent), 'route intent belongs in optional details');
}
assert.equal((ownRouteChoicesHTML(study, '', true).match(/disabled/g) || []).length, 3, 'busy state disables every route switch');
const failedChoices = ownRouteChoicesHTML(undefined, '', false, '读取失败');
assert.ok(failedChoices.includes('读取失败') && failedChoices.includes('data-action="own-route-reload"'), 'loading errors retain an actionable retry');
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
  const html = ownRouteDetailHTML(route, bundle, candidate, evaluation, false, study);
  const disclosure = html.indexOf('<details class="own-route-disclosure">');
  assert.ok(disclosure > 0 && !html.includes('<details class="own-route-disclosure" open'), 'advanced route information is collapsed by default');
  assert.equal((html.match(/<details /g) || []).length, 1, 'route details do not create nested accordions');
  const compact = html.slice(0, disclosure);
  assert.ok(compact.includes(route.label) && compact.includes(`移手 ${metrics.handTransfers} · 换脚 ${metrics.footTransfers}`), 'compact summary shows the actual route and movement count');
  assert.ok(!compact.includes(route.intent) && !compact.includes('<table') && !compact.includes('data-action="phase"'), 'long copy, statistics, and contact navigation are optional');
  assert.ok(compact.includes('支撑需调整'), 'known support gaps remain visible without opening details');
  assert.ok(html.indexOf('<table') > disclosure && html.includes('三条线路对照'), 'the full comparison remains reachable inside route details');
  const mislabeledStage = { ...route, completion: { ...route.completion, before: { ...route.completion.before, status: 'complete' } } };
  assert.ok(ownRouteDetailHTML(mislabeledStage, bundle, candidate, evaluation, false).includes('补全前预算内未找到完整走法'), 'stage label cannot overrule validated incomplete evidence');
  assert.ok(html.includes(route.label), 'actual route label shown');
  assert.ok(html.includes('几何通过不代表静态支撑全部通过'), 'geometric and mechanical checks remain distinct');
  assert.equal((html.match(/data-action="phase"/g) || []).length, metrics.handToFoot.length, 'every hand-to-foot moment is locatable');
  const stale = ownRouteDetailHTML(route, bundle, candidate, undefined, true);
  assert.ok(stale.slice(0, stale.indexOf('<details')).includes('修改后待检查') && stale.includes('待重算') && !stale.includes('支撑需调整'), 'stale detail cannot show previous check status');
  const incomplete = ownRouteDetailHTML(route, bundle, { ...candidate, layout_report: {} }, evaluation, false);
  assert.ok(incomplete.slice(0, incomplete.indexOf('<details')).includes('预算内未找到完整走法'), 'incomplete search remains visible without opening details');
  const geometryFailed = ownRouteDetailHTML(route, bundle, candidate, { ...evaluation, summary: { ...evaluation.summary, status: 'fail' } }, false);
  assert.ok(geometryFailed.slice(0, geometryFailed.indexOf('<details')).includes('几何需调整'), 'failed geometric checks remain visible without opening details');
  const unchecked = ownRouteDetailHTML(route, bundle, candidate, undefined, false);
  assert.ok(unchecked.slice(0, unchecked.indexOf('<details')).includes('待检查'), 'missing checks are not labeled ready for climbing');
  const unknown = ownRouteDetailHTML(route, bundle, candidate, { ...evaluation, mechanics_report: { ...evaluation.mechanics_report, summary: { ...evaluation.mechanics_report.summary, status: 'unknown' } } }, false);
  assert.ok(unknown.slice(0, unknown.indexOf('<details')).includes('支撑待核查'), 'unknown mechanics are not labeled passed');
  const escapedDetail = ownRouteDetailHTML({ ...route, intent: '<script>unsafe</script>' }, bundle, candidate, evaluation, false);
  assert.ok(!escapedDetail.includes('<script>') && escapedDetail.includes('&lt;script&gt;'), 'optional route description is escaped');
  routes.push({ id: route.id, movements: candidate.events.length, stepped_handholds: metrics.steppedHandholds, hand_to_foot: uiHandToFoot });
}
assert.ok(standingContacts > 0 && handToFootMoments > 0, 'saved examples exercise concrete foot surfaces and hand-to-foot transitions');
const escaped = ownRouteChoicesHTML({ ...study, routes: [{ ...study.routes[0], label: '<img onerror=alert(1)>', intent: '<script>unsafe</script>' }] }, '', false);
assert.ok(!escaped.includes('<img ') && !escaped.includes('<script>'), 'saved text is escaped');
console.log(JSON.stringify({ status: 'pass', routes, contacts, standing_contacts: standingContacts, hand_to_foot_moments: handToFootMoments }, null, 2));
