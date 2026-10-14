import type { Bundle, Candidate, Evaluation, SettingAlternative, SettingReport, StyleExample } from './types';
import { escape as esc, holdNames, limbNames, shortHoldName, statusLabels } from './types';
import { holdAssets } from './hold-assets';
import { wallProfileNames } from './scene-palette';
import { burdenChartHTML } from './route-design';
import { mechanicsLabel, mechanicsLabels } from './mechanics';
import { roofStudyHTML } from './roof-study';

export const settingNames: Record<string, string> = { diagonal_balance: '斜向移重', opposing_sidepulls: '对向侧拉', roof_exit: '仰角转出' };
const number = (value: unknown, digits = 1) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
const text = (value: unknown) => typeof value === 'object' ? JSON.stringify(value) : String(value ?? '');
function evidenceText(value: unknown) {
  if (!value || typeof value !== 'object') return text(value);
  const values = value as Record<string, unknown>;
  const labels: Record<string, string> = { score: '几何特征指数', hand_lateral_travel_m: '移手横向累计距离（米）', mean_directional_demand: '平均方向需求', foot_hand_transfer_ratio: '移脚 / 移手次数比' };
  return Object.entries(labels).filter(([key]) => key in values).map(([key, label]) => `${label} ${number(values[key], 2)}`).join(' · ') || '按当前接触序列观察，尚未验证技巧与受力。';
}
function searchHTML(report: SettingReport) {
  const trials = Array.isArray(report.search.trials) ? report.search.trials as Record<string, unknown>[] : [];
  return `<p>试算 ${report.search.geometry_trials ?? '—'} 个摆点变体，选中第 ${typeof report.search.selected_trial === 'number' ? report.search.selected_trial + 1 : '—'} 个。只固定起点与终点，不要求固定手数或用完岩点。</p><p>${report.baseline.mechanics_summary || report.result.mechanics_summary ? '摆点变体在同一合成参数下比较各姿态与释放态的力学可行性和容量需求。' : '按已通过检查的不同走法中最低的几何特征指数选择布局。'}手脚变化指数只衡量横向移动、方向与脚步比例，不等于真人的动作质量。</p>${trials.map((trial, index) => {
    const searches = Array.isArray(trial.search) ? trial.search as Record<string, unknown>[] : [];
    const evaluations = Array.isArray(trial.evaluations) ? trial.evaluations as Record<string, unknown>[] : [];
    return `<p>变体 ${index + 1}：${trial.status === 'pass' ? '通过几何与姿态检查' : trial.status === 'fail' ? '有检查违反约束' : trial.status === 'no_sequence' ? '未搜索到完整序列' : '有检查尚无法判断'} · ${evaluations.filter(item => item.status === 'pass').length} 条走法通过复核${searches.length ? ` · 搜索累计展开 ${searches.reduce((sum, item) => sum + (typeof item.expanded === 'number' ? item.expanded : 0), 0)} 个状态` : ''}${typeof trial.character_score === 'number' ? ` · 几何特征指数 ${number(trial.character_score, 2)}` : ''}。</p>`;
  }).join('')}`;
}
const handMoves = (candidate?: Candidate) => candidate?.events.filter(event => event.limb.endsWith('H')).length ?? 0;
function name(bundle: Bundle, candidate: Candidate, id: string) {
  const placement = candidate.placements.find(item => item.id === id), hold = bundle.request.scene.inventory.find(item => item.id === placement?.inventory_id);
  return hold ? shortHoldName(hold, bundle.request.scene.inventory) : id;
}
export function settingExamplesHTML(examples: StyleExample[], activeId: string, busy: boolean, currentBundle?: Bundle) {
  const request = currentBundle?.request || examples[0]?.bundle.request;
  const source = request?.setting_design?.hold_source || (request?.scene.inventory.some(hold => hold.asset_id) ? 'assets' : 'templates');
  const missingAssets = ['jug', 'crimp', 'pinch', 'sloper', 'pocket'].filter(family => !holdAssets.some(asset => asset.family === family));
  return `<div class="setting-examples-heading"><div><span class="section-label">手脚配合与空间墙面</span><h2>三种定线实验</h2></div><p>调整位置、朝向与脚点后重新搜索走法。动作数量由搜索结果产生；允许跳点和不同解法。</p></div><div class="setting-source-options"><span>读取保存示例</span><div role="group" aria-label="切换已保存岩点来源">${([['assets', '已登记网格'], ['templates', '参数模板']] as const).map(([id, label]) => `<button data-action="setting-source" data-source="${id}" class="${source === id ? 'active' : ''}" aria-pressed="${source === id}" ${busy ? 'disabled' : ''}>${label}</button>`).join('')}</div><p>当前结果：${source === 'assets' ? '已登记外部网格与保留模板' : '参数模板'}。${source === 'assets' && missingAssets.length ? `外部资产仍缺 ${missingAssets.map(family => esc(holdNames[family])).join('、')}，本组保留对应参数模板。` : ''}两组沿用相同意图与空间原型，分别搜索点位和走法；并非同一动作的控制实验。</p></div><div class="setting-example-options">${examples.map((example, index) => {
    const candidate = example.bundle.candidates[0], report = candidate?.setting_report;
    return `<button data-action="setting-example" data-id="${esc(example.id)}" class="${example.id === activeId ? 'active' : ''}" aria-pressed="${example.id === activeId}" ${busy ? 'disabled' : ''}><span>0${index + 1}</span><strong>${esc(example.label)}</strong><small>${example.bundle.request.scene.wall_panels?.length || 1} 个墙面 · ${handMoves(candidate)} 次移手${report?.allowed_alternatives?.length ? ` · ${report.allowed_alternatives.length} 条备选走法` : ''}</small></button>`;
  }).join('')}</div>`;
}
function comparisonRow(label: string, data: SettingReport['baseline'], evaluation?: Evaluation) {
  return `<tr><th scope="row">${label}</th><td>${data.summary.hand_moves} / ${data.summary.foot_moves}</td><td>${number(data.summary.total_proxy_effort)}</td><td>${number(data.summary.peak_proxy_burden)}</td><td>${number(data.character?.score, 2)}</td><td>${evaluation ? statusLabels[evaluation.summary.status] : '—'}</td><td>${data.mechanics_summary ? mechanicsLabels[data.mechanics_summary.status] : mechanicsLabel(evaluation)}</td></tr>`;
}
function changePanelLabel(bundle: Bundle, change: SettingReport['changes'][number]) {
  if (!change.before.wall_panel_id || !change.after.wall_panel_id || change.before.wall_panel_id === change.after.wall_panel_id) return '';
  const label = (id: string) => bundle.request.scene.wall_panels?.find(panel => panel.id === id)?.label || id;
  return `安装面 ${esc(label(change.before.wall_panel_id))} → ${esc(label(change.after.wall_panel_id))} · `;
}
export function settingStudyHTML(bundle: Bundle, candidate: Candidate, evaluation: Evaluation | undefined, report: SettingReport | undefined, stage: string, alternative: SettingAlternative | undefined, step: number, canSwitch: boolean, busy: boolean, afterEvaluation?: Evaluation) {
  const program = bundle.request.setting_design?.program || report?.program || '';
  const isRoof = bundle.request.setting_design?.wall_profile === 'roof';
  const heading = `<div class="setting-study-heading"><div><span class="section-label">从摆点到试算，再返回摆点</span><h2>${esc(isRoof ? '屋檐转出 · 布局与走法对照' : settingNames[program] || program || '手脚协同实验')}</h2></div>${canSwitch ? `<div class="setting-stage-toggle" role="group" aria-label="调整前后布局"><button data-action="setting-stage" data-stage="before" class="${stage === 'before' ? 'active' : ''}" aria-pressed="${stage === 'before'}" ${busy ? 'disabled' : ''}>调整前</button><button data-action="setting-stage" data-stage="after" class="${stage !== 'before' ? 'active' : ''}" aria-pressed="${stage !== 'before'}" ${busy ? 'disabled' : ''}>调整后</button></div>` : ''}</div>`;
  if (candidate.layout_report) return `${heading}<p class="setting-layout-note"><strong>布局试案 · 尚未找到完整走法</strong><br />${esc(wallProfileNames[candidate.layout_report.wall_profile] || candidate.layout_report.wall_profile)}：${esc(candidate.layout_report.reason)}</p><p class="index-caption">画布保留全部 ${candidate.placements.length} 个真实安装位置，仅显示起始接触；没有把起点状态当作完成路线。几何、接触法向与准静态结果仍来自当前墙形。</p><details class="setting-evidence"><summary>本次搜索与边界</summary><p>${candidate.layout_report.limitations.map(esc).join(' ')}</p><pre>${esc(JSON.stringify(candidate.layout_report.search, null, 2))}</pre></details>`;
  if (!report) return `${heading}<p class="index-caption">当前点位已经修改，原来的摆点比较与备选走法不再适用于这个修订。可以重新检查当前姿态，再运行替代走法检查。</p>`;
  const analysis = alternative?.analysis || (stage === 'before' ? report.baseline_analysis : evaluation?.design_analysis);
  const currentState = candidate.states[step]?.id, eventIndex = candidate.events.findIndex(event => event.to_state === currentState || event.release_state === currentState);
  const move = analysis?.moves.find(item => item.event_index === eventIndex);
  return `${heading}<p class="setting-intent">${esc(isRoof ? '从檐前进入水平屋檐，再移向出口；比较实际手脚支撑、身体位置与带入的消耗。' : report.intent)}</p><div class="setting-stage-caption"><strong>画布：${stage === 'before' ? '调整前布局' : '调整后布局'}${alternative ? ' · 备选走法' : ' · 搜索返回走法'}</strong><span>点位变化会改变实际几何、接触步骤和姿态。</span></div>
    <div class="beta-table-scroll" role="region" aria-label="摆点前后模型比较" tabindex="0"><table class="beta-table setting-summary-table"><thead><tr><th>布局</th><th>移手 / 移脚</th><th>模型总负荷</th><th>峰值负担</th><th>手脚变化指数</th><th>几何与姿态</th><th>准静态 · 当前姿态集</th></tr></thead><tbody>${comparisonRow('调整前', report.baseline, report.baseline_evaluation)}${comparisonRow('调整后', report.result, afterEvaluation || (stage === 'after' && !alternative ? evaluation : undefined))}</tbody></table></div><p class="index-caption">手脚变化指数只反映横向移动、朝向与脚步比例。更低的总负荷不自动等于更好的线路，难点也不必对应一个唯一的接触顺序。</p>
    ${stage === 'after' && report.allowed_alternatives.length ? `<div class="setting-paths"><h3>同一布局，允许不同走法</h3><div role="group" aria-label="切换搜索走法"><button data-action="setting-path" data-id="" class="${!alternative ? 'active' : ''}" aria-pressed="${!alternative}" ${busy ? 'disabled' : ''}>生成选中的走法</button>${report.allowed_alternatives.map((item, index) => `<button data-action="setting-path" data-id="${esc(item.candidate.id)}" class="${alternative?.candidate.id === item.candidate.id ? 'active' : ''}" aria-pressed="${alternative?.candidate.id === item.candidate.id}" ${busy ? 'disabled' : ''}>${esc(item.label || `备选 ${index + 1}`)}<small>${item.summary.hand_moves} 手 / ${item.summary.foot_moves} 脚 · 几何${esc(statusLabels[item.evaluation.summary.status])}<br />准静态：${esc(mechanicsLabel(item.evaluation))}</small></button>`).join('')}</div><p class="index-caption">切换后，所有已安装岩点仍保留。灰色是当前走法没有使用的点。</p></div>` : ''}
    ${report.observed_movement_tags.length ? `<div class="setting-tags"><h3>从接触关系观察到</h3>${report.observed_movement_tags.map(tag => `<details><summary>${esc(tag.label)}</summary><p>${esc(evidenceText(tag.evidence))}</p></details>`).join('')}<p class="index-caption">这些是接触几何的特征标签；没有把“高抬脚”或“侧拉”名称当作动作已经成功的证明。</p></div>` : ''}
    ${roofStudyHTML(bundle.request, candidate, evaluation, analysis, step, busy, report, stage)}
    ${analysis ? `<div class="rhythm-heading"><h3>当前走法的连续负担估计</h3><span>按实际序列重新累计</span></div>${burdenChartHTML(analysis)}<div class="move-demand-list full-route-moves" role="region" aria-label="当前走法动作" tabindex="0">${analysis.moves.map(item => { const to = candidate.events[item.event_index]?.to_state; const index = candidate.states.findIndex(state => state.id === to); return `<button class="move-demand ${item.event_index === eventIndex ? 'active' : ''}" data-action="phase" data-step="${Math.max(0, index)}"><span>${item.event_index + 1}</span><strong>${esc(limbNames[item.limb])}</strong><small>${esc(name(bundle, candidate, item.to_placement_id))}</small></button>`; }).join('')}</div>${move ? `<p class="beta-move-details">动作 ${move.event_index + 1} · ${esc(limbNames[move.limb])} · 基线 ${number(move.fresh_burden ?? move.load)} · 带前序负荷 ${number(move.effective_burden ?? move.burden)}${move.orientation_support ? ` · 支撑与拉向附加负荷 ${number(move.orientation_support.proxy_penalty)}` : ''}</p>` : ''}<p class="index-caption">虚线对每一步清零前序负荷，实线连续带入同一走法的前序负荷。两者是模型对照，未标定为真实疲劳或体能百分比。</p>` : ''}
    <details class="setting-evidence"><summary>改了哪些点，以及搜索的边界</summary><div class="setting-changes">${report.changes.map(change => `<p><button class="text-button" data-action="select-hold" data-id="${esc(change.placement_id)}">${esc(name(bundle, candidate, change.placement_id))}</button><span>${changePanelLabel(bundle, change)}面内位置 (${number(change.before.u, 2)}, ${number(change.before.v, 2)}) → (${number(change.after.u, 2)}, ${number(change.after.v, 2)}) m · 朝向 ${number(change.before.rotation_deg, 0)}° → ${number(change.after.rotation_deg, 0)}°</span><small>${esc(change.reason)}</small></p>`).join('') || '<p>本次没有选中不同的点位变体。</p>'}</div>${searchHTML(report)}${report.limitations.map(item => `<p>${esc(item)}</p>`).join('')}<p>准静态力只针对所列姿态与合成参数。真实摩擦、完整身体碰撞与动态轨迹仍未验证；有限搜索没有找到捷径，不代表真人无法绕过。</p></details>`;
}

export function movementVocabularyHTML() {
  const layers = [
    ['岩点形态', 'Jug、Crimp、Pinch、Sloper、Pocket', '描述物体和可接触面，不等于一个固定动作。'],
    ['接触方式', '扣、捏、掌压；鞋尖、内外沿、摩擦踩点、Heel hook、Toe hook', '接触部位与方向要结合具体的抓握面、鞋面与人体姿态。'],
    ['作用方向', '下拉、Sidepull、Undercling、Gaston、对抗', '同一块岩点旋转后，可能支持不同的发力与身体位置。'],
    ['身体与接触转换', 'Flag、Backstep、Drop knee、Rock-over、Stemming、Mantle、并手、换脚', '可组合的技巧。形态、身材与手脚顺序共同影响能否使用。'],
    ['时间与动量', 'Static、Deadpoint、Dyno、Paddle、Run-and-jump、Coordination', '动态动作需要速度、接触时机与动量模型，当前还没有求解。'],
  ];
  return `<details class="movement-vocabulary"><summary><span>动作词汇如何进入定线？</span><span>五层描述 · 可以组合，不能穷尽</span></summary><p>先提出动作与体验意图，再选墙面、岩点和脚点，搜索不同走法；用试算与试爬反过来改布局。动作和岩点相互约束，不存在必须先做完其中一项的固定顺序。</p><div class="vocabulary-layers">${layers.map(([label, examples, meaning]) => `<article><h3>${label}</h3><p>${examples}</p><small>${meaning}</small></article>`).join('')}</div><p>当前模型使用接触角色、局部面方向、离散手脚转换与支撑代理量，并在合成参数下检查准静态力平衡。勾脚、膝部姿态和动态技巧仍是知识词汇，尚未作为已验证能力加入生成器。</p><p class="vocabulary-sources">资料：<a href="https://www.rei.com/learn/expert-advice/climbing-techniques.html" target="_blank" rel="noopener noreferrer">REI 动作与脚法</a> · <a href="https://www.thebmc.co.uk/en/climbing-how-to-talk-the-talk" target="_blank" rel="noopener noreferrer">BMC 攀岩术语</a> · <a href="https://movementgyms.com/baker/climbing/our-routesetting/" target="_blank" rel="noopener noreferrer">Movement 定线与复核流程</a> · <a href="https://www.epsets.com/routesetting/red-coordination" target="_blank" rel="noopener noreferrer">EP 动量与几何案例</a></p></details>`;
}
export function gymReferencesHTML() {
  const references = [
    { title: '折面与内外角', project: 'Glücksgriff', image: 'https://cdn.walltopia.com/wp-content/uploads/20231027223039/24_08_2017_BoulderhalleGlucksgriff-9-5.jpg', observation: '不同朝向的面在内角与外棱相接。点位需要属于一个局部墙面；跨面后接触方向也随之改变。' },
    { title: '曲面与洞顶', project: 'Urban Climb', image: 'https://cdn.walltopia.com/wp-content/uploads/20231030102010/UrbanClimb-24.jpg', observation: '桥状墙体包含连续变化的朝向与悬垂空间。原型目前只支持多个平面，不能代表这类连续曲面。' },
    { title: '从腹面转向上方', project: 'Touchstone · Cliffs of Id', image: 'https://cdn.walltopia.com/wp-content/uploads/20231026092409/Touchstone-Cliffs-of-id-CulverCity-CA-USA-2.jpg', observation: '同一个空间中组合下部墙面、仰角腹面、上方折面及体积块。转换需要同时考虑墙面和已安装岩点。' },
  ];
  return `<details class="competition-references gym-references"><summary><span>普通岩馆的空间与造型</span><span class="reference-summary">内角 · 外棱 · 仰角转出</span></summary><div class="reference-grid">${references.map(ref => `<article><a href="https://walltopia.com/products/boulder-walls/#design" target="_blank" rel="noopener noreferrer"><img src="${ref.image}" loading="lazy" referrerpolicy="no-referrer" alt="${ref.project} 的${ref.title}" /><span class="source-credit">Walltopia / ${ref.project}</span></a><p class="reference-event">${ref.project}</p><h3>${ref.title}</h3><p>${ref.observation}</p></article>`).join('')}</div><div class="reference-method"><p>以上照片展示空间与岩壁形状，不能从单张照片还原完整走法、精确角度或受力。原型中的墙面和线路是原创合成实验，没有从这些照片恢复尺寸。</p><a class="source-link" href="https://walltopia.com/products/boulder-walls/#design" target="_blank" rel="noopener noreferrer">查看 Walltopia 原始项目图库 ↗</a></div></details>`;
}

export function settingWorkflowHTML() {
  const steps = [
    { title: '确定简报', status: '工具中已有', implemented: true, detail: '选择目标体验与人体样例。当前以三种合成实验表达定线意图，还不是完整岩馆运营简报。' },
    { title: '确认空间与库存', status: '工具中已有', implemented: true, detail: '记录墙面的实际空间朝向、岩点形状、接触面和安装位置。现场尺寸、安装质量与缓冲地面仍需现场检查。' },
    { title: '动作意图与摆点', status: '工具中已有', implemented: true, detail: '提出动作特征，联动手点、朝向和脚点，再搜索不同走法。这里是数字摆点，实际安装仍需现场完成。' },
    { title: '计算检查', status: '工具中已有', implemented: true, detail: '检查几何、离散姿态与假设参数下的准静态力平衡，寻找替代走法。接触力尚未实测标定，也未验证连续动态与完整人体碰撞。' },
    { title: '真人试爬', status: '待现场完成', implemented: false, detail: '由具备相应能力的人员试爬，观察可达性、意外走法、动作体验与疲劳变化。计算通过不能替代这一环。' },
    { title: '另一位定线员复核', status: '待现场完成', implemented: false, detail: '独立检查线路目标与完成方式，结合不同身材、能力及现场风险复核；需要人完成判断与记录。' },
    { title: '调整与反馈', status: '设计反馈已支持', implemented: true, detail: '保存点位修订和设计意见，回到计算与试爬。页面中的反馈不是试爬记录，当前没有自动学习真实试爬结果。' },
  ];
  return `<details class="movement-vocabulary setting-workflow" id="setting-workflow"><summary><span>定线工作流</span><span>从简报到试爬与独立复核</span></summary><p>定线包含设计、制作、试爬和复核。这里把工具能提供的证据与需要现场完成的工作分开，计算报告不会生成认证或安全合格结论。</p><ol class="workflow-steps">${steps.map((item, index) => `<li><span class="workflow-order">${String(index + 1).padStart(2, '0')}</span><div><h3>${item.title}</h3><p>${item.detail}</p></div><small class="workflow-status ${item.implemented ? 'implemented' : 'onsite'}">${item.status}</small></li>`).join('')}</ol><div class="wall-height-guidance"><h3>展开长度、几何高度与标准墙高</h3><p>展开高度描述这组面板沿设计布局的长度；几何垂直高是墙面最高角点距模型地面原点的高度。倾斜、折面和转出会让两者不同。画布按实际面板角点计算几何垂直高，墙体厚度与岩点突出深度不计入这个数值。</p><p><a href="https://cdn.standards.iteh.ai/samples/39968/eb82f102549541eba9b79bad025432c2/SIST-EN-12572-2-2017.pdf" target="_blank" rel="noopener noreferrer">EN 12572-2:2017 §3.6 / §4.1</a> 的墙高从落地区顶面量到最高可抓握点，最高 4.5 m；若可站上顶部，最高 4.0 m。本模型未确定垫面和墙顶可抓性，<strong>标准墙高待现场确认</strong>。</p><p>普通岩馆规划可参考 <a href="https://walltopia.com/products/boulder-walls/" target="_blank" rel="noopener noreferrer">Walltopia 的 3–4.5 m 墙高建议</a>。其中 3 m 是厂商规划下限建议，不是该标准规定的最低墙高。本实验默认采用 4.2 m 展开布局，几何垂直高按实际角点计算；场馆仍按适用的完整标准和当地设计审查确定尺寸。</p></div><p class="workflow-profession">职业培训可参考 <a href="https://www.cwapro.org/certification-dashboard" target="_blank" rel="noopener noreferrer">CWA 的 PRS 1、PRS 2 Boulder 与 PRS 2 Ropes 培训考核</a>：除定线与试爬，也关注团队沟通和风险判断。这里借鉴工作环节，工具的计算通过不会授予定线员资格。</p><p class="vocabulary-sources">流程参考：<a href="https://movementgyms.com/baker/climbing/our-routesetting/" target="_blank" rel="noopener noreferrer">Movement：摆点、试爬与另一位定线员复核</a> · <a href="https://www.cwapro.org/certification-dashboard" target="_blank" rel="noopener noreferrer">CWA 职业定线员培训与考核</a>。</p></details>`;
}
