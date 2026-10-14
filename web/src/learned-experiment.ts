import type { Limb, Status } from './types';
import { escape as esc } from './types';

export interface LearnedRun {
  id: string;
  source: 'betazero' | 'random' | 'baseline';
  condition: string | null;
  grade: number | null;
  seed: number | null;
  pair_id: string | null;
  status: 'complete' | 'search_unresolved' | 'generation_failed';
  selected_contacts: Record<Limb, string[]>;
  metrics: Partial<Record<'hand_holds' | 'foot_holds' | 'selected_holds' | 'used_holds' | 'transfers' | 'hand_transfers' | 'foot_transfers' | 'static_release_pass' | 'static_release_total' | 'static_landed_pass' | 'static_landed_total' | 'peak_load' | 'final_load' | 'total_proxy_effort', number | null>> & { p0_status?: Status | null; skipped_holds?: string[] | number | null };
  search: Record<string, unknown>;
  adjustments: Record<string, unknown>;
  duplicate_of: string | null;
  bundle_url: string | null;
  error?: string;
  proposal?: { raw_selections?: unknown[]; [key: string]: unknown };
}
interface LearnedSummary { total: number; complete: number; p0_pass: number; unique: number; search_unresolved: number; generation_failed: number; empty_proposals?: number; no_intermediate_holds?: number }
export interface LearnedExperiment {
  schema_version: 'learned-experiment-v1';
  id: string;
  title: string;
  source: Record<string, unknown>;
  wall: { angle_deg: number; hold_count: number };
  protocol: { sample_count: number; seeds: number[]; search_seconds: number; [key: string]: unknown };
  conditions: { label: string; grade: number; representative_run_id: string | null }[];
  summary: { model: LearnedSummary; random: LearnedSummary; baseline: LearnedSummary };
  runs: LearnedRun[];
}

export const learnedSourceNames = { betazero: 'BetaZero 选点', random: '配对随机选点', baseline: '全部岩点基线' };
const statusNames = { complete: '找到完整走法', search_unresolved: '预算内未找到', generation_failed: '模型生成失败' };
const number = (value: number | null | undefined, precision = 0) => value == null || !Number.isFinite(value) ? '—' : value.toFixed(precision);
const fraction = (passed: number | null | undefined, total: number | null | undefined) => passed == null || total == null ? '—' : `${passed}/${total}`;
const geometry = (status: Status | null | undefined) => status === 'pass' ? '通过' : status === 'fail' ? '未通过' : status === 'unknown' ? '待判断' : '未检查';
const runGeometry = (run: LearnedRun) => run.status === 'complete' ? geometry(run.metrics.p0_status) : '未成线';

function summaryRow(label: string, summary: LearnedSummary) {
  return `<tr><th scope="row">${label}</th><td>${number(summary.total)}</td><td>${number(summary.complete)}</td><td>${number(summary.p0_pass)}</td><td>${number(summary.unique)}</td><td>${number(summary.search_unresolved)}</td><td>${number(summary.generation_failed)}</td></tr>`;
}
export function learnedExperimentHTML(experiment: LearnedExperiment | undefined, active: LearnedRun | undefined, open: boolean, busy: boolean, error: string) {
  const disabled = busy ? 'disabled' : '';
  const shortSummary = open && experiment ? `${number(experiment.summary.model.total)} 个模型样本 · 完整走法 ${number(experiment.summary.model.complete)}${experiment.summary.model.empty_proposals == null ? '' : ` · 原始空选点 ${number(experiment.summary.model.empty_proposals)}`}` : '固定墙面与岩点，比较模型、随机和全部岩点。';
  const heading = `<div class="learned-entry-heading"><div><h2>学习生成对照</h2><p>${shortSummary}</p></div><button class="button outlined" data-action="learned-open" ${disabled}>${open ? '重新读取' : '打开保存实验'}</button></div>`;
  const message = error ? `<p class="learned-error" role="status">${esc(error)}</p>` : '';
  if (!open || !experiment) return heading + message;
  const selectedCondition = active?.condition;
  const emptyProposals = experiment.summary.model.empty_proposals;
  return `${heading}${message}<details class="learned-batch"><summary>查看学习实验对照与全部样本</summary><div class="learned-overview"><p class="learned-protocol">${number(experiment.wall.angle_deg)}° 单面墙 · ${number(experiment.wall.hold_count)} 个已安装岩点 · ${number(experiment.protocol.sample_count)} 个模型样本 · 每方案最多 ${number(experiment.protocol.search_seconds)} 秒。选点不规定动作顺序，走法由独立搜索产生。</p>
    ${emptyProposals == null ? '' : `<p class="learned-result-note">模型原始选点为空 ${number(emptyProposals)} / ${number(experiment.summary.model.total)}；起终点由 bettar 统一补入。${experiment.summary.model.complete === 0 ? '这批模型候选尚未找到完整走法，可切换“全部岩点基线”查看对照。' : ''}</p>`}
    <div class="learned-conditions" role="group" aria-label="查看模型条件代表案例">${experiment.conditions.map(condition => `<button data-action="learned-run" data-run-id="${esc(condition.representative_run_id)}" class="${selectedCondition === condition.label ? 'active' : ''}" aria-pressed="${selectedCondition === condition.label}" ${busy || !condition.representative_run_id ? 'disabled' : ''}><strong>${esc(condition.label)}</strong><span>模型条件 · 代表案例</span></button>`).join('')}</div>
    <p class="learned-condition-note">V3 / V4 / V5 是模型输入条件，尚未通过真人试攀定级。</p>
    <div class="learned-table-scroll" tabindex="0" role="region" aria-label="整批实验统计，可横向滚动"><table class="learned-table"><caption>全部样本统计 · 包含失败结果</caption><thead><tr><th scope="col">选点来源</th><th scope="col">样本</th><th scope="col">完整走法</th><th scope="col">几何通过</th><th scope="col">不同选点</th><th scope="col">搜索未决</th><th scope="col">生成失败</th></tr></thead><tbody>${summaryRow('BetaZero', experiment.summary.model)}${summaryRow('数量匹配随机', experiment.summary.random)}${summaryRow('全部岩点', experiment.summary.baseline)}</tbody></table></div>
    <div class="learned-table-scroll" tabindex="0" role="region" aria-label="全部实验记录，可横向滚动"><table class="learned-table learned-runs"><caption>全部 ${experiment.runs.length} 条记录与失败结果</caption><thead><tr><th scope="col">查看方案</th><th scope="col">条件 / 种子</th><th scope="col">搜索结果</th><th scope="col">选点 / 使用</th><th scope="col">几何</th><th scope="col">释放态</th><th scope="col">峰值负荷</th><th scope="col">重复</th></tr></thead><tbody>${experiment.runs.map(run => `<tr class="${active?.id === run.id ? 'active' : ''}"><th scope="row"><button data-action="learned-run" data-run-id="${esc(run.id)}" aria-pressed="${active?.id === run.id}" ${disabled}>${learnedSourceNames[run.source]}</button></th><td>${esc(run.condition || '—')} / ${run.seed ?? '—'}</td><td>${statusNames[run.status]}</td><td>${number(run.metrics.selected_holds)} / ${number(run.metrics.used_holds)}</td><td>${runGeometry(run)}</td><td>${fraction(run.metrics.static_release_pass, run.metrics.static_release_total)}</td><td>${number(run.metrics.peak_load, 2)}</td><td>${run.duplicate_of ? `<span title="${esc(run.duplicate_of)}">重复选点</span>` : '—'}</td></tr>`).join('')}</tbody></table></div><p class="learned-condition-note">“预算内未找到”不表示不可攀；重复项保留在样本总数中。几何通过不等于受力检查通过。</p></div></details>`;
}

export function pairedLearnedRun(experiment: LearnedExperiment, run: LearnedRun) {
  return experiment.runs.find(item => item.id === run.pair_id || (item.pair_id === run.pair_id && item.source !== run.source && item.source !== 'baseline'));
}
export function learnedRunHTML(experiment: LearnedExperiment, run: LearnedRun, busy: boolean, comparisonRun = run) {
  const pair = pairedLearnedRun(experiment, comparisonRun), baseline = experiment.runs.find(item => item.source === 'baseline');
  const metrics = run.metrics;
  const originalCount = run.proposal?.raw_selections?.length;
  const sources = comparisonRun.source === 'baseline' ? [run] : [comparisonRun, pair, baseline].filter((item): item is LearnedRun => !!item).sort((a, b) => ['betazero', 'random', 'baseline'].indexOf(a.source) - ['betazero', 'random', 'baseline'].indexOf(b.source));
  const links = sources.map(item => `<button data-action="learned-run" data-run-id="${esc(item.id)}" class="${item.id === run.id ? 'active' : ''}" aria-pressed="${item.id === run.id}" ${busy ? 'disabled' : ''}>${learnedSourceNames[item.source]}</button>`).join('');
  return `<div class="learned-run-heading"><div><span class="section-label">保存实验 · ${esc(run.condition || '全部岩点')} ${run.seed == null ? '' : `· 种子 ${run.seed}`}</span><h2>${learnedSourceNames[run.source]}</h2></div><span class="learned-status ${run.status}">${statusNames[run.status]}</span></div>
    <div class="learned-comparison-switch" role="group" aria-label="相同岩壁的选点对照">${links}</div>
    <p class="learned-run-note">${run.status === 'generation_failed' ? `生成失败，未用规则结果替代模型。${esc(run.error || '详细原因见实验记录。')}` : run.status === 'search_unresolved' ? `本次搜索预算内未找到完整走法。场景只显示安装布局与起始接触，不代表这些点不可攀。${run.error ? ` ${esc(run.error)}` : ''}` : '下方回放展示独立搜索找到的手脚序列；允许跳过候选点。亮色为允许使用的岩点，淡色岩点仍保留在墙上并参与碰撞检查。'}</p>
    ${run.source === 'betazero' && originalCount != null ? `<p class="learned-result-note">模型原始选点 ${originalCount} 个；下方允许点数包含 bettar 补入的固定起终点。${originalCount === 0 ? '当前亮色起终点不是模型生成的完整线路。' : ''}</p>` : ''}
    <dl class="learned-metrics"><div><dt>选中 / 实际使用 / 跳过</dt><dd>${number(metrics.selected_holds)} / ${number(metrics.used_holds)} / ${number(Array.isArray(metrics.skipped_holds) ? metrics.skipped_holds.length : metrics.skipped_holds)}</dd></div><div><dt>移手 / 移脚</dt><dd>${number(metrics.hand_transfers)} / ${number(metrics.foot_transfers)}</dd></div><div><dt>几何检查</dt><dd>${runGeometry(run)}</dd></div><div><dt>释放 / 落点静态通过</dt><dd>${fraction(metrics.static_release_pass, metrics.static_release_total)} · ${fraction(metrics.static_landed_pass, metrics.static_landed_total)}</dd></div><div><dt>峰值 / 最终负荷</dt><dd>${number(metrics.peak_load, 2)} / ${number(metrics.final_load, 2)}</dd></div><div><dt>累计动作代价</dt><dd>${number(metrics.total_proxy_effort, 2)}</dd></div></dl>
    <p class="learned-condition-note">负荷与动作代价是合成模型中的相对数值，尚未以真人疲劳标定。${run.duplicate_of ? `此选点组合与 ${esc(run.duplicate_of)} 重复，仍保留计数。` : ''}</p>
    <details class="learned-provenance"><summary>模型来源、选点调整与搜索记录</summary><p>原始模型只提供岩点集合与角色；固定起终点由 bettar 补入。该补入不属于模型能力。</p><pre>${esc(JSON.stringify({ run_id: run.id, source: experiment.source, proposal: run.proposal, selected_contacts: run.selected_contacts, adjustments: run.adjustments, search: run.search, error: run.error }, null, 2))}</pre></details>`;
}
