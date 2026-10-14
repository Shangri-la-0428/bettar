import './style.css';
import './workbench.css';
import { timelineNavigation } from './timeline-navigation';
import { scanWorkbenchHTML, mountScanWorkbench } from './scan-model';
import { mechanicsHTML } from './mechanics';
import { WallView } from './scene';
import { inversePoint, placementFrame, wallFrame, panelFrame, wallHeightMeasures } from './placement-geometry';
import { boardReferences, competitionReferences } from './competition-references';
import { HoldPreview, holdThumbnail } from './hold-preview';
import { holdAssetDetailsHTML, resolveHoldAsset } from './hold-assets';
import { defaultPaletteId, getScenePalette, presentationHold, scenePalettes, wallProfileNames } from './scene-palette';
import { holdAttributesHTML, rhythmNames, routeDesignHTML, styleExamplesHTML, styleNames, routeExamplesHTML, programNames } from './route-design';
import { betaAuditHTML, betaPathCount } from './beta-audit';
import { settingExamplesHTML, settingStudyHTML, settingNames, movementVocabularyHTML, gymReferencesHTML, settingWorkflowHTML } from './setting-design';
import { learnedExperimentHTML, learnedRunHTML, learnedSourceNames } from './learned-experiment';
import type { LearnedExperiment, LearnedRun } from './learned-experiment';
import { contactPresentation, ownRouteChoicesHTML, ownRouteDetailHTML, readOwnRouteBundle } from './own-route-study';
import type { OwnRouteStudy, OwnRoute } from './own-route-study';
import type { BetaAudit, Bundle, Candidate, Defaults, Evaluation, Placement, Request, Review, Status, StyleExample, SettingReport } from './types';
import { escape as esc, holdDisplayName, holdFamily, holdRoleName, holdNames, limbNames, limbs, shortHoldName, statusLabels } from './types';

const icons: Record<string, string> = {
  move: '<path d="M12 3v18M3 12h18m-12-6 3-3 3 3m-9 3-3 3 3 3m3 3 3 3 3-3m3-9 3 3-3 3"/>',
  cursor: '<path d="m5 3 14 9-7 1-3 7-4-17Z"/>',
  focus: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/><circle cx="12" cy="12" r="3"/>',
  import: '<path d="M12 3v12m-4-4 4 4 4-4M4 15v5h16v-5"/>',
  export: '<path d="M12 16V4m-4 4 4-4 4 4M4 15v5h16v-5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5M5.4 8a7 7 0 0 1 11.8-2L20 9M4 15l2.8 3A7 7 0 0 0 18.6 16"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  cross: '<path d="m6 6 12 12M18 6 6 18"/>',
  question: '<path d="M9 8a3 3 0 0 1 6 0c0 2-3 2-3 4M12 16v.1"/><circle cx="12" cy="12" r="9"/>',
  minus: '<path d="M5 12h14"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  cube: '<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Zm0 9 8-4.5M12 12 4 7.5M12 12v9"/>',
  front: '<rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 8h.1M15 8h.1M9 13h.1M15 13h.1M9 18h.1M15 18h.1"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v.1"/>',
};
const icon = (name: string, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${icons[name] || icons.info}</svg>`;
const statusIcon = (status: Status) => icon(status === 'pass' ? 'check' : status === 'fail' ? 'cross' : status === 'unknown' ? 'question' : 'minus');

document.querySelector<HTMLDivElement>('#app')!.innerHTML = `
  <header class="app-header">
    <a class="brand" href="/" aria-label="bettar 定线工作台">
      <span class="brand-mark">${icon('cube')}</span>
      <span><span class="brand-name">bettar</span><span class="brand-caption">定线工作台</span></span>
    </a>
    <label class="draft-switcher"><span class="sr-only">切换草稿</span><select id="draft-picker" aria-label="切换草稿"><option>读取草稿…</option></select></label>
    <div class="header-actions">
      <button class="button quiet" data-action="tools" aria-controls="tools-view" aria-expanded="false">更多</button>
      <button class="button outlined" data-action="export-bundle" disabled>${icon('export')}<span>保存</span></button>
    </div>
  </header>
  <main>
    <div id="notice" class="notice" role="alert" hidden></div>
    <section id="workbench-view" aria-label="定线工作台">
      <h1 class="sr-only">定线工作台</h1>
    <div class="workspace">
      <section class="design-area" aria-label="候选与三维场景">
        <div class="canvas-toolbar" aria-label="移动岩点" hidden><span id="tool-status" class="tool-status">拖动岩点调整位置</span><button class="button outlined" data-action="browse-mode">完成移动</button></div>
        <div class="canvas-shell">
          <div id="wall-view" class="wall-view"></div>
          <div class="canvas-top"><div class="scene-meta"><span id="scene-title">3D 场景</span><span id="scene-subtitle">等待本地数据</span></div><div class="view-controls"><details class="display-settings"><summary>显示</summary><div class="display-settings-content">          <label class="palette-control">配色<select id="scene-palette" aria-label="场景配色，仅影响展示" title="仅影响展示，不改变几何、受力或计算指纹">${scenePalettes.map(palette => `<option value="${palette.id}">${palette.label}</option>`).join('')}</select></label>

          <div class="route-controls"><label><input id="route-only" type="checkbox" checked />仅显示当前线路</label><label><input id="show-surfaces" type="checkbox" />抓握面与方向</label><label><input id="route-path" type="checkbox" />手点顺序连线</label></div><div class="canvas-toggles"><label><input id="show-labels" type="checkbox" title="常显手点编号；脚点编号在选中或当前接触时显示" />编号</label><label><input id="show-body" type="checkbox" />计算姿态</label></div></div></details><button class="view-button" data-action="front" title="正视图" aria-label="正视图">${icon('front')}</button><button class="view-button active" data-action="perspective" title="三维视角" aria-label="三维视角">${icon('cube')}</button></div></div>
          <div id="canvas-empty" class="canvas-empty"><span class="loading-spinner"></span><h2>正在打开工作台</h2><p>读取场景与已检查的示例</p></div>
          <div id="pose-status" class="pose-status" hidden></div>
          <div class="canvas-bottom"><div id="canvas-legend" class="canvas-legend"><span><i class="dot jug"></i>大把手</span><span><i class="dot edge"></i>方向边缘点</span><span><i class="dot foot"></i>脚点</span></div></div>
          <div id="canvas-hint" class="canvas-hint">点岩点调整 · 拖动空白旋转</div>
        </div>
        <div class="workbench-bottom"><button id="open-replay" class="button primary" data-action="open-replay" disabled>看走法</button>
        <section class="timeline" aria-label="动作回放" hidden>
          <div class="timeline-header"><span id="step-count" class="muted">等待草稿</span><div class="step-controls"><button class="button quiet" data-action="previous" aria-label="上一步" disabled>${icon('chevron', 'reverse')}</button><button class="button outlined" data-action="next" aria-label="下一步" disabled>${icon('chevron')}</button><button class="button quiet" data-action="close-replay" aria-label="收起走法">${icon('cross')}</button></div></div>
        </section><button id="quick-check" class="button quiet" data-action="checks" disabled>查看检查</button></div>
      </section>
      <aside class="inspector" hidden aria-label="编辑与检查">
        <div class="inspector-heading"><h2>调整岩点</h2><span id="revision-badge" class="small-badge">—</span></div>
        <section id="editor-section" class="edit-section" aria-label="选中岩点近看与编辑"><div class="section-heading"><h3 id="selected-hold-title">选择岩点</h3><button class="text-button" data-action="close-editor" aria-label="关闭岩点编辑">收起</button></div><div id="hold-editor"><p class="muted">点击画布或下方岩点库选择岩点。</p></div><details class="model-details"><summary>岩点资料</summary><div id="hold-preview" class="hold-preview" aria-label="选中岩点三维近看，可拖动旋转"></div><span id="hold-model-kind" class="small-note">程序示意模型</span><div id="hold-asset-details"></div><p class="model-limit">接触与受力属性待实测。</p><p id="hold-model-scope">原创参数模板，不是真实岩点扫描。浅色区域为声明接触面；每个动作引用具体接触面；同一岩点可以先抓握、再踩其声明的脚面。每个面以代表点计算姿态。朝向与安装关系会进入几何计算。抓握面上的白色箭头是声明拉向；“显示求解的力”中的箭头来自独立准静态报告。尚未搜索面内任意抓握位置。</p></details></section>
      </aside>
    </div>
    </section>
    <section id="checks-view" hidden aria-labelledby="checks-title"><div class="tools-heading"><h1 id="checks-title" tabindex="-1">草稿检查</h1><button class="button outlined" data-action="workbench">返回岩壁</button></div>
        <section class="inspector-section check-section"><div id="summary" class="summary-panel"><p class="muted">选择方案后查看计算结果。</p></div></section>
        <div class="candidates-bar">
          <div class="candidate-title"><span class="section-label">方案</span><span id="candidate-count" class="count">—</span></div>
          <div id="candidates" class="candidate-tabs" role="tablist" aria-label="候选方案"></div>

        </div>
        <section id="own-route-detail" class="own-route-detail" aria-label="当前规则线路的实际走法" hidden></section>
<details class="checks-disclosure"><summary>检查明细 <span id="check-count" class="small-note"></span>${icon('chevron', 'details-chevron')}</summary><div id="checks" tabindex="0" aria-label="检查明细，可滚动"></div></details>
        <details class="analysis-disclosure"><summary>更多分析</summary>        <section id="learned-study" class="learned-study" aria-label="当前学习生成实验与配对对照" hidden></section>
        <details class="mechanics-disclosure"><summary>受力、摩擦与支撑检查<span>展开查看模型估计与具体状态</span></summary><section id="mechanics-study" class="mechanics-study" aria-label="准静态受力与摩擦检查" hidden></section></details>
        <section id="setting-study" class="setting-study" aria-label="摆点调整与备选走法" hidden></section>
        <section id="beta-audit" class="beta-audit" aria-label="线路合理性与替代走法检查" hidden></section>
        <section id="design-brief" class="design-brief" aria-label="线路设计意图" hidden></section>
        <section id="route-study" class="route-study" aria-label="风格估计与阶段节奏" hidden></section>
<div id="route-inventory-summary" class="route-inventory-summary"></div></details>
<div id="move-state-switch" class="move-state-switch"></div>          <details class="contact-disclosure"><summary>手脚接触明细</summary><div id="steps" class="step-list"></div><div id="movement-intent" class="movement-intent" hidden></div><div id="contact-strip" class="contact-strip"></div><p class="timeline-note">按离散姿态查看，连续动作未验证。</p></details>
    </section>
    <section id="tools-view" hidden aria-labelledby="tools-title">
      <div class="tools-heading"><h1 id="tools-title" tabindex="-1">工具与资料</h1><button class="button outlined" data-action="workbench">返回岩壁 ${icon('chevron')}</button></div>
      <div class="draft-toolbar" hidden>
        <form id="draft-form"><label class="wall-choice">墙面<select id="draft-wall"><option value="own-overhang">25° 仰角</option><option value="roof">屋檐</option><option value="dihedral">内角</option><option value="arete">外角</option></select></label></form>
        <section id="own-route-choices" class="own-route-section" aria-label="选择线路草稿"></section>
      </div>
      <div class="file-tools"><button class="button outlined" data-action="import">${icon('import')}导入草稿</button><button class="button quiet" data-action="export-review" disabled>导出反馈</button>          <label class="history-control" title="切换本次会话中的结果包"><span class="sr-only">结果包历史</span><select id="history" aria-label="结果包历史" disabled><option>当前实验</option></select></label></div>
              <details class="hold-library">
          <summary><span>岩点库 <span id="library-count" class="count">16</span></span><span class="library-description">当前合成库存 · 程序示意模型</span>${icon('chevron', 'details-chevron')}</summary>
          <div class="library-content"><p class="library-taxonomy-note">手点按抓握家族区分；手／脚是动作中的用途，同一个岩点可以兼用。体积块单独作为结构，能否接触以所选表面的声明为准。</p><div id="library-filters" class="library-filters" role="group" aria-label="筛选岩点类型"><button data-action="hold-filter" data-type="all" aria-pressed="true" class="active">全部</button><button data-action="hold-filter" data-type="jug" aria-pressed="false">大把手</button><button data-action="hold-filter" data-type="directional_edge" aria-pressed="false">方向边缘点</button><button data-action="hold-filter" data-type="foothold" aria-pressed="false">脚点</button></div><div id="stock-summary" class="stock-summary" hidden></div><div id="hold-library-grid" class="hold-library-grid"></div></div>
        </details>

      <details class="tool-group"><summary>版本对照与反馈</summary>        <section class="inspector-section"><div class="section-heading"><h3>方案对照</h3><span class="small-note">保留同一视角</span></div><label class="sr-only" for="compare">选择对照方案</label><select id="compare" class="full-select" disabled><option value="">不叠加对照</option></select><div id="comparison-detail"></div></section>
        <section class="inspector-section limits-section"><h3>目前未验证</h3><div id="limits"></div><p>几何与姿态结果不等于真人能够完成，也不代表攀爬等级。</p></section>
        <section class="inspector-section review-section"><div class="section-heading"><h3>设计反馈</h3><span class="small-note">不是试爬记录</span></div><label class="sr-only" for="review-text">反馈内容</label><textarea id="review-text" rows="3" placeholder="例如：下一手点偏远，想试试先调整右脚。"></textarea><button class="button outlined full-width" data-action="save-review" disabled>保存这条反馈</button><div id="review-list"></div></section>
</details>
<details class="intent-notes"><summary>定线意图备注</summary><p>仅作为备注，不改变已保存草稿。</p><label class="control">线路风格<select id="draft-style"><option value="mixed">对比三种思路</option><option value="power">力量</option><option value="balance">技巧与平衡</option><option value="sustained">持续输出</option></select></label><label class="control">目标难度<select id="draft-grade"><option value="ungraded">待试攀定级</option><option value="V3">V3 · 意图</option><option value="V4">V4 · 意图</option><option value="V5">V5 · 意图</option></select></label><p id="draft-condition-note"></p><div id="draft-context" hidden></div></details>    <details class="advanced-generation"><summary>高级生成与研究参数<span>人体、库存、摆点与搜索实验</span></summary>
    <section class="setup-strip" aria-labelledby="setup-title">
      <div class="setup-title"><h2 id="setup-title">定线研究</h2><p>下一次生成的条件</p></div>
      <form id="generation-form" class="generation-form">
        <label class="control profile-control">工作场景<select id="profile" name="profile"><option value="setting">手脚协同摆点</option><option value="route">完整混合线路</option><option value="style">四手风格实验</option><option value="catalog">标准模板岩点库</option><option value="competition">竞赛风格研究</option><option value="basic">基础算法算例</option></select></label>
        <label class="control wall-profile-control" hidden>墙形<select id="wall-profile" name="wall_profile">${Object.entries(wallProfileNames).map(([id, label]) => `<option value="${id}">${label}</option>`).join('')}</select></label>
        <label class="control hold-source-control" hidden>岩点来源<select id="hold-source" name="hold_source"><option value="assets">已登记网格</option><option value="templates">参数模板</option></select></label>
        <label class="control route-program-control" hidden>线路计划<select id="route-program" name="route_program"><option value="compare">对比三条线路</option>${Object.entries(programNames).map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}</select></label>
        <label class="control style-goal-control" hidden>生成目标<select id="style-goal" name="style_goal"><option value="compare">对比三种风格</option>${Object.entries(styleNames).map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}</select></label>
        <label class="control scenario-control">动作情境<select id="scenario" name="scenario" disabled><option>加载中</option></select></label>
        <label class="control">人体样例<select id="body" name="body" disabled><option>A</option></select></label>
        <label class="control">墙面角度<select id="angle" name="angle"><option value="0">垂直 · 0°</option><option value="10">仰角 · 10°</option></select></label>
        <label class="control">布局方式<select id="mode" name="mode"><option value="free">自由摆点</option><option value="fixed">固定点位</option></select></label>
        <label class="control compact">手部移动<select id="hand-moves" name="hand_moves"><option value="2">2 次</option><option value="3">3 次</option><option value="4">4 次</option></select></label>
        <label class="control rhythm-control" hidden>阶段节奏<select id="rhythm" name="rhythm">${Object.entries(rhythmNames).map(([value, label]) => `<option value="${value}" ${value === 'late_crux' ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
        <label class="control seed-control">随机种子<input id="seed" name="seed" type="number" step="1" value="42" required /></label>
        <button id="generate-button" class="button primary" type="submit" disabled>${icon('plus')}生成线路实验</button>
      </form>
    </section>
    <details id="catalog-setup" class="catalog-setup" hidden>
      <summary><span>模拟岩馆库存</span><span class="small-note">标准模板库 v1 · 数量用于下一次生成</span>${icon('chevron', 'details-chevron')}</summary>
      <div id="catalog-quantities" class="catalog-quantities"></div>
      <p>每件岩点有独立库存编号，同型号共享形状与接触面。数量不足时会提示；修改这里不会改变当前方案。</p>
    </details>
    </details>
    <details class="historical-experiments"><summary>历史模型实验 · BetaZero<span>暂停使用，仅保留已保存记录</span></summary><section id="learned-experiment" class="learned-experiment" aria-label="历史学习生成对照"></section></details>
    <details class="saved-reference-drafts"><summary>其他规则草稿与墙形</summary><p id="reference-load-status" class="field-hint" hidden></p>
    <section id="wall-examples" class="wall-examples" aria-label="查看已保存墙形实验" hidden></section>
    <section id="setting-examples" class="setting-examples" aria-label="手脚协同摆点实验" hidden></section>
    <section id="style-examples" class="style-examples" aria-label="同墙风格示例对照" hidden></section>
    </details>
    <section id="scan-workbench">${scanWorkbenchHTML()}</section>
    ${settingWorkflowHTML()}
    ${movementVocabularyHTML()}
    ${gymReferencesHTML()}
    <details class="competition-references" id="competition-references">
      <summary><span>比赛参考与差距</span><span class="reference-summary">世界杯 · 世锦赛 · 3 个真实案例</span>${icon('chevron', 'details-chevron')}</summary>
      <div class="reference-grid">${competitionReferences.map(ref => `<article><a href="${ref.url}" target="_blank" rel="noopener noreferrer"><img src="${ref.image}" loading="lazy" referrerpolicy="no-referrer" alt="${ref.event}：${ref.title}" /><span class="source-credit">${ref.credit}</span></a><p class="reference-event">${ref.event}</p><h3>${ref.title}</h3><p>${ref.observation}</p><a class="source-link" href="${ref.url}" target="_blank" rel="noopener noreferrer">查看原始照片 ↗</a></article>`).join('')}</div>
      <div class="reference-method"><h3>从动作意图到候选线路</h3><p>风格研究在同一面固定墙上搜索选点和手脚动作，再按目标风格与阶段节奏排序、复核。基础和竞赛算例保留模板变体。当前用合成人体质量和摩擦参数做准静态检查，尚未实现连续动态轨迹，也不保证自动找出所有解法。</p><p><a class="source-link" href="https://www.flathold.com/obsessed/" target="_blank" rel="noopener noreferrer">Flathold：从五步动态动作构想开发岩点</a> · <a class="source-link" href="https://research.aalto.fi/en/publications/discovering-and-synthesizing-humanoid-climbing-movements/" target="_blank" rel="noopener noreferrer">Naderi 等：接触图与采样优化</a></p><p>照片用于研究对照，版权归原作者；本页远程引用，不随原型打包。三维案例是原创合成方案，未从照片恢复尺寸，也不是赛事原线复刻。</p></div>
    </details>
    <details class="competition-references board-references" id="board-references">
      <summary><span>固定训练板参考</span><span class="reference-summary">布局、朝向与反馈</span>${icon('chevron', 'details-chevron')}</summary>
      <div class="board-intro"><p>比赛帮助我们研究动作与体量；训练板帮助我们控制变量、复现线路。两者共用接触与动作问题，但固定板需要先锁定位置和朝向。</p><button class="button outlined" data-action="board-study">设置固定布局条件</button></div>
      <div class="board-comparison">${boardReferences.map(ref => `<article><h3><a href="${ref.url}" target="_blank" rel="noopener noreferrer">${ref.name} ↗</a></h3><p>${ref.lesson}</p><p><span>原型下一步</span>${ref.gap}</p></article>`).join('')}</div>
      <p class="board-limit">A 板的具体品牌／型号待确认。这里借鉴固定布局、条件控制和反馈机制，尚未导入真实品牌布局、岩点模型或社区线路。风格研究在原创合成固定板上搜索选点与动作。</p>
    </details>
    </section>
    <footer class="app-footer"><span>定线草稿 · 需定线员调整与试攀</span><span id="run-meta">bettar / 0.1</span></footer>
  </main>
  <input id="import-file" type="file" accept=".json,application/json" hidden />
  <div id="toast" class="toast" role="status" aria-live="polite" hidden></div>
`;

const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
document.body.classList.add('distilled');
function showScreen(screen: 'workbench' | 'tools' | 'checks', focus = true) {
  for (const name of ['workbench', 'tools', 'checks']) $(`#${name}-view`).hidden = name !== screen;
  document.body.classList.toggle('at-workbench', screen === 'workbench');
  const toggle = $<HTMLButtonElement>('[data-action="tools"]');
  toggle.setAttribute('aria-expanded', String(screen === 'tools')); toggle.textContent = screen === 'tools' ? '返回岩壁' : '更多';
  if (focus) (screen === 'workbench' ? $('#draft-picker') : $(`#${screen}-title`)).focus({ preventScroll: true });
  if (focus) window.scrollTo({ top: 0, behavior: 'auto' });
}
function showWorkspace(tools = false, focus = true) { showScreen(tools ? 'tools' : 'workbench', focus); }
document.body.classList.add('at-workbench');
mountScanWorkbench($('#scan-workbench'));
let defaults: Defaults | undefined;
let bundle: Bundle | undefined;
let activeId = '';
let step = 0;
let replayOpen = false;
let selectedHold = '';
let selectedInventory = '';
let holdFilter = 'all';
let editMode = false;
let preview: HoldPreview | undefined;
let previewKey = '';
const thumbnailCache = new Map<string, string>();
let compareId = '';
let busy = false;
let view: WallView | undefined;
let toastTimer = 0;
const histories: Bundle[] = [];
let styleExamples: StyleExample[] = [];
let routeExamples: StyleExample[] = [];
let settingExamples: StyleExample[] = [];
let wallExamples: StyleExample[] = [];
let learnedExperiment: LearnedExperiment | undefined;
let learnedOpen = false;
let learnedError = '';
let activeLearnedRunId = '';
let learnedComparisonId = '';
const learnedBundles = new Map<string, Bundle>();
let ownRouteStudy: OwnRouteStudy | undefined;
let activeOwnRouteId = '';
let ownRouteError = '';
const ownRouteBundles = new Map<string, Bundle>();
const ownRouteStyleIds: Record<string, string> = { mixed: 'lateral-balance', balance: 'lateral-balance', power: 'compact-strength', sustained: 'sustained-transfer' };
const draftStyleNames: Record<string, string> = { mixed: '对比三种思路', power: '力量', balance: '技巧与平衡', sustained: '持续输出', coordination: '动态协调' };
let activeDraftIntent: { style: string; grade: string; wall: string; learned: boolean } | undefined;
try { const saved = localStorage.getItem('bettar.draft-style'); if (saved && ownRouteStyleIds[saved]) $<HTMLSelectElement>('#draft-style').value = saved; } catch { /* Intent storage is optional. */ }
let palette = getScenePalette(defaultPaletteId);
try { palette = getScenePalette(localStorage.getItem('betar.scene-palette') || defaultPaletteId); } catch { /* Storage is optional; rendering remains local. */ }
$<HTMLSelectElement>('#scene-palette').value = palette.id;
const settingBeforeBundles = new Map<string, { bundle: Bundle; exampleId: string; candidateId: string }>();
let settingAlternativeId = '';
let betaReport: BetaAudit | undefined;
let betaSelectedId = '';
let betaAuditing = false;
let betaInvalidated = false;
let betaError = '';
let originalStep = 0;
let originalRouteOnly = true;
let showForces = false;
const scenarioNames: Record<string, string> = { foot_first: '脚先移动，再抬手', sidepull: '侧拉横移', foot_reposition: '脚点重定位', competition_sequence: '侧拉、转移与收尾', style_search: '四手风格搜索', route_search: '完整混合线路', setting_search: '手脚协同摆点' };

try {
  view = new WallView($('#wall-view'), (id) => selectPlacement(id), (id, u, v) => {
    if (busy || bundle?.request.mode === 'fixed' || !editMode) { updateScene(); return; }
    savePlacementRevision(id, { u, v }, '拖动');
  });
  view.setBody(false);
  view.setRouteOnly(true);
  preview = new HoldPreview($('#hold-preview'));
}
catch (error) { showNotice(`三维画布无法启动：${error instanceof Error ? error.message : String(error)}。请使用支持 WebGL 的浏览器。`); }

function sourceCandidate(): Candidate | undefined { return bundle?.candidates.find((candidate) => candidate.id === activeId); }
function selectedBeta() { return betaReport?.alternatives.find(item => item.id === betaSelectedId); }
function settingContext() {
  const before = [...settingBeforeBundles.values()].find(item => item.bundle.id === bundle?.id);
  const example = [...settingExamples, ...wallExamples].find(item => before ? item.id === before.exampleId : item.bundle.id === bundle?.id);
  const originCandidate = before ? example?.bundle.candidates.find(item => item.id === before.candidateId) : sourceCandidate();
  return example ? { example, originCandidate, stage: before ? 'before' : 'after' } : undefined;
}
function activeSettingReport(): SettingReport | undefined {
  const context = settingContext();
  return context?.stage === 'before' && sourceCandidate()?.id === context.originCandidate?.setting_report?.baseline_candidate.id
    ? context.originCandidate?.setting_report : sourceCandidate()?.setting_report;
}
function selectedSettingAlternative() { return activeSettingReport()?.allowed_alternatives?.find(item => item.candidate.id === settingAlternativeId); }
function viewingAlternative() { return !!selectedBeta() || !!selectedSettingAlternative(); }
function current(): Candidate | undefined { return selectedSettingAlternative()?.candidate || selectedBeta()?.candidate || sourceCandidate(); }
function activeLearnedRun() { return learnedExperiment?.runs.find(run => run.id === activeLearnedRunId); }
function activeOwnRoute() { return ownRouteStudy?.routes.find(route => route.id === activeOwnRouteId); }
function clearOwnRoute() { activeOwnRouteId = ''; ownRouteError = ''; }
function clearLearnedExperiment() { activeLearnedRunId = ''; learnedComparisonId = ''; learnedOpen = false; learnedError = ''; }
function syncWallChoice(request: Request) {
  const wallSelect = $<HTMLSelectElement>('#draft-wall');
  wallSelect.querySelector('option[value="current"]')?.remove();
  const wallProfile = request.setting_design?.wall_profile;
  const wallValue = wallProfile === 'overhang' ? 'own-overhang' : wallProfile;
  if (wallValue && [...wallSelect.options].some(option => option.value === wallValue)) wallSelect.value = wallValue;
  else { wallSelect.add(new Option(`当前墙面 · ${request.scene.angle_deg}°`, 'current')); wallSelect.value = 'current'; }
}
function syncDraftPicker() {
  const picker = $<HTMLSelectElement>('#draft-picker');
  const routes = ownRouteStudy?.routes || [];
  const value = activeOwnRouteId && !viewingAlternative() ? `own:${activeOwnRouteId}` : 'current';
  const name = viewingAlternative() ? '备选走法' : (current()?.name || '选择一份草稿').replace(/ · 修改 \d+$/, '');
  picker.innerHTML = `${value === 'current' ? `<option value="current">${esc(name)}${current() ? ` · 修订 ${current()!.revision}` : ''}</option>` : ''}<optgroup label="25° 仰角">${routes.map(route => `<option value="own:${esc(route.id)}">${esc(route.label)} · 25°</option>`).join('')}</optgroup><optgroup label="其他墙形"><option value="wall:roof">屋檐</option><option value="wall:dihedral">内角</option><option value="wall:arete">外角</option></optgroup>`;
  picker.value = value; picker.disabled = busy;
}
async function chooseDraft() {
  if (busy) return;
  const value = $<HTMLSelectElement>('#draft-picker').value;
  if (value.startsWith('own:')) await openOwnRouteStudy(value.slice(4));
  else if (value.startsWith('wall:')) await loadWallExample(value.slice(5));
  syncDraftPicker();
}
function syncDraftControls() {
  $<HTMLSelectElement>('#draft-wall').disabled = busy;
  syncDraftPicker();
  $('#draft-condition-note').textContent = '难度由定线员试攀后确认。';
}
function renderDraftContext() {
  const host = $('#draft-context'); host.hidden = !bundle;
  if (!bundle) return;
  const run = activeLearnedRun(), own = activeOwnRoute();
  const wallName = bundle.request.setting_design?.wall_profile ? wallProfileNames[bundle.request.setting_design.wall_profile] : `${bundle.request.scene.angle_deg}° 单面墙`;
  const source = own ? own.label : run ? learnedSourceNames[run.source] : bundle.request.route_constraints ? '限定选点草稿' : '规则草稿';
  host.innerHTML = `<strong>当前草稿</strong><span>${esc(wallName || '单面墙')} · ${esc(source)}${run?.condition ? ` · ${esc(run.condition)} 模型条件` : ''}</span>${activeDraftIntent ? `<span>意图：${esc(draftStyleNames[activeDraftIntent.style])}${activeDraftIntent.grade !== 'ungraded' ? ` · ${esc(activeDraftIntent.grade)}` : ''}</span><small>${own ? '风格映射到已保存的摆点与搜索目标；目标等级不参与计算，待试攀确认。' : '这份已有草稿未按上方风格或目标等级重新生成。'}</small>` : own ? '<small>手与脚按每个动作的接触面区分；允许先抓、后踩同一个岩点。</small>' : '<small>上方条件用于下一次查看草稿。</small>'}`;
}
async function viewIntentDraft(event: Event) {
  event.preventDefault(); if (busy) return;
  const style = $<HTMLSelectElement>('#draft-style').value, grade = $<HTMLSelectElement>('#draft-grade').value, wall = $<HTMLSelectElement>('#draft-wall').value;
  if (wall === 'current') return;
  const previous = bundle;
  if (wall === 'own-overhang') await openOwnRouteStudy(ownRouteStyleIds[style]);
  else await loadWallExample(wall);
  if (bundle) syncWallChoice(bundle.request);
  if (bundle && bundle !== previous) {
    activeDraftIntent = { style, grade, wall, learned: false };
    renderDraftContext();
    showWorkspace(false, false);
  }
}
function renderOwnRouteStudy() {
  syncDraftPicker();
  const choices = $('#own-route-choices');
  choices.hidden = !!bundle && bundle.request.setting_design?.wall_profile !== 'overhang';
  choices.innerHTML = ownRouteChoicesHTML(ownRouteStudy, activeOwnRouteId, busy, ownRouteError);
  const host = $('#own-route-detail'), opened = host.querySelector<HTMLDetailsElement>('.own-route-disclosure')?.open;
  const route = activeOwnRoute(), candidate = current();
  host.hidden = !route || !bundle || !candidate || viewingAlternative();
  host.innerHTML = !host.hidden && route && bundle && candidate ? ownRouteDetailHTML(route, bundle, candidate, evaluation(), isStale(), ownRouteStudy) : '';
  const details = host.querySelector<HTMLDetailsElement>('.own-route-disclosure'); if (details && opened) details.open = true;
}
async function readOwnRoute(route: OwnRoute) {
  const path = `/api/own-routes-study/routes/${encodeURIComponent(route.id)}`;
  const loaded = await readOwnRouteBundle(route, ownRouteBundles, () => api<Bundle>(path));
  const preserveView = !!activeOwnRouteId;
  acceptBundle(structuredClone(loaded), true, !preserveView);
  activeOwnRouteId = route.id; ownRouteError = '';
  $<HTMLSelectElement>('#draft-wall').value = 'own-overhang';
  const style = Object.entries(ownRouteStyleIds).find(([key, value]) => key !== 'mixed' && value === route.id)?.[0];
  if (style) $<HTMLSelectElement>('#draft-style').value = style;
  renderAll();
}
async function openOwnRouteStudy(routeId?: string) {
  if (busy) return;
  setBusy(true, '读取规则线路…'); ownRouteError = '';
  try {
    if (!ownRouteStudy) {
      const next = await api<OwnRouteStudy>('/api/own-routes-study');
      if (next.schema_version !== 'own-routes-study-v1' || !Array.isArray(next.routes)) throw new Error('规则线路记录的格式无法识别。');
      ownRouteStudy = next; ownRouteBundles.clear();
    }
    const route = ownRouteStudy.routes.find(item => item.id === routeId) || ownRouteStudy.routes[0];
    if (!route) throw new Error('尚无保存的规则线路。');
    await readOwnRoute(route);
  } catch (error) { ownRouteError = `线路未切换：${error instanceof Error ? error.message : String(error)}。当前场景保持不变。`; showNotice(ownRouteError); }
  finally { setBusy(false); renderOwnRouteStudy(); }
}
function renderLearnedExperiment() {
  const host = $('#learned-experiment'), recordsOpen = host.querySelector<HTMLDetailsElement>('.learned-records')?.open, batchOpen = host.querySelector<HTMLDetailsElement>('.learned-batch')?.open;
  host.innerHTML = learnedExperimentHTML(learnedExperiment, activeLearnedRun(), learnedOpen, busy, learnedError);
  const records = host.querySelector<HTMLDetailsElement>('.learned-records'); if (records && recordsOpen) records.open = true;
  const batch = host.querySelector<HTMLDetailsElement>('.learned-batch'); if (batch && batchOpen) batch.open = true;
  const study = $('#learned-study'), provenanceOpen = study.querySelector<HTMLDetailsElement>('.learned-provenance')?.open;
  const run = activeLearnedRun(); study.hidden = !run || !learnedExperiment;
  study.innerHTML = run && learnedExperiment ? learnedRunHTML(learnedExperiment, run, busy, learnedExperiment.runs.find(item => item.id === learnedComparisonId)) : '';
  const provenance = study.querySelector<HTMLDetailsElement>('.learned-provenance'); if (provenance && provenanceOpen) provenance.open = true;
}
async function readLearnedRun(run: LearnedRun) {
  if (!run.bundle_url) throw new Error(`${run.error || '该记录没有可加载的结果包。'} 当前场景保持不变；失败记录已保留在全部样本统计中。`);
  if (!run.bundle_url.startsWith('/api/learned-experiment/runs/')) throw new Error('实验返回了无法识别的结果包路径。');
  const loaded = learnedBundles.get(run.id) || await api<Bundle>(run.bundle_url);
  learnedBundles.set(run.id, loaded);
  const comparisonId = run.source === 'baseline' ? learnedComparisonId : run.id;
  const draftIntent = activeDraftIntent;
  // Cached saved evidence stays immutable when a displayed bundle receives edits.
  acceptBundle(structuredClone(loaded), true, !activeLearnedRunId, run.id);
  if (draftIntent?.learned) activeDraftIntent = { ...draftIntent, grade: run.condition || draftIntent.grade };
  learnedComparisonId = comparisonId || run.id;
  learnedOpen = true; learnedError = '';
  renderAll();
}
async function openLearnedExperiment(condition?: string) {
  if (busy) return;
  setBusy(true, '读取学习生成对照…'); learnedError = '';
  try {
    const next = await api<LearnedExperiment>('/api/learned-experiment');
    if (next.schema_version !== 'learned-experiment-v1' || !Array.isArray(next.runs) || !Array.isArray(next.conditions) || !next.summary) throw new Error('保存实验的格式无法识别。');
    learnedExperiment = next; learnedBundles.clear(); learnedOpen = true;
    const id = (next.conditions.find(item => item.label === condition && item.representative_run_id) || next.conditions.find(item => item.representative_run_id))?.representative_run_id;
    const run = next.runs.find(item => item.id === id) || next.runs.find(item => item.bundle_url);
    if (run) await readLearnedRun(run);
    else learnedError = '尚无可展示的结果包。失败结果保留在下方记录中，当前场景保持不变。';
  } catch (error) { learnedError = `实验未切换：${error instanceof Error ? error.message : String(error)} 可重新读取；其他工作台功能不受影响。`; }
  finally { setBusy(false); renderLearnedExperiment(); }
}
async function selectLearnedRun(id: string) {
  const run = learnedExperiment?.runs.find(item => item.id === id); if (!run || busy) return;
  setBusy(true, '读取保存方案…'); learnedError = '';
  try { await readLearnedRun(run); }
  catch (error) { learnedError = `方案未切换：${error instanceof Error ? error.message : String(error)}`; }
  finally { setBusy(false); renderLearnedExperiment(); }
}
function selectSettingExample(id: string, stage = 'after') {
  const example = [...settingExamples, ...wallExamples].find(item => item.id === id); if (!example || busy) return;
  const context = settingContext();
  const chosen = context?.example.id === id && context.originCandidate?.setting_report ? context.originCandidate : example.bundle.candidates[0];
  const report = chosen?.setting_report;
  const resetView = context?.example.id !== id;
  if (stage === 'before' && report) {
    const key = `${example.bundle.id}:${chosen.id}`;
    if (!settingBeforeBundles.has(key)) settingBeforeBundles.set(key, { exampleId: id, candidateId: chosen.id, bundle: { ...example.bundle, id: `${example.bundle.id}-before-${chosen.id}`, candidates: [report.baseline_candidate], evaluations: [report.baseline_evaluation], reviews: [] } });
    const beforeBundle = settingBeforeBundles.get(key)!.bundle;
    acceptBundle(beforeBundle, !histories.includes(beforeBundle), resetView);
  } else {
    acceptBundle(example.bundle, !histories.includes(example.bundle), resetView);
    if (chosen && chosen.id !== activeId) { activeId = chosen.id; renderAll(); }
  }
}
async function loadWallExample(profile: string) {
  if (busy) return;
  setBusy(true, '读取墙形试案…'); $('#notice').hidden = true;
  try {
    let example = wallExamples.find(item => item.bundle.request.setting_design?.wall_profile === profile);
    if (!example) {
      const response = await api<{ examples: StyleExample[] }>(`/api/wall-examples?wall_profile=${encodeURIComponent(profile)}`);
      example = response.examples?.find(item => item.bundle.request.setting_design?.wall_profile === profile);
      if (example) wallExamples.push(example);
    }
    if (!example) throw new Error('这个墙形还没有已保存的结果包。');
    acceptBundle(example.bundle, !histories.includes(example.bundle));
    toast(example.bundle.candidates[0]?.layout_report ? '已读取真实墙形与安装布局；当前尚未找到完整走法。' : '已读取墙形实验及对应检查结果。');
  } catch (error) { showNotice(`墙形未切换：${error instanceof Error ? error.message : error}`); }
  finally { setBusy(false); renderSettingStudy(); }
}
async function loadSettingSource(source: 'assets' | 'templates') {
  if (busy) return;
  const program = bundle?.request.setting_design?.program;
  setBusy(true, '读取已保存示例…'); $('#notice').hidden = true;
  try {
    const response = await api<{ examples: StyleExample[] }>(`/api/setting-examples?hold_source=${source}`);
    if (!response.examples?.length) throw new Error('这组岩点来源还没有已保存示例。');
    settingExamples = response.examples; settingBeforeBundles.clear();
    const next = settingExamples.find(item => item.bundle.request.setting_design?.program === program) || settingExamples[0];
    acceptBundle(next.bundle);
    toast('已读取保存示例；两组按相同意图独立搜索，不是同一动作的控制实验。');
  } catch (error) { showNotice(`示例未切换：${error instanceof Error ? error.message : error}`); }
  finally { setBusy(false); renderSettingStudy(); }
}
function selectSettingPath(id: string) {
  if (busy || (id && !activeSettingReport()?.allowed_alternatives.some(item => item.candidate.id === id))) return;
  if (selectedBeta()) selectBeta('');
  if (!settingAlternativeId && id) { originalStep = step; originalRouteOnly = $<HTMLInputElement>('#route-only').checked; }
  settingAlternativeId = id; editMode = false; compareId = ''; step = id ? 0 : originalStep;
  if (id) clearLearnedExperiment();
  $<HTMLInputElement>('#route-only').checked = id ? false : originalRouteOnly;
  showWorkspace(false); renderAll();
}
function renderMechanics() {
  const candidate = current(), host = $('#mechanics-study');
  const assumptionsOpen = host.querySelector<HTMLDetailsElement>('.mechanics-assumptions')?.open;
  host.hidden = !candidate || !bundle;
  host.innerHTML = !host.hidden && candidate ? mechanicsHTML(candidate, evaluation(), step, isStale(), showForces, !!bundle?.request.mechanics_parameters) : '';
  const assumptions = host.querySelector<HTMLDetailsElement>('.mechanics-assumptions'); if (assumptions && assumptionsOpen) assumptions.open = true;
  $('#show-forces')?.addEventListener('change', event => { showForces = (event.target as HTMLInputElement).checked; view?.setForces(showForces); renderMechanics(); });
}
function renderSettingStudy() {
  const context = settingContext(), candidate = current(), host = $('#setting-study'), list = $('#setting-examples');
  const wallHost = $('#wall-examples'); wallHost.hidden = bundle?.request.profile !== 'setting';
  wallHost.innerHTML = wallHost.hidden ? '' : `<span>查看墙形试案</span><div role="group" aria-label="读取已保存墙形">${Object.entries(wallProfileNames).filter(([id]) => id !== 'default').map(([id, label]) => `<button data-action="wall-example" data-wall-profile="${id}" class="${bundle?.request.setting_design?.wall_profile === id ? 'active' : ''}" aria-pressed="${bundle?.request.setting_design?.wall_profile === id}" ${busy ? 'disabled' : ''}>${label}</button>`).join('')}</div><small>读取真实布局与检查结果；未找到完整走法时保留布局试案。</small>`;
  list.hidden = bundle?.request.profile !== 'setting' || !settingExamples.length;
  list.innerHTML = list.hidden ? '' : settingExamplesHTML(settingExamples, context?.example.id || '', busy, bundle);
  host.hidden = bundle?.request.profile !== 'setting' || !candidate || !!selectedBeta() || !!bundle?.request.route_constraints;
  const evidenceOpen = host.querySelector<HTMLDetailsElement>('.setting-evidence')?.open;
  host.innerHTML = !host.hidden && bundle && candidate ? settingStudyHTML(bundle, candidate, evaluation(), activeSettingReport(), context?.stage || 'after', selectedSettingAlternative(), step, !!context && !!activeSettingReport(), busy, context?.example.bundle.evaluations.find(item => item.candidate_id === context.originCandidate?.id)) : '';
  const evidence = host.querySelector<HTMLDetailsElement>('.setting-evidence'); if (evidence && evidenceOpen) evidence.open = true;
}
function clearBetaAudit() {
  betaInvalidated = !!betaReport || betaInvalidated;
  if (settingAlternativeId) { step = originalStep; $<HTMLInputElement>('#route-only').checked = originalRouteOnly; settingAlternativeId = ''; }
  if (betaSelectedId) { step = originalStep; $<HTMLInputElement>('#route-only').checked = originalRouteOnly; }
  betaReport = undefined; betaSelectedId = ''; betaError = '';
}
function renderBetaAudit() {
  const candidate = sourceCandidate(), host = $('#beta-audit');
  host.hidden = !bundle || !candidate || !!candidate.layout_report || !['route', 'setting'].includes(bundle.request.profile || '');
  if (host.hidden || !bundle || !candidate) { host.innerHTML = ''; return; }
  const evidenceOpen = host.querySelector<HTMLDetailsElement>('.beta-audit-evidence')?.open;
  host.innerHTML = betaAuditHTML(bundle, candidate, betaReport, selectedBeta(), busy, betaAuditing, betaInvalidated, betaError, step);
  const evidence = host.querySelector<HTMLDetailsElement>('.beta-audit-evidence');
  if (evidence && evidenceOpen) evidence.open = true;
}
async function auditBeta() {
  const candidate = sourceCandidate(); if (!bundle || !candidate || busy) return;
  if (selectedBeta()) selectBeta('');
  if (selectedSettingAlternative()) selectSettingPath('');
  const workingBundle = bundle;
  betaError = ''; betaAuditing = true; setBusy(true, '检查替代走法…'); renderBetaAudit();
  try {
    const report = await api<BetaAudit>('/api/beta-audit', { request: workingBundle.request, candidate });
    if (bundle !== workingBundle || sourceCandidate()?.id !== candidate.id) return;
    if (report.schema_version !== 'beta-audit/1' || report.source.candidate_id !== candidate.id || report.source.revision !== candidate.revision) throw new Error('审计结果与当前候选不匹配，请重新检查。');
    betaReport = report; betaInvalidated = false;
    toast(report.alternatives.length ? `已返回 ${report.alternatives.length} 个目标结果，共 ${betaPathCount(report)} 条不同接触序列。` : '本次预算内未找到通过复核的替代走法；不代表没有捷径。');
  } catch (error) { betaError = `替代走法检查未完成：${error instanceof Error ? error.message : String(error)}`; }
  finally { betaAuditing = false; setBusy(false); renderAll(); }
}
function selectBeta(id: string) {
  if (busy || (id && !betaReport?.alternatives.some(item => item.id === id))) return;
  if (settingAlternativeId) selectSettingPath('');
  if (!betaSelectedId && id) { originalStep = step; originalRouteOnly = $<HTMLInputElement>('#route-only').checked; }
  settingAlternativeId = '';
  betaSelectedId = id; editMode = false; compareId = '';
  if (id) clearLearnedExperiment();
  step = id ? 0 : originalStep;
  $<HTMLInputElement>('#route-only').checked = id ? false : originalRouteOnly;
  showWorkspace(false); renderAll();
}

function evaluation(candidate = current()): Evaluation | undefined {
  if (candidate && selectedSettingAlternative()?.candidate.id === candidate.id) return selectedSettingAlternative()!.evaluation;
  if (candidate && selectedBeta()?.candidate.id === candidate.id) return selectedBeta()!.evaluation;
  return candidate ? bundle?.evaluations.filter((item) => item.candidate_id === candidate.id).at(-1) : undefined;
}
function isStale(candidate = current()) { return !!candidate && !!candidate.parent_id && !evaluation(candidate); }
function statusText(ev = evaluation()): string {
  if (isStale()) return '已修改，等待重新检查';
  if (current()?.layout_report) return '布局试案 · 尚未找到完整走法';
  if (!ev) return '尚无检查结果';
  return ev.summary.status === 'pass' ? '几何与姿态检查通过' : ev.summary.status === 'fail' ? '有违反条件的项目' : '有项目无法判断';
}
function showNotice(message: string) {
  $('#notice').hidden = false;
  $('#notice').innerHTML = `${icon('info')}<span>${esc(message)}</span><button class="icon-button" data-action="dismiss-notice" aria-label="关闭提示">${icon('cross')}</button>`;
}
function toast(message: string) {
  clearTimeout(toastTimer); $('#toast').textContent = message; $('#toast').hidden = false;
  toastTimer = window.setTimeout(() => { $('#toast').hidden = true; }, 4200);
}
async function api<T>(path: string, data?: unknown): Promise<T> {
  const response = await fetch(path, data === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  const raw = await response.text();
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { throw new Error('本地服务没有返回有效 JSON，请检查 Python 服务是否已启动。'); }
  if (!response.ok) throw new Error((parsed as { error?: string }).error || `请求失败（${response.status}）`);
  return parsed as T;
}
function setBusy(value: boolean, label?: string) {
  busy = value;
  const setting = $<HTMLSelectElement>('#profile').value === 'setting';
  const pendingLabel = label || (setting ? '搜索摆点与走法…' : '生成候选中…');
  $('#generate-button').innerHTML = value ? `<span class="loading-spinner small"></span>${esc(pendingLabel)}` : setting ? `${icon('plus')}重新生成三条实验` : `${icon('plus')}生成 ${bundle?.request.budget || defaults?.request.budget || 3} 个候选`;
  $('#generation-form').querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLSelectElement>('input,button,select').forEach((el) => { el.disabled = value || !defaults; });
  document.querySelectorAll<HTMLButtonElement>('[data-action="recheck"], [data-action="save-edit"]').forEach((button) => { button.disabled = value; });
  document.querySelectorAll<HTMLButtonElement>('[data-action="candidate"], [data-action="style-example"], [data-action="route-example"], [data-action="setting-example"], [data-action="setting-stage"], [data-action="setting-path"], [data-action="setting-source"], [data-action="wall-example"], [data-action="import"], [data-action="save-review"]').forEach((button) => { button.disabled = value || (button.dataset.action !== 'import' && !bundle); });
  document.querySelectorAll<HTMLButtonElement>('[data-action="export-bundle"], [data-action="export-review"]').forEach((button) => { button.disabled = value || !bundle; });
  $<HTMLSelectElement>('#history').disabled = value || histories.length < 2;
  document.querySelectorAll<HTMLInputElement>('[form="generation-form"]').forEach(input => { input.disabled = value || !defaults; });
  syncProfileControls();
  syncDraftControls();
  syncToolState();
  renderEditor(); renderBetaAudit(); renderLearnedExperiment(); renderOwnRouteStudy(); renderSteps();
}

function syncProfileControls() {
  const profile = $<HTMLSelectElement>('#profile').value;
  const competition = profile === 'competition', catalog = profile === 'catalog', style = profile === 'style', route = profile === 'route', setting = profile === 'setting';
  $('#catalog-setup').hidden = !catalog;
  $('.style-goal-control').hidden = !style;
  $('.route-program-control').hidden = !route;
  $('.hold-source-control').hidden = !setting;
  $('.wall-profile-control').hidden = !setting;
  $<HTMLSelectElement>('#wall-profile').disabled = busy || !defaults || !setting;
  $<HTMLSelectElement>('#hold-source').disabled = busy || !defaults || !setting;
  $('.rhythm-control').hidden = !style;
  $('.scenario-control').hidden = style || route || setting;
  $<HTMLSelectElement>('#mode').closest<HTMLElement>('label')!.hidden = style || route || setting;
  $<HTMLSelectElement>('#hand-moves').closest<HTMLElement>('label')!.hidden = style || setting;
  $<HTMLSelectElement>('#angle').closest<HTMLElement>('label')!.hidden = setting;
  $<HTMLSelectElement>('#style-goal').disabled = busy || !defaults || !style;
  $<HTMLSelectElement>('#route-program').disabled = busy || !defaults || !route;
  $<HTMLSelectElement>('#rhythm').disabled = busy || !defaults || !style;
  const angle = $<HTMLSelectElement>('#angle'), previousAngle = Number(angle.value);
  const nextAngle = Number.isFinite(previousAngle) ? Math.max(0, Math.min(style || route ? 40 : 10, previousAngle)) : 0;
  angle.innerHTML = [...new Set([...(style || route ? [0, 10, 20, 30, 40] : [0, 10]), nextAngle])].sort((a, b) => a - b).map(value => `<option value="${value}">${value === 0 ? '垂直 · 0°' : `仰角 · ${value}°`}</option>`).join('');
  angle.value = String(nextAngle);
  angle.disabled = busy || !defaults || setting;
  document.querySelectorAll<HTMLInputElement>('[form="generation-form"]').forEach(input => { input.disabled = busy || !defaults || !catalog; });
  const options = competition ? [{ id: 'competition_sequence', label: '侧拉、转移与收尾' }] : (defaults?.scenarios || []).filter(item => !['competition_sequence', 'route_search', 'style_search', 'setting_search'].includes(item.id));
  const select = $<HTMLSelectElement>('#scenario'), previous = select.value;
  select.innerHTML = options.map(item => `<option value="${esc(item.id)}">${esc(item.label)}</option>`).join('');
  if (options.some(item => item.id === previous)) select.value = previous;
  select.disabled = busy || !defaults || competition || style || route || setting;
  const moves = $<HTMLSelectElement>('#hand-moves'), previousMoves = Number(moves.value), allowedMoves = route ? [8, 10, 12] : [2, 3, 4];
  moves.innerHTML = allowedMoves.map(value => `<option value="${value}">${value} 次</option>`).join('');
  moves.value = String(competition || style ? 4 : allowedMoves.includes(previousMoves) ? previousMoves : route ? 10 : 4);
  moves.disabled = busy || !defaults || competition || style || setting;
  $<HTMLSelectElement>('#mode').disabled = busy || !defaults || style || route || setting;
  if (!busy) $('#generate-button').innerHTML = `${icon('plus')}${setting ? '重新生成三条实验' : route && $<HTMLSelectElement>('#route-program').value === 'compare' ? '生成线路对照' : style && $<HTMLSelectElement>('#style-goal').value === 'compare' ? '生成风格对照' : `生成 ${plannedBudget()} 个候选`}`;
}
function plannedBudget() {
  return $<HTMLSelectElement>('#profile').value === 'competition' && $<HTMLSelectElement>('#mode').value === 'fixed' ? 1 : defaults?.request.budget || 3;
}
function renderCatalogSetup(request: Request) {
  const stock = new Map(request.scene.catalog_stock?.map(item => [item.type, item.count]));
  $('#catalog-quantities').innerHTML = (defaults?.catalog_templates || []).map(item => `<label>${esc(item.template_name)}<span>${Math.round(item.width * 1000)} × ${Math.round(item.height * 1000)} mm</span><input type="number" name="stock_${esc(item.type)}" form="generation-form" aria-label="${esc(item.template_name)}库存数量" min="${item.min_count}" max="${item.max_count}" step="1" value="${stock.get(item.type) ?? item.default_count}" required /></label>`).join('');
}
function renderBrief() {
  const brief = bundle?.request.design_brief, host = $('#design-brief');
  host.hidden = !brief || ['style', 'route', 'setting'].includes(bundle?.request.profile || '');
  if (host.hidden || !brief) { host.innerHTML = ''; return; }
  host.innerHTML = `<div class="brief-heading"><div><span class="section-label">设计意图 · 待试爬</span><h2>${esc(brief.title)}</h2></div><a href="#competition-references" data-action="show-references">查看比赛参考 ↗</a></div><p>${esc(brief.intent)}</p><div class="phase-list">${brief.phases.map((phase, i) => `<button data-action="phase" data-step="${(phase.event_start === 0 ? 0 : phase.event_start * 2 + 1)}"><span>${String(i + 1).padStart(2, '0')}</span><strong>${esc(phase.label)}</strong><small>${esc(phase.intent)}</small></button>`).join('')}</div><p class="brief-limit">${esc(brief.disclaimer)}${bundle?.request.mode === 'fixed' ? ' 固定布局目前只复核同一接触序列，尚未实现训练板选点与多线路搜索。' : ''}</p>`;
}
function renderMovementIntent() {
  const brief = bundle?.request.design_brief, host = $('#movement-intent');
  if (['style', 'route', 'setting'].includes(bundle?.request.profile || '')) { host.hidden = true; host.innerHTML = ''; return; }
  const eventIndex = Math.max(0, Math.ceil(step / 2) - 1);
  const phase = brief?.phases.find(item => eventIndex >= item.event_start && eventIndex <= item.event_end);
  host.hidden = !phase;
  host.innerHTML = phase ? `<strong>${esc(phase.label)}</strong><span>${esc(phase.intent)}</span><small>意图说明；未验证受力与连续运动</small>` : '';
}
function renderStyleStudy() {
  const host = $('#route-study'), candidate = current();
  const evidenceOpen = host.querySelector<HTMLDetailsElement>('.style-evidence')?.open;
  host.hidden = viewingAlternative() || bundle?.request.profile === 'setting' || !bundle?.request.route_design || !candidate;
  host.innerHTML = !host.hidden && bundle && candidate && bundle.request.route_design ? routeDesignHTML(bundle, candidate, evaluation(), isStale(), step) : '';
  const evidence = host.querySelector<HTMLDetailsElement>('.style-evidence');
  if (evidence && evidenceOpen) evidence.open = true;
  const examples = $('#style-examples');
  const fullRoute = bundle?.request.profile === 'route';
  examples.setAttribute('aria-label', fullRoute ? '完整线路示例对照' : '同墙风格示例对照');
  const list = fullRoute ? routeExamples : styleExamples;
  examples.hidden = !['style', 'route'].includes(bundle?.request.profile || '') || list.length === 0;
  examples.innerHTML = examples.hidden ? '' : fullRoute ? routeExamplesHTML(list, bundle) : styleExamplesHTML(list, bundle);
}

function populateControls(request: Request) {
  const scenarios = defaults?.scenarios?.length ? defaults.scenarios : Object.entries(scenarioNames).map(([id, label]) => ({ id, label, description: '' }));
  $('#scenario').innerHTML = scenarios.map((item) => `<option value="${esc(item.id)}">${esc(item.label || scenarioNames[item.id])}</option>`).join('');
  $('#body').innerHTML = (defaults?.body_profiles || [request.body]).map((body) => `<option value="${esc(body.id)}">样例 ${esc(body.id)}</option>`).join('');
  $('#scenario').setAttribute('title', '改变条件后点击生成；当前结果保持原有条件。');
  $('#scenario').removeAttribute('disabled'); $('#body').removeAttribute('disabled');
  $<HTMLSelectElement>('#profile').value = request.profile || 'basic';
  $<HTMLSelectElement>('#style-goal').value = request.route_design?.style_goal || 'compare';
  $<HTMLSelectElement>('#route-program').value = request.route_design?.program || 'compare';
  $<HTMLSelectElement>('#rhythm').value = request.route_design?.rhythm || 'late_crux';
  renderCatalogSetup(request);
  syncProfileControls();
  $<HTMLSelectElement>('#scenario').value = request.scenario;
  $<HTMLSelectElement>('#body').value = request.body.id;
  const angle = $<HTMLSelectElement>('#angle');
  if (![...angle.options].some(option => Number(option.value) === request.scene.angle_deg)) angle.add(new Option(`仰角 · ${request.scene.angle_deg}°`, String(request.scene.angle_deg)));
  angle.value = String(request.scene.angle_deg);
  $<HTMLSelectElement>('#mode').value = request.mode;
  $<HTMLSelectElement>('#hand-moves').value = String(request.hand_moves);
  $<HTMLInputElement>('#seed').value = String(request.seed);
  $<HTMLSelectElement>('#hold-source').value = request.setting_design?.hold_source === 'templates' ? 'templates' : 'assets';
  $<HTMLSelectElement>('#wall-profile').value = request.setting_design?.wall_profile || 'default';
  setBusy(false);
}

function acceptBundle(next: Bundle, addHistory = true, resetView = true, learnedRunId = '') {
  clearBetaAudit();
  clearOwnRoute();
  if (!next.request || !Array.isArray(next.candidates) || !Array.isArray(next.evaluations)) throw new Error('结果包缺少场景、候选或评价数据。');
  if (!learnedRunId) clearLearnedExperiment();
  else activeLearnedRunId = learnedRunId;
  activeDraftIntent = undefined;
  bundle = next;
  showWorkspace(false, $('#workbench-view').hidden);
  replayOpen = false; $<HTMLInputElement>('#show-body').checked = false;
  syncWallChoice(next.request);
  if (addHistory) histories.push(next);
  activeId = next.candidates[0]?.id || ''; step = 0; selectedHold = ''; selectedInventory = ''; compareId = ''; editMode = false; holdFilter = !next.candidates[0]?.layout_report && ['route', 'setting'].includes(next.request.profile || '') ? 'route' : 'all';
  $('#review-text').textContent = ''; $<HTMLTextAreaElement>('#review-text').value = '';
  populateControls(next.request);
  $('#canvas-empty').hidden = next.candidates.length > 0;
  if (!next.candidates.length) $('#canvas-empty').innerHTML = `<h2>没有生成候选</h2><p>当前条件下没有可展示的方案，可调整条件后重试。</p>`;
  $<HTMLInputElement>('#show-surfaces').checked = next.request.profile === 'catalog';
  $<HTMLInputElement>('#route-only').checked = next.request.profile !== 'setting';
  renderAll();
  if (resetView) {
    view?.perspective();
    document.querySelectorAll('.view-button').forEach(button => button.classList.toggle('active', (button as HTMLElement).dataset.action === 'perspective'));
  }
}

function renderAll() {
  ensureSelection();
  renderCandidates(); renderSummary(); renderEditor(); renderLibrary(); renderChecks(); renderSteps(); renderComparison(); renderReviews(); renderBrief(); renderStyleStudy(); renderRouteInventory(); renderBetaAudit(); renderSettingStudy(); renderMechanics(); renderLearnedExperiment(); renderOwnRouteStudy(); renderDraftContext(); updateScene(); syncToolState();
  document.querySelectorAll<HTMLButtonElement>('[data-action="export-bundle"], [data-action="export-review"], [data-action="save-review"]').forEach((button) => { button.disabled = busy || !bundle || (button.dataset.action === 'save-review' && viewingAlternative()); });
  const candidate = current();
  $('#revision-badge').textContent = candidate ? `修订 ${candidate.revision}${viewingAlternative() ? ' · 替代走法' : ''}` : '—';
  if (bundle) {
    const r = bundle.request;
    $('#scene-title').textContent = viewingAlternative() ? `同一岩壁 · ${selectedBeta()?.label || selectedSettingAlternative()?.label || '备选走法'}` : r.profile === 'setting' ? (r.setting_design?.wall_profile === 'roof' ? '水平屋檐 · 出檐手脚配合' : settingNames[r.setting_design?.program || ''] || '手脚协同摆点') : r.profile === 'route' ? '当前线路 · 同色岩点' : r.profile === 'style' ? '固定训练板 · 选点与动作搜索' : r.design_brief?.title || (r.profile === 'catalog' ? '标准模板 · 有限库存与组合安装' : '') || scenarioNames[r.scenario] || r.scenario;
    $('#canvas-legend').style.setProperty('--route-ink', `#${palette.route.toString(16).padStart(6, '0')}`);
    $('#canvas-legend').innerHTML = `<span><i class="dot jug"></i>${current()?.layout_report ? '布局试案' : viewingAlternative() ? '当前走法使用' : '当前线路'}</span>${viewingAlternative() ? '<span><i class="dot skipped"></i>已安装但未用</span>' : '<span>手 / 脚：实际用途</span>'}` + (r.profile === 'catalog' ? '<span><i class="dot normal"></i>面法向</span>' : current()?.layout_report ? '<span>仅起始接触，未生成移手序列</span>' : '<span>数字：移手次序</span>');
    if (r.route_constraints) {
      $('#canvas-legend').innerHTML = '<span><i class="dot jug"></i>允许使用</span><span><i class="dot skipped"></i>未选入，仍在墙上</span><span>数字：实际移手次序</span>';
      $('#scene-title').textContent = activeLearnedRun() ? `固定岩壁 · ${learnedSourceNames[activeLearnedRun()!.source]}` : '固定岩壁 · 限定选点';
    }
    $('#scene-title').textContent = activeOwnRoute()?.label || wallProfileNames[r.setting_design?.wall_profile || ''] || '当前草稿';
    $('#canvas-legend').innerHTML = '<span><i class="dot jug"></i>本线路</span><span><i class="dot skipped"></i>其他岩点</span>';
    const wallHeight = wallHeightMeasures(r.scene);
    $('#scene-subtitle').textContent = `${r.scene.wall_panels?.length ? `${r.scene.wall_panels.length} 个空间墙面` : r.scene.angle_deg === 0 ? '垂直墙' : `仰角 ${r.scene.angle_deg}°`} · 展开高度 ${wallHeight.unfolded.toFixed(1)} m · 几何垂直高 ${wallHeight.vertical.toFixed(2)} m · 人体 ${r.body.id}${r.setting_design?.wall_profile && r.setting_design.wall_profile !== 'default' ? ` · ${wallProfileNames[r.setting_design.wall_profile]}` : ''}`;
    const ev = evaluation();
    $('#run-meta').textContent = `种子 ${r.seed} · ${candidate?.generator || 'rules'}${ev ? ` · 检查器 ${ev.version} · ${(ev.elapsed_ms / 1000).toFixed(2)} s` : ''}`;
  }
}
function renderCandidates() {
  const setting = bundle?.request.profile === 'setting';
  $('.candidate-title > .section-label').textContent = setting ? '布局修订' : '方案';
  $('#candidates').setAttribute('aria-label', setting ? '布局修订' : '候选方案');
  $('.candidates-bar').hidden = (bundle?.candidates.length || 0) < 2;
  $('#candidate-count').textContent = String(bundle?.candidates.length || '—');
  $('#candidates').innerHTML = (bundle?.candidates || []).map((candidate, index) => {
    const ev = evaluation(candidate);
    const status = isStale(candidate) ? 'stale' : ev?.summary.status || 'unknown';
    return `<button role="tab" aria-selected="${candidate.id === activeId}" class="candidate-tab ${candidate.id === activeId ? 'active' : ''}" data-action="candidate" data-id="${esc(candidate.id)}" title="${esc(candidate.name)}"><span class="status-dot ${status}"></span>${esc(candidate.name || `方案 ${index + 1}`)}<span class="revision-mini">r${candidate.revision}</span></button>`;
  }).join('');
  $('#history').innerHTML = histories.map((item, index) => `<option value="${index}">实验 ${String(index + 1).padStart(2, '0')} · 种子 ${item.request.seed}</option>`).join('');
  $<HTMLSelectElement>('#history').value = String(histories.indexOf(bundle!));
  $<HTMLSelectElement>('#history').disabled = busy || histories.length < 2;
}
function renderSummary() {
  const candidate = current(); if (!candidate) return;
  $<HTMLButtonElement>('#quick-check').disabled = false;
  const ev = evaluation(), stale = isStale();
  const cls = stale ? 'stale' : candidate.layout_report ? 'unknown' : ev?.summary.status || 'unknown';
  const label = stale ? '调整后待检查' : candidate.layout_report ? '尚未找到完整走法' : !ev ? '尚未检查' : ev.summary.status === 'pass' ? '几何检查通过' : ev.summary.status === 'fail' ? '几何需要调整' : '部分姿态未解出';
  const support = ev?.mechanics_report?.summary;
  const compact = stale ? '调整后待检查' : candidate.layout_report ? '尚无完整走法' : !ev ? '尚未检查' : ev.summary.status !== 'pass' ? label : support?.status === 'infeasible' ? '支撑需调整' : '待试攀';
  $('#quick-check').textContent = `${compact} · 检查`;
  $('#quick-check').classList.toggle('needs-check', stale || !ev);
  const note = stale ? '重新检查后更新结果。' : ev?.summary.status === 'pass' && support?.status === 'infeasible' ? '静态支撑仍需调整，待试攀。' : '草稿需定线员调整与试攀。';
  $('#summary').innerHTML = `<div class="summary-title ${cls}">${stale ? icon('refresh') : statusIcon(candidate.layout_report ? 'unknown' : ev?.summary.status || 'unknown')}<strong>${label}</strong></div><p class="summary-limit">${note}</p>${viewingAlternative() ? '<p class="field-hint">备选走法只读，返回主走法可编辑。</p>' : `<button class="button ${stale || !ev ? 'primary' : 'outlined'} full-width" data-action="recheck" ${busy ? 'disabled' : ''}>${icon('refresh')}${stale || !ev ? '检查调整' : '重新检查'}</button>`}`;
}
function ensureSelection() {
  const candidate = current(); if (!candidate || !bundle) return;
  if (!selectedHold && !selectedInventory) return;
  const inventory = bundle.request.scene.inventory;
  const placed = candidate.placements.find(p => p.id === selectedHold);
  if (placed) selectedInventory = placed.inventory_id;
  if (!inventory.some(h => h.id === selectedInventory)) { selectedInventory = ''; selectedHold = ''; return; }
  selectedHold = candidate.placements.find(p => p.inventory_id === selectedInventory)?.id || '';
}
function revealEditor(_scroll = true) {
  showWorkspace(false, false);
  // The editor overlays the wall; opening it must not shift the canvas.
}
function selectPlacement(id: string) {
  const placement = current()?.placements.find((p) => p.id === id);
  if (!placement) return;
  selectedHold = id; selectedInventory = placement.inventory_id;
  view?.select(id); renderEditor(); renderLibrary(); revealEditor(!editMode);
}
function selectInventory(id: string) {
  if (!bundle?.request.scene.inventory.some((h) => h.id === id)) return;
  selectedInventory = id; selectedHold = current()?.placements.find((p) => p.inventory_id === id)?.id || '';
  view?.select(selectedHold); renderEditor(); renderLibrary(); revealEditor();
}
function routePlacementIds() {
  return new Set(current()?.states.flatMap((state) => Object.values(state.contacts).flatMap((contact) => contact ? [contact.placement_id] : [])) || []);
}
function renderRouteInventory() {
  const candidate = current(), host = $('#route-inventory-summary');
  if (!candidate || !bundle) { host.innerHTML = ''; return; }
  const hand = new Set<string>(), foot = new Set<string>();
  candidate.states.forEach(state => Object.entries(state.contacts).forEach(([limb, contact]) => { if (contact) (limb.endsWith('H') ? hand : foot).add(contact.placement_id); }));
  const shared = [...hand].filter(id => foot.has(id)).length;
  const used = new Set([...hand, ...foot]);
  const parents = new Set(candidate.placements.filter(p => used.has(p.id) && p.mount).map(p => p.mount!.parent_id));
  const unused = candidate.placements.filter(p => !used.has(p.id) && !parents.has(p.id)).length;
  const moves = candidate.events.filter(event => event.limb.endsWith('H')).length;
  host.innerHTML = candidate.layout_report ? `<strong>布局试案 · ${candidate.placements.length} 个安装点</strong><span>仅声明 ${used.size} 个起始接触，尚未找到完整走法</span><small>全部点位按真实墙面显示；未声明后续动作，也未将起点当作终点。</small>` : `<strong>当前线路 ${used.size} 个接触点</strong><span>仅手用 ${hand.size - shared} · 仅脚用 ${foot.size - shared} · 手脚共用 ${shared}${parents.size ? ` · 支撑体积块 ${parents.size}` : ''}</span><span>${moves} 次移手 · ${candidate.events.length} 次接触转换</span>${viewingAlternative() || bundle.request.profile === 'setting' ? `<small>本走法跳过的 ${unused} 个已安装点保留为灰色；全部 ${candidate.placements.length} 个安装位置不变。</small>` : unused ? `<small>${unused} 个未用安装点默认隐藏；取消“仅显示当前线路”可查看。</small>` : '<small>已安装点来自原定走法；用替代走法检查判断哪些点可能被跳过。未选库存不计入当前岩壁。</small>'}`;
  const control = $<HTMLInputElement>('#route-only');
  control.disabled = viewingAlternative() || bundle.request.profile === 'setting' || unused === 0; control.closest('label')!.title = candidate.layout_report ? '布局试案显示全部已安装点；尚未找到完整走法' : viewingAlternative() || bundle.request.profile === 'setting' ? '审计视图始终保留全部已安装点，灰色表示本走法未用' : unused ? '取消后以灰色显示该方案的未用安装点' : '当前方案没有未用安装点';
  if (bundle.request.route_constraints) {
    const selected = new Set(Object.values(bundle.request.route_constraints.allowed_contacts).flat());
    control.disabled = true; control.checked = false;
    control.closest('label')!.title = '限定选点始终保留整墙，未选岩点继续参与碰撞检查';
    host.innerHTML = `<strong>整墙 ${candidate.placements.length} 个安装点 · 允许 ${selected.size} 个</strong><span>${candidate.layout_report ? `起始接触 ${used.size} 个，尚无完整走法` : `实际使用 ${used.size} 个 · 跳过 ${[...selected].filter(id => !used.has(id)).length} 个候选点`}</span><small>亮色表示允许接触；灰色表示本方案未选入。所有安装位置与朝向保持不变。</small>`;
  }
}
function renderLibrary() {
  if (!bundle) return;
  const inventory = bundle.request.scene.inventory;
  const used = routePlacementIds();
  const installed = new Set(current()?.placements.map(item => item.inventory_id));
  const stock = bundle.request.scene.catalog_stock;
  const layoutOnly = !!current()?.layout_report;
  $('#stock-summary').hidden = !stock;
  $('#stock-summary').innerHTML = stock ? `<p><strong>${stock.length} 款模板 · ${inventory.length} 件库存</strong><span>已安装 ${installed.size} · 可用 ${inventory.length - installed.size}</span></p><div>${stock.map(item => { const placed = inventory.filter(h => h.template_id === item.template_id && installed.has(h.id)).length; const family = holdFamily(inventory.find(h => h.template_id === item.template_id) || { type: item.type } as import('./types').Hold); return `<button data-action="hold-filter" data-type="${esc(family)}" class="${holdFilter === family ? 'active' : ''}"><span>${esc(item.template_name)}</span><strong>${item.count - placed}<small> / ${item.count} 可用</small></strong></button>`; }).join('')}</div>` : '';
  const types = ['route', 'all', ...new Set(inventory.map(holdFamily))];
  if (!types.includes(holdFilter)) holdFilter = 'all';
  $('#library-filters').innerHTML = types.map(type => `<button data-action="hold-filter" data-type="${esc(type)}" aria-pressed="${type === holdFilter}" class="${type === holdFilter ? 'active' : ''}">${type === 'route' ? `${layoutOnly ? '起始接触' : '线路使用'} · ${used.size}` : type === 'all' ? '全部库存' : esc(holdNames[type] || type)}</button>`).join('');
  $('#library-count').textContent = String(inventory.length);
  const meshCount = inventory.filter(hold => hold.asset_id).length;
  $('.library-description').textContent = meshCount ? `${meshCount} 件外部网格 · ${inventory.length - meshCount} 件参数模板` : '参数模板 · 当前有限库存';
  document.querySelectorAll<HTMLButtonElement>('[data-action="hold-filter"]').forEach((button) => {
    const active = button.dataset.type === holdFilter;
    button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
  });
  $('#hold-library-grid').innerHTML = inventory.filter((hold) => holdFilter === 'all' || holdFamily(hold) === holdFilter || (holdFilter === 'route' && current()?.placements.some(p => p.inventory_id === hold.id && used.has(p.id)))).map((hold) => {
    const placement = current()?.placements.find((p) => p.inventory_id === hold.id);
    const inRoute = !!placement && used.has(placement.id);
    const useLabel = layoutOnly ? inRoute ? '起始接触' : placement ? '已安装' : '未布置' : inRoute ? '线路使用' : placement ? '未用' : '未布置';
    const displayHold = presentationHold(hold, palette);
    const key = JSON.stringify({ ...displayHold, id: hold.template_id || hold.id });
    let thumbnail = thumbnailCache.get(key);
    if (!thumbnail) { try { thumbnail = holdThumbnail(displayHold); thumbnailCache.set(key, thumbnail); if (thumbnailCache.size > 48) thumbnailCache.delete(thumbnailCache.keys().next().value!); } catch { thumbnail = ''; } }
    const name = shortHoldName(hold, inventory);
    return `<button class="library-hold ${selectedInventory === hold.id ? 'selected' : ''} ${inRoute ? 'in-route' : ''}" data-action="library-hold" data-id="${esc(hold.id)}" aria-pressed="${selectedInventory === hold.id}" aria-label="${esc(name)} ${esc(holdNames[holdFamily(hold)] || holdNames[hold.type])}，${useLabel}"><span class="thumbnail-stage">${thumbnail ? `<img src="${esc(thumbnail)}" alt="" width="112" height="82" />` : icon('cube')}</span><span class="library-hold-family">${esc(holdNames[holdFamily(hold)] || hold.type)}</span><span class="library-hold-caption"><strong>${esc(name)}</strong><span>${useLabel}</span></span></button>`;
  }).join('') || '<p class="muted">该类型暂无库存。</p>';
}
function renderEditor() {
  const candidate = current(); if (!candidate || !bundle) { preview?.setHold(undefined); return; }
  ensureSelection();
  const empty = !selectedInventory;
  $('#editor-section').classList.toggle('empty', empty);
  $('.inspector').hidden = empty || editMode;
  if (empty) {
    preview?.setHold(undefined); previewKey = '';
    $('#selected-hold-title').textContent = '点选一个岩点';
    $('#hold-editor').innerHTML = '<p class="editor-empty-note">点击岩壁上的点，调整位置与朝向。</p><button class="text-button" data-action="open-inventory">从岩点库选择</button>';
    $('#hold-asset-details').innerHTML = '';
    return;
  }
  const inventory = bundle.request.scene.inventory;
  const placement = candidate.placements.find(p => p.id === selectedHold);
  const hold = inventory.find(item => item.id === selectedInventory);
  const locked = bundle.request.mode === 'fixed' || viewingAlternative(), disabled = locked || busy;
  const surfaceId = placement?.contact_surface_id || hold?.grip_surfaces?.[0]?.id;
  const surface = hold?.grip_surfaces?.find(item => item.id === surfaceId);
  const displayHold = hold ? presentationHold(hold, palette) : undefined;
  const key = hold ? JSON.stringify([displayHold, surfaceId]) : '';
  if (key !== previewKey) { preview?.setHold(displayHold, surfaceId); previewKey = key; }
  const assetResolution = hold ? resolveHoldAsset(hold) : undefined;
  $('#hold-model-kind').textContent = assetResolution?.kind === 'asset' ? '外部网格' : assetResolution?.kind === 'unavailable' ? '资产未匹配' : '参数模板';
  $('#hold-asset-details').innerHTML = hold ? holdAssetDetailsHTML(hold, surface) : '';
  const usedSurfaces = placement && hold ? [...new Set(current()?.states.flatMap(state => Object.entries(state.contacts).flatMap(([limb, contact]) => contact?.placement_id === placement.id ? [`${limbNames[limb as import('./types').Limb]} · ${contactPresentation(contact, limb as import('./types').Limb, placement, hold).surfaceLabel}`] : [])) || [])] : [];
  $('.model-limit').textContent = assetResolution && assetResolution.kind !== 'template' ? '真实网格形状与实验接触标注；来源尺度、抓握能力和受力仍按当前声明的假设处理。' : '模板区域是可接触面的设计假设，未验证真实摩擦、抓握或受力。';
  $('#hold-model-scope').textContent = assetResolution && assetResolution.kind !== 'template' ? '外部三角网格用于画布、近看和拾取；浅色区域裁切自网格表面。每次接触引用具体表面，以标注代表点计算姿态；同一岩点可使用不同的抓握面与踩面。白色箭头是声明拉向，求解力另列；尚未搜索面内任意抓握位置。' : '原创参数模板，不是真实岩点扫描。浅色区域为声明接触面；每次接触引用具体表面，以面上的代表点计算姿态；同一岩点可先抓后踩。白色箭头是声明拉向，求解力另列；尚未搜索面内任意抓握位置。';
  $('#selected-hold-title').textContent = hold ? `${shortHoldName(hold, inventory)} · ${holdNames[holdFamily(hold)] || hold.type}` : '选择岩点';
  const parentOptions = hold?.type === 'volume' ? [] : candidate.placements.filter(p => p.id !== placement?.id && !p.mount).flatMap(p => {
    const parent = inventory.find(h => h.id === p.inventory_id);
    return (parent?.mounting_faces || []).map(face => ({ value: JSON.stringify({ parent_id: p.id, face_id: face.id }), label: `${shortHoldName(parent!, inventory)} · ${face.label}` }));
  });
  const panels = bundle.request.scene.wall_panels || [];
  const panel = panels.find(item => item.id === placement?.wall_panel_id);
  const mountValue = placement?.mount ? JSON.stringify({ parent_id: placement.mount.parent_id, face_id: placement.mount.face_id }) : placement?.wall_panel_id ? `panel:${placement.wall_panel_id}` : '';
  const missingMount = !!mountValue && !parentOptions.some(item => item.value === mountValue) && !panels.some(item => `panel:${item.id}` === mountValue);
  const missingSurface = !!surfaceId && !surface;
  const inRoute = !!placement && routePlacementIds().has(placement.id);
  const hasChildren = !!placement && candidate.placements.some(p => p.mount?.parent_id === placement.id);
  const removeBlocked = inRoute || hasChildren;
  $('#hold-editor').innerHTML = `<details class="hold-facts"><summary>属性与接触用途</summary><label class="sr-only" for="hold-select">选择库存岩点</label><select id="hold-select" class="full-select">${inventory.map(h => `<option value="${esc(h.id)}" ${h.id === selectedInventory ? 'selected' : ''}>${esc(shortHoldName(h, inventory))} · ${esc(holdDisplayName(h))}</option>`).join('')}</select>
    ${usedSurfaces.length ? `<p class="hold-used-surfaces"><strong>本走法实际接触</strong>${usedSurfaces.map(label => `<span>${esc(label)}</span>`).join('')}</p>` : ''}
    ${hold ? `<div class="hold-specs"><span>${assetResolution?.kind === 'asset' && !assetResolution.asset.scale.verified ? '实验宽 × 高 × 深' : '宽 × 高 × 深'}<strong>${[hold.width, hold.height, hold.depth].map(n => Math.round(n * 1000)).join(' × ')} mm</strong></span><span>库存状态<strong>${placement ? inRoute ? '已安装 · 线路使用' : '已安装 · 线路未用' : '未安装 · 可用'}</strong></span><span>适用接触<strong id="surface-limbs">${(surface?.limbs || hold.contact.limbs).map(limb => limbNames[limb]).join(' / ')}</strong></span></div>` : ''}
    ${hold ? `<p class="hold-taxonomy">${esc(holdNames[holdFamily(hold)] || hold.type)}<span>潜在用途：${esc(holdRoleName(hold))} · 本动作接触以所选表面为准</span></p>` + holdAttributesHTML(hold) : ''}</details>
    ${hold ? `<form id="edit-form">
      <details class="precise-edit"><summary>位置与接触面</summary>${hold.grip_surfaces?.length || missingSurface ? `<label class="editor-control">默认接触面<select id="surface-select" name="contact_surface_id" ${disabled ? 'disabled' : ''}>${missingSurface ? `<option value="${esc(surfaceId)}" selected>未识别接触面 · ${esc(surfaceId)}</option>` : ''}${(hold.grip_surfaces || []).map(item => `<option value="${esc(item.id)}" ${item.id === surfaceId ? 'selected' : ''}>${esc(item.label)}</option>`).join('')}</select></label><p class="field-hint surface-explanation">${hold.asset_id ? '浅色区域来自本资产三角面。' : '浅色为模板接触区域。'}这里修改 main 接触的默认面；明确引用其他面的动作保持各自接触面。手抓面与脚踩面分别检查。</p>` : ''}
      <label class="editor-control">安装位置<select id="mount-select" name="mount" ${disabled ? 'disabled' : ''}>${panels.length ? panels.map(item => `<option value="panel:${esc(item.id)}" ${`panel:${item.id}` === mountValue ? 'selected' : ''}>${esc(item.label)} · 墙面分区</option>`).join('') : '<option value="">直接安装在墙面</option>'}${missingMount ? `<option value="${esc(mountValue)}" selected>无效安装面 · 请重新选择</option>` : ''}${parentOptions.map(item => `<option value="${esc(item.value)}" ${item.value === mountValue ? 'selected' : ''}>${esc(item.label)}</option>`).join('')}</select></label>
      ${placement?.mount ? `<button class="text-button" type="button" data-action="focus-parent">查看组合安装 ↗</button>` : ''}
      <div class="numeric-grid"><label><span id="u-coordinate-label">${placement?.mount || panel ? '面内 u · m' : '水平 u · m'}</span><input name="u" type="number" step="any" value="${placement?.u ?? 0}" required ${disabled ? 'disabled' : ''}/></label><label><span id="v-coordinate-label">${placement?.mount || panel ? '面内 v · m' : '沿墙 v · m'}</span><input name="v" type="number" step="any" value="${placement?.v ?? 1}" required ${disabled ? 'disabled' : ''}/></label></div>
      <p id="mount-hint" class="field-hint">${placement?.mount ? 'u / v 以体积块该面中心为原点；旋转沿该面法线。父体积块移动时一起跟随。' : panel ? `u / v 以“${esc(panel.label)}”底部中心为原点；随该墙面的空间朝向安装。` : 'u / v 以墙面底部中心为原点；旋转沿墙面法线。'}</p>
      </details>
      <div class="rotation-control"><label>旋转 · °<input name="rotation_deg" type="number" step="any" value="${placement?.rotation_deg ?? 0}" required ${disabled ? 'disabled' : ''}/></label></div>
      <div class="editor-shortcuts"><div class="angle-shortcuts"><button class="button quiet" type="button" data-action="rotate-minus" ${disabled ? 'disabled' : ''}>−15°</button><button class="button quiet" type="button" data-action="rotate-plus" ${disabled ? 'disabled' : ''}>+15°</button></div>${placement ? `<button class="button quiet" type="button" data-action="move-mode" ${disabled ? 'disabled' : ''}>${icon('move')}移动位置</button>` : ''}</div>
      ${locked ? `<p class="field-hint">${viewingAlternative() ? '替代走法固定原岩壁。返回原定走法后可修改点位，修改后需重新检查替代走法。' : '固定模式锁定安装与接触选择；仍可浏览和近看模型。'}</p>` : `<button class="button primary full-width" type="submit" data-action="save-edit" ${busy ? 'disabled' : ''}>${placement ? '应用调整' : '安装岩点'}</button><p class="field-hint">${placement ? '保留旧版；应用后需重新检查。' : '安装后占用当前这件库存；仍需检查边界和碰撞，不会自动加入动作序列。'}</p>${placement ? `<details class="remove-options"><summary>移除岩点</summary><button class="button quiet full-width remove-hold" type="button" data-action="remove-installation" ${busy || removeBlocked ? 'disabled' : ''}>卸下并归还库存</button>${removeBlocked ? `<p class="field-hint">${hasChildren ? '该体积块仍承载子岩点，不能卸下。' : '该岩点被动作序列使用，不能直接卸下。'}</p>` : ''}</details>` : ''}`}
    </form>` : ''}`;
  $('#hold-select').addEventListener('change', event => selectInventory((event.target as HTMLSelectElement).value));
  $('#edit-form')?.addEventListener('submit', saveEdit);
  $('#surface-select')?.addEventListener('change', event => {
    const nextId = (event.target as HTMLSelectElement).value;
    preview?.setHold(hold ? presentationHold(hold, palette) : undefined, nextId); previewKey = '';
    const next = hold?.grip_surfaces?.find(item => item.id === nextId);
    if (next) $('#surface-limbs').textContent = next.limbs.map(limb => limbNames[limb]).join(' / ');
    if (hold) { const open = $('#hold-asset-details').querySelector('details')?.open; $('#hold-asset-details').innerHTML = holdAssetDetailsHTML(hold, next); const details = $('#hold-asset-details').querySelector('details'); if (details && open) details.open = true; }
  });
  $('#mount-select')?.addEventListener('change', event => {
    const value = (event.target as HTMLSelectElement).value;
    const panel = panels.find(item => `panel:${item.id}` === value);
    const mounted = !!value && !panel;
    let u = 0, v = mounted ? 0 : 1;
    if (!mounted && placement && bundle) {
      try {
        const frame = placementFrame(placement, { angleDeg: bundle.request.scene.angle_deg, placements: candidate.placements, inventory, wallPanels: panels });
        const target = panel ? panelFrame(bundle.request.scene.angle_deg, panel) : wallFrame(bundle.request.scene.angle_deg);
        const uv = inversePoint(target, frame.origin); u = uv[0]; v = uv[1];
      } catch { /* New placements start at the chosen installation reference point. */ }
    }
    $<HTMLInputElement>('#edit-form input[name="u"]').value = String(Number(u.toFixed(4)));
    $<HTMLInputElement>('#edit-form input[name="v"]').value = String(Number(v.toFixed(4)));
    $<HTMLInputElement>('#edit-form input[name="rotation_deg"]').value = '0';
    $('#u-coordinate-label').textContent = mounted || panel ? '面内 u · m' : '水平 u · m';
    $('#v-coordinate-label').textContent = mounted || panel ? '面内 v · m' : '沿墙 v · m';
    $('#mount-hint').textContent = mounted ? '已将草稿坐标放在该面中心；保存后检查小岩点是否完全位于该面内。' : panel ? `草稿已投影到“${panel.label}”平面；u / v 以该面底部中心为原点，保存后重新检查。` : '已将草稿位置投影回墙面；保存后重新检查。';
  });
}
function syncToolState() {
  const disabled = busy || !current() || viewingAlternative() || bundle?.request.mode === 'fixed';
  const active = editMode && !disabled;
  view?.setEditMode(active);
  document.querySelectorAll<HTMLButtonElement>('[data-action="browse-mode"], [data-action="move-mode"]').forEach((button) => {
    const isMove = button.dataset.action === 'move-mode';
    button.disabled = isMove && disabled;
    button.classList.toggle('active', isMove ? active : !active);
    button.removeAttribute('aria-pressed');
  });
  $('.canvas-toolbar').hidden = !active;
  $('#tool-status').textContent = busy ? '处理中…' : viewingAlternative() ? '备选走法 · 只读' : bundle?.request.mode === 'fixed' ? '固定点位' : active ? '拖动岩点，松开即保存' : '点选岩点可调整';
  $('#canvas-hint').textContent = active ? '拖动岩点 · 松开保存' : '点岩点调整 · 拖动空白旋转';
  $('.canvas-shell').classList.toggle('editing', active);
}
function renderChecks() {
  const ev = evaluation();
  const checks = isStale() ? [] : (ev?.checks || []).filter((check) => check.status !== 'not_checked');
  $('#check-count').textContent = checks.length ? `${checks.length} 项` : '';
  $('#checks').innerHTML = checks.length ? checks.map((check, index) => `<details class="check-row ${check.status}"><summary data-check-index="${index}">${statusIcon(check.status)}<span>${esc(check.label || check.id)}</span><small>${statusLabels[check.status]}</small>${icon('chevron', 'details-chevron')}</summary><div class="check-detail"><p>${esc(check.detail)}</p>${check.state_id || check.placement_ids?.length ? `<button class="text-button" data-action="locate-check" data-check-index="${index}">定位到场景 ${icon('chevron')}</button>` : ''}${check.evidence ? `<details class="evidence"><summary>计算依据</summary><pre>${esc(JSON.stringify(check.evidence, null, 2))}</pre></details>` : ''}</div></details>`).join('') : `<p class="muted">${isStale() ? '等待当前修订的检查结果。' : '尚无检查明细。'}</p>`;
  const limits = (ev?.checks || []).filter((check) => check.status === 'not_checked');
  const mechanicsScope: Record<string, { label: string; detail: string }> = ev?.mechanics_report && !isStale() ? {
    force: { label: '真实抓握、摩擦与力量能力', detail: '准静态报告使用合成摩擦系数与接触容量；真实材料、鞋底摩擦和人体力量尚未测量标定。' },
    balance: { label: '连续平衡与动态稳定性', detail: '准静态报告只检查当前离散姿态的力与力矩平衡；连续运动、扰动后的稳定性和真人完成情况尚未验证。' },
  } : {};
  $('#limits').innerHTML = limits.length ? limits.map((check) => { const scope = mechanicsScope[check.id]; return `<details class="limit-row"><summary>${icon('minus')}<span>${esc(scope?.label || check.label || check.id)}</span><small>未验证</small>${icon('chevron', 'details-chevron')}</summary><p>${esc(scope?.detail || check.detail)}</p></details>`; }).join('') : '<div class="limit-chips"><span>连续动作轨迹</span><span>真实受力参数</span><span>完整人体碰撞</span><span>真人难度</span></div>';
}
function showStep(index: number) {
  if (busy || !Number.isInteger(index) || !current()?.states[index]) return;
  showWorkspace(false, false); replayOpen = true; step = index;
  $<HTMLInputElement>('#show-body').checked = true; view?.setBody(true);
  renderSteps(); view?.setStep(step);
}
function stepName(index: number): string {
  const candidate = current(); if (!candidate) return '';
  if (index === 0) return '起始接触';
  const state = candidate.states[index];
  const event = candidate.events.find((item) => item.release_state === state.id || item.to_state === state.id);
  return event ? `${limbNames[event.limb]}${event.release_state === state.id ? '释放' : '接触'}` : state.label || `状态 ${index + 1}`;
}
function renderSteps() {
  $('.timeline').hidden = !replayOpen; $('#open-replay').hidden = replayOpen;
  $<HTMLButtonElement>('#open-replay').disabled = busy || !current()?.events.length;
  const candidate = current(); if (!candidate) return;
  const states = candidate.states;
  step = Math.max(0, Math.min(step, states.length - 1));
  const state = states[step];
  const handEvents = candidate.events.filter((event) => event.limb.endsWith('H')).length;
  const nav = timelineNavigation(candidate, step);
  $('#step-count').textContent = nav.eventIndex === null ? `起点 · 共 ${candidate.events.length} 步` : `${nav.eventIndex + 1} / ${candidate.events.length} · ${limbNames[candidate.events[nav.eventIndex].limb]}`;
  $('#move-state-switch').innerHTML = nav.eventIndex === null ? '' : `<span>动作状态</span><button data-action="step" data-step="${nav.release}" aria-pressed="${nav.phase === 'release'}" ${busy || nav.release === null ? 'disabled' : ''}>松开时</button><button data-action="step" data-step="${nav.landing}" aria-pressed="${nav.phase === 'landing'}" ${busy || nav.landing === null ? 'disabled' : ''}>落点后</button>`;
  $('#steps').innerHTML = states.map((state, index) => {
    const pose = evaluation()?.poses.find((item) => item.state_id === state.id);
    return `<button class="step ${index === step ? 'active' : ''}" data-action="step" data-step="${index}" ${busy ? 'disabled' : ''} aria-current="${index === step ? 'step' : 'false'}"><span class="step-number">${String(index).padStart(2, '0')}</span><span>${esc(stepName(index))}</span><i class="status-dot ${isStale() ? 'stale' : pose?.status || 'unknown'}"></i></button>`;
  }).join('');
  const stepList = $('#steps');
  const activeStep = stepList.querySelector<HTMLElement>('.step.active');
  if (activeStep) {
    const viewport = stepList.getBoundingClientRect();
    const item = activeStep.getBoundingClientRect();
    const delta = item.left < viewport.left ? item.left - viewport.left - 4 : item.right > viewport.right ? item.right - viewport.right + 4 : 0;
    if (delta) stepList.scrollBy({ left: delta, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }
  renderMovementIntent();
  $('#contact-strip').innerHTML = state ? limbs.map((limb) => {
    const contact = state.contacts[limb];
    const placement = candidate.placements.find(item => item.id === contact?.placement_id);
    const hold = bundle?.request.scene.inventory.find(item => item.id === placement?.inventory_id);
    const detail = contact ? contactPresentation(contact, limb, placement, hold) : undefined;
    return `<span class="limb-contact ${detail?.onHandHold ? 'foot-on-handhold' : ''}" ${contact ? `data-contact-id="${esc(contact.contact_id)}"` : ''}><i class="limb-dot ${limb.toLowerCase()}"></i><b>${limb}</b><span>${limbNames[limb]}</span><strong>${esc(contact?.placement_id || '释放')}</strong>${detail ? `<small>${detail.onHandHold ? '踩手点 · ' : `${detail.action} · `}${esc(detail.surfaceLabel)}</small>` : ''}</span>`;
  }).join('') : '';
  $<HTMLButtonElement>('[data-action="previous"]').disabled = busy || nav.previous === null;
  $<HTMLButtonElement>('[data-action="next"]').disabled = busy || nav.next === null;
  const pose = evaluation()?.poses.find((item) => item.state_id === state?.id);
  $('#pose-status').hidden = !$<HTMLInputElement>('#show-body').checked;
  $('#pose-status').className = `pose-status ${isStale() ? 'stale' : pose?.status || 'unknown'}`;
  $('#pose-status').innerHTML = isStale() ? `${icon('refresh')}新修订待检查 · 仅显示接触目标` : pose?.status === 'pass' && pose.joints ? `${icon('check')}计算姿态` : `${icon('question')}${pose?.status === 'fail' ? '违反模型约束' : '当前未找到姿态'} · 仅显示接触目标`;
  renderStyleStudy(); renderBetaAudit(); renderSettingStudy(); renderMechanics();
}
function renderComparison() {
  const candidate = current();
  if (viewingAlternative()) { compareId = ''; $('#compare').innerHTML = '<option value="">替代走法保持原布局</option>'; $<HTMLSelectElement>('#compare').disabled = true; $('#comparison-detail').innerHTML = '<p class="field-hint">上方替代走法表在同一布局内比较动作；返回原定走法可叠加其他摆点方案。</p>'; return; }
  const options = bundle?.candidates.filter((item) => item.id !== candidate?.id) || [];
  if (!options.some((item) => item.id === compareId)) compareId = '';
  $('#compare').innerHTML = '<option value="">不叠加对照</option>' + options.map((item) => `<option value="${esc(item.id)}" ${item.id === compareId ? 'selected' : ''}>${esc(item.name)} · r${item.revision}</option>`).join('');
  $<HTMLSelectElement>('#compare').disabled = !options.length;
  const base = options.find((item) => item.id === compareId);
  if (!candidate || !base) { $('#comparison-detail').innerHTML = '<p class="field-hint">选择另一方案，以浅色轮廓叠加它的点位。</p>'; return; }
  const original = new Map(base.placements.map((p) => [p.inventory_id, p]));
  const changed = candidate.placements.flatMap((p) => {
    const prev = original.get(p.inventory_id);
    if (!prev) return [{ id: p.id, description: '新增岩点' }];
    const changes: string[] = [];
    try {
      const context = { angleDeg: bundle!.request.scene.angle_deg, inventory: bundle!.request.scene.inventory, wallPanels: bundle!.request.scene.wall_panels };
      const nextFrame = placementFrame(p, { ...context, placements: candidate.placements });
      const prevFrame = placementFrame(prev, { ...context, placements: base.placements });
      const distance = Math.hypot(...nextFrame.origin.map((value, i) => value - prevFrame.origin[i]));
      const trace = [nextFrame.u, nextFrame.v, nextFrame.normal].reduce((sum, axis, index) => sum + axis.reduce((dot, value, i) => dot + value * [prevFrame.u, prevFrame.v, prevFrame.normal][index][i], 0), 0);
      const rotation = Math.acos(Math.max(-1, Math.min(1, (trace - 1) / 2))) * 180 / Math.PI;
      if (distance > 1e-6) changes.push(`${(distance * 100).toFixed(1)} cm`);
      if (rotation > 1e-4) changes.push(`朝向 ${rotation.toFixed(1)}°`);
    } catch { changes.push('安装关系无效'); }
    if (p.mount?.parent_id !== prev.mount?.parent_id || p.mount?.face_id !== prev.mount?.face_id) changes.push('更换安装面');
    if (p.contact_surface_id !== prev.contact_surface_id) changes.push('更换接触面');
    return changes.length ? [{ id: p.id, description: changes.join(' · ') }] : [];
  });
  const removed = base.placements.filter((p) => !candidate.placements.some((x) => x.inventory_id === p.inventory_id));
  const path = (item: Candidate) => item.events.map(event => {
    const contact = item.states.find(state => state.id === event.to_state)?.contacts[event.limb];
    const inventoryId = item.placements.find(p => p.id === contact?.placement_id)?.inventory_id;
    const hold = bundle?.request.scene.inventory.find(h => h.id === inventoryId);
    return `${limbNames[event.limb]} ${hold ? shortHoldName(hold, bundle!.request.scene.inventory) : contact?.placement_id || '释放'}`;
  });
  const currentPath = path(candidate), basePath = path(base);
  const pathChanged = JSON.stringify(currentPath) !== JSON.stringify(basePath);
  const pathComparison = ['style', 'route'].includes(bundle?.request.profile || '') || pathChanged ? `<div class="path-comparison"><strong>${pathChanged ? '选点或动作顺序不同' : '选点与动作顺序相同'}</strong><p><span>当前</span>${esc(currentPath.join(' → '))}</p><p><span>对照</span>${esc(basePath.join(' → '))}</p></div>` : '';
  $('#comparison-detail').innerHTML = `${pathComparison}<div class="comparison-caption">${changed.length + removed.length ? `${changed.length + removed.length} 个点位发生变化` : '安装点位保持一致'}</div>${changed.map((item) => `<button class="delta-row" data-action="select-hold" data-id="${esc(item.id)}"><span>${esc(item.id)}</span><strong>${esc(item.description)}</strong></button>`).join('')}${removed.map((item) => `<div class="delta-row"><span>${esc(item.id)}</span><strong>已移除</strong></div>`).join('')}<p class="field-hint">当前：${esc(isStale() ? '待重新检查' : evaluation()?.summary ? statusLabels[evaluation()!.summary.status] : '未检查')} · 对照：${esc(isStale(base) ? '待重新检查' : evaluation(base)?.summary ? statusLabels[evaluation(base)!.summary.status] : '未检查')}</p>`;
}
function renderReviews() {
  const reviews = bundle?.reviews?.filter((review) => review.candidate_id === activeId) || [];
  $('#review-list').innerHTML = reviews.slice(-3).map((review) => `<div class="saved-review"><small>修订 ${review.candidate_revision} · ${new Date(review.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</small><p>${esc(review.text)}</p></div>`).join('');
}
function updateScene() {
  const candidate = current();
  view?.setPalette(palette.id);
  if (bundle && candidate) view?.update(bundle.request, candidate, isStale() ? undefined : evaluation(), step, bundle.candidates.find((item) => item.id === compareId));
  view?.select(selectedHold);
  view?.setBody($<HTMLInputElement>('#show-body').checked);
  view?.setLabels($<HTMLInputElement>('#show-labels').checked);
  view?.setRouteOnly(viewingAlternative() || bundle?.request.profile === 'setting' ? false : $<HTMLInputElement>('#route-only').checked);
  view?.setRoutePath($<HTMLInputElement>('#route-path').checked);
  view?.setSurfaces($<HTMLInputElement>('#show-surfaces').checked);
}

function makeRevision(change: (candidate: Candidate) => void, note: string, inventoryId = selectedInventory) {
  const candidate = current(); if (!candidate || !bundle || busy || viewingAlternative() || bundle.request.mode === 'fixed') return;
  const updated = structuredClone(candidate);
  updated.id = `manual-${crypto.randomUUID()}`; updated.parent_id = candidate.id; updated.revision = candidate.revision + 1;
  updated.name = `${candidate.name.replace(/ · 修改 \d+$/, '')} · 修改 ${updated.revision}`; updated.generator = 'manual';
  delete updated.search_metadata;
  if (updated.layout_report) updated.layout_report = { ...updated.layout_report, reason: '当前修订仅保留起始接触，尚未为新点位搜索完整走法。', search: [] };
  change(updated); delete updated.setting_report; updated.design_notes = [...(updated.design_notes || []), note];
  clearLearnedExperiment();
  clearOwnRoute();
  activeDraftIntent = undefined;
  clearBetaAudit();
  bundle.candidates.push(updated); activeId = updated.id; compareId = candidate.id;
  selectedInventory = inventoryId; selectedHold = updated.placements.find(p => p.inventory_id === inventoryId)?.id || '';
  const updatedRoute = new Set(updated.states.flatMap(state => Object.values(state.contacts).flatMap(contact => contact ? [contact.placement_id] : [])));
  // Installing or editing a spare hold is an explicit request to inspect it; reveal it as background.
  if (selectedHold && !updatedRoute.has(selectedHold)) $<HTMLInputElement>('#route-only').checked = false;
  renderAll(); toast('已保存新修订。原方案保留，当前修订待重新检查。');
}
function saveEdit(event: SubmitEvent) {
  event.preventDefault(); if (!bundle || busy || viewingAlternative() || bundle.request.mode === 'fixed') return;
  const form = new FormData(event.target as HTMLFormElement);
  const raw = ['u', 'v', 'rotation_deg'].map(name => form.get(name));
  if (raw.some(value => value === null || String(value).trim() === '' || !Number.isFinite(Number(value)))) { showNotice('请填写有效的位置和旋转数值，0 是有效数值。'); return; }
  const original = current()?.placements.find(p => p.id === selectedHold);
  const changed: Placement = { ...(original || { id: `installation-${crypto.randomUUID()}`, inventory_id: selectedInventory }), u: Number(raw[0]), v: Number(raw[1]), rotation_deg: Number(raw[2]) };
  const mount = form.get('mount');
  if (String(mount || '').startsWith('panel:')) { changed.wall_panel_id = String(mount).slice(6); delete changed.mount; }
  else if (mount) { changed.mount = JSON.parse(String(mount)); delete changed.wall_panel_id; }
  else { delete changed.mount; delete changed.wall_panel_id; }
  const surface = form.get('contact_surface_id');
  if (surface) changed.contact_surface_id = String(surface); else delete changed.contact_surface_id;
  if (original && JSON.stringify(changed) === JSON.stringify(original)) { toast('安装和接触选择没有变化。'); return; }
  if (!original && current()?.placements.some(p => p.inventory_id === selectedInventory)) { showNotice('这件库存已经安装，不能重复使用。'); return; }
  makeRevision(candidate => {
    if (original) candidate.placements[candidate.placements.findIndex(p => p.id === original.id)] = changed;
    else candidate.placements.push(changed);
  }, `${original ? '修改' : '安装'} ${changed.inventory_id}：${JSON.stringify(changed)}`);
}
function savePlacementRevision(id: string, changes: Partial<Pick<Placement, 'u' | 'v' | 'rotation_deg'>>, source: string) {
  if (busy || !bundle || viewingAlternative() || bundle.request.mode === 'fixed') { updateScene(); return; }
  const placement = current()?.placements.find(p => p.id === id); if (!placement) return;
  if (!Object.values(changes).every(value => typeof value === 'number' && Number.isFinite(value))) { showNotice('位置和旋转必须是有效数字。'); updateScene(); return; }
  if (Object.entries(changes).every(([key, value]) => Math.abs(value! - placement[key as 'u' | 'v' | 'rotation_deg']) < 1e-9)) { updateScene(); return; }
  makeRevision(candidate => Object.assign(candidate.placements.find(p => p.id === id)!, changes), `${source} ${id}：${JSON.stringify(changes)}`, placement.inventory_id);
}
function removeInstallation() {
  const candidate = current(), placement = candidate?.placements.find(p => p.id === selectedHold);
  if (!candidate || !placement || routePlacementIds().has(placement.id) || candidate.placements.some(p => p.mount?.parent_id === placement.id)) return;
  makeRevision(next => { next.placements = next.placements.filter(p => p.id !== placement.id); }, `卸下 ${placement.inventory_id} 并归还库存。`);
}
async function recheck() {
  const candidate = current(); if (!bundle || !candidate || busy || viewingAlternative()) return;
  clearBetaAudit();
  const workingBundle = bundle; setBusy(true, '检查计算中…');
  try {
    const result = await api<{ candidate: Candidate; evaluation: Evaluation }>('/api/evaluate', { request: bundle.request, candidate });
    const index = workingBundle.candidates.findIndex((item) => item.id === candidate.id);
    workingBundle.candidates[index] = result.candidate;
    workingBundle.evaluations = workingBundle.evaluations.filter((item) => item.candidate_id !== candidate.id);
    workingBundle.evaluations.push(result.evaluation);
    activeId = result.candidate.id;
    renderAll(); toast('检查完成。结果仅适用于当前模型与检查范围。');
  } catch (error) { showNotice(`检查未完成：${error instanceof Error ? error.message : error}`); }
  finally { setBusy(false); renderSummary(); }
}
async function generate(event: SubmitEvent) {
  event.preventDefault(); if (busy || !defaults) return;
  const form = new FormData(event.target as HTMLFormElement);
  const seed = Number(form.get('seed')); if (!Number.isSafeInteger(seed)) { showNotice('随机种子必须为整数。'); return; }
  setBusy(true); $('#notice').hidden = true;
  try {
    if (form.get('profile') === 'setting') {
      setBusy(true, '联合搜索摆点与走法…');
      const comparison = await api<{ examples: StyleExample[] }>('/api/setting-comparison', { body_id: form.get('body'), seed, hold_source: form.get('hold_source'), wall_profile: form.get('wall_profile') });
      if (!comparison.examples?.length) throw new Error('本次没有返回摆点实验。');
      settingExamples = comparison.examples; settingBeforeBundles.clear();
      acceptBundle(settingExamples[0].bundle);
      toast('三种空间摆点实验已返回；可以切换调整前后与不同走法。');
      return;
    }
    if (form.get('profile') === 'route' && form.get('route_program') === 'compare') {
      setBusy(true, '搜索三条完整线路…');
      const comparison = await api<{ examples: StyleExample[] }>('/api/route-comparison', { body_id: form.get('body'), angle_deg: Number(form.get('angle')), hand_moves: Number(form.get('hand_moves')), seed, budget: defaults.request.budget || 3 });
      if (!Array.isArray(comparison.examples) || !comparison.examples.length) throw new Error('本次没有返回线路对照。');
      routeExamples = comparison.examples; acceptBundle(routeExamples[0].bundle);
      $<HTMLSelectElement>('#route-program').value = 'compare';
      toast('三种阶段计划已分别搜索，选点和动作均已重新检查。');
      return;
    }
    if (form.get('profile') === 'style' && form.get('style_goal') === 'compare') {
      setBusy(true, '搜索三种风格…');
      const comparison = await api<{ examples: StyleExample[] }>('/api/style-comparison', { body_id: form.get('body'), angle_deg: Number(form.get('angle')), seed, budget: defaults.request.budget || 3, rhythm: form.get('rhythm') });
      if (!Array.isArray(comparison.examples) || !comparison.examples.length) throw new Error('本次没有返回风格对照。');
      styleExamples = comparison.examples;
      acceptBundle(styleExamples[0].bundle);
      $<HTMLSelectElement>('#style-goal').value = 'compare';
      toast('三种风格已在同墙、同身材和同节奏下分别搜索并检查。');
      return;
    }
    const catalogCounts = form.get('profile') === 'catalog' ? Object.fromEntries((defaults.catalog_templates || []).map(item => [item.type, Number(form.get(`stock_${item.type}`))])) : undefined;
    const isStyle = form.get('profile') === 'style', isRoute = form.get('profile') === 'route';
    const parameters = { ...(catalogCounts ? { catalog_counts: catalogCounts } : {}), ...(isRoute ? { route_program: form.get('route_program'), scenario: 'route_search' } : isStyle ? { style_goal: form.get('style_goal'), rhythm: form.get('rhythm') } : { scenario: form.get('profile') === 'competition' ? 'competition_sequence' : form.get('scenario') }), profile: form.get('profile'), body_id: form.get('body'), mode: isRoute ? 'free' : isStyle ? 'fixed' : form.get('mode'), angle_deg: Number(form.get('angle')), hand_moves: isStyle || form.get('profile') === 'competition' ? 4 : Number(form.get('hand_moves')), seed, budget: form.get('profile') === 'competition' && form.get('mode') === 'fixed' ? 1 : defaults.request.budget || 3 };
    const response = await api<Request | { request: Request }>('/api/request', parameters);
    const request = 'request' in response ? response.request as Request : response as Request;
    const result = await api<Bundle>('/api/generate', { request });
    acceptBundle(result); toast(`已生成并检查 ${result.candidates.length} 个候选。`);
  } catch (error) { showNotice(`生成未完成：${error instanceof Error ? error.message : error}。当前方案已保留。`); }
  finally { setBusy(false); }
}
function download(data: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function exportBundle() {
  if (!bundle || busy) return;
  const source = bundle, savedCandidateId = activeId; setBusy(true, '整理结果包…');
  try {
    // Opening a saved draft should show the revision the setter was working on.
    // Order it before canonicalization so the integrity digest covers that order.
    const savedCandidate = source.candidates.find(candidate => candidate.id === savedCandidateId);
    const candidates = savedCandidate ? [savedCandidate, ...source.candidates.filter(candidate => candidate.id !== savedCandidateId)] : source.candidates;
    const canonical = await api<Bundle>('/api/bundle', { request: source.request, candidates, evaluations: source.evaluations, reviews: source.reviews || [] });
    download(canonical, `bettar-${canonical.request.seed}-${new Date().toISOString().slice(0, 10)}.json`);
    toast('结果包已校验并导出，包含候选、当前检查与反馈。');
  } catch (error) { showNotice(`导出未完成：${error instanceof Error ? error.message : error}`); }
  finally { setBusy(false); }
}
function saveReview() {
  if (viewingAlternative()) return;
  const text = $<HTMLTextAreaElement>('#review-text').value.trim(); const candidate = current();
  if (!bundle || !candidate || !text) { toast('先写下这份方案的反馈。'); return; }
  const ev = isStale() ? undefined : evaluation();
  const review: Review = { id: crypto.randomUUID(), candidate_id: candidate.id, candidate_revision: candidate.revision, evaluation_id: ev?.id || null, evaluation_fingerprint: ev?.fingerprint || null, state_id: candidate.states[step]?.id || null, placement_id: selectedHold || null, kind: 'design_review', text, created_at: new Date().toISOString() };
  (bundle.reviews ||= []).push(review); $<HTMLTextAreaElement>('#review-text').value = ''; renderReviews(); toast('反馈已保存到当前结果包，可导出留存。');
}

$('#generation-form').addEventListener('submit', generate);
$('#scene-palette').addEventListener('change', event => {
  palette = getScenePalette((event.target as HTMLSelectElement).value);
  try { localStorage.setItem('betar.scene-palette', palette.id); } catch { /* Optional presentation preference. */ }
  renderEditor(); renderLibrary(); updateScene();
  $('#canvas-legend').style.setProperty('--route-ink', `#${palette.route.toString(16).padStart(6, '0')}`);
});
$('#profile').addEventListener('change', syncProfileControls);
$('#style-goal').addEventListener('change', syncProfileControls);
$('#route-program').addEventListener('change', syncProfileControls);
$('#mode').addEventListener('change', syncProfileControls);
$('#show-surfaces').addEventListener('change', (e) => view?.setSurfaces((e.target as HTMLInputElement).checked));
$('#show-labels').addEventListener('change', (e) => view?.setLabels((e.target as HTMLInputElement).checked));
$('#show-body').addEventListener('change', (e) => { view?.setBody((e.target as HTMLInputElement).checked); renderSteps(); });
$('#route-only').addEventListener('change', (e) => view?.setRouteOnly((e.target as HTMLInputElement).checked));
$('#route-path').addEventListener('change', (e) => view?.setRoutePath((e.target as HTMLInputElement).checked));
$('#compare').addEventListener('change', (e) => { compareId = (e.target as HTMLSelectElement).value; renderComparison(); updateScene(); });
$('#history').addEventListener('change', (e) => { if (busy) return; const next = histories[Number((e.target as HTMLSelectElement).value)]; if (next) acceptBundle(next, false); });
$('#draft-picker').addEventListener('change', () => { void chooseDraft(); });
$('#draft-form').addEventListener('submit', event => { void viewIntentDraft(event as SubmitEvent); });
$('#draft-wall').addEventListener('change', event => { void viewIntentDraft(event); });
$('#draft-style').addEventListener('change', () => { try { localStorage.setItem('bettar.draft-style', $<HTMLSelectElement>('#draft-style').value); } catch { /* Optional storage. */ } });
$('#import-file').addEventListener('change', async (event) => {
  const input = event.target as HTMLInputElement; const file = input.files?.[0]; if (!file || busy) return;
  setBusy(true, '校验导入中…');
  try {
    const parsed = JSON.parse(await file.text());
    const result = await api<Bundle>('/api/validate', { bundle: parsed });
    acceptBundle(result); toast('已完成校验并导入结果包。');
  } catch (error) { showNotice(`导入失败：${error instanceof Error ? error.message : error}。当前方案未改变。`); }
  finally { input.value = ''; setBusy(false); }
});
document.addEventListener('click', (event) => {
  const button = (event.target as HTMLElement).closest<HTMLElement>('[data-action]');
  if (!button || button.hasAttribute('disabled')) return;
  const action = button.dataset.action;
  if (busy && ['candidate', 'style-example', 'route-example', 'setting-example', 'setting-stage', 'setting-path', 'import', 'save-review', 'export-bundle', 'export-review'].includes(action || '')) return;
  if (action === 'tools') showWorkspace($('#tools-view').hidden);
  else if (action === 'workbench') showWorkspace(false);
  else if (action === 'checks') showScreen('checks');
  else if (action === 'open-replay') { showStep(0); }
  else if (action === 'close-replay') { replayOpen = false; $<HTMLInputElement>('#show-body').checked = false; view?.setBody(false); renderSteps(); }
  else if (action === 'close-editor') { selectedHold = ''; selectedInventory = ''; editMode = false; view?.select(''); renderEditor(); renderLibrary(); syncToolState(); }
  else if (action === 'open-inventory') { showWorkspace(true); const library = $<HTMLDetailsElement>('.hold-library'); library.open = true; library.scrollIntoView({block:'start'}); }
  else if (action === 'board-study') { $<HTMLSelectElement>('#profile').value = 'style'; $<HTMLSelectElement>('#style-goal').value = 'compare'; syncProfileControls(); $('#generation-form').scrollIntoView({ block: 'center' }); $<HTMLSelectElement>('#style-goal').focus(); toast('已设置同墙风格对照；点击生成后搜索不同选点与动作序列。'); }
  else if (action === 'setting-example') selectSettingExample(button.dataset.id || '');
  else if (action === 'own-route') void openOwnRouteStudy(button.dataset.routeId);
  else if (action === 'own-route-reload') { ownRouteStudy = undefined; void openOwnRouteStudy(); }
  else if (action === 'learned-open') void openLearnedExperiment();
  else if (action === 'learned-run') void selectLearnedRun(button.dataset.runId || '');
  else if (action === 'setting-stage') { const context = settingContext(); if (context) selectSettingExample(context.example.id, button.dataset.stage); }
  else if (action === 'wall-example') void loadWallExample(button.dataset.wallProfile || 'overhang');
  else if (action === 'setting-source') void loadSettingSource(button.dataset.source === 'templates' ? 'templates' : 'assets');
  else if (action === 'setting-path') selectSettingPath(button.dataset.id || '');
  else if (action === 'route-example') { const example = routeExamples.find(item => item.id === button.dataset.id); if (example) acceptBundle(example.bundle, !histories.includes(example.bundle)); }
  else if (action === 'style-example') { const example = styleExamples.find(item => item.id === button.dataset.id); if (example) acceptBundle(example.bundle, !histories.includes(example.bundle)); }
  else if (action === 'show-references') { showWorkspace(true); ($('#competition-references') as HTMLDetailsElement).open = true; $('#competition-references').scrollIntoView({block:'start'}); }
  else if (action === 'beta-audit') void auditBeta();
  else if (action === 'beta-select') selectBeta(button.dataset.id || '');
  else if (action === 'beta-export' && betaReport && !busy) download(betaReport, `beta-audit-${betaReport.source.candidate_id}-r${betaReport.source.revision}.json`);
  else if (action === 'candidate') { clearBetaAudit(); if (activeId !== button.dataset.id) { clearLearnedExperiment(); clearOwnRoute(); activeDraftIntent = undefined; } activeId = button.dataset.id!; step = 0; selectedHold = ''; selectedInventory = ''; replayOpen = false; $<HTMLInputElement>('#show-body').checked = false; view?.setBody(false); showWorkspace(false); renderAll(); }
  else if (action === 'phase') { showStep(Number(button.dataset.step)); renderBrief(); }
  else if (action === 'roof-step' || action === 'roof-view') {
    const nextStep = Number(button.dataset.step);
    if (busy || !Number.isInteger(nextStep) || !current()?.states[nextStep]) return;
    showWorkspace(false, false); replayOpen = true; step = nextStep; $<HTMLInputElement>('#show-body').checked = true; view?.setBody(true);
    renderSteps(); view?.setStep(step);
    if (action === 'roof-view') $('.canvas-shell').scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }
  else if (action === 'step') showStep(Number(button.dataset.step));
  else if (action === 'previous' || action === 'next') { const target = current() ? timelineNavigation(current()!, step)[action] : null; if (target !== null) showStep(target); }
  else if (action === 'front' || action === 'perspective') {
    if (action === 'front') view?.front(); else view?.perspective();
    document.querySelectorAll('.view-button').forEach((element) => element.classList.toggle('active', element === button));
  }
  else if (action === 'remove-installation') removeInstallation();
  else if (action === 'recheck') void recheck();
  else if (action === 'import') $<HTMLInputElement>('#import-file').click();
  else if (action === 'export-bundle') void exportBundle();
  else if (action === 'export-review' && bundle) download({ schema_version: '1.0', bundle_id: bundle.id, reviews: bundle.reviews || [] }, `bettar-reviews-${bundle.request.seed}.json`);
  else if (action === 'save-review') saveReview();
  else if (action === 'dismiss-notice') $('#notice').hidden = true;
  else if (action === 'retry') void initialize();
  else if (action === 'select-hold') selectPlacement(button.dataset.id!);
  else if (action === 'library-hold') selectInventory(button.dataset.id!);
  else if (action === 'hold-filter') { holdFilter = button.dataset.type || 'all'; renderLibrary(); }
  else if (action === 'browse-mode') { editMode = false; selectedHold = ''; selectedInventory = ''; view?.select(''); renderEditor(); syncToolState(); }
  else if (action === 'move-mode' && !busy && !viewingAlternative() && bundle?.request.mode === 'free') { editMode = true; renderEditor(); syncToolState(); }
  else if (action === 'focus-hold' && selectedHold) { showWorkspace(false, false); view?.focusHold(selectedHold); }
  else if (action === 'focus-parent') { const parent = current()?.placements.find(p => p.id === selectedHold)?.mount?.parent_id; if (parent) { view?.focusHold(parent); view?.select(selectedHold); } }
  else if ((action === 'rotate-minus' || action === 'rotate-plus') && !busy && !viewingAlternative() && bundle?.request.mode === 'free') {
    const input = document.querySelector<HTMLInputElement>('#edit-form input[name="rotation_deg"]');
    if (input) { const value = Number(input.value); if (Number.isFinite(value)) { input.value = String(value + (action === 'rotate-plus' ? 15 : -15)); toast('点“应用调整”确认新朝向。'); } }
  }
  else if (action === 'locate-check') {
    showWorkspace(false, false);
    const check = evaluation()?.checks.filter((item) => item.status !== 'not_checked')[Number(button.dataset.checkIndex)];
    if (check?.state_id) { const index = current()?.states.findIndex((item) => item.id === check.state_id); if (index !== undefined && index >= 0) showStep(index); }
    selectedHold = check?.placement_ids?.[0] || ''; selectedInventory = '';
    ensureSelection(); renderSteps(); renderEditor(); renderLibrary(); view?.setStep(step); view?.select(selectedHold); if (selectedHold) view?.focusHold(selectedHold);
  }
});
document.addEventListener('keydown', (event) => {
  if ($('#workbench-view').hidden || ['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'SUMMARY'].includes((event.target as HTMLElement).tagName) || !current()) return;
  const nav = timelineNavigation(current()!, step);
  if (event.key === 'ArrowLeft' && nav.previous !== null) { event.preventDefault(); showStep(nav.previous); }
  if (event.key === 'ArrowRight' && nav.next !== null) { event.preventDefault(); showStep(nav.next); }
});

let referenceLoad: Promise<void> | undefined;
async function loadReferenceDrafts() {
  if (referenceLoad) return referenceLoad;
  const message = $('#reference-load-status');
  message.hidden = false; message.textContent = '读取其他已保存规则草稿…';
  referenceLoad = (async () => {
    const results = await Promise.allSettled([api<{ examples: StyleExample[] }>('/api/route-examples'), api<{ examples: StyleExample[] }>('/api/setting-examples')]);
    if (results[0].status === 'fulfilled') routeExamples = results[0].value.examples || [];
    if (results[1].status === 'fulfilled') settingExamples = results[1].value.examples || [];
    const failures = results.filter(result => result.status === 'rejected');
    message.hidden = !failures.length;
    message.textContent = failures.length ? '部分旧草稿暂不可用；当前规则线路不受影响。墙形可通过下方按钮单独读取。' : '';
    renderStyleStudy(); renderSettingStudy();
  })();
  return referenceLoad;
}
$('.saved-reference-drafts').addEventListener('toggle', event => { if ((event.target as HTMLDetailsElement).open) void loadReferenceDrafts(); });
async function initialize() {
  $('#canvas-empty').hidden = false;
  $('#canvas-empty').innerHTML = '<span class="loading-spinner"></span><h2>正在打开工作台</h2><p>读取规则线路与检查结果</p>';
  // Current rules are independent of optional historical fixtures and model runs.
  const results = await Promise.allSettled([api<Defaults>('/api/defaults'), api<OwnRouteStudy>('/api/own-routes-study')]);
  if (results[0].status === 'fulfilled') { defaults = results[0].value; populateControls(defaults.request); }
  let ownLoaded = false;
  if (results[1].status === 'fulfilled' && results[1].value.schema_version === 'own-routes-study-v1') {
    ownRouteStudy = results[1].value;
    try {
      const route = ownRouteStudy.routes.find(item => item.id === ownRouteStyleIds[$<HTMLSelectElement>('#draft-style').value]) || ownRouteStudy.routes[0];
      if (route) { await readOwnRoute(route); ownLoaded = true; }
    } catch (error) { ownRouteError = `规则线路暂不可用：${error instanceof Error ? error.message : String(error)}`; }
  } else if (results[1].status === 'rejected') { ownRouteError = `规则线路暂不可用：${results[1].reason instanceof Error ? results[1].reason.message : String(results[1].reason)}`; }
  if (!ownLoaded) {
    $('#canvas-empty').innerHTML = `<div class="empty-icon">${icon('cube')}</div><h2>草稿未能载入</h2><p>重新连接，或从顶部菜单选择其他草稿。</p><button class="button outlined" data-action="retry">${icon('refresh')}重新连接</button>`;
  }
  syncDraftControls(); renderOwnRouteStudy();
  if (results[0].status === 'rejected') showNotice('默认配置加载失败，生成暂不可用。请确认本地服务已运行后重新连接。');
}
window.addEventListener('pagehide', () => preview?.dispose(), { once: true });
renderLearnedExperiment();
void initialize();
