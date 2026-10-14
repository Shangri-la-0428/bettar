import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLExporter } from 'three/addons/exporters/STLExporter.js';
import { demoJug, demoWall, normalizeScan, parseScan, trianglePatch, MAX_SCAN_BYTES } from './scan-geometry';
import type { ScanTriangle, ScanUnit, ScanUp } from './scan-geometry';
import './scan-model.css';

export function scanWorkbenchHTML(): string {
  return `<details class="scan-workbench"><summary><span>墙体与岩点 · 三维网格工作台</span><span>导入扫描 / 检查凹腔与接触法向</span></summary>
    <p class="scan-intro">复杂墙面、倒扣和孔洞需要完整三角网格。先确认尺寸、坐标和接触面，再接入定线计算。这里保留真实网格形状；示例为原创几何，尚无实扫数据。</p>
    <div class="scan-toolbar"><button class="button outlined" data-scan="wall">折面墙示例</button><button class="button outlined" data-scan="jug">倒扣岩点示例</button><button class="button primary" data-scan="import">导入 STL / OBJ</button><input class="scan-file" type="file" accept=".stl,.obj" hidden />
      <label>模型对象<select class="scan-role" aria-label="扫描模型对象"><option value="unassigned">待指定</option><option value="wall" selected>墙体</option><option value="hold">岩点</option></select></label>
      <label>文件原始单位<select class="scan-unit" aria-label="扫描原始单位"><option value="m">米 m</option><option value="cm">厘米 cm</option><option value="mm">毫米 mm</option></select></label>
      <label>向上轴<select class="scan-up" aria-label="扫描向上轴"><option value="Y">Y</option><option value="Z">Z</option></select></label>
      <button class="button quiet" data-scan="transform">应用到当前模型</button><label class="scan-wire-label"><input type="checkbox" class="scan-wire" /> 网格边线</label>
    </div>
    <div class="scan-grid"><div class="scan-viewport" role="img" aria-label="三维网格预览，拖动旋转、点击选择三角面"></div><div class="scan-inspector">
      <span class="section-label">网格与标注</span><h3 class="scan-name">折面墙 · 原创几何</h3><p class="scan-stats"></p>
      <p class="scan-guidance">拖动旋转，点击模型检查一个三角面。也可输入三角面编号选择。</p>
      <div class="scan-face-control"><label>三角面编号<input class="scan-face-index" type="number" min="0" step="1" value="0" aria-label="三角面编号" /></label><button class="button outlined" data-scan="select-face">查看面</button></div>
      <div class="scan-patch" aria-live="polite">尚未选择接触面。</div>
      <label class="scan-flip-label"><input type="checkbox" class="scan-flip" disabled /> 反转标注法向（人工确认外侧）</label>
      <div class="scan-exports"><button class="button outlined" data-scan="export" disabled>导出网格与标注</button><button class="button quiet" data-scan="stl">下载当前 STL</button></div>
      <p class="scan-message" role="status"></p>
    </div></div>
    <div class="scan-layers"><p><strong>显示网格</strong>已接入 STL / OBJ，可查看任意凹凸几何；单位换算保留原点。</p><p><strong>接触标注</strong>记录面编号、代表点、法向与网格摘要；摩擦、包裹方式、承载能力仍须独立定义。</p><p><strong>计算与安装</strong>当前线路仍使用墙板与模板。这个入口尚未替换其接触模型、碰撞体或安装面；还需场馆配准与人工复核。</p></div>
    <p class="scan-footnote">仅在本机浏览器解析，单文件 ≤15 MB / 15 万三角形。OBJ 只读取几何。纹理粗糙度不等于摩擦系数；点选单个三角面也不等于可抓握区域。<a href="https://threejs.org/docs/pages/STLLoader.html" target="_blank" rel="noopener noreferrer">格式说明 ↗</a></p>
  </details>`;
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = filename;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function digest(bytes: ArrayBuffer): Promise<string> {
  return 'sha256:' + Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2, '0')).join('');
}
const vectorText = (v: number[]) => v.map(n => n.toFixed(3)).join(', ');

export function mountScanWorkbench(container: HTMLElement): void {
  const find = <T extends HTMLElement>(selector: string) => container.querySelector<T>(selector)!;
  const details = find<HTMLDetailsElement>('details'), viewport = find<HTMLDivElement>('.scan-viewport');
  const unit = find<HTMLSelectElement>('.scan-unit'), up = find<HTMLSelectElement>('.scan-up');
  const roleInput = find<HTMLSelectElement>('.scan-role');
  const faceIndex = find<HTMLInputElement>('.scan-face-index'), flip = find<HTMLInputElement>('.scan-flip');
  const exportButton = find<HTMLButtonElement>('[data-scan=export]'), message = find<HTMLParagraphElement>('.scan-message');
  let renderer: THREE.WebGLRenderer | undefined, controls: OrbitControls | undefined;
  const scene = new THREE.Scene(); scene.background = new THREE.Color('#efede5');
  const camera = new THREE.PerspectiveCamera(38, 1, .001, 200), raycaster = new THREE.Raycaster();
  const marker = new THREE.Group(); scene.add(marker);
  const material = new THREE.MeshStandardMaterial({ color: 0xb6b2a4, roughness: .83, metalness: 0, side: THREE.DoubleSide });
  const mesh = new THREE.Mesh(new THREE.BufferGeometry(), material); scene.add(mesh);
  const wireMaterial = new THREE.LineBasicMaterial({ color: 0x565c58, transparent: true, opacity: .30 });
  let wire: THREE.LineSegments | undefined, raw: THREE.BufferGeometry = demoWall();
  let role = 'wall', source = 'synthetic_reference', sourceName = '折面墙 · 原创几何', sourceHash = '', sourceData: ArrayBuffer | undefined;
  let selected: ScanTriangle | undefined, pointerStart = [0, 0], importVersion = 0;
  let appliedUnit = unit.value, appliedUp = up.value;
  scene.add(new THREE.HemisphereLight(0xfff9e9, 0x747d83, 2.4));
  const light = new THREE.DirectionalLight(0xffffff, 3); light.position.set(-3, 6, 7); scene.add(light);
  const light2 = new THREE.DirectionalLight(0xffffff, 1.2); light2.position.set(4, 1, -2); scene.add(light2);
  const render = () => { if (details.open && renderer) renderer.render(scene, camera); };
  const resize = () => {
    if (!renderer || !details.open) return;
    const width = viewport.clientWidth, height = viewport.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix(); render();
  };
  function clearMarker() {
    for (const child of [...marker.children]) { child.traverse(object => {
      if (object instanceof THREE.Mesh || object instanceof THREE.Line) { object.geometry.dispose(); for (const material of Array.isArray(object.material) ? object.material : [object.material]) material.dispose(); }
    }); marker.remove(child); }
  }
  function clearSelection() {
    selected = undefined; clearMarker(); flip.checked = false; flip.disabled = true; exportButton.disabled = true;
    find('.scan-patch').textContent = '尚未选择接触面。';
  }
  function fit() {
    const bounds = mesh.geometry.boundingBox!;
    const center = bounds.getCenter(new THREE.Vector3()), size = bounds.getSize(new THREE.Vector3());
    const distance = size.length() * 1.5;
    camera.position.copy(center).add((role === 'hold' ? new THREE.Vector3(.9, .95, 1) : new THREE.Vector3(.45, .25, 1)).normalize().multiplyScalar(distance));
    camera.near = Math.max(.0001, distance / 1000); camera.far = Math.max(10, distance * 10); camera.updateProjectionMatrix();
    camera.lookAt(center); controls?.target.copy(center); controls?.update();
  }
  function applyGeometry() {
    const next = normalizeScan(raw, unit.value as ScanUnit, up.value as ScanUp);
    appliedUnit = unit.value; appliedUp = up.value;
    mesh.geometry.dispose(); mesh.geometry = next; clearSelection();
    if (wire) { scene.remove(wire); wire.geometry.dispose(); }
    wire = new THREE.LineSegments(new THREE.WireframeGeometry(next), wireMaterial); wire.visible = find<HTMLInputElement>('.scan-wire').checked; scene.add(wire);
    const size = next.boundingBox!.getSize(new THREE.Vector3());
    find('.scan-name').textContent = sourceName;
    find('.scan-stats').textContent = `${(next.getAttribute('position').count / 3).toLocaleString()} 个三角形 · X ${size.x.toFixed(3)} / Y ${size.y.toFixed(3)} / Z ${size.z.toFixed(3)} m · 原始 ${appliedUnit} / ${appliedUp} 向上`;
    faceIndex.max = String(next.getAttribute('position').count / 3 - 1); faceIndex.value = '0';
    material.color.set(role === 'hold' ? 0xa86e52 : 0xb6b2a4); fit(); render();
  }
  function selectFace(index: number) {
    selected = trianglePatch(mesh.geometry, index, flip.checked); clearMarker();
    const patch = selected, p = new THREE.Vector3(...patch.position_m), n = new THREE.Vector3(...patch.normal);
    const extent = mesh.geometry.boundingBox!.getSize(new THREE.Vector3()).length();
    const highlight = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(patch.vertices_m.flat(), 3));
    highlight.computeVertexNormals();
    marker.add(new THREE.Mesh(highlight, new THREE.MeshBasicMaterial({ color: 0xc17b40, side: THREE.DoubleSide, transparent: true, opacity: .7, depthTest: false })));
    marker.add(new THREE.ArrowHelper(n, p, extent * .13, 0x426d76, extent * .025, extent * .013));
    const dot = new THREE.Mesh(new THREE.SphereGeometry(extent * .006, 12, 8), new THREE.MeshBasicMaterial({ color: 0x294f55, depthTest: false })); dot.position.copy(p); marker.add(dot);
    faceIndex.value = String(index); flip.disabled = false; exportButton.disabled = false;
    find('.scan-patch').innerHTML = `<strong>三角面 ${index}</strong><p>代表点（m）<br>${vectorText(patch.position_m)}</p><p>法向<br>${vectorText(patch.normal)}</p><p>面积 ${(patch.area_m2 * 10_000).toFixed(2)} cm² · 几何标注</p>`;
    message.textContent = ''; render();
  }
  function initialize() {
    if (renderer) { resize(); return; }
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false }); renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); viewport.appendChild(renderer.domElement);
    controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = false; controls.addEventListener('change', render);
    renderer.domElement.addEventListener('pointerdown', e => { pointerStart = [e.clientX, e.clientY]; });
    renderer.domElement.addEventListener('pointerup', e => {
      if (Math.hypot(e.clientX - pointerStart[0], e.clientY - pointerStart[1]) > 4) return;
      const rect = renderer!.domElement.getBoundingClientRect();
      raycaster.setFromCamera(new THREE.Vector2((e.clientX - rect.left) / rect.width * 2 - 1, -(e.clientY - rect.top) / rect.height * 2 + 1), camera);
      const hit = raycaster.intersectObject(mesh)[0]; if (hit?.faceIndex == null) return;
      try { flip.checked = false; selectFace(hit.faceIndex); } catch (error) { message.textContent = String(error); }
    });
    applyGeometry(); resize(); new ResizeObserver(resize).observe(viewport);
  }
  details.addEventListener('toggle', () => { if (details.open) try { initialize(); } catch (error) { message.textContent = `预览无法启动：${String(error)}`; } });
  for (const control of [unit, up]) control.addEventListener('change', () => {
    message.textContent = '已设置下一次导入的坐标。如需变换当前模型，请点击“应用到当前模型”。';
  });
  find<HTMLInputElement>('.scan-wire').addEventListener('change', e => { if (wire) wire.visible = (e.target as HTMLInputElement).checked; render(); });
  roleInput.addEventListener('change', () => { role = roleInput.value; material.color.set(role === 'hold' ? 0xa86e52 : 0xb6b2a4); fit(); render(); });
  flip.addEventListener('change', () => { if (selected) selectFace(selected.triangle_index); });
  container.addEventListener('click', async event => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>('button[data-scan]'); if (!button || button.disabled) return;
    const action = button.dataset.scan;
    try {
      if (action === 'wall' || action === 'jug') {
        importVersion++; raw.dispose(); raw = action === 'wall' ? demoWall() : demoJug(); source = 'synthetic_reference'; role = action === 'wall' ? 'wall' : 'hold';
        roleInput.value = role;
        sourceName = action === 'wall' ? '折面墙 · 原创几何' : '倒扣岩点 · 原创几何'; sourceData = undefined; sourceHash = ''; unit.value = 'm'; up.value = 'Y'; applyGeometry(); message.textContent = '';
      } else if (action === 'import') find<HTMLInputElement>('.scan-file').click();
      else if (action === 'transform') { applyGeometry(); message.textContent = '当前模型坐标已更新，请重新确认接触面。'; }
      else if (action === 'select-face') selectFace(Number(faceIndex.value));
      else if (action === 'stl') {
        const data = new STLExporter().parse(mesh, { binary: true });
        saveBlob(new Blob([data.buffer as ArrayBuffer], { type: 'application/octet-stream' }), 'beta-mesh-metres.stl');
      } else if (action === 'export' && selected) {
        // Snapshot before hashing: changing the view must not mix geometry and annotations.
        const vertices = Array.from(mesh.geometry.getAttribute('position').array);
        const rawVertices = Float32Array.from(raw.getAttribute('position').array);
        const metadata = { schema_version: 'annotated-mesh-1', source, source_name: sourceName, asset_role: role, source_unit: appliedUnit, source_up_axis: appliedUp,
          units: 'm', up_axis: 'Y', origin_policy: 'preserved; no gym registration performed', source_sha256: sourceHash,
          vertices_m: vertices, triangle_indexing: 'non-indexed consecutive triples', contact_annotation: { ...selected, barycentric: [1 / 3, 1 / 3, 1 / 3], normal_flipped: flip.checked, contact_mode: 'unassigned', friction_coefficient: null, force_capacity_n: null },
          computation_status: 'not_connected_to_route_solver', mounting_surface: null, collision_proxy: null };
        metadata.source_sha256 ||= await digest(sourceData || rawVertices.buffer);
        const artifact = { ...metadata, normalized_mesh_sha256: await digest(Float32Array.from(vertices).buffer) };
        saveBlob(new Blob([JSON.stringify(artifact, null, 2)], { type: 'application/json' }), 'beta-annotated-mesh.json'); message.textContent = '已导出米制网格、接触面与摘要；不是线路结果包。';
      }
    } catch (error) { message.textContent = String(error); }
  });
  find<HTMLInputElement>('.scan-file').addEventListener('change', async event => {
    const input = event.target as HTMLInputElement, file = input.files?.[0]; input.value = ''; if (!file) return;
    const version = ++importVersion; message.textContent = '正在读取本地网格…';
    let next: THREE.BufferGeometry | undefined;
    try {
      if (file.size > MAX_SCAN_BYTES) throw new Error('文件超过 15 MB，请先减面。');
      const bytes = await file.arrayBuffer(); if (version !== importVersion) return;
      next = parseScan(bytes, file.name);
      // Check scale before replacing the last usable model.
      normalizeScan(next, unit.value as ScanUnit, up.value as ScanUp).dispose();
      raw.dispose(); raw = next; next = undefined; sourceData = bytes; sourceHash = ''; source = 'local_import'; role = roleInput.value; sourceName = file.name;
      applyGeometry(); message.textContent = '已读取，请核对尺寸与向上轴，再标注接触面。';
    } catch (error) { next?.dispose(); message.textContent = `导入失败，保留原模型：${String(error)}`; }
  });
}
