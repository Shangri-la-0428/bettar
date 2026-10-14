import type { Candidate } from './types';

export interface TimelineNavigation {
  step: number;
  eventIndex: number | null;
  phase: 'start' | 'release' | 'landing' | 'other';
  previous: number | null;
  next: number | null;
  release: number | null;
  landing: number | null;
}

/** All returned positions refer to states, never arithmetic event/state offsets. */
export function timelineNavigation(candidate: Pick<Candidate, 'states' | 'events'>, requestedStep: number): TimelineNavigation {
  const { states, events } = candidate;
  const step = Number.isInteger(requestedStep) && requestedStep >= 0 && requestedStep < states.length ? requestedStep : 0;
  const result: TimelineNavigation = { step, eventIndex: null, phase: step === 0 ? 'start' : 'other', previous: null, next: null, release: null, landing: null };
  if (!states.length || !events.length) return { ...result, step: 0, phase: 'start' };

  // Duplicate IDs cannot identify one unambiguous scene state.
  const stateIndex = new Map<string, number>();
  states.forEach((state, index) => stateIndex.set(state.id, stateIndex.has(state.id) ? -1 : index));
  const resolved = events.map(event => {
    const from = stateIndex.get(event.from_state), release = stateIndex.get(event.release_state), landing = stateIndex.get(event.to_state);
    if (from === undefined || release === undefined || landing === undefined || from < 0 || release < 0 || landing < 0 || new Set([from, release, landing]).size !== 3) return null;
    return { from, release, landing };
  });

  if (step === 0) {
    const first = resolved[0];
    if (first?.from === step) result.next = first.landing;
    return result;
  }

  let index = resolved.findIndex(event => event?.release === step);
  if (index >= 0) {
    const event = resolved[index]!;
    return { ...result, eventIndex: index, phase: 'release', previous: event.from, next: event.landing, release: event.release, landing: event.landing };
  }

  index = resolved.findIndex(event => event?.landing === step);
  if (index >= 0) {
    const event = resolved[index]!, following = resolved[index + 1];
    return { ...result, eventIndex: index, phase: 'landing', previous: event.from, next: following?.from === step ? following.landing : null, release: event.release, landing: event.landing };
  }

  // A located from-state can still enter its event; never guess a previous one.
  index = resolved.findIndex(event => event?.from === step);
  if (index >= 0) {
    const event = resolved[index]!;
    return { ...result, eventIndex: index, next: event.landing, release: event.release, landing: event.landing };
  }
  return result;
}
