import type { Bundle, Candidate, Contact, Evaluation, Hold, Limb, Placement } from './types.ts';
import { escape as esc, holdFamily, limbNames } from './types.ts';
import { selectedGripSurface } from './placement-geometry.ts';

export interface OwnRoute {
  id: string; label: string; style?: string; intent: string; status: string;
  bundle_digest: string;
  bundle_url?: string;
  metrics?: Record<string, unknown>;
  completion?: { added_foot_ids?: string[]; enabled_standing_ids?: string[]; before?: Record<string, unknown>; after?: Record<string, unknown> };
}
export interface OwnRouteStudy {
  schema_version: 'own-routes-study-v1'; id: string; title: string;
  routes: OwnRoute[]; limitations?: string[]; pairwise?: { a: string; b: string; shared_used_fraction: number; geometry_same: boolean; sequence_same: boolean }[];
}
const value = (v: unknown, digits = 1) => typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—';
const count = (v: unknown) => Array.isArray(v) ? v.length : typeof v === 'number' ? v : '—';

export async function readOwnRouteBundle(route: OwnRoute, cache: Map<string, Bundle>, read: () => Promise<Bundle>) {
  const bundle = cache.get(route.id) || await read();
  if (typeof route.bundle_digest !== 'string' || !/^sha256:[a-f0-9]{64}$/.test(route.bundle_digest)
      || bundle.manifest?.bundle_digest !== route.bundle_digest) {
    throw new Error('规则线路包与当前对照记录不属于同一批次，请刷新页面，重新读取整组规则线路后重试');
  }
  cache.set(route.id, bundle);
  return bundle;
}

function comparisonHTML(study: OwnRouteStudy) {
  const names = new Map(study.routes.map(route => [route.id, route.label]));
  return `<details class="own-route-compare"><summary>比较实际结果与线路差异</summary><div class="learned-table-scroll" tabindex="0" role="region" aria-label="三条规则线路的实际结果，可横向滚动"><table class="learned-table"><thead><tr><th scope="col">线路</th><th scope="col">移手 / 移脚</th><th scope="col">先抓后踩的点</th><th scope="col">补入可用脚点</th><th scope="col">峰值负荷</th><th scope="col">释放态静态通过</th></tr></thead><tbody>${study.routes.map(route => { const m = route.metrics || {}; return `<tr><th scope="row">${esc(route.label)}</th><td>${value(m.hand_moves, 0)} / ${value(m.foot_moves, 0)}</td><td>${count(m.hand_then_foot_ids)}</td><td>${route.completion?.added_foot_ids?.length ?? '—'}</td><td>${value(m.peak_load)}</td><td>${value(m.static_release_pass, 0)} / ${value(m.static_release_total, 0)}</td></tr>`; }).join('')}</tbody></table></div>${study.pairwise?.map(pair => `<p>${esc(names.get(pair.a) || pair.a)} / ${esc(names.get(pair.b) || pair.b)}：${pair.geometry_same ? '点位与朝向相同' : '点位或朝向不同'}，${pair.sequence_same ? '接触序列相同' : '接触序列不同'}${typeof pair.shared_used_fraction === 'number' ? `，使用点重合 ${value(100 * pair.shared_used_fraction, 0)}%` : ''}。</p>`).join('') || ''}<p>这里比较保存结果中的实际指标；意图不等同于已验证的风格或难度。</p></details>`;
}

export function contactPresentation(contact: Contact, limb: Limb, placement: Placement | undefined, hold: Hold | undefined) {
  const isFoot = limb.endsWith('F');
  let surfaceLabel = contact.contact_id;
  if (placement && hold) {
    try { surfaceLabel = selectedGripSurface(placement, hold, contact.contact_id)?.label || '默认接触面'; }
    catch { surfaceLabel = `未识别面 · ${contact.contact_id}`; }
  }
  const onHandHold = !!hold && isFoot && !['foot_chip', 'volume'].includes(holdFamily(hold));
  return { surfaceLabel, onHandHold, action: isFoot ? '踩踏' : '抓握' };
}

export function actualRouteMetrics(bundle: Bundle, candidate: Candidate, evaluation?: Evaluation) {
  const hand = new Set<string>(), foot = new Set<string>(), steppedHandholds = new Set<string>();
  const holds = new Map(bundle.request.scene.inventory.map(hold => [hold.id, hold]));
  const placements = new Map(candidate.placements.map(placement => [placement.id, placement]));
  candidate.states.forEach(state => Object.entries(state.contacts).forEach(([limb, contact]) => {
    if (!contact) return;
    (limb.endsWith('H') ? hand : foot).add(contact.placement_id);
    const placement = placements.get(contact.placement_id), hold = placement && holds.get(placement.inventory_id);
    if (contactPresentation(contact, limb as Limb, placement, hold).onHandHold) steppedHandholds.add(contact.placement_id);
  }));
  const handTransfers = candidate.events.filter(event => event.limb.endsWith('H')).length;
  const release = evaluation?.mechanics_report?.states.filter(state => state.is_release) || [];
  const moves = evaluation?.design_analysis?.moves || [];
  const loads = moves.map(move => move.accumulated_load).filter(Number.isFinite);
  const handToFoot = candidate.events.flatMap((event, index) => {
    if (!event.limb.endsWith('F')) return [];
    const destination = candidate.states.find(state => state.id === event.to_state)?.contacts[event.limb];
    if (!destination) return [];
    const prior = candidate.states.slice(0, candidate.states.findIndex(state => state.id === event.to_state));
    if (!prior.some(state => state.contacts.LH?.placement_id === destination.placement_id || state.contacts.RH?.placement_id === destination.placement_id)) return [];
    return [{ eventIndex: index, stateIndex: candidate.states.findIndex(state => state.id === event.to_state), limb: event.limb, placementId: destination.placement_id, contactId: destination.contact_id }];
  });
  return { handTransfers, footTransfers: candidate.events.length - handTransfers, used: new Set([...hand, ...foot]).size, shared: [...hand].filter(id => foot.has(id)).length, steppedHandholds: [...steppedHandholds], handToFoot, releasePassed: release.filter(state => state.status === 'feasible').length, releaseTotal: release.length, peakLoad: loads.length ? Math.max(...loads) : undefined, finalLoad: loads.at(-1), geometry: evaluation?.summary.status };
}

export function ownRouteChoicesHTML(study: OwnRouteStudy | undefined, activeId: string, busy: boolean, error = '') {
  if (!study) return error ? `<p class="own-route-error" role="status">${esc(error)}</p><button class="button outlined" data-action="own-route-reload" ${busy ? 'disabled' : ''}>重新读取规则线路</button>` : '';
  return `<div class="own-route-heading"><h2>三条规则线路</h2><p>比较点位、踩踏与手脚顺序，再选一条继续调整。</p></div><div class="own-route-choices" role="group" aria-label="选择规则线路">${study.routes.map((route, index) => `<button data-action="own-route" data-route-id="${esc(route.id)}" class="own-route-choice ${activeId === route.id ? 'active' : ''}" aria-pressed="${activeId === route.id}" ${busy ? 'disabled' : ''}><span class="own-route-number">${String(index + 1).padStart(2, '0')}</span><span><strong>${esc(route.label)}</strong><small>${esc(route.intent)}</small></span></button>`).join('')}</div>${comparisonHTML(study)}${error ? `<p class="own-route-error" role="status">${esc(error)}</p>` : ''}`;
}

export function ownRouteDetailHTML(route: OwnRoute, bundle: Bundle, candidate: Candidate, evaluation: Evaluation | undefined, stale: boolean) {
  const m = actualRouteMetrics(bundle, candidate, stale ? undefined : evaluation);
  const added = route.completion?.added_foot_ids;
  const before = route.completion?.before?.metrics as Record<string, unknown> | undefined;
  const progress = before ? before.complete === true && before.p0_status === 'pass' ? '补全前已有完整走法' : '补全前预算内未找到完整走法' : '';
  const enabled = route.completion?.enabled_standing_ids?.length;
  return `<div class="own-route-detail-heading"><div><span class="section-label">规则搜索 · 待定线员调整</span><h2>${esc(route.label)}</h2></div><span class="small-badge">${candidate.layout_report ? '预算内未找到完整走法' : stale ? '修订待检查' : '已保存走法'}</span></div><p class="own-route-intent">${esc(route.intent)}</p><dl class="own-route-metrics"><div><dt>移手 / 移脚</dt><dd>${m.handTransfers} / ${m.footTransfers}</dd></div><div><dt>踩到手点 / 手脚共用</dt><dd>${m.steppedHandholds.length} / ${m.shared}</dd></div><div><dt>使用 / 安装</dt><dd>${m.used} / ${candidate.placements.length}</dd></div><div><dt>峰值 / 最终负荷</dt><dd>${value(m.peakLoad)} / ${value(m.finalLoad)}</dd></div><div><dt>几何检查</dt><dd>${stale ? '待重算' : m.geometry === 'pass' ? '通过' : m.geometry === 'fail' ? '需调整' : '尚未通过'}</dd></div><div><dt>释放态静态通过</dt><dd>${m.releaseTotal ? `${m.releasePassed} / ${m.releaseTotal}` : '—'}</dd></div></dl>${m.handToFoot.length ? `<div class="own-route-moments"><span>手转脚位置</span>${m.handToFoot.map(item => `<button class="text-button" data-action="phase" data-step="${item.stateIndex}">${esc(limbNames[item.limb])}踩 ${esc(item.placementId)} ↗</button>`).join('')}</div>` : '<p class="own-route-note">这条走法没有先抓后踩同一点；踩手点与手脚共用均按实际接触记录计数。</p>'}${progress || added?.length || enabled ? `<p class="own-route-note">${progress ? `${progress}；` : ''}${added?.length ? `补入 ${added.length} 个可用脚点（${added.map(esc).join('、')}）` : '沿用现有可用脚点'}${enabled ? `，启用 ${enabled} 个岩点的独立踩面` : ''}。每次踩踏仍需通过几何与支撑检查。</p>` : ''}<p class="own-route-note">负荷是算法的相对估计，不能换算为真人等级；几何通过不代表静态支撑全部通过。动态跳跃与连续动作尚未模拟。</p>`;
}
