import type { Bundle, Candidate, Evaluation, MechanicsStatus } from './types';

export function draftSupportSummary(candidate: Candidate, evaluation?: Evaluation) {
  const report = evaluation?.mechanics_report;
  const results = new Map(report?.states.map(state => [state.state_id, state.status]));
  const stateStatus = (id: string): MechanicsStatus => results.get(id) || 'unknown';
  const count = (ids: string[]) => {
    const statuses = [...new Set(ids)].map(stateStatus);
    return {
      total: statuses.length,
      feasible: statuses.filter(status => status === 'feasible').length,
      infeasible: statuses.filter(status => status === 'infeasible').length,
      unknown: statuses.filter(status => status === 'unknown').length,
    };
  };
  const release = count(candidate.events.map(event => event.release_state));
  const landing = count(candidate.events.map(event => event.to_state));
  const all = count(candidate.states.map(state => state.id));
  // A missing or partial report is not evidence of support feasibility. Count
  // actual checked states, never the generator's before/after metadata.
  const status: MechanicsStatus = all.infeasible ? 'infeasible'
    : report?.summary.status === 'feasible' && all.total > 0 && all.unknown === 0 ? 'feasible' : 'unknown';
  const label = status === 'infeasible' ? '支撑需调整' : status === 'feasible' ? '待试攀' : '支撑待确认';
  const firstIssue = candidate.states.find(state => stateStatus(state.id) === 'infeasible')
    || candidate.states.find(state => stateStatus(state.id) === 'unknown');
  const initialFailed = candidate.states[0] && stateStatus(candidate.states[0].id) === 'infeasible';
  const failedParts = [initialFailed ? '起始姿态' : '', release.infeasible ? `换点 ${release.infeasible} 处` : '', landing.infeasible ? `落点 ${landing.infeasible} 处` : ''].filter(Boolean);
  const detail = !report ? '尚无静态支撑检查结果。'
    : failedParts.length ? `静态支撑未满足：${failedParts.join('，')}。${all.unknown ? `另有 ${all.unknown} 处待确认。` : ''}`
    : status === 'feasible' ? '换点与落点的静态支撑检查通过，仍需试攀。'
    : `静态支撑${all.unknown ? `有 ${all.unknown} 处` : ''}待确认。`;
  return { status, label, release, landing, detail, firstIssueStateId: report ? firstIssue?.id : undefined, hasReport: !!report };
}

export interface DraftBrief {
  wall_profile: 'overhang' | 'roof' | 'dihedral' | 'arete';
  style: 'balance' | 'power' | 'sustained';
  difficulty: 'easy' | 'medium' | 'hard';
}
export interface DraftInput extends DraftBrief { seed: number; variant: number }
export interface DraftOption {
  id: string;
  label: string;
  status: 'complete' | 'unverified' | 'search_unresolved';
  bundle: Bundle;
  brief: DraftInput;
  geometry_digest: string;
  sequence_digest: string;
  elapsed_ms: number;
}
export interface DraftEntry {
  variant: number;
  state: 'waiting' | 'running' | 'ready' | 'error';
  result?: DraftOption;
  error?: string;
  duplicateOf?: number;
  selectedCandidateId?: string;
}

// Each result owns its request: comparing layouts must never reuse another
// option's contact constraints, fingerprints or evaluations.
export async function generateDraftBatch(
  brief: DraftBrief,
  seed: number,
  request: (input: DraftInput) => Promise<DraftOption>,
  update: (entries: DraftEntry[]) => void,
): Promise<DraftEntry[]> {
  const entries: DraftEntry[] = [0, 1, 2].map(variant => ({ variant, state: 'waiting' }));
  update(entries);
  for (const entry of entries) {
    entry.state = 'running'; update(entries);
    const input = { ...brief, seed, variant: entry.variant };
    try {
      const result = await request(input);
      const savedBrief = result.bundle?.request?.generation_brief as DraftInput | undefined;
      if (!result.bundle?.candidates.length || !savedBrief || !result.brief ||
          Object.entries(input).some(([key, value]) => result.brief[key as keyof DraftInput] !== value || savedBrief[key as keyof DraftInput] !== value)) {
        throw new Error('返回的方案与生成条件不一致');
      }
      entry.result = result;
      entry.selectedCandidateId = result.bundle.candidates[0].id;
      entry.state = 'ready';
      const repeated = entries.find(other => other !== entry && other.result && result.geometry_digest && result.sequence_digest &&
        other.result.geometry_digest === result.geometry_digest && other.result.sequence_digest === result.sequence_digest);
      if (repeated) entry.duplicateOf = repeated.variant;
    } catch (error) {
      entry.state = 'error';
      entry.error = error instanceof Error ? error.message : String(error);
    }
    update(entries);
  }
  return entries;
}
