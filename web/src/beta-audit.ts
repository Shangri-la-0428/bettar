import type { BetaAudit, BetaAlternative, BetaSummary, Bundle, Candidate } from './types';
import { escape as esc, limbNames, shortHoldName, statusLabels } from './types';
import { burdenChartHTML } from './route-design';
import { mechanicsLabel } from './mechanics';

const num = (value: unknown, digits = 1) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
const delta = (value: number) => `${value > 0 ? '+' : ''}${num(value)}`;
function holdName(bundle: Bundle, candidate: Candidate, id: string) {
  const placement = candidate.placements.find(p => p.id === id);
  const hold = bundle.request.scene.inventory.find(h => h.id === placement?.inventory_id);
  return hold ? shortHoldName(hold, bundle.request.scene.inventory) : id;
}
export function betaPathCount(report: BetaAudit) {
  return new Set(report.alternatives.map(a => JSON.stringify(a.candidate.events.map(event => [event.limb, a.candidate.states.find(state => state.id === event.to_state)?.contacts[event.limb]])))).size;
}
function cruxExplanation(bundle: Bundle, candidate: Candidate, report: BetaAudit, selected: BetaAlternative) {
  const result = selected.crux_bypass;
  const point = esc(holdName(bundle, candidate, result.original_hold_id));
  const originalMove = report.original.analysis.moves.find(move => move.event_index === report.original.crux.event_index);
  const moveName = originalMove ? `${limbNames[originalMove.limb]} ${holdName(bundle, candidate, originalMove.from_placement_id)} → ${holdName(bundle, candidate, originalMove.to_placement_id)}` : '原定难点移手';
  const contact = !result.contacted ? `原模型难点点位 ${point} 被跳过` : result.contacted_as_hand === true ? `原模型难点点位 ${point} 仍作手点` : result.contacted_as_hand === false ? `原模型难点点位 ${point} 只作脚点` : `原模型难点点位 ${point} 仍被接触`;
  const transition = result.original_transition_used === true ? `原难点移手（${esc(moveName)}）仍出现，支撑脚步可能不同。` : result.original_transition_used === false ? `原难点移手（${esc(moveName)}）未出现，进入方式或移手顺序已改变。` : '这份报告没有比较原难点移手是否仍出现。';
  return `${contact}。${transition}${result.peak_reduced ? '整条走法的模型峰值降低' : '整条走法的模型峰值未降低'}；这不能证明真人难点已经消失。`;
}
function row(label: string, id: string, summary: BetaSummary, status: string, active: boolean, mechanicsStatus = '未计算') {
  return `<tr class="${active ? 'active' : ''}"><th scope="row"><button data-action="beta-select" data-id="${esc(id)}" aria-pressed="${active}">${esc(label)}<small>${active ? '画布正在查看' : '在画布查看'}</small></button></th><td>${summary.hand_moves} / ${summary.foot_moves}</td><td>${summary.transfers}</td><td>${num(summary.total_proxy_effort)}</td><td>${num(summary.peak_proxy_burden)}</td><td>${esc(status)}</td><td>${esc(mechanicsStatus)}</td></tr>`;
}
function betaAuditMarkup(bundle: Bundle, candidate: Candidate, report: BetaAudit | undefined, selected: BetaAlternative | undefined, busy: boolean, auditing: boolean, invalidated: boolean, error: string, step: number) {
  const heading = `<div class="beta-audit-heading"><div><h2>这条线有没有别的走法？</h2><p>固定已安装的岩点、朝向和起终点，允许跳点、换手顺序和不同脚步。</p></div><button class="button ${report ? 'outlined' : 'primary'}" data-action="beta-audit" ${busy ? 'disabled' : ''}>${auditing ? '<span class="loading-spinner small"></span>搜索与姿态复核中…' : report ? '重新检查替代走法' : '检查替代走法'}</button></div>`;
  if (!report) return `${heading}<p class="beta-audit-intro">${auditing ? '在当前岩点布局中寻找不同接触序列，并复核返回方案。原定走法保持不变。' : invalidated ? '点位、方向或候选已改变，旧的替代走法结论已失效。重新检查当前布局。' : '原定动作只是定线意图。检查会尝试用更少接触转换、或更低模型总负荷完成线路，不要求每个点都用到。'}</p>${error ? `<p class="beta-audit-error" role="alert">${esc(error)}</p>` : ''}<p class="index-caption">搜索使用获准接触的抓握面与踩踏面代表点；无法凭此确认真人的最省力走法。</p>`;
  const original = report.original;
  const view = selected || original;
  const currentState = view.candidate.states[step]?.id;
  const eventIndex = view.candidate.events.findIndex(e => e.to_state === currentState || e.release_state === currentState);
  const move = view.analysis.moves.find(m => m.event_index === eventIndex);
  const skipped = selected?.skipped_hold_ids || [];
  const support = move?.orientation_support;
  return `${heading}
    <p class="beta-audit-result">${report.alternatives.length ? `返回 ${report.alternatives.length} 个通过几何与姿态检查的目标结果，包含 ${betaPathCount(report)} 条不同接触序列。` : '在本次预算内未找到通过复核的替代走法；这不等于没有捷径。'}更少动作不等于更容易；模型负荷较低也不等于真人更省力。${report.search.unverified_count ? `另有 ${report.search.unverified_count} 条序列尚未通过姿态复核，不计入这些结论。` : ''}</p>
    <div class="beta-table-scroll" role="region" tabindex="0" aria-label="原定与替代走法对照，可横向滚动"><table class="beta-table"><thead><tr><th scope="col">走法</th><th scope="col">移手 / 移脚</th><th scope="col">接触转换</th><th scope="col">模型总负荷（含朝向）</th><th scope="col">峰值负担</th><th scope="col">几何与姿态</th><th scope="col">准静态 · 当前姿态集</th></tr></thead><tbody>${row('原定走法', '', original.summary, statusLabels[original.evaluation.summary.status], !selected, mechanicsLabel(original.evaluation))}${report.alternatives.map(a => row(a.label, a.id, a.summary, statusLabels[a.evaluation.summary.status], a.id === selected?.id, mechanicsLabel(a.evaluation))).join('')}</tbody></table></div><p class="index-caption">总负荷包含支撑与拉向的代理惩罚；峰值负担沿用带前序负荷的模型。两列计算口径不同，不是测得的体力消耗。</p>
    ${selected ? `<div class="beta-selected"><div><strong>正在查看：${esc(selected.label)}</strong><button class="text-button" data-action="beta-select" data-id="">返回原定走法</button></div><p class="index-caption">${selected.search_source === 'bounded_single_transfer_deletion' ? '这条反例来自补充跳点试验：删除原走法中的一次转换，重新建立并复核全部接触状态；独立搜索中未通过的走法仍保留在下方。' : '这条走法来自固定安装布局上的独立接触顺序搜索。'}</p><p>与原定相比：接触转换 ${delta(selected.comparison.transfers_delta)} · 模型总负荷 ${delta(selected.comparison.proxy_effort_delta)} · 峰值负担 ${delta(selected.comparison.peak_burden_delta)}。</p><p>同一组 ${candidate.placements.length} 个已安装点保留在墙上；本走法未使用的点以灰色显示，不能因跳过而从墙上删除。</p><div class="beta-skipped"><span>跳过原定接触点 ${skipped.length} 个</span>${skipped.length ? skipped.map(id => `<button class="button quiet" data-action="select-hold" data-id="${esc(id)}" title="${esc(id)}">${esc(holdName(bundle, candidate, id))}</button>`).join('') : '<small>接触点未减少，动作顺序或手脚配合不同。</small>'}</div><p>${cruxExplanation(bundle, candidate, report, selected)}</p></div>` : '<p class="index-caption">选择一条替代走法，画布、下方动作与姿态检查会一同切换。原定走法及报告保持保留。</p>'}
    ${selected ? `<div class="rhythm-heading"><h3>替代走法的实际动作负担</h3><span>不套用原定阶段名称</span></div>${burdenChartHTML(view.analysis)}<div class="move-demand-list full-route-moves" tabindex="0" role="region" aria-label="替代走法动作，可横向滚动">${view.analysis.moves.map(m => { const target = view.candidate.events[m.event_index]?.to_state; const stateIndex = view.candidate.states.findIndex(s => s.id === target); return `<button class="move-demand ${m.event_index === eventIndex ? 'active' : ''}" data-action="phase" data-step="${Math.max(0, stateIndex)}" aria-pressed="${m.event_index === eventIndex}"><span>${m.event_index + 1}${m.event_index === view.analysis.summary.crux_event_index ? '<b>模型峰值</b>' : ''}</span><strong>${esc(limbNames[m.limb])}</strong><small>${esc(holdName(bundle, candidate, m.to_placement_id))}</small></button>`; }).join('')}</div>${move ? `<p class="beta-move-details">动作 ${move.event_index + 1} · ${esc(limbNames[move.limb])} → ${esc(holdName(bundle, candidate, move.to_placement_id))} · 基线负担 ${num(move.fresh_burden ?? move.load)} · 带前序负荷 ${num(move.effective_burden ?? move.burden)} · 动作后累计 ${num(move.accumulated_load)}</p>${support ? `<div class="beta-support-details"><strong>这个动作的朝向与脚步关系</strong><span>保留手拉向偏差 ${num(support.pull_mismatch, 2)}</span><span>名义躯干超出脚间范围 ${num(support.trunk_outside_foot_interval, 2)}</span><span>代理附加负荷 ${num(support.proxy_penalty)}</span><small>按移动前仍在支撑的手与脚估算；名义躯干不是求解的重心，未验证受力平衡与摩擦。</small></div>` : ''}` : ''}<p class="index-caption">曲线按当前替代序列重新累计；虚线为逐动作基线，实线携带前序模型负荷。两条曲线不是两种走法。</p>` : ''}
    <details class="beta-audit-evidence"><summary>搜索范围与未验证部分</summary><p>展开 ${report.search.expanded} / ${report.search.expansion_limit} 个状态 · 每轮保留 ${report.search.beam_width} · 完整序列 ${report.search.complete_sequences} · 姿态复核 ${report.search.ik_checked} · 通过的目标结果 ${report.search.verified_alternatives}${report.search.unverified_count ? ` · 未通过复核的序列 ${report.search.unverified_count}` : ''}。</p><p>${report.search.time_budget_exhausted ? '搜索与姿态复核达到共同时间预算；未完成的姿态保留为无法判断。这不证明动作不可完成，也不证明没有其他走法。' : report.search.budget_exhausted ? '已达到展开或动作深度预算；仍可能存在未搜到的走法。' : '有限宽度与动作范围内的搜索，不证明已找到全局最优走法。'}</p><p>同一岩点可以有不同的抓握面与踩踏面；每个面仍只取一个代表点，尚未搜索面内所有接触位置。</p>${report.unverified_alternatives?.length ? `<div class="beta-unverified"><strong>未通过复核，不计为可行替代</strong>${report.unverified_alternatives.map(a => `<p>${esc(a.label)} · ${statusLabels[a.evaluation.summary.status]}${a.evaluation.poses.some(p => p.status === 'unknown') ? ' · 有姿态未找到' : ''}</p>`).join('')}</div>` : ''}${report.limitations.map(item => `<p>${esc(item)}</p>`).join('')}<button class="button outlined" data-action="beta-export">保存这份审计报告</button><p class="beta-fingerprint">布局标识 ${esc(report.source.geometry_hash.slice(0, 12))} · 修订 ${report.source.revision}</p></details>${error ? `<p class="beta-audit-error" role="alert">${esc(error)}</p>` : ''}`;
}

export function betaAuditHTML(...args: Parameters<typeof betaAuditMarkup>) {
  const markup = betaAuditMarkup(...args);
  return args[0].request.profile === 'setting' ? markup
    .replaceAll('原定走法', '生成走法')
    .replaceAll('原定动作只是定线意图。', '当前动作序列来自几何布局上的搜索。')
    .replaceAll('原定接触点', '生成走法使用的点') : markup;
}
