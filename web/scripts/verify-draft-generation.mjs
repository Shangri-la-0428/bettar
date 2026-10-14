import assert from 'node:assert/strict';
import { generateDraftBatch } from '../src/draft-generation.ts';

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

const duplicates = await generateDraftBatch(brief, 42, async input => ({
  ...response(input), geometry_digest: 'same-wall-holds', sequence_digest: 'same-beta',
}), () => {});
assert.equal(duplicates[0].duplicateOf, undefined);
assert.equal(duplicates[1].duplicateOf, 0);
assert.equal(duplicates[2].duplicateOf, 0);
assert.notEqual(duplicates[0].result.bundle, duplicates[1].result.bundle, 'each option retains its own request and evaluation package');
console.log(JSON.stringify({ status: 'pass', cases: ['three conditioned calls', 'partial failure continuation', 'unresolved retained', 'no saved fallback', 'request provenance mismatch', 'duplicate identification', 'independent bundles'] }));
