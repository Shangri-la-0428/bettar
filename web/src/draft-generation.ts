import type { Bundle } from './types';

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
