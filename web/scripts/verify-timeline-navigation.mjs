import assert from 'node:assert/strict';
import { timelineNavigation } from '../src/timeline-navigation.ts';

// States deliberately do not follow event order, and include an unrelated state.
const route = {
  states: ['start', 'release-2', 'unused', 'land-1', 'land-2', 'release-1'].map(id => ({ id })),
  events: [
    { limb: 'LH', from_state: 'start', release_state: 'release-1', to_state: 'land-1' },
    { limb: 'RF', from_state: 'land-1', release_state: 'release-2', to_state: 'land-2' },
  ],
};
const navigation = step => timelineNavigation(route, step);
assert.deepEqual(navigation(0), { step: 0, eventIndex: null, phase: 'start', previous: null, next: 3, release: null, landing: null });
assert.deepEqual(navigation(3), { step: 3, eventIndex: 0, phase: 'landing', previous: 0, next: 4, release: 5, landing: 3 });
assert.deepEqual(navigation(5), { step: 5, eventIndex: 0, phase: 'release', previous: 0, next: 3, release: 5, landing: 3 });
assert.deepEqual(navigation(1), { step: 1, eventIndex: 1, phase: 'release', previous: 3, next: 4, release: 1, landing: 4 });
assert.equal(navigation(4).previous, 3);
assert.equal(navigation(4).next, null);
assert.equal(navigation(2).eventIndex, null);
assert.equal(navigation(2).next, null, 'unrelated state cannot invent an action');
for (const input of [-1, 99, NaN, 1.5]) assert.deepEqual(navigation(input), navigation(0), 'invalid step returns to start');

const invalid = structuredClone(route);
invalid.events[1].release_state = 'missing';
assert.equal(timelineNavigation(invalid, 3).next, null, 'missing adjacent event does not get skipped');
assert.equal(timelineNavigation(invalid, 1).next, null, 'malformed event cannot expose a release jump');
invalid.events[1] = { ...route.events[1], from_state: 'unused' };
assert.equal(timelineNavigation(invalid, 3).next, null, 'broken event chain is not followed');
assert.equal(timelineNavigation(invalid, 2).next, 4, 'explicit from-state resolves by ID');
invalid.events[0].to_state = 'start';
assert.equal(timelineNavigation(invalid, 0).next, null, 'self-loop event is rejected');

const duplicate = structuredClone(route);
duplicate.states.push({ id: 'land-1' });
assert.equal(timelineNavigation(duplicate, 0).next, null, 'ambiguous state IDs cannot be jumped to');
for (const candidate of [{ states: [], events: [] }, { states: [{ id: 'start' }], events: [] }]) {
  assert.deepEqual(timelineNavigation(candidate, 99), { step: 0, eventIndex: null, phase: 'start', previous: null, next: null, release: null, landing: null });
}
assert.equal(timelineNavigation({ states: route.states, events: [] }, 3).step, 0, 'a layout without events returns to its start');
console.log(JSON.stringify({ status: 'pass', cases: 'event endpoints, release substates, unordered states, unknown states, invalid steps/events, broken chains, duplicate IDs, empty layout' }));
