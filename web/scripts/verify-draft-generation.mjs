import assert from 'node:assert/strict';
import { draftSupportSummary, generateDraftBatch } from '../src/draft-generation.ts';

const brief = { wall_profile: 'roof', style: 'sustained', difficulty: 'hard' };
const response = input => ({
  id: `option-${input.variant}`, label: `方案 ${input.variant}`, status: 'complete',
  brief: { ...input }, geometry_digest: `geometry-${input.variant}`, sequence_digest: `sequence-${input.variant}`,
  bundle: { request: { generation_brief: { ...input } }, candidates: [{ id: `candidate-${input.variant}` }], evaluations: [] },
});

const calls = [], progress = [];
const entries = await generateDraftBatch(brief, 42, async input => {
  calls.push(input);
  if (input.variant === 1) throw new Error('服务暂不可用');
  const result = response(input);
  if (input.variant === 2) result.status = 'search_unresolved';
  return result;
}, items => progress.push(items.map(item => item.state)));
assert.deepEqual(calls, [0, 1, 2].map(variant => ({ ...brief, seed: 42, variant })));
assert.deepEqual(entries.map(item => item.state), ['ready', 'error', 'ready']);
assert.equal(entries[1].error, '服务暂不可用');
assert.equal(entries[1].result, undefined, 'failed generation must not substitute a saved draft');
assert.equal(entries[2].result.status, 'search_unresolved', 'a budget failure remains inspectable');
assert.ok(progress.some(items => items.join() === 'ready,running,waiting'));
assert.ok(progress.some(items => items.join() === 'ready,error,running'));

const mismatched = await generateDraftBatch(brief, 42, async input => {
  const result = response(input);
  result.bundle.request.generation_brief.wall_profile = 'overhang';
  return result;
}, () => {});
assert.ok(mismatched.every(item => item.state === 'error'), 'bundle provenance must match selected wall, style, difficulty and seed');

const gymBrief = { ...brief, gym_id: 'bettar-demo', region_id: 'roof-exit' };
const gymCalls = [];
const gymEntries = await generateDraftBatch(gymBrief, 42, async input => {
  gymCalls.push(input); return response(input);
}, () => {});
assert.equal(gymEntries.filter(item => item.state === 'ready').length, 3);
assert.ok(gymCalls.every(input => input.gym_id === gymBrief.gym_id && input.region_id === gymBrief.region_id));
const wrongRegion = await generateDraftBatch(gymBrief, 42, async input => {
  const result = response(input); result.bundle.request.generation_brief.region_id = 'overhang-bay'; return result;
}, () => {});
assert.ok(wrongRegion.every(item => item.state === 'error'), 'a plausible wall profile cannot conceal a different gym region');

const duplicates = await generateDraftBatch(brief, 42, async input => ({
  ...response(input), geometry_digest: 'same-wall-holds', sequence_digest: 'same-beta',
}), () => {});
assert.equal(duplicates[0].duplicateOf, undefined);
assert.equal(duplicates[1].duplicateOf, 0);
assert.equal(duplicates[2].duplicateOf, 0);
assert.notEqual(duplicates[0].result.bundle, duplicates[1].result.bundle, 'each option retains its own request and evaluation package');

const candidate = {
  states: ['start', 'release-1', 'land-1', 'release-2', 'land-2'].map(id => ({ id })),
  events: [{ release_state: 'release-1', to_state: 'land-1' }, { release_state: 'release-2', to_state: 'land-2' }],
  refinement: { after: { release_feasible: 99 } },
};
const checked = statuses => ({ mechanics_report: {
  summary: { status: 'feasible' },
  states: Object.entries(statuses).map(([state_id, status]) => ({ state_id, status })),
} });
const mixedSupport = draftSupportSummary(candidate, checked({ start: 'feasible', 'release-1': 'infeasible', 'land-1': 'infeasible', 'release-2': 'feasible', 'land-2': 'unknown' }));
assert.equal(mixedSupport.label, '支撑需调整');
assert.deepEqual(mixedSupport.release, { total: 2, feasible: 1, infeasible: 1, unknown: 0 });
assert.deepEqual(mixedSupport.landing, { total: 2, feasible: 0, infeasible: 1, unknown: 1 });
assert.equal(mixedSupport.firstIssueStateId, 'release-1');
assert.match(mixedSupport.detail, /换点 1 处，落点 1 处/);
assert.match(mixedSupport.detail, /1 处待确认/);
const partialSupport = draftSupportSummary(candidate, checked({ start: 'feasible', 'release-1': 'feasible', 'land-1': 'feasible' }));
assert.equal(partialSupport.label, '支撑待确认', 'missing states must not become a feasible support claim');
assert.equal(partialSupport.release.unknown, 1);
const missingSupport = draftSupportSummary(candidate);
assert.equal(missingSupport.label, '支撑待确认');
assert.equal(missingSupport.hasReport, false);
assert.equal(missingSupport.firstIssueStateId, undefined);
const feasibleSupport = draftSupportSummary(candidate, checked(Object.fromEntries(candidate.states.map(state => [state.id, 'feasible']))));
assert.equal(feasibleSupport.label, '待试攀');
assert.equal(feasibleSupport.release.feasible, 2, 'counts come from current mechanics states, never refinement metadata');
const unknownReport = checked(Object.fromEntries(candidate.states.map(state => [state.id, 'feasible'])));
unknownReport.mechanics_report.summary.status = 'unknown';
assert.equal(draftSupportSummary(candidate, unknownReport).label, '支撑待确认');
console.log(JSON.stringify({ status: 'pass', cases: ['three conditioned calls', 'partial failure continuation', 'unresolved retained', 'no saved fallback', 'request provenance mismatch', 'gym and region propagated and verified', 'duplicate identification', 'independent bundles', 'actual support counts', 'first support issue', 'partial and missing support unknown', 'generator metadata ignored'] }));
