import type { Candidate, DesignAnalysis, DesignMove, Evaluation, Limb, Request, SettingReport, State, Vec3 } from './types';
import { escape as esc, limbNames, limbs, shortHoldName } from './types.ts';
import { inversePoint, panelFrame } from './placement-geometry.ts';

export type RoofPhase = 'approach' | 'under_roof' | 'lip_transition' | 'exit' | 'unknown';
export const roofPhaseNames: Record<RoofPhase, string> = {
  approach: '檐前立面', under_roof: '檐下接触', lip_transition: '跨檐接触', exit: '出口上段', unknown: '接触待核对',
};
const panelNames: Record<string, string> = { 'lower-wall': '檐前立面', roof: '屋檐下侧', 'upper-wall': '出口立面' };
const finiteVector = (value: Vec3 | undefined): value is Vec3 => !!value && value.length === 3 && value.every(Number.isFinite);
const number = (value: unknown, digits = 1) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';

/** Resolve structural parents too: a child hold belongs to its volume's panel. */
function contactPanel(candidate: Candidate, state: State, limb: Limb): string | null {
  const ref = state.contacts[limb];
  if (!ref) return null;
  let placement = candidate.placements.find(item => item.id === ref.placement_id);
  const visited = new Set<string>();
  while (placement?.mount && !visited.has(placement.id)) {
    visited.add(placement.id);
    placement = candidate.placements.find(item => item.id === placement!.mount!.parent_id);
  }
  return placement?.wall_panel_id || 'unknown';
}

/** Contact categories can repeat or disappear. Their names never dictate search order. */
export function roofContactPhase(panels: (string | null)[]): RoofPhase {
  const occupied = panels.filter((id): id is string => id !== null);
  if (!occupied.length || occupied.some(id => !panelNames[id])) return 'unknown';
  if (occupied.every(id => id === 'upper-wall')) return 'exit';
  if (occupied.includes('upper-wall')) return 'lip_transition';
  if (occupied.includes('roof')) return 'under_roof';
  return 'approach';
}

export function roofStudyData(request: Request, candidate: Candidate, evaluation: Evaluation | undefined, analysis?: DesignAnalysis) {
  if (request.setting_design?.wall_profile !== 'roof' || candidate.layout_report || !candidate.events.length || !evaluation || evaluation.candidate_id !== candidate.id) return undefined;
  const roof = request.scene.wall_panels?.find(panel => panel.id === 'roof');
  const exit = request.scene.wall_panels?.find(panel => panel.id === 'upper-wall');
  if (!roof || !exit) return undefined;
  const frame = panelFrame(request.scene.angle_deg, exit);
  const states = candidate.states.map((state, step) => {
    const panels = Object.fromEntries(limbs.map(limb => [limb, contactPanel(candidate, state, limb)])) as Record<Limb, string | null>;
    const eventIndex = candidate.events.findIndex(event => event.to_state === state.id || event.release_state === state.id);
    const event = candidate.events[eventIndex];
    const pose = evaluation.poses.find(item => item.state_id === state.id);
    const wallCheck = evaluation.checks?.find(item => item.id === 'skeleton_wall' && item.state_id === state.id);
    const joints = pose?.status === 'pass' ? pose.joints : undefined;
    const pelvis = joints?.pelvis;
    const shoulders = finiteVector(joints?.left_shoulder) && finiteVector(joints?.right_shoulder)
      ? joints.left_shoulder.map((value, index) => (value + joints.right_shoulder[index]) / 2) as Vec3 : undefined;
    return { step, state, panels, phase: roofContactPhase(Object.values(panels)), eventIndex,
      isRelease: event?.release_state === state.id, wallCheck,
      pelvis: finiteVector(pelvis) ? inversePoint(frame, pelvis) : undefined,
      shoulders: shoulders ? inversePoint(frame, shoulders) : undefined,
      move: analysis?.moves.find(move => move.event_index === eventIndex),
    };
  });
  const segments: { phase: RoofPhase; firstStep: number; lastStep: number; eventStart: number; eventEnd: number }[] = [];
  // Group landed contact states; transient release states remain selectable separately.
  for (const state of states.filter(item => !item.isRelease)) {
    const last = segments.at(-1);
    if (last?.phase === state.phase) { last.lastStep = state.step; last.eventEnd = state.eventIndex; }
    else segments.push({ phase: state.phase, firstStep: state.step, lastStep: state.step, eventStart: state.eventIndex, eventEnd: state.eventIndex });
  }
  const transitions = states.filter(item => !item.isRelease && item.phase === 'lip_transition' && item.eventIndex >= 0);
  const firstExit = states.find(item => !item.isRelease && item.phase === 'exit');
  return { states, segments, transitions, firstExit, depth: roof.height, lip: frame.origin };
}

function positionLabel(point: Vec3) {
  const depth = point[2], height = point[1];
  return `${depth >= 0 ? '出口面外侧' : '出口面内侧'} ${number(Math.abs(depth), 2)} m · 檐口${height >= 0 ? '以上' : '以下'} ${number(Math.abs(height), 2)} m`;
}
function historyHTML(move: DesignMove) {
  return `<div class="move-history-values"><span>进入前累计 <b>${number(move.prior_load)}</b></span><span>清零前序负担 <b>${number(move.fresh_burden)}</b></span><span>带前序负担 <b>${number(move.effective_burden ?? move.burden)}</b></span><span>动作后累计 <b>${number(move.accumulated_load)}</b></span></div><p class="index-caption">这是当前完整转移动作的模型估计。累计量不是体力百分比；接触状态与释放状态共用这一步的负担记录。</p>`;
}

function clearanceHTML(check: Evaluation['checks'][number] | undefined) {
  const status = check?.status || 'not_checked';
  const labels = { pass: '本态骨架中心线：未检出穿墙', fail: '本态骨架中心线：存在穿墙，需复核', unknown: '本态骨架与墙板：尚无法判断', not_checked: '本态骨架与墙板：未检查' };
  const violations = Array.isArray(check?.evidence?.violations) ? check.evidence.violations : [];
  return `<p class="roof-clearance ${status}"><strong>${labels[status]}</strong>${violations.length ? `<span>${violations.length} 处交叉</span>` : ''}</p><small>该检查仅覆盖当前姿态的 15 条零半径骨架线段与有限、零厚度墙板；人体厚度、擦碰及连续动作仍未验证。</small>`;
}

export function roofComparisonData(candidate: Candidate, report: SettingReport | undefined) {
  if (!report?.baseline.exit_support || !report.result.exit_support) return undefined;
  const used = new Set(candidate.states.flatMap(state => Object.values(state.contacts).flatMap(contact => contact ? [contact.placement_id] : [])));
  return {
    before: report.baseline, after: report.result, selectionRole: report.selection_role,
    unusedChanges: report.changes.filter(change => !used.has(change.placement_id)),
    transferDelta: report.result.summary.transfers - report.baseline.summary.transfers,
    effortDelta: report.result.summary.total_proxy_effort - report.baseline.summary.total_proxy_effort,
  };
}

function comparisonHTML(request: Request, candidate: Candidate, report: SettingReport | undefined, stage: string) {
  const data = roofComparisonData(candidate, report);
  if (!data) return '';
  const mechanicsNames = { feasible: '当前假设下可行', infeasible: '当前假设下不满足', unknown: '无法判断' };
  const releaseCount = (value: SettingReport['baseline']) => value.mechanics_summary
    ? `${value.mechanics_summary.release_states - value.mechanics_summary.release_infeasible_states - (value.mechanics_summary.release_unknown_states || 0)} / ${value.mechanics_summary.release_states}` : '—';
  const signed = (value: number, digits = 1) => `${value >= 0 ? '+' : ''}${number(value, digits)}`;
  const rows: [string, string, string][] = [
    ['出口窗口 · 静态可行姿态', `${data.before.exit_support!.feasible_states} / ${data.before.exit_support!.states}`, `${data.after.exit_support!.feasible_states} / ${data.after.exit_support!.states}`],
    ['其中 · 释放态', `${data.before.exit_support!.release_feasible_states} / ${data.before.exit_support!.release_states}`, `${data.after.exit_support!.release_feasible_states} / ${data.after.exit_support!.release_states}`],
    ['TOP 静态诊断', mechanicsNames[data.before.exit_support!.finish_status], mechanicsNames[data.after.exit_support!.finish_status]],
    ['全程 · 静态可行释放态', releaseCount(data.before), releaseCount(data.after)],
    ['全程 · 手脚转换次数', String(data.before.summary.transfers), String(data.after.summary.transfers)],
    ['全程 · 模型总负荷', number(data.before.summary.total_proxy_effort), number(data.after.summary.total_proxy_effort)],
    ['全程 · 峰值负担 / 结束累计', `${number(data.before.summary.peak_proxy_burden)} / ${number(data.before.summary.final_load)}`, `${number(data.after.summary.peak_proxy_burden)} / ${number(data.after.summary.final_load)}`],
  ];
  const unusedName = (id: string) => {
    const placement = candidate.placements.find(item => item.id === id), hold = request.scene.inventory.find(item => item.id === placement?.inventory_id);
    return hold ? `${shortHoldName(hold, request.scene.inventory)}（${id}）` : id;
  };
  const unusedExit = data.unusedChanges.filter(change => change.after.wall_panel_id === 'upper-wall' && change.before.wall_panel_id !== 'upper-wall');
  return `<div class="roof-tradeoff"><h3>${data.selectionRole === 'exit_support_tradeoff' ? '出口支撑与全程消耗的取舍' : '全程排序保留方案 · 出口仍需复核'}</h3><p>${data.selectionRole === 'exit_support_tradeoff' ? `相对原布局，当前主方案的转换次数变化 ${signed(data.transferDelta, 0)}，模型总负荷变化 ${signed(data.effortDelta)}。出口诊断与全程代价分开比较。` : '当前方案保留全程支撑排序的结果。切换另一主方案，可比较整组朝向、脚点与独立走法变化带来的代价。'}</p>
    <div class="beta-table-scroll" role="region" aria-label="屋檐出口与全程代价比较" tabindex="0"><table class="beta-table roof-tradeoff-table"><thead><tr><th scope="col">比较项</th><th scope="col">原布局主走法</th><th scope="col">本方案主走法</th></tr></thead><tbody>${rows.map(([label, before, after]) => `<tr><th scope="row">${label}</th><td>${before}</td><td>${after}</td></tr>`).join('')}</tbody></table></div>
    <p class="index-caption">出口窗口从第一次手移向出口立面之前的释放态开始，一直计至 TOP；包含转出时的支撑缺口。以上为主走法统计，备选走法的状态与连续负担在下方单独更新。静态结果使用合成参数，不等于真人通过率。</p>
    ${stage === 'after' && data.unusedChanges.length ? `<p class="roof-unused-change">当前走法跳过的改动点：${data.unusedChanges.map(change => esc(unusedName(change.placement_id))).join('、')}。${unusedExit.length ? `试装到出口面的 ${unusedExit.map(change => esc(unusedName(change.placement_id))).join('、')} 仍未使用。` : ''}不要求用完安装点，也不能把出口变化单独归因于某个脚点。</p>` : ''}
  </div>`;
}

export function roofStudyHTML(request: Request, candidate: Candidate, evaluation: Evaluation | undefined, analysis: DesignAnalysis | undefined, step: number, busy: boolean, report?: SettingReport, stage = 'after') {
  const data = roofStudyData(request, candidate, evaluation, analysis);
  if (!data) return '';
  const current = data.states[step];
  if (!current) return '';
  const event = candidate.events[current.eventIndex];
  const transitionMoves = data.transitions.flatMap(item => item.move ? [item.move] : []);
  const peak = transitionMoves.length ? transitionMoves.reduce((best, move) => (move.effective_burden ?? move.burden) > (best.effective_burden ?? best.burden) ? move : best) : undefined;
  const peakStep = peak ? data.states.find(item => !item.isRelease && item.eventIndex === peak.event_index)?.step : undefined;
  const phaseStep = (stateId: string) => candidate.states.findIndex(state => state.id === stateId);
  return `<section class="roof-study" aria-label="屋檐转出观察">${comparisonHTML(request, candidate, report, stage)}<div class="rhythm-heading"><h3>从檐下到出口，手脚怎样交接</h3><span>屋檐段展开深度 ${number(data.depth, 2)} m</span></div>
    <p class="index-caption">下列分段来自当前走法的真实接触面，可以回到前一段。名称只描述接触位置，不代表已完成某项技巧或连续转出。</p>
    <div class="roof-phases" role="group" aria-label="按实际接触面查看屋檐阶段">${data.segments.map(segment => `<button data-action="roof-step" data-step="${segment.firstStep}" aria-pressed="${step >= segment.firstStep && step <= segment.lastStep}" class="${step >= segment.firstStep && step <= segment.lastStep ? 'active' : ''}" ${busy ? 'disabled' : ''}><strong>${roofPhaseNames[segment.phase]}</strong><small>${segment.eventStart < 0 ? '起始接触' : `动作 ${segment.eventStart + 1}`}${segment.eventEnd > Math.max(-1, segment.eventStart) ? ` — ${segment.eventEnd + 1}` : ''}</small></button>`).join('')}</div>
    <div class="roof-key-states">${data.transitions.length ? `<button class="text-button" data-action="roof-step" data-step="${data.transitions[0].step}" ${busy ? 'disabled' : ''}>看首次跨檐接触</button>` : '<span>当前走法未出现上下跨檐接触</span>'}${peakStep !== undefined ? `<button class="text-button" data-action="roof-step" data-step="${peakStep}" ${busy ? 'disabled' : ''}>看跨檐段负担峰值 · 动作 ${peak!.event_index + 1}</button>` : ''}${data.firstExit ? `<button class="text-button" data-action="roof-step" data-step="${data.firstExit.step}" ${busy ? 'disabled' : ''}>看所有接触进入出口</button>` : '<span>终点仍有接触留在檐下或檐前</span>'}</div>
    <div class="roof-state-heading"><strong>${current.eventIndex < 0 ? '起始接触' : `动作 ${current.eventIndex + 1} · ${limbNames[event.limb]}${current.isRelease ? '释放' : '落点'}`}<span>${roofPhaseNames[current.phase]}</span></strong>${event ? `<div role="group" aria-label="当前动作释放与落点"><button data-action="roof-step" data-step="${phaseStep(event.release_state)}" aria-pressed="${current.isRelease}" class="${current.isRelease ? 'active' : ''}" ${busy ? 'disabled' : ''}>释放时</button><button data-action="roof-step" data-step="${phaseStep(event.to_state)}" aria-pressed="${!current.isRelease}" class="${!current.isRelease ? 'active' : ''}" ${busy ? 'disabled' : ''}>落点后</button></div>` : `<button class="text-button" data-action="roof-step" data-step="${step}" ${busy ? 'disabled' : ''}>显示当前身体与接触</button>`}</div>
    <dl class="roof-contacts">${limbs.map(limb => { const ref = current.state.contacts[limb], placement = candidate.placements.find(item => item.id === ref?.placement_id), hold = request.scene.inventory.find(item => item.id === placement?.inventory_id); return `<div><dt><i class="limb-dot ${limb.toLowerCase()}"></i>${limbNames[limb]}</dt><dd>${ref ? `${esc(hold ? shortHoldName(hold, request.scene.inventory) : ref.placement_id)}<small>${esc(panelNames[current.panels[limb] || ''] || '墙面未知')}</small>` : '释放中'}</dd></div>`; }).join('')}</dl>
    <div class="roof-body-position">${current.pelvis ? `<p><strong>髋中心</strong><span>${positionLabel(current.pelvis)}</span></p>` : '<p>当前没有通过检查的计算姿态，仅显示真实接触目标。</p>'}${current.shoulders ? `<p><strong>肩中点</strong><span>${positionLabel(current.shoulders)}</span></p>` : ''}<small>身体位置沿出口面法向与向上轴测量，来自当前离散 IK 姿态；不等于完整身体已避开檐口。</small>${clearanceHTML(current.wallCheck)}<button class="text-button" data-action="roof-view" data-step="${step}" ${busy ? 'disabled' : ''}>在岩壁上看当前${current.pelvis ? '姿态' : '接触'}</button></div>
    ${current.move ? historyHTML(current.move) : '<p class="index-caption">选择转移动作，查看进入该动作前的累计负荷。</p>'}
  </section>`;
}
