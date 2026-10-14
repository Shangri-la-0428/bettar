/// <reference types="vite/client" />
import type { GripSurface, Hold, Vec3 } from './types';
import { escape as esc } from './types.ts';

export interface HoldAsset {
  id: string; family: string; label: string;
  width: number; height: number; depth: number;
  geometry: { positions: Vec3[]; triangles: [number, number, number][] };
  geometry_sha256: string;
  asset_record_sha256: string;
  source: { url: string; author: string; license: string; license_url: string; original_sha256: string; [key: string]: unknown };
  scale: { basis: string; verified: boolean; [key: string]: unknown };
  installation: Record<string, unknown>;
  classification?: { basis?: string; confidence?: string; observation?: string };
  preparation?: { original_triangles?: number; prepared_triangles?: number; modifications?: string[] };
  grip_surfaces: GripSurface[];
}
export const holdAssets: HoldAsset[] = [];
const registry = new Map<string, HoldAsset>();
/** Pure registry entry point also used by the offline geometry verifier. */
export function registerHoldAssetLibrary(library: { schema_version: string; assets: HoldAsset[] }) {
  if (library.schema_version !== 'hold-assets/1' || !Array.isArray(library.assets)) throw new Error('Unsupported hold asset registry');
  registry.clear(); holdAssets.splice(0, holdAssets.length, ...library.assets);
  for (const asset of holdAssets) registry.set(asset.id, asset);
}
// Vite watches this optional normalized registry. During source preparation the
// existing template UI remains usable; no placeholder third-party asset is made.
const libraries = typeof window !== 'undefined' ? import.meta.glob('../../assets/holds/library.json', { eager: true, import: 'default' }) : {};
for (const library of Object.values(libraries)) registerHoldAssetLibrary(library as { schema_version: string; assets: HoldAsset[] });

export type HoldAssetResolution = { kind: 'template' } | { kind: 'unavailable'; reason: string } | { kind: 'asset'; asset: HoldAsset; scale: number };
/** Referenced meshes never silently fall back to a synthetic shape. Geometry hash
 * is checked against the normalized registry; the offline importer owns hashing. */
export function resolveHoldAsset(hold: Hold): HoldAssetResolution {
  const externalEvidence = (typeof hold.template_id === 'string' && hold.template_id.startsWith('asset:'))
    || ['asset_id', 'asset_geometry_sha256', 'asset_record_sha256', 'asset_scale', 'asset_source'].some(key => key in hold)
    || (Array.isArray(hold.grip_surfaces) && hold.grip_surfaces.some(surface => 'mesh_anchor' in surface));
  if (!hold.asset_id) return externalEvidence ? { kind: 'unavailable', reason: '这件岩点保留了外部网格标记，但资产引用不完整。' } : { kind: 'template' };
  if (hold.asset_source !== 'external_mesh') return { kind: 'unavailable', reason: '结果包缺少有效的外部网格来源声明。' };
  const asset = registry.get(hold.asset_id);
  if (!asset) return { kind: 'unavailable', reason: '此资产未收录在当前本机库中。' };
  if (hold.asset_geometry_sha256 !== asset.geometry_sha256) return { kind: 'unavailable', reason: '结果包引用的几何版本与本机资产不一致。' };
  if (hold.asset_record_sha256 !== asset.asset_record_sha256) return { kind: 'unavailable', reason: '结果包引用的资产标注版本与本机资产不一致。' };
  const scale = hold.asset_scale;
  if (typeof scale !== 'number' || !Number.isFinite(scale) || scale <= 0) return { kind: 'unavailable', reason: '结果包缺少有效的同比缩放值。' };
  if (['width', 'height', 'depth'].some(key => !Number.isFinite(hold[key]) || Number(hold[key]) <= 0 || Math.abs(Number(hold[key]) - Number(asset[key as keyof HoldAsset]) * scale) > 1e-7)) return { kind: 'unavailable', reason: '库存尺寸与资产的同比缩放不一致。' };
  return { kind: 'asset', asset, scale };
}
function link(url: unknown, label: string) {
  if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) return esc(label);
  return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;
}
const vector = (value?: Vec3) => value ? value.map(n => n.toFixed(3)).join(', ') : '未声明';
const installationText = (asset: HoldAsset) => {
  const values = asset.installation || {};
  return typeof values.basis === 'string' ? values.basis : typeof values.description === 'string' ? values.description : '本机归一化安装面：局部 XY 平面，背面 z = 0；只声明几何贴合，不证明安装强度。';
};
export function holdAssetDetailsHTML(hold: Hold, surface?: GripSurface): string {
  const result = resolveHoldAsset(hold);
  if (result.kind === 'template') return hold.asset_fallback_reason ? `<p class="asset-fallback">当前使用参数模板：${esc(hold.asset_fallback_reason)}</p>` : '';
  if (result.kind === 'unavailable') return `<p class="asset-unavailable" role="status">资产无法显示：${esc(result.reason)}已省略模型与抓握面；请选择匹配的资产版本后再检查。</p>`;
  const { asset, scale } = result;
  return `<details class="model-details hold-asset-details"><summary>资产来源、尺度与接触标注</summary>
    <p><strong>${esc(asset.label)}</strong> · 外部三角网格 · ${asset.geometry.triangles.length.toLocaleString()} 面</p>
    <dl><div><dt>来源 / 作者</dt><dd>${link(asset.source.url, '原始模型')} · ${esc(asset.source.author || '未提供')}</dd></div>
    <div><dt>使用许可</dt><dd>${link(asset.source.license_url, asset.source.license || '未提供')}</dd></div>
    ${asset.classification?.confidence === 'provisional' ? '<div><dt>形态分类</dt><dd>根据网格形态暂定，尚未经定线员复核；不是厂家给出的型号分类。</dd></div>' : ''}
    ${asset.preparation ? `<div><dt>本机加工</dt><dd>已统一轴向与安装原点，使用界面材质${asset.preparation.original_triangles && asset.preparation.prepared_triangles ? `；三角面 ${asset.preparation.original_triangles.toLocaleString()} → ${asset.preparation.prepared_triangles.toLocaleString()}` : ''}。保留来源和加工记录。</dd></div>` : ''}
    <div><dt>尺度</dt><dd>${asset.scale.verified ? '已核实来源尺度' : '实验尺度假设'} · 当前同比缩放 ×${scale.toFixed(3)}<br />${esc(asset.scale.basis)}</dd></div>
    <div><dt>安装面</dt><dd>${esc(installationText(asset))}<br />${asset.installation.verified ? '已核实安装面标注' : '实验标注，未核验现场安装条件'}</dd></div>
    <div><dt>所选接触</dt><dd>${esc(surface?.label || '未选择')}${surface?.mesh_anchor ? ` · 登记网格三角面 ${surface.mesh_anchor.triangle_index}` : ''}</dd></div>
    <div><dt>局部面法向</dt><dd>[${vector(surface?.normal)}]</dd></div>
    <div><dt>声明有效拉向</dt><dd>[${vector(surface?.pull_direction)}] · 是定线假设，非实测受力</dd></div></dl>
    <p>浅色区域裁切自本资产的三角面，代表点来自网格标注。碰撞仍使用保守包围体；接触只取代表点，不等于完整手指接触仿真。</p>
    <p class="asset-fingerprint">几何 ${esc(asset.geometry_sha256)}<br />原文件 ${esc(asset.source.original_sha256)}</p></details>`;
}
