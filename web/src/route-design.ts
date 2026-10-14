import type { Bundle, Candidate, DemandDimensions, DesignAnalysis, Evaluation, Hold, Rhythm, RouteProgram, StyleExample, StyleGoal } from './types';
import { escape as esc, limbNames, shortHoldName, statusLabels } from './types';

export const styleNames: Record<StyleGoal, string> = { power: '力量与爆发', sustained: '持续输出', technical: '技巧变化' };
export const programNames: Record<RouteProgram, string> = { mixed_flow: '混合节奏', power_finish: '后段力量', sustained_finish: '持续收尾' };
export const rhythmNames: Record<Rhythm, string> = { early_crux: '前段难点', late_crux: '后段难点', sustained: '持续施压' };
const dimensions: { key: keyof DemandDimensions; name: string; explanation: string }[] = [
  { key: 'strength', name: '力量需求', explanation: '握持属性、支撑与倾角的组合估计' },
  { key: 'power', name: '爆发倾向', explanation: '跨度与转换特征；尚未计算动态动作' },
  { key: 'load', name: '动作负荷', explanation: '单动作相对负荷；不是生理能量' },
  { key: 'technical', name: '技巧需求', explanation: '精度、方向与支撑转换的组合估计' },
];
const number = (value: unknown, digits = 0) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
const bar = (value: number) => Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0;
const eventStep = (candidate: Candidate, eventIndex: number) => {
  const event = candidate.events[eventIndex];
  const index = candidate.states.findIndex(state => state.id === event?.to_state);
  return Math.max(0, index);
};
function contactName(bundle: Bundle, candidate: Candidate, placementId: string) {
  const inventory = bundle.request.scene.inventory;
  const placement = candidate.placements.find(item => item.id === placementId);
  const hold = inventory.find(item => item.id === placement?.inventory_id);
  return hold ? shortHoldName(hold, inventory) : placementId;
}
function selectedPath(bundle: Bundle, candidate: Candidate) {
  return candidate.events.map(event => {
    const state = candidate.states.find(item => item.id === event.to_state);
    const id = state?.contacts[event.limb]?.placement_id;
    return id ? `${limbNames[event.limb]} ${contactName(bundle, candidate, id)}` : limbNames[event.limb];
  }).join(' → ');
}

export function styleExamplesHTML(examples: StyleExample[], activeBundle?: Bundle) {
  if (!examples.length) return '';
  const first = examples[0].bundle.request;
  const partOfComparison = examples.some(example => example.bundle.id === activeBundle?.id);
  return `<div class="style-examples-heading"><h2>同墙风格对照</h2><span>人体 ${esc(first.body.id)} · ${first.scene.angle_deg}° · 种子 ${first.seed}</span></div>
    <p class="field-hint">同一固定布局与阶段节奏。点击一条线路，查看实际选点、动作顺序和检查结果。四项需求为移手动作的平均模型指数；负荷波动为标准差，越小表示这个短段较均匀。</p>
    ${partOfComparison ? '' : '<p class="field-hint">当前下方展示单独生成的方案；此表保留上一次对照实验，点击可切回。</p>'}
    <div class="style-table-scroll" tabindex="0" role="region" aria-label="三种风格示例对照，可横向滚动"><table class="style-example-table"><thead><tr><th scope="col">生成目标</th>${dimensions.map(item => `<th scope="col" title="${esc(item.explanation)}">${item.name}</th>`).join('')}<th scope="col" title="移手单动作负荷的标准差；越小表示短段较均匀">负荷波动</th><th scope="col">几何与姿态</th></tr></thead><tbody>${examples.map(example => {
      const candidate = example.bundle.candidates[0];
      const ev = example.bundle.evaluations.find(item => item.candidate_id === candidate?.id);
      const analysis = ev?.design_analysis;
      const active = activeBundle?.id === example.bundle.id;
      return `<tr class="${active ? 'active' : ''}"><th scope="row"><button data-action="style-example" data-id="${esc(example.id)}" aria-pressed="${active}"><strong>${esc(example.label || styleNames[example.bundle.request.route_design!.style_goal])}</strong><span>${esc(rhythmNames[example.bundle.request.route_design!.rhythm])} · ${candidate?.events.filter(event => event.limb.endsWith('H')).length ?? 0} 手</span></button></th>${dimensions.map(item => `<td>${number(analysis?.dimensions[item.key])}</td>`).join('')}<td>${number(analysis?.summary.load_variability, 2)}</td><td><span class="style-check ${ev?.summary.status || 'unknown'}">${esc(ev ? statusLabels[ev.summary.status] : '未检查')}</span></td></tr>`;
    }).join('')}</tbody></table></div>`;
}

export function routeDesignHTML(bundle: Bundle, candidate: Candidate, evaluation: Evaluation | undefined, stale: boolean, step: number) {
  if (bundle.request.profile === 'route') return fullRouteHTML(bundle, candidate, evaluation, stale, step);
  const target = bundle.request.route_design;
  if (!target) return '';
  const analysis = stale ? undefined : evaluation?.design_analysis;
  const heading = `<div class="route-study-heading"><div><span class="section-label">当前生成目标</span><h2>${esc(styleNames[target.style_goal])}<span> / ${esc(rhythmNames[target.rhythm])}</span></h2></div><span class="small-note">${analysis ? `模型 ${esc(analysis.model_version)}` : '等待检查'}</span></div>`;
  if (!analysis) return `${heading}<p class="study-pending">${stale ? '当前修订已变化，旧的风格估计与阶段曲线已收起。重新检查后显示新版结果。' : '这条线路尚无风格分析。运行检查后查看当前模型的估计。'}</p>`;
  const activeState = candidate.states[step]?.id;
  const activeEvent = candidate.events.findIndex(event => event.to_state === activeState || event.release_state === activeState);
  const activeMove = analysis.moves.find(move => move.event_index === activeEvent) || analysis.moves[0];
  const crux = analysis.moves.find(move => move.event_index === analysis.summary.crux_event_index);
  return `${heading}
    <div class="demand-dimensions">${dimensions.map(item => `<div title="${esc(item.explanation)}"><span>${item.name}</span><strong>${number(analysis.dimensions[item.key])}<small> / 100</small></strong><div class="demand-track"><i style="width:${bar(analysis.dimensions[item.key])}%"></i></div></div>`).join('')}</div>
    <p class="index-caption">四项为移手动作均值。移手负荷波动 ${number(analysis.summary.load_variability, 2)}（标准差）；越小表示这个短段较均匀。所有手脚动作负荷合计 ${number(analysis.summary.total_load, 1)}；这些指数尚未标定，不代表体力百分比或攀爬等级。</p>
    ${crux ? `<p class="actual-crux"><strong>本方案难点估计：动作 ${crux.event_index + 1}</strong><span>${esc(limbNames[crux.limb])} → ${esc(contactName(bundle, candidate, crux.to_placement_id))} · 含前段累积的负担 ${number(crux.burden, 1)}</span></p>` : ''}
    <div class="rhythm-heading"><h3>阶段与节奏</h3><span>虚线：设计目标 · 实色：模型估计</span></div>
    <div class="rhythm-phases">${analysis.phases.map(phase => {
      const active = activeEvent >= phase.event_start && activeEvent <= phase.event_end;
      return `<button class="rhythm-phase ${active ? 'active' : ''}" data-action="phase" data-step="${eventStep(candidate, phase.event_start)}" aria-pressed="${active}"><strong>${esc(phase.label)}</strong><span class="phase-events">动作 ${phase.event_start + 1}–${phase.event_end + 1}</span>${dimensions.map(item => `<span class="phase-demand"><span>${item.name}</span><i><b class="phase-target" style="width:${bar(phase.target[item.key])}%"></b><b class="phase-estimate" style="width:${bar(phase.estimate[item.key])}%"></b></i><small>${number(phase.target[item.key])} / ${number(phase.estimate[item.key])}</small></span>`).join('')}</button>`;
    }).join('')}</div>
    <p class="index-caption">每行右侧为目标 / 估计；阶段负荷加入前段累积的影响。目标与结果有差距时照实保留。</p>
    <div class="rhythm-heading move-heading"><h3>逐动作负荷</h3><span>单动作指数 · 点击查看</span></div>
    <div class="move-demand-list">${analysis.moves.map(move => `<button class="move-demand ${move.event_index === activeEvent ? 'active' : ''}" data-action="phase" data-step="${eventStep(candidate, move.event_index)}" aria-pressed="${move.event_index === activeEvent}" title="${esc(limbNames[move.limb])} → ${esc(contactName(bundle, candidate, move.to_placement_id))} · 负荷 ${number(move.load)}"><span>${move.event_index + 1}${move.event_index === analysis.summary.crux_event_index ? '<b>难点估计</b>' : ''}</span><i style="--demand:${bar(move.load)}%"><b></b></i><strong>${esc(contactName(bundle, candidate, move.to_placement_id))}</strong></button>`).join('')}</div>
    <p class="index-caption">柱高表示单动作负荷；难点标记按含前段累积的负担估计，可能与最高柱不同。</p>
    ${activeMove ? `<div class="move-explanation"><strong>${activeEvent < 0 ? '下一动作 · ' : ''}${esc(limbNames[activeMove.limb])} → ${esc(contactName(bundle, candidate, activeMove.to_placement_id))}</strong><span>${dimensions.map(item => `${item.name} ${number(activeMove[item.key])}`).join(' · ')}</span><small>跨度 / 臂长 ${number(activeMove.attributes.span_ratio, 2)} · 支撑指标 ${number(activeMove.attributes.foot_support, 2)} · 当前负担 ${number(activeMove.burden, 1)} · 累计负荷 ${number(activeMove.accumulated_load, 1)}</small></div>` : ''}
    <details class="style-evidence"><summary>选点顺序与模型依据</summary><p class="selected-path">${esc(selectedPath(bundle, candidate))}</p><p>${esc(analysis.source === 'synthetic_assumption' ? '基于合成属性与启发式搜索。' : analysis.source)} 这些结果用于比较设计方案，尚未用真人试爬数据校准。</p>${analysis.limitations.map(item => `<p>${esc(item)}</p>`).join('')}<div class="search-evidence">${searchHTML(analysis)}</div></details>`;
}

function searchHTML(analysis: DesignAnalysis) {
  const names: Record<string, string> = { beam_width: '每轮保留上限', expanded: '展开状态', expansion_limit: '展开上限', complete_sequences: '完整序列', returned_candidates: '返回候选', distinct_hand_sequences: '不同手序列', expanded_nodes: '展开状态', attempted: '尝试', considered: '考虑方案', generated: '产生方案', feasible: '可行方案', retained: '保留方案', evaluated: '完整复核', rejected: '淘汰', rejected_geometry: '几何淘汰', rejected_ik: '姿态淘汰', unique_paths: '不同路径', candidates_evaluated: '完整复核', candidate_count: '候选数', valid_candidates: '通过方案', max_depth: '搜索深度' };
  const pairs = Object.entries(analysis.search).filter(([key, value]) => key in names && typeof value === 'number');
  const rejected = analysis.search.rejected as Record<string, number> | undefined;
  const reasons: Record<string, string> = { nonprogressing_hand: '手点未向终点推进', nonprogressing_foot: '脚点未向终点推进', duplicate_contact: '同类肢体占用同点', necessary_geometry: '未满足必要几何条件', beam_duplicate_state: '重复接触状态', beam_pruned: '搜索宽度截断' };
  return pairs.length ? `<span>搜索记录</span>${pairs.map(([key, value]) => `<span>${names[key]} <strong>${number(value)}</strong></span>`).join('')}${rejected ? `<p class="search-reasons">${Object.entries(rejected).map(([key, value]) => `${esc(reasons[key] || key)} ${number(value)}`).join(' · ')}</p>` : ''}<p>${analysis.search.budget_exhausted ? '已用完展开预算；返回结果不保证覆盖全部可行线路。' : '搜索受宽度与动作语法限制，返回候选另行接受几何与姿态检查。'}</p>` : '<p>这份修订没有可归属的生成搜索记录；当前几何与风格估计已单独重算。</p>';
}

export function holdAttributesHTML(hold: Hold) {
  const attributes = hold.design_attributes;
  if (!attributes) return '';
  const rows: [string, number][] = [['握持便利度', attributes.grip_accessibility], ['精度要求', attributes.precision], ['用力倾向', attributes.force_demand], ['摩擦依赖', attributes.friction_dependence]];
  return `<details class="hold-attributes"><summary>定线属性 <span>模板声明 · 0–1</span></summary><dl>${rows.map(([name, value]) => `<div><dt>${name}</dt><dd>${number(value, 2)}</dd></div>`).join('')}</dl><p>来源：${attributes.source === 'synthetic_assumption' ? '合成模板假设，尚未实测' : esc(attributes.source)}。属性不是该岩点固定的难度等级；方向、倾角、支撑和移动距离会共同改变动作需求。摩擦依赖仅作声明记录，未计算摩擦可行性。</p></details>`;
}

export function routeExamplesHTML(examples: StyleExample[], activeBundle?: Bundle) {
  if (!examples.length) return '';
  const first = examples[0].bundle.request;
  return `<div class="style-examples-heading"><h2>完整线路对照</h2><span>同一候选库 · 人体 ${esc(first.body.id)} · ${first.scene.angle_deg}° · ${first.hand_moves} 次移手</span></div>
    <p class="field-hint">每条线在力量、技巧与持续输出之间切换。比较目标不同，墙面、身材、起终点与搜索预算相同；需求为模型指数，需与下方独立检查一起阅读。</p>
    <div class="style-table-scroll" tabindex="0" role="region" aria-label="三条完整线路对照，可横向滚动"><table class="style-example-table route-example-table"><thead><tr><th scope="col">阶段计划</th><th scope="col">实际接触点</th><th scope="col">力量 / 技巧</th><th scope="col">单动作基线峰值</th><th scope="col">含前序负荷峰值</th><th scope="col">后段负担增量</th><th scope="col">几何与姿态</th></tr></thead><tbody>${examples.map(example => {
      const candidate = example.bundle.candidates[0];
      const ev = example.bundle.evaluations.find(item => item.candidate_id === candidate?.id);
      const a = ev?.design_analysis, h = a?.history_comparison;
      const count = new Set(candidate?.states.flatMap(state => Object.values(state.contacts).flatMap(c => c ? [c.placement_id] : []))).size;
      const active = activeBundle?.id === example.bundle.id;
      return `<tr class="${active ? 'active' : ''}"><th scope="row"><button data-action="route-example" data-id="${esc(example.id)}" aria-pressed="${active}"><strong>${esc(example.label || programNames[example.bundle.request.route_design!.program!])}</strong><span>${candidate?.events.length ?? 0} 次接触转换</span></button></th><td>${count}</td><td>${number(a?.dimensions.strength)} / ${number(a?.dimensions.technical)}</td><td>${number(h?.fresh_peak, 1)}</td><td>${number(h?.with_history_peak, 1)}</td><td>${h ? '+' : ''}${number(h?.late_move_delta, 1)}</td><td><span class="style-check ${ev?.summary.status || 'unknown'}">${esc(ev ? statusLabels[ev.summary.status] : '未检查')}</span></td></tr>`;
    }).join('')}</tbody></table></div>`;
}

const phaseKindNames: Record<string, string> = { establish: '建立', establishment: '建立', build: '进入', entry: '进入', crux: '难点', power: '力量', technical: '技巧', transition: '转换', recovery: '缓和', relief: '缓和', sustain: '持续输出', sustained: '持续输出', finish: '收尾' };
function fullRouteHTML(bundle: Bundle, candidate: Candidate, evaluation: Evaluation | undefined, stale: boolean, step: number) {
  const target = bundle.request.route_design;
  if (!target) return '';
  const a = stale ? undefined : evaluation?.design_analysis;
  const heading = `<div class="route-study-heading"><div><span class="section-label">当前线路计划</span><h2>${esc(programNames[target.program!] || '混合线路')}<span> / ${bundle.request.hand_moves} 次移手</span></h2></div><span class="small-note">${a ? `模型 ${esc(a.model_version)}` : '等待检查'}</span></div>`;
  if (!a) return `${heading}<p class="study-pending">${stale ? '当前修订已变化，旧的阶段与负荷分析已收起。重新检查后显示新版结果。' : '这条线路尚无阶段分析。运行检查后查看当前模型估计。'}</p>`;
  const activeState = candidate.states[step]?.id;
  const activeEvent = candidate.events.findIndex(event => event.to_state === activeState || event.release_state === activeState);
  const activeMove = a.moves.find(move => move.event_index === activeEvent) || a.moves[0];
  const crux = a.moves.find(move => move.event_index === a.summary.crux_event_index);
  const h = a.history_comparison;
  return `${heading}
    <div class="demand-dimensions">${dimensions.map(item => `<div title="${esc(item.explanation)}"><span>${item.name}</span><strong>${number(a.dimensions[item.key])}<small> / 100</small></strong><div class="demand-track"><i style="width:${bar(a.dimensions[item.key])}%"></i></div></div>`).join('')}</div>
    <p class="index-caption">四项为移手动作平均需求；它们可同时升高，并非必须加总到 100 的风格占比。每段目标参与选点和动作搜索。</p>
    <div class="rhythm-heading"><h3>把阶段连成一条线</h3><span>点击阶段，查看对应动作</span></div>
    <div class="full-route-phases">${a.phases.map((phase, index) => {
      const active = activeEvent >= phase.event_start && activeEvent <= phase.event_end;
      const moves = a.moves.filter(move => move.event_index >= phase.event_start && move.event_index <= phase.event_end);
      const before = moves[0]?.prior_load, after = moves.at(-1)?.accumulated_load;
      const recovery = moves.length ? moves.reduce((sum, m) => sum + (m.rest_opportunity || 0), 0) / moves.length : 0;
      return `<button class="full-route-phase ${active ? 'active' : ''}" data-action="phase" data-step="${eventStep(candidate, phase.event_start)}" aria-pressed="${active}"><span class="phase-position">${index + 1}</span><span class="full-phase-title"><strong>${esc(phase.label)}</strong><small>${esc(phaseKindNames[phase.phase_kind || ''] || phase.phase_kind || '')} · 动作 ${phase.event_start + 1}–${phase.event_end + 1}</small></span><span class="phase-targets">${dimensions.map(d => `<span><small>${d.name}</small><b>${number(phase.target[d.key])}<i> / ${number(phase.estimate[d.key])}</i></b></span>`).join('')}</span><span class="phase-history"><small>累计状态</small><strong>${number(before, 1)} → ${number(after, 1)}</strong><small>缓和机会 ${number(recovery, 2)}</small></span></button>`;
    }).join('')}</div>
    <p class="index-caption">阶段名称为设计目标，实际难点见下方曲线；“缓和”阶段不保证累计负荷净下降。每项数值为目标 / 估计。累计状态带入后续动作；缓和机会是由支撑与握持推算的模型量，不保证可以休息，也不代表真实恢复比例。</p>
    <div class="rhythm-heading"><h3>前面的消耗，如何影响后面的动作</h3><span>同一动作序列的两种计算</span></div>
    ${h ? `<div class="history-comparison"><div><span>逐动作重新从基线计算</span><strong>${number(h.fresh_peak, 1)}<small>峰值负担</small></strong></div><div><span>连续携带前序负荷</span><strong>${number(h.with_history_peak, 1)}<small>峰值负担</small></strong></div><div><span>最后三分之一移手</span><strong>+${number(h.late_move_delta, 1)}<small>平均负担增量</small></strong></div></div>` : ''}
    ${burdenChartHTML(a)}
    <div class="move-demand-list full-route-moves" tabindex="0" role="region" aria-label="逐动作负担，可横向滚动">${a.moves.map(move => `<button class="move-demand ${move.event_index === activeEvent ? 'active' : ''}" data-action="phase" data-step="${eventStep(candidate, move.event_index)}" aria-pressed="${move.event_index === activeEvent}" title="${esc(limbNames[move.limb])} → ${esc(contactName(bundle, candidate, move.to_placement_id))} · 带前序负荷 ${number(move.effective_burden ?? move.burden, 1)}"><span>${move.event_index + 1}${move.event_index === a.summary.crux_event_index ? '<b>难点</b>' : ''}</span><strong>${esc(limbNames[move.limb])}</strong><small>${esc(contactName(bundle, candidate, move.to_placement_id))}</small></button>`).join('')}</div>
    ${activeMove ? `<div class="move-explanation route-move-explanation"><strong>${activeEvent < 0 ? '下一动作 · ' : `动作 ${activeMove.event_index + 1} · `}${esc(limbNames[activeMove.limb])} → ${esc(contactName(bundle, candidate, activeMove.to_placement_id))}</strong><span>${dimensions.map(item => `${item.name} ${number(activeMove[item.key])}`).join(' · ')}</span><div class="move-history-values"><span>进入前累计 <b>${number(activeMove.prior_load, 1)}</b></span><span>基线负担 <b>${number(activeMove.fresh_burden, 1)}</b></span><span>带前序负荷 <b>${number(activeMove.effective_burden ?? activeMove.burden, 1)}</b></span><span>动作后累计 <b>${number(activeMove.accumulated_load, 1)}</b></span></div><small>跨度 / 臂长 ${number(activeMove.attributes.span_ratio, 2)} · 支撑指标 ${number(activeMove.attributes.foot_support, 2)} · 缓和机会 ${number(activeMove.rest_opportunity, 2)}</small></div>` : ''}
    ${crux ? `<p class="actual-crux"><strong>当前模型难点：动作 ${crux.event_index + 1}</strong><span>${esc(limbNames[crux.limb])} → ${esc(contactName(bundle, candidate, crux.to_placement_id))} · 负担 ${number(crux.effective_burden ?? crux.burden, 1)}</span></p>` : ''}
    <p class="index-caption">虚线将每个动作视为独立的新鲜状态；实线计算同一动作序列中前序负荷的影响。二者不是不同路线，也不是测得的疲劳、体能百分比或真实攀爬等级。</p>
    <details class="style-evidence"><summary>完整选点顺序与模型依据</summary><p class="selected-path">${esc(selectedPath(bundle, candidate))}</p>${a.limitations.map(item => `<p>${esc(item)}</p>`).join('')}<div class="search-evidence">${searchHTML(a)}</div></details>`;
}
export function burdenChartHTML(a: DesignAnalysis) {
  if (!a.moves.length) return '';
  const width = 700, height = 166, left = 37, right = 13, top = 14, bottom = 29;
  const max = Math.max(20, Math.ceil(Math.max(...a.moves.flatMap(m => [m.fresh_burden ?? m.load, m.effective_burden ?? m.burden])) / 20) * 20);
  const x = (i: number) => left + i / Math.max(a.moves.length - 1, 1) * (width - left - right);
  const y = (v: number) => top + (1 - v / max) * (height - top - bottom);
  const points = (history: boolean) => a.moves.map((m, i) => `${x(i).toFixed(1)},${y(history ? m.effective_burden ?? m.burden : m.fresh_burden ?? m.load).toFixed(1)}`).join(' ');
  const ticks = [0, max / 2, max];
  return `<div class="burden-chart"><div class="burden-chart-legend"><span class="fresh">逐动作基线</span><span class="continuous">带前序负荷</span><small>负担模型指数</small></div><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="同一线路逐动作基线与带前序负荷的需求曲线"><title>动作序列 ${a.moves.length} 步，负担模型指数范围 0 至 ${max}</title>${ticks.map(v => `<line x1="${left}" x2="${width - right}" y1="${y(v)}" y2="${y(v)}" class="chart-grid"/><text x="${left - 9}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join('')}<polyline points="${points(false)}" class="fresh-line"/><polyline points="${points(true)}" class="continuous-line"/>${a.moves.map((m, i) => `<circle cx="${x(i)}" cy="${y(m.effective_burden ?? m.burden)}" r="${m.event_index === a.summary.crux_event_index ? 4.3 : 2.3}" class="history-point"/><text x="${x(i)}" y="${height - 8}" text-anchor="middle">${m.event_index + 1}</text>`).join('')}</svg></div>`;
}
