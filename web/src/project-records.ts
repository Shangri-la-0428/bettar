import type { DraftBrief, DraftEntry } from './draft-generation';

export interface ProjectSnapshot {
  name: string; gym_id: string; gym_version: string; region_id: string;
  brief: DraftBrief; entries: DraftEntry[]; selected_variant: number | null;
  notes: string; status: 'draft' | 'generating' | 'editing';
}
export interface ProjectRecord extends ProjectSnapshot {
  id: string; revision: number; created_at: string; updated_at: string;
  compatibility: { status: 'current' | 'stale' | 'unavailable'; messages: string[]; read_only?: boolean };
  read_only?: boolean; interrupted?: boolean;
}
export type ProjectSummary = Omit<ProjectRecord, 'entries'> & { option_count?: number };
export type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error';

/** Serial, coalesced writes: slow saves cannot replace newer edits or another task. */
export class ProjectAutosave {
  private identity: { id: string; revision: number } | undefined;
  private pending: ProjectSnapshot | undefined;
  private copyPending = false;
  private running: Promise<boolean> | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  state: SaveState = 'idle';
  error = '';
  private send: (value: ProjectSnapshot & { id?: string; revision?: number }) => Promise<ProjectRecord>;
  private changed: (state: SaveState, record?: ProjectRecord) => void;
  constructor(
    send: (value: ProjectSnapshot & { id?: string; revision?: number }) => Promise<ProjectRecord>,
    changed: (state: SaveState, record?: ProjectRecord) => void,
  ) { this.send = send; this.changed = changed; }
  get dirty() { return !!this.pending || !!this.running; }
  reset(record?: Pick<ProjectRecord, 'id' | 'revision'>) {
    if (this.dirty) throw new Error('当前记录尚未保存');
    this.identity = record ? { id: record.id, revision: record.revision } : undefined;
    this.copyPending = false;
    this.state = record ? 'saved' : 'idle'; this.error = ''; this.changed(this.state);
  }
  schedule(snapshot: ProjectSnapshot) {
    this.pending = structuredClone(snapshot); this.error = ''; this.state = 'pending'; this.changed(this.state);
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => { void this.flush(); }, 300);
  }
  async flush(): Promise<boolean> {
    if (this.timer) clearTimeout(this.timer); this.timer = undefined;
    if (this.running) return this.running;
    if (!this.pending) return this.state !== 'error';
    this.running = this.drain();
    try { return await this.running; } finally { this.running = undefined; }
  }
  /** Explicit conflict recovery: preserve the old record and continue in a copy. */
  async saveCopy(): Promise<boolean> {
    if (this.running) throw new Error('正在保存，请完成后再另存副本。');
    if (!this.pending) throw new Error('当前没有待另存的修改。');
    // Retain this intent across errors. A later automatic retry must not send
    // the user's copy back to the original, conflicting record.
    this.copyPending = true;
    return this.flush();
  }
  private async drain(): Promise<boolean> {
    while (this.pending) {
      const snapshot = this.pending; this.pending = undefined;
      this.state = 'saving'; this.changed(this.state);
      try {
        const payload: ProjectSnapshot & { id?: string; revision?: number } = { ...snapshot };
        // Record-shaped inputs may have extra fields at runtime. Transport
        // identity comes only from this queue, never from snapshot contents.
        delete payload.id; delete payload.revision;
        if (!this.copyPending && this.identity) Object.assign(payload, this.identity);
        const record = await this.send(payload);
        this.identity = { id: record.id, revision: record.revision };
        this.copyPending = false; this.error = '';
        this.state = this.pending ? 'pending' : 'saved'; this.changed(this.state, record);
      } catch (error) {
        this.pending ||= snapshot;
        this.error = error instanceof Error ? error.message : String(error);
        this.state = 'error'; this.changed(this.state); return false;
      }
    }
    return true;
  }
}
