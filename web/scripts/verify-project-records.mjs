// Exercise persistence races with controlled I/O, not timing-dependent sleeps.
import assert from 'node:assert/strict';
import { ProjectAutosave } from '../src/project-records.ts';

const snapshot = (name, notes = name) => ({
  name, gym_id: 'bettar-demo', gym_version: 'demo-gym-1', region_id: 'roof-exit',
  brief: { gym_id: 'bettar-demo', region_id: 'roof-exit', wall_profile: 'roof', style: 'balance', difficulty: 'medium' },
  entries: [{ variant: 0, state: 'waiting' }], selected_variant: null, notes, status: 'draft',
});
function harness() {
  const requests = [], changes = [];
  let inflight = 0, peak = 0;
  const save = new ProjectAutosave(value => {
    inflight++; peak = Math.max(peak, inflight);
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    requests.push({ value: structuredClone(value),
      resolve: (id = value.id || 'project-1', revision = (value.revision || 0) + 1) => {
        inflight--;
        resolve({ ...structuredClone(value), id, revision, created_at: '2026-10-15T00:00:00Z', updated_at: '2026-10-15T00:00:01Z', compatibility: { status: 'current', messages: [] } });
      },
      reject: error => { inflight--; reject(error); },
    });
    return promise;
  }, (state, record) => changes.push({ state, id: record?.id, revision: record?.revision }));
  return { save, requests, changes, peak: () => peak };
}
const tick = async () => { await Promise.resolve(); await Promise.resolve(); };

// Coalescing and defensive copies before the first request.
const first = harness();
first.save.schedule(snapshot('superseded'));
const original = snapshot('latest');
first.save.schedule(original);
original.notes = 'mutated after scheduling'; original.entries[0].state = 'error';
assert.throws(() => first.save.reset({ id: 'another-task', revision: 9 }), /尚未保存/);
const firstFlush = first.save.flush();
assert.equal(first.requests.length, 1);
assert.equal(first.requests[0].value.name, 'latest');
assert.equal(first.requests[0].value.notes, 'latest');
assert.equal(first.requests[0].value.entries[0].state, 'waiting');
assert.equal(first.requests[0].value.id, undefined);

// An edit during a slow save must follow it with the server's returned revision.
first.save.schedule(snapshot('middle'));
first.save.schedule(snapshot('newest'));
const joinedFlush = first.save.flush();
assert.equal(first.requests.length, 1, 'concurrent flush joins existing write');
assert.throws(() => first.save.reset(), /尚未保存/, 'cannot cross task identity during a write');
first.requests[0].resolve('project-1', 1);
await tick();
assert.equal(first.requests.length, 2);
assert.equal(first.requests[1].value.name, 'newest');
assert.equal(first.requests[1].value.id, 'project-1');
assert.equal(first.requests[1].value.revision, 1);
first.requests[1].resolve('project-1', 2);
assert.deepEqual(await Promise.all([firstFlush, joinedFlush]), [true, true]);
assert.equal(first.peak(), 1, 'writes stay serial');
assert.equal(first.save.dirty, false); assert.equal(first.save.state, 'saved');
assert.deepEqual(first.changes.filter(change => change.id).map(change => change.revision), [1, 2]);
assert.equal(await first.save.flush(), true, 'clean flush does not create a write');
assert.equal(first.requests.length, 2);

// A completed task can be switched, and its former ID never leaks to the next.
first.save.reset({ id: 'project-2', revision: 7 });
first.save.schedule(snapshot('different task'));
const otherFlush = first.save.flush();
assert.equal(first.requests[2].value.id, 'project-2');
assert.equal(first.requests[2].value.revision, 7);
first.requests[2].resolve('project-2', 8); assert.equal(await otherFlush, true);
first.save.reset(); first.save.schedule(snapshot('new task'));
const freshFlush = first.save.flush();
assert.equal(first.requests[3].value.id, undefined);
assert.equal(first.requests[3].value.revision, undefined);
first.requests[3].resolve('project-3', 1); assert.equal(await freshFlush, true);

// A rejected save retains the NEWER edit, not the request that just failed.
const failed = harness(); failed.save.reset({ id: 'existing', revision: 4 });
failed.save.schedule(snapshot('older in flight'));
const failureFlush = failed.save.flush();
failed.save.schedule(snapshot('latest unsaved'));
const failureJoined = failed.save.flush();
failed.requests[0].reject(new Error('local service unavailable'));
assert.deepEqual(await Promise.all([failureFlush, failureJoined]), [false, false]);
assert.equal(failed.save.state, 'error'); assert.equal(failed.save.dirty, true);
assert.equal(failed.save.error, 'local service unavailable');
assert.throws(() => failed.save.reset({ id: 'unsafe-switch', revision: 1 }), /尚未保存/);
const retry = failed.save.flush();
assert.equal(failed.requests[1].value.name, 'latest unsaved');
assert.equal(failed.requests[1].value.id, 'existing');
assert.equal(failed.requests[1].value.revision, 4, 'a failed request cannot advance local revision');
failed.requests[1].resolve('existing', 5);
assert.equal(await retry, true); assert.equal(failed.save.dirty, false); assert.equal(failed.save.state, 'saved');
assert.equal(failed.peak(), 1);

// With no later edit, retry preserves the original snapshot exactly.
const lone = harness(); lone.save.schedule(snapshot('only unsaved edit'));
const loneFailure = lone.save.flush(); lone.requests[0].reject(new Error('disk full'));
assert.equal(await loneFailure, false);
const loneRetry = lone.save.flush();
assert.deepEqual(lone.requests[1].value, lone.requests[0].value);
lone.requests[1].resolve(); assert.equal(await loneRetry, true);

// A version conflict can be escaped without overwriting the original record.
const conflict = harness(); conflict.save.reset({ id: 'original', revision: 4 });
await assert.rejects(conflict.save.saveCopy(), /没有待另存/, 'no empty or implicit duplicate');
conflict.save.schedule(snapshot('conflicting edit'));
const conflictFlush = conflict.save.flush();
await assert.rejects(conflict.save.saveCopy(), /正在保存/, 'cannot change identity while original write is in flight');
assert.equal(conflict.requests.length, 1);
conflict.requests[0].reject(new Error('revision conflict'));
assert.equal(await conflictFlush, false);
const copyFlush = conflict.save.saveCopy();
assert.equal(conflict.requests[1].value.id, undefined);
assert.equal(conflict.requests[1].value.revision, undefined);
assert.equal(conflict.requests[1].value.name, 'conflicting edit');
await assert.rejects(conflict.save.saveCopy(), /正在保存/, 'second copy click cannot create another concurrent copy');
conflict.save.schedule(snapshot('edited while copy saves'));
const copyJoined = conflict.save.flush();
conflict.requests[1].resolve('copy-1', 1); await tick();
assert.equal(conflict.requests[2].value.id, 'copy-1');
assert.equal(conflict.requests[2].value.revision, 1);
assert.equal(conflict.requests[2].value.name, 'edited while copy saves');
conflict.requests[2].resolve('copy-1', 2);
assert.deepEqual(await Promise.all([copyFlush, copyJoined]), [true, true]);
assert.equal(conflict.save.error, ''); assert.equal(conflict.save.state, 'saved');
assert.equal(conflict.save.dirty, false); assert.equal(conflict.peak(), 1);
assert.deepEqual(conflict.requests.filter(item => item.value.id === 'original').map(item => item.value.name), ['conflicting edit'], 'only the originally rejected write names the old record');
conflict.save.reset({ id: 'next-task', revision: 3 });
conflict.save.schedule(snapshot('after copy'));
const postCopy = conflict.save.flush();
assert.equal(conflict.requests[3].value.id, 'next-task'); conflict.requests[3].resolve('next-task', 4); await postCopy;

// A failed copy keeps the latest edit and the copy destination across retries.
const copyFailure = harness(); copyFailure.save.reset({ id: 'untouched', revision: 6 });
copyFailure.save.schedule({ ...snapshot('copy first edit'), id: 'untouched', revision: 6 });
const failedCopy = copyFailure.save.saveCopy();
assert.equal(copyFailure.requests[0].value.id, undefined, 'record-shaped snapshot cannot inject an ID into a copy');
assert.equal(copyFailure.requests[0].value.revision, undefined);
copyFailure.save.schedule(snapshot('copy newest edit'));
const failedCopyJoined = copyFailure.save.flush();
copyFailure.requests[0].reject(new Error('disk unavailable'));
assert.deepEqual(await Promise.all([failedCopy, failedCopyJoined]), [false, false]);
assert.equal(copyFailure.save.state, 'error'); assert.equal(copyFailure.save.dirty, true);
assert.throws(() => copyFailure.save.reset(), /尚未保存/);
const copiedRetry = copyFailure.save.flush();
assert.equal(copyFailure.requests[1].value.name, 'copy newest edit');
assert.equal(copyFailure.requests[1].value.id, undefined, 'normal retry retains copy intent');
assert.equal(copyFailure.requests[1].value.revision, undefined);
copyFailure.requests[1].resolve('recovered-copy', 1);
assert.equal(await copiedRetry, true); assert.equal(copyFailure.save.dirty, false);
assert.equal(copyFailure.requests.some(item => item.value.id === 'untouched'), false, 'no copy attempt writes the original record');
assert.equal(copyFailure.peak(), 1);

console.log(JSON.stringify({ status: 'pass', checks: ['coalesced snapshots', 'defensive copy', 'serial writes', 'mid-save edits retained', 'returned revision chaining', 'concurrent flush', 'failed save keeps latest pending', 'retry recovery', 'pending/running identity reset blocked', 'new task clears former identity', 'conflict save-copy omits original identity', 'copy chains newer edits onto new record', 'copy failure retains latest edit and new-record intent', 'inflight copy and empty copy rejected'] }));
