import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import type { Candidate, Evaluation, Hold, Placement, Request, State, Vec3 } from './types';
import { limbs, shortHoldName } from './types';
import { createGripOverlay, createHoldModel, grainTexture } from './hold-models';
import { inversePoint, transformPoint, tryContactFrame, tryInstallationFrame, tryPlacementFrame, wallFrame, panelFrame, wallHeightMeasures } from './placement-geometry';
import type { Frame, PlacementContext } from './placement-geometry';
import { getScenePalette, defaultPaletteId, presentationHold } from './scene-palette';
import type { ScenePalette } from './scene-palette';

const limbColors = { LH: 0xad654d, RH: 0x597c88, LF: 0x6e8052, RF: 0xaf8a42 };
type Drag = { id: string; pointer: number; u: number; v: number; frame: Frame; offsetU: number; offsetV: number; x: number; y: number; moved: boolean };

export class WallView {
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(34, 1, .01, 100);
  private renderer: THREE.WebGLRenderer;
  private labelRenderer = new CSS2DRenderer();
  private controls: OrbitControls;
  private wallGroup = new THREE.Group();
  private poseGroup = new THREE.Group();
  private forceGroup = new THREE.Group();
  private comparisonGroup = new THREE.Group();
  private pathGroup = new THREE.Group();
  private markerGroup = new THREE.Group();
  private raycaster = new THREE.Raycaster();
  private pickables: THREE.Object3D[] = [];
  private labels: CSS2DObject[] = [];
  private holdGroups = new Map<string, THREE.Group>();
  private gripOverlays = new Map<string, THREE.Group>();
  private request?: Request;
  private candidate?: Candidate;
  private evaluation?: Evaluation;
  private step = 0;
  private selected?: string;
  private showLabels = true;
  private showBody = false;
  private showForces = false;
  private editMode = false;
  private routeOnly = false;
  private routePath = false;
  private showSurfaces = false;
  private drag?: Drag;
  private baseMaterials = new Map<string, THREE.MeshStandardMaterial[]>();
  private clickStart = { x: 0, y: 0 };
  private palette: ScenePalette = getScenePalette(defaultPaletteId);
  private floorMaterial = new THREE.MeshStandardMaterial({ roughness: .98 });

  constructor(private host: HTMLElement, private onSelect: (id: string) => void, private onMove?: (id: string, u: number, v: number) => void) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); this.renderer.setClearColor(0xeeeae1, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace; this.renderer.toneMapping = THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure = .98;
    this.renderer.shadowMap.enabled = true; this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.domElement.setAttribute('aria-label', '三维岩壁；浏览模式拖动旋转，移动模式拖动岩点，Esc 取消。');
    this.renderer.domElement.setAttribute('role', 'img'); this.host.appendChild(this.renderer.domElement);
    this.labelRenderer.domElement.className = 'scene-labels'; this.host.appendChild(this.labelRenderer.domElement);
    this.camera.position.set(2.9, 2.25, 5.25);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, 1.47, .08); this.controls.minDistance = .35; this.controls.maxDistance = 18;
    this.controls.maxPolarAngle = Math.PI * .73; this.controls.enableDamping = true; this.controls.dampingFactor = .12; this.controls.update();
    this.scene.add(new THREE.HemisphereLight(0xfffdf8, 0x8d9698, 1.05));
    const key = new THREE.DirectionalLight(0xfffdf7, 2.4); key.position.set(-3.5, 7, 6); key.target.position.set(0, 2, .4); key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048); key.shadow.camera.left = -5; key.shadow.camera.right = 5; key.shadow.camera.top = 5; key.shadow.camera.bottom = -5;
    key.shadow.camera.near = .1; key.shadow.camera.far = 20; key.shadow.normalBias = .0015; key.shadow.bias = -.00005; key.shadow.radius = 3; this.scene.add(key, key.target);
    const fill = new THREE.DirectionalLight(0xeaf2ff, .65); fill.position.set(4, 2.8, 5); this.scene.add(fill);
    const lowerFill = new THREE.DirectionalLight(0xf3f0e7, .35); lowerFill.position.set(0, .6, 5); this.scene.add(lowerFill);
    this.floorMaterial.color.setHex(this.palette.floor);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(30, 30), this.floorMaterial);
    floor.rotation.x = -Math.PI / 2; floor.position.y = -.16; floor.receiveShadow = true;
    this.scene.add(floor, this.wallGroup, this.poseGroup, this.forceGroup, this.comparisonGroup, this.pathGroup, this.markerGroup);
    const canvas = this.renderer.domElement;
    canvas.addEventListener('pointerdown', (event) => this.pointerDown(event), true);
    canvas.addEventListener('pointermove', (event) => this.pointerMove(event), true);
    canvas.addEventListener('pointerup', (event) => this.pointerUp(event), true);
    canvas.addEventListener('pointercancel', () => this.cancelDrag(), true);
    canvas.addEventListener('lostpointercapture', () => this.cancelDrag());
    window.addEventListener('keydown', (event) => { if (event.key === 'Escape') this.cancelDrag(); });
    new ResizeObserver(() => this.resize()).observe(host); this.resize();
    this.renderer.setAnimationLoop(() => { if (!this.drag) this.controls.update(); this.renderer.render(this.scene, this.camera); this.labelRenderer.render(this.scene, this.camera); });
  }
  private resize() {
    const { width, height } = this.host.getBoundingClientRect(); if (!width || !height) return;
    const previousFit = this.request ? this.fitDistance() : 0;
    this.camera.aspect = width / height; this.camera.updateProjectionMatrix(); this.renderer.setSize(width, height); this.labelRenderer.setSize(width, height);
    if (previousFit) {
      const offset = this.camera.position.clone().sub(this.controls.target).multiplyScalar(this.fitDistance() / previousFit);
      this.camera.position.copy(this.controls.target).add(offset); this.controls.update();
    }
  }
  private clear(group: THREE.Group) {
    group.traverse((obj) => {
      if (obj instanceof CSS2DObject) obj.element.remove();
      if (obj instanceof THREE.Mesh || obj instanceof THREE.Line) {
        obj.geometry.dispose(); (Array.isArray(obj.material) ? obj.material : [obj.material]).forEach((material) => material.dispose());
      }
    }); group.clear();
  }
  private label(text: string, position: THREE.Vector3, className = 'hold-label') {
    const el = document.createElement('span'); el.className = className; el.textContent = text;
    const label = new CSS2DObject(el); label.position.copy(position); return label;
  }
  private wallPosition(u: number, v: number, n = 0): THREE.Vector3 {
    return new THREE.Vector3(...transformPoint(wallFrame(this.request?.scene.angle_deg || 0), [u, v, n]));
  }
  private context(placements = this.candidate?.placements || [], live = false): PlacementContext {
    return { angleDeg: this.request?.scene.angle_deg || 0, inventory: this.request?.scene.inventory || [], wallPanels: this.request?.scene.wall_panels, placements: live && this.drag ? placements.map(p => p.id === this.drag!.id ? { ...p, u: this.drag!.u, v: this.drag!.v } : p) : placements };
  }
  private applyFrame(object: THREE.Object3D, frame: Frame) {
    object.position.set(...frame.origin);
    object.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(new THREE.Vector3(...frame.u), new THREE.Vector3(...frame.v), new THREE.Vector3(...frame.normal)));
  }
  private syncPlacementFrames(live = false) {
    const context = this.context(undefined, live);
    for (const placement of context.placements) {
      const group = this.holdGroups.get(placement.id);
      const frame = tryPlacementFrame(placement, context);
      if (group) { group.visible = !!frame; if (frame) this.applyFrame(group, frame); }
    }
  }
  private setRay(event: PointerEvent) {
    const bounds = this.renderer.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2((event.clientX - bounds.left) / bounds.width * 2 - 1, -(event.clientY - bounds.top) / bounds.height * 2 + 1), this.camera);
  }
  private planePoint(event: PointerEvent, frame: Frame): { u: number; v: number } | undefined {
    this.setRay(event);
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(new THREE.Vector3(...frame.normal), new THREE.Vector3(...frame.origin));
    const point = this.raycaster.ray.intersectPlane(plane, new THREE.Vector3());
    if (!point) return;
    const [u, v] = inversePoint(frame, point.toArray() as Vec3); return { u, v };
  }
  private pointerDown(event: PointerEvent) {
    this.clickStart = { x: event.clientX, y: event.clientY };
    if (!this.editMode || this.request?.mode === 'fixed' || !this.onMove || event.button !== 0 || this.drag) return;
    this.setRay(event); const hit = this.raycaster.intersectObjects(this.pickables.filter(object => this.holdGroups.get(String(object.userData.id))?.visible), false)[0];
    const id = hit?.object.userData.id as string | undefined;
    const placement = this.candidate?.placements.find((p) => p.id === id);
    if (!id || !placement) return;
    const frame = tryInstallationFrame(placement, this.context()); if (!frame) return;
    const point = this.planePoint(event, frame); if (!point) return;
    event.preventDefault(); event.stopImmediatePropagation(); this.controls.enabled = false;
    this.renderer.domElement.setPointerCapture(event.pointerId); this.renderer.domElement.style.cursor = 'grabbing';
    this.drag = { id, pointer: event.pointerId, u: placement.u, v: placement.v, frame, offsetU: placement.u - point.u, offsetV: placement.v - point.v, x: event.clientX, y: event.clientY, moved: false };
    this.select(id); this.onSelect(id);
  }
  private pointerMove(event: PointerEvent) {
    const drag = this.drag; if (!drag || drag.pointer !== event.pointerId) return;
    event.preventDefault(); event.stopImmediatePropagation(); const point = this.planePoint(event, drag.frame); if (!point) return;
    drag.moved ||= Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > 3;
    if (!drag.moved) return;
    drag.u = point.u + drag.offsetU; drag.v = point.v + drag.offsetV;
    this.syncPlacementFrames(true);
    // Old solved poses and route cues must not follow an uncommitted edit as if re-solved.
    this.poseGroup.visible = false; this.forceGroup.visible = false; this.pathGroup.visible = false; this.markerGroup.visible = false;
  }
  private pointerUp(event: PointerEvent) {
    const drag = this.drag;
    if (drag && drag.pointer === event.pointerId) {
      event.preventDefault(); event.stopImmediatePropagation(); const moved = drag.moved;
      this.cancelDrag(); if (moved && this.editMode && this.request?.mode !== 'fixed') this.onMove?.(drag.id, drag.u, drag.v); return;
    }
    if (Math.hypot(event.clientX - this.clickStart.x, event.clientY - this.clickStart.y) > 5) return;
    this.setRay(event); const hit = this.raycaster.intersectObjects(this.pickables.filter(object => this.holdGroups.get(String(object.userData.id))?.visible), false)[0];
    const id = hit?.object.userData.id || this.nearestVisibleHold(event); if (id) this.onSelect(String(id));
  }
  private nearestVisibleHold(event: PointerEvent): string | undefined {
    // A small click allowance helps tiny footholds without changing drag geometry.
    const bounds = this.renderer.domElement.getBoundingClientRect();
    const nearby: { id: string; point: THREE.Vector3; distance: number; depth: number }[] = [];
    this.scene.updateMatrixWorld(true); this.camera.updateMatrixWorld(true);
    for (const object of this.pickables) {
      const id = String(object.userData.id);
      if (!(object instanceof THREE.Mesh) || !object.userData.resin || !object.visible || !this.holdGroups.get(id)?.visible) continue;
      const point = new THREE.Box3().setFromObject(object).getCenter(new THREE.Vector3()), projected = point.clone().project(this.camera);
      if (Math.abs(projected.x) > 1 || Math.abs(projected.y) > 1 || Math.abs(projected.z) > 1) continue;
      const x = bounds.left + (projected.x + 1) * bounds.width / 2, y = bounds.top + (1 - projected.y) * bounds.height / 2;
      const distance = Math.hypot(event.clientX - x, event.clientY - y);
      if (distance <= 12) nearby.push({ id, point: projected, distance, depth: this.camera.position.distanceTo(point) });
    }
    if (!nearby.length) return;
    const occluders: THREE.Object3D[] = [];
    this.wallGroup.traverseVisible(object => {
      if (object instanceof THREE.Mesh && !object.userData.surfaceOverlay) occluders.push(object);
    });
    for (const candidate of nearby.sort((a, b) => a.distance - b.distance || a.depth - b.depth)) {
      // Never promote a nearby hold whose centre is hidden behind the wall or another hold.
      this.raycaster.setFromCamera(new THREE.Vector2(candidate.point.x, candidate.point.y), this.camera);
      const hit = this.raycaster.intersectObjects(occluders, false)[0];
      if (hit?.object.userData.id === candidate.id) return candidate.id;
    }
  }
  private cancelDrag() {
    const drag = this.drag; if (!drag) return; this.drag = undefined;
    if (this.renderer.domElement.hasPointerCapture(drag.pointer)) this.renderer.domElement.releasePointerCapture(drag.pointer);
    this.syncPlacementFrames(); this.setRouteOnly(this.routeOnly);
    this.controls.enabled = true; this.renderer.domElement.style.cursor = this.editMode ? 'grab' : '';
    this.poseGroup.visible = true; this.forceGroup.visible = this.showForces; this.pathGroup.visible = this.routePath; this.markerGroup.visible = true;
  }
  private holdMesh(hold: Hold, placement: Placement, context: PlacementContext, ghost = false) {
    const frame = tryPlacementFrame(placement, context); if (!frame) return;
    const displayHold = presentationHold(hold, this.palette);
    const group = createHoldModel(displayHold, { id: placement.id, ghost }); this.applyFrame(group, frame);
    if (!ghost) {
      const materials: THREE.MeshStandardMaterial[] = [];
      group.traverse((obj) => { if (obj instanceof THREE.Mesh) { this.pickables.push(obj); if (obj.userData.resin && obj.material instanceof THREE.MeshStandardMaterial) materials.push(obj.material); } });
      this.baseMaterials.set(placement.id, materials); this.holdGroups.set(placement.id, group);
      const offsetU = hold.width / 2 + .025, offsetV = hold.height / 2 + .018;
      const label = this.label(this.routeLabel(hold, placement), new THREE.Vector3(offsetU, offsetV, hold.depth + .02));
      label.element.dataset.compact = this.routeLabel(hold, placement, true);
      label.visible = this.showLabels; label.element.dataset.placement = placement.id; label.element.dataset.smallFoot = String(hold.type === 'foothold'); label.element.title = `${placement.id} · ${hold.id}`;
      this.labels.push(label); group.add(label);
      // An unknown selected ID highlights no surface; it must not become a fabricated contact.
      const overlay = createGripOverlay(displayHold, placement.contact_surface_id, { id: placement.id, arrows: true, all: true });
      overlay.traverse(object => { object.userData.surfaceOverlay = true; }); overlay.visible = this.showSurfaces;
      this.gripOverlays.set(placement.id, overlay); group.add(overlay);
    }
    return group;
  }
  private panelBounds(): THREE.Box3 | undefined {
    if (!this.request?.scene.wall_panels?.length) return;
    const bounds = new THREE.Box3();
    for (const panel of this.request.scene.wall_panels) {
      const frame = panelFrame(this.request.scene.angle_deg, panel);
      for (const u of [-panel.width / 2, panel.width / 2]) for (const v of [0, panel.height]) for (const n of [-.12, 0]) bounds.expandByPoint(new THREE.Vector3(...transformPoint(frame, [u, v, n])));
    }
    return bounds;
  }
  private makePanelWall() {
    const { wall_panels = [], angle_deg } = this.request!.scene;
    wall_panels.forEach((panel, index) => {
      const frame = panelFrame(angle_deg, panel);
      const wall = new THREE.Mesh(new THREE.BoxGeometry(panel.width, panel.height, .12), new THREE.MeshStandardMaterial({ color: this.palette.wall[index % this.palette.wall.length], roughness: .93, bumpMap: grainTexture(), bumpScale: .00035 }));
      this.applyFrame(wall, { ...frame, origin: transformPoint(frame, [0, panel.height / 2, -.06]) });
      wall.receiveShadow = true; wall.castShadow = true; this.wallGroup.add(wall);
      const edge = new THREE.LineSegments(new THREE.EdgesGeometry(wall.geometry), new THREE.LineBasicMaterial({ color: this.palette.seam, transparent: true, opacity: .38 }));
      edge.position.copy(wall.position); edge.quaternion.copy(wall.quaternion); this.wallGroup.add(edge);
      // Panel seams sit on the actual face. They are finish marks, never geometry
      // folds or extra contact targets.
      const seam = (a: Vec3, b: Vec3) => this.wallGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b].map(point => new THREE.Vector3(...transformPoint(frame, point)))), new THREE.LineBasicMaterial({ color: this.palette.seam, transparent: true, opacity: .22 })));
      for (let u = -panel.width / 2 + 1.2; u < panel.width / 2 - .1; u += 1.2) seam([u, 0, .0006], [u, panel.height, .0006]);
      for (let v = 1.2; v < panel.height - .1; v += 1.2) seam([-panel.width / 2, v, .0006], [panel.width / 2, v, .0006]);
      const positions: THREE.Vector3[] = [];
      for (let u = -panel.width / 2 + .15; u < panel.width / 2 - .08; u += .2) for (let v = .15; v < panel.height - .08; v += .2) positions.push(new THREE.Vector3(...transformPoint(frame, [u, v, .0008])));
      const holes = new THREE.InstancedMesh(new THREE.CircleGeometry(.0055, 12), new THREE.MeshBasicMaterial({ color: this.palette.holes, transparent: true, opacity: .42 }), positions.length);
      const matrix = new THREE.Matrix4();
      positions.forEach((position, i) => { matrix.compose(position, wall.quaternion, new THREE.Vector3(1, 1, 1)); holes.setMatrixAt(i, matrix); });
      this.wallGroup.add(holes);
      this.wallGroup.add(this.label(panel.label, new THREE.Vector3(...transformPoint(frame, [0, panel.height - .1, .02])), 'panel-label'));
    });
    const bounds = this.panelBounds()!, size = bounds.getSize(new THREE.Vector3()), centre = bounds.getCenter(new THREE.Vector3());
    const pad = new THREE.Mesh(new RoundedBoxGeometry(size.x + .6, .14, Math.max(2.6, size.z + 2), 3, .04), new THREE.MeshStandardMaterial({ color: this.palette.mat, roughness: .97, bumpMap: grainTexture(), bumpScale: .00045 }));
    pad.position.set(centre.x, -.08, centre.z + .9); pad.receiveShadow = true; this.wallGroup.add(pad);
    this.wallGroup.add(this.label(`${size.x.toFixed(1)} m`, new THREE.Vector3(centre.x, -.18, bounds.max.z + .03), 'dimension-label'));
    const verticalHeight = wallHeightMeasures(this.request!.scene).vertical;
    this.wallGroup.add(this.label(`几何高 ${verticalHeight.toFixed(2)} m`, new THREE.Vector3(bounds.min.x - .18, verticalHeight / 2, bounds.min.z), 'dimension-label vertical'));
  }
  private makeWall() {
    if (this.request?.scene.wall_panels?.length) { this.makePanelWall(); return; }
    const { width, height, margin, angle_deg } = this.request!.scene;
    const wall = new THREE.Mesh(new THREE.BoxGeometry(width, height, .12), new THREE.MeshStandardMaterial({ color: this.palette.wall[0], roughness: .93, bumpMap: grainTexture(), bumpScale: .00035 }));
    wall.position.copy(this.wallPosition(0, height / 2, -.062)); wall.rotation.x = THREE.MathUtils.degToRad(angle_deg); wall.receiveShadow = true; wall.castShadow = true; this.wallGroup.add(wall);
    const line = (points: THREE.Vector3[], color: number) => new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({ color, transparent: true, opacity: .7 }));
    for (let v = 1.2; v < height; v += 1.2) this.wallGroup.add(line([this.wallPosition(-width / 2, v, .0005), this.wallPosition(width / 2, v, .0005)], this.palette.seam));
    for (let u = -width / 2 + 1.2; u < width / 2; u += 1.2) this.wallGroup.add(line([this.wallPosition(u, 0, .0005), this.wallPosition(u, height, .0005)], this.palette.seam));
    // Flush installation holes are visual marks, never extra contact targets or protrusions.
    const holeGeometry = new THREE.CircleGeometry(.0055, 12), holeMaterial = new THREE.MeshBasicMaterial({ color: this.palette.holes, transparent: true, opacity: .42 });
    const positions: THREE.Vector3[] = [];
    for (let u = -width / 2 + .15; u < width / 2 - .08; u += .2) for (let v = .15; v < height - .08; v += .2) positions.push(this.wallPosition(u, v, .0008));
    const holes = new THREE.InstancedMesh(holeGeometry, holeMaterial, positions.length), matrix = new THREE.Matrix4(), quaternion = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), THREE.MathUtils.degToRad(angle_deg));
    positions.forEach((position, i) => { matrix.compose(position, quaternion, new THREE.Vector3(1, 1, 1)); holes.setMatrixAt(i, matrix); }); this.wallGroup.add(holes);
    const bounds = [[-width / 2 + margin, margin], [width / 2 - margin, margin], [width / 2 - margin, height - margin], [-width / 2 + margin, height - margin], [-width / 2 + margin, margin]];
    const edge = new THREE.Line(new THREE.BufferGeometry().setFromPoints(bounds.map(([u, v]) => this.wallPosition(u, v, .001))), new THREE.LineDashedMaterial({ color: 0xb0a996, dashSize: .018, gapSize: .027, transparent: true, opacity: .75 })); edge.computeLineDistances(); this.wallGroup.add(edge);
    const pad = new THREE.Mesh(new RoundedBoxGeometry(width + .6, .14, 2.6, 3, .04), new THREE.MeshStandardMaterial({ color: this.palette.mat, roughness: .97, bumpMap: grainTexture(), bumpScale: .00045 }));
    pad.position.set(0, -.08, 1.13); pad.receiveShadow = true; this.wallGroup.add(pad);
    for (let u = -width / 2; u <= width / 2; u += 1.5) this.wallGroup.add(line([new THREE.Vector3(u, -.007, -.13), new THREE.Vector3(u, -.007, 2.39)], 0x555d58));
    this.wallGroup.add(this.label(`${width.toFixed(1)} m`, this.wallPosition(0, -.18), 'dimension-label'));
    this.wallGroup.add(this.label(`几何高 ${wallHeightMeasures(this.request!.scene).vertical.toFixed(2)} m`, this.wallPosition(-width / 2 - .15, height / 2), 'dimension-label vertical'));
  }
  update(request: Request, candidate: Candidate, evaluation: Evaluation | undefined, step: number, comparison?: Candidate) {
    this.cancelDrag(); this.request = request; this.candidate = candidate; this.evaluation = evaluation; this.step = step;
    this.clear(this.wallGroup); this.clear(this.comparisonGroup); this.pickables = []; this.labels = []; this.baseMaterials.clear(); this.holdGroups.clear(); this.gripOverlays.clear(); this.makeWall();
    const holdMap = new Map(request.scene.inventory.map((hold) => [hold.id, hold]));
    candidate.placements.forEach((placement) => { const hold = holdMap.get(placement.inventory_id); if (hold) { const mesh = this.holdMesh(hold, placement, this.context()); if (mesh) this.wallGroup.add(mesh); } });
    comparison?.placements.filter(placement => this.usedPlacements(comparison).visible.has(placement.id)).forEach((placement) => { const hold = holdMap.get(placement.inventory_id); if (hold) { const mesh = this.holdMesh(hold, placement, this.context(comparison.placements), true); if (mesh) this.comparisonGroup.add(mesh); } });
    this.updatePose(); this.updateMechanics(); this.drawRoute(); this.drawMarkers(); this.select(this.selected); this.setRouteOnly(this.routeOnly);
  }
  setPalette(id: string) { this.palette = getScenePalette(id); this.floorMaterial.color.setHex(this.palette.floor); this.host.style.backgroundColor = this.palette.background; }
  setStep(step: number) { this.step = step; this.updatePose(); this.updateMechanics(); this.setRouteOnly(this.routeOnly); }
  setLabels(value: boolean) { this.showLabels = value; this.refreshLabelVisibility(); }
  setSurfaces(value: boolean) { this.showSurfaces = value; this.gripOverlays.forEach(overlay => { overlay.visible = value; }); }
  setBody(value: boolean) { this.showBody = value; this.updatePose(); }
  setForces(value: boolean) { this.showForces = value; this.updateMechanics(); }
  setEditMode(value: boolean) { this.cancelDrag(); this.editMode = value; this.renderer.domElement.style.cursor = value && this.request?.mode !== 'fixed' ? 'grab' : ''; }
  private usedPlacements(candidate = this.candidate) {
    const used = new Set(candidate?.states.flatMap(state => Object.values(state.contacts).flatMap(contact => contact ? [contact.placement_id] : [])) || []);
    const visible = new Set(used);
    candidate?.placements.forEach(placement => { if (used.has(placement.id) && placement.mount) visible.add(placement.mount.parent_id); });
    return { used, visible };
  }
  private routeLabel(hold: Hold, placement: Placement, compact = false) {
    if (!this.candidate) return shortHoldName(hold, this.request!.scene.inventory);
    const hand = this.candidate.states.some(state => ['LH', 'RH'].some(limb => state.contacts[limb as 'LH' | 'RH']?.placement_id === placement.id));
    const foot = this.candidate.states.some(state => ['LF', 'RF'].some(limb => state.contacts[limb as 'LF' | 'RF']?.placement_id === placement.id));
    let handIndex = 0;
    const steps = this.candidate.events.flatMap(event => {
      if (!event.limb.endsWith('H')) return [];
      handIndex++;
      const state = this.candidate!.states.find(item => item.id === event.to_state);
      return state?.contacts[event.limb]?.placement_id === placement.id ? [handIndex] : [];
    });
    if (compact) return steps.length ? steps.join('/') : shortHoldName(hold, this.request!.scene.inventory);
    if (foot && !hand) return shortHoldName(hold, this.request!.scene.inventory) + (hold.type === 'foothold' ? '' : ' · 脚');
    return `${shortHoldName(hold, this.request!.scene.inventory)}${hand || foot ? ` · ${hand && foot ? '手脚' : hand ? '手' : '脚'}${steps.length ? ` ${steps.join('/')}` : ''}` : ''}`;
  }
  setRouteOnly(value: boolean) {
    this.routeOnly = value;
    const { used, visible } = this.usedPlacements();
    const allowed = this.request?.route_constraints ? new Set(Object.values(this.request.route_constraints.allowed_contacts).flat()) : undefined;
    const layoutOnly = this.candidate?.layout_report?.status === 'no_sequence';
    const inventory = new Map(this.request?.scene.inventory.map(hold => [hold.id, hold]));
    const contacts = new Set(Object.values(this.candidate?.states[this.step]?.contacts || {}).flatMap(contact => contact ? [contact.placement_id] : []));
    this.holdGroups.forEach((group, id) => {
      // A selected route is a permission mask, never a change to the physical wall.
      group.visible = !!allowed || layoutOnly || !value || visible.has(id);
      const placement = this.candidate?.placements.find(p => p.id === id);
      const structural = placement && inventory.get(placement.inventory_id)?.type === 'volume';
      const inRoute = allowed ? allowed.has(id) : layoutOnly || used.has(id);
      const tint = new THREE.Color(structural ? this.palette.volume : inRoute ? this.palette.route : this.palette.unused);
      group.traverse(object => {
        if (!(object instanceof THREE.Mesh) || !(object.material instanceof THREE.MeshStandardMaterial) || (!object.userData.resin && !object.userData.gripSurface)) return;
        // Route colour is a display preference shared by hands and feet. Grip
        // overlays retain a lighter finish without reverting to family colours.
        object.material.color.copy(tint);
        if (object.userData.gripSurface) object.material.color.lerp(new THREE.Color(0xf7f5e9), object.userData.gripBase ? .13 : object.userData.selected ? .42 : .18);
        object.material.emissive.setHex(id === this.selected ? 0xe4e4da : contacts.has(id) ? 0xcbd8d8 : 0);
        object.material.emissiveIntensity = id === this.selected ? .13 : .05;
      });
    });
    this.labels.forEach(label => { const id = label.element.dataset.placement || ''; label.element.classList.toggle('background-hold', allowed ? !allowed.has(id) : !layoutOnly && !used.has(id)); label.element.classList.toggle('current-contact', contacts.has(id)); });
    this.refreshLabelVisibility();
  }
  private refreshLabelVisibility() {
    const hand = new Set<string>(), foot = new Set<string>();
    this.candidate?.states.forEach(state => Object.entries(state.contacts).forEach(([limb, contact]) => {
      if (contact) (limb.endsWith('H') ? hand : foot).add(contact.placement_id);
    }));
    const currentContacts = new Set(Object.values(this.candidate?.states[this.step]?.contacts || {}).flatMap(contact => contact ? [contact.placement_id] : []));
    this.labels.forEach(label => {
      const id = label.element.dataset.placement || '';
      const footOnly = !hand.has(id) && (foot.has(id) || label.element.dataset.smallFoot === 'true');
      label.visible = this.showLabels && (!footOnly || id === this.selected || currentContacts.has(id));
    });
  }
  setRoutePath(value: boolean) { this.routePath = value; this.pathGroup.visible = value && !this.drag?.moved; }
  private drawMarkers() {
    this.clear(this.markerGroup);
    if (!this.request || !this.candidate) return;
    const brief = this.request.design_brief;
    const holds = new Map(this.request.scene.inventory.map(hold => [hold.id, hold]));
    const starts = new Map<string, string[]>(), ends = new Set<string>();
    const first = this.candidate.states[0], last = this.candidate.states.at(-1);
    if (first) for (const [limb, contact] of Object.entries(first.contacts)) {
      if (contact) starts.set(contact.placement_id, [...(starts.get(contact.placement_id) || []), limb]);
    }
    if (last && !this.candidate.layout_report) for (const limb of ['LH', 'RH'] as const) {
      const contact = last.contacts[limb]; if (contact) ends.add(contact.placement_id);
    }
    const used = this.usedPlacements().used;
    const startGroups: { hand: THREE.Vector3[]; foot: THREE.Vector3[] } = { hand: [], foot: [] };
    for (const placement of this.candidate.placements) {
      const hold = holds.get(placement.inventory_id); if (!hold || !used.has(placement.id)) continue;
      const top = ['route', 'setting'].includes(this.request.profile || '') ? ends.has(placement.id) : brief?.top_placement_ids.includes(placement.id);
      const zone = brief?.zone_placement_ids.includes(placement.id), start = starts.get(placement.id);
      if (!top && !zone && !start) continue;
      const frame = tryPlacementFrame(placement, this.context()); if (!frame) continue;
      if (['route', 'setting'].includes(this.request.profile || '') && start && !top && !zone) {
        const kind = start.some(limb => limb.endsWith('H')) ? 'hand' : 'foot';
        startGroups[kind].push(new THREE.Vector3(...transformPoint(frame, [0, -hold.height / 2 - .1, .015])));
        continue;
      }
      const text = top ? '终点 TOP' : zone ? 'ZONE' : start!.some(limb => limb.endsWith('H')) ? '起手 START' : '起脚';
      const markerOffset: Vec3 = top && ['route', 'setting'].includes(this.request.profile || '') ? [0, hold.height / 2 + .33, .015] : [0, -hold.height / 2 - .07, .015];
      const marker = this.label(text, new THREE.Vector3(...transformPoint(frame, markerOffset)), `route-marker ${top ? 'top' : zone ? 'zone' : 'start'}`);
      if (!top && !zone) { marker.center.set(1, .5); marker.element.style.marginLeft = '-16px'; }
      this.markerGroup.add(marker);
    }
    for (const kind of ['hand', 'foot'] as const) {
      const points = startGroups[kind];
      if (points.length) {
        const marker = this.label(kind === 'hand' ? '起手 START' : '起脚', points.reduce((sum, p) => sum.add(p), new THREE.Vector3()).divideScalar(points.length), 'route-marker start');
        marker.center.set(1, .5); marker.element.style.marginLeft = '-16px'; this.markerGroup.add(marker);
      }
    }
  }
  private drawRoute() {
    this.clear(this.pathGroup); this.pathGroup.visible = this.routePath; if (!this.candidate || !this.request) return;
    const stateMap = new Map(this.candidate.states.map((s) => [s.id, s])), placementMap = new Map(this.candidate.placements.map((p) => [p.id, p])), holdMap = new Map(this.request.scene.inventory.map((h) => [h.id, h]));
    this.candidate.events.filter((event) => event.limb.endsWith('H')).forEach((event) => {
      const from = stateMap.get(event.from_state)?.contacts[event.limb], to = stateMap.get(event.to_state)?.contacts[event.limb]; if (!from || !to) return;
      const p0 = placementMap.get(from.placement_id), p1 = placementMap.get(to.placement_id); if (!p0 || !p1) return;
      const h0 = holdMap.get(p0.inventory_id), h1 = holdMap.get(p1.inventory_id); if (!h0 || !h1) return;
      const fromFrame = tryContactFrame(p0, h0, this.context(), from.contact_id), toFrame = tryContactFrame(p1, h1, this.context(), to.contact_id);
      if (!fromFrame || !toFrame) return;
      const a = new THREE.Vector3(...transformPoint(fromFrame, [0, 0, .025])), b = new THREE.Vector3(...transformPoint(toFrame, [0, 0, .025]));
      const path = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), new THREE.LineDashedMaterial({ color: limbColors[event.limb as 'LH' | 'RH'], dashSize: .035, gapSize: .025, transparent: true, opacity: .8, depthTest: false })); path.computeLineDistances(); path.renderOrder = 8; this.pathGroup.add(path);
      const direction = b.clone().sub(a), length = direction.length(); if (length > .03) this.pathGroup.add(new THREE.ArrowHelper(direction.normalize(), b.clone().addScaledVector(direction, -.07), .06, limbColors[event.limb as 'LH' | 'RH'], .03, .02));
    });
  }
  select(id?: string) {
    this.selected = id; this.baseMaterials.forEach((materials, key) => materials.forEach((material) => { material.emissive.setHex(key === id ? 0x603120 : 0); material.emissiveIntensity = .24; }));
    this.labels.forEach((label) => label.element.classList.toggle('selected', label.element.dataset.placement === id));
    this.setRouteOnly(this.routeOnly);
  }
  focusHold(id: string) {
    const placement = this.candidate?.placements.find((item) => item.id === id); if (!placement) return;
    this.cancelDrag(); const group = this.holdGroups.get(id); if (!group?.visible) return;
    // Use the installed model envelope, including its mounted children, rather than one off-centre grip.
    const bounds = new THREE.Box3().setFromObject(group);
    for (const child of this.candidate!.placements) {
      const childGroup = child.mount?.parent_id === id ? this.holdGroups.get(child.id) : undefined;
      if (childGroup?.visible) bounds.expandByObject(childGroup);
    }
    if (bounds.isEmpty()) return;
    const target = bounds.getCenter(new THREE.Vector3()), direction = this.camera.position.clone().sub(this.controls.target).normalize();
    const right = new THREE.Vector3().crossVectors(this.camera.up, direction);
    if (right.lengthSq() < 1e-8) right.setFromMatrixColumn(this.camera.matrixWorld, 0);
    right.normalize(); const up = new THREE.Vector3().crossVectors(direction, right).normalize();
    const halfVertical = Math.tan(THREE.MathUtils.degToRad(this.camera.getEffectiveFOV() / 2)), halfHorizontal = halfVertical * this.camera.aspect;
    let distance = Math.max(.65, this.controls.minDistance);
    for (const x of [bounds.min.x, bounds.max.x]) for (const y of [bounds.min.y, bounds.max.y]) for (const z of [bounds.min.z, bounds.max.z]) {
      const offset = new THREE.Vector3(x, y, z).sub(target), depth = offset.dot(direction);
      distance = Math.max(distance, depth + Math.abs(offset.dot(right)) * 1.2 / halfHorizontal, depth + Math.abs(offset.dot(up)) * 1.2 / halfVertical);
    }
    this.controls.target.copy(target); this.camera.position.copy(target).addScaledVector(direction, distance + .06); this.controls.update(); this.select(id);
  }
  private updatePose() {
    this.clear(this.poseGroup);
    const state = this.candidate?.states[this.step]; if (!state || !this.request || !this.candidate) return;
    if (this.showBody) this.drawContacts(state);
    const pose = this.evaluation?.poses.find((p) => p.state_id === state.id);
    if (!this.showBody || pose?.status !== 'pass' || !pose.joints) return;
    const joints = pose.joints;
    const segments = [
      ['pelvis', 'neck'], ['left_shoulder', 'right_shoulder'], ['left_hip', 'right_hip'],
      ['neck', 'left_shoulder'], ['neck', 'right_shoulder'], ['pelvis', 'left_hip'], ['pelvis', 'right_hip'],
      ['left_shoulder', 'left_elbow'], ['left_elbow', 'left_wrist'], ['right_shoulder', 'right_elbow'], ['right_elbow', 'right_wrist'],
      ['left_hip', 'left_knee'], ['left_knee', 'left_ankle'], ['right_hip', 'right_knee'], ['right_knee', 'right_ankle'],
    ];
    const boneMaterial = new THREE.MeshStandardMaterial({ color: 0x343b3b, roughness: 0.68 });
    for (const [from, to] of segments) {
      const a = joints[from], b = joints[to];
      if (!this.validJoint(a) || !this.validJoint(b)) continue;
      const start = new THREE.Vector3(...a), end = new THREE.Vector3(...b);
      const distance = start.distanceTo(end); if (distance < 1e-6) continue;
      const bone = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.023, distance, 10), boneMaterial.clone());
      bone.position.copy(start).add(end).multiplyScalar(0.5);
      bone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), end.sub(start).normalize());
      bone.castShadow = true; this.poseGroup.add(bone);
    }
    for (const [name, position] of Object.entries(joints)) {
      if (!this.validJoint(position)) continue;
      const color = name.includes('wrist') ? (name.startsWith('left') ? limbColors.LH : limbColors.RH) : name.includes('ankle') ? (name.startsWith('left') ? limbColors.LF : limbColors.RF) : 0x505957;
      const joint = new THREE.Mesh(new THREE.SphereGeometry(0.034, 14, 10), new THREE.MeshStandardMaterial({ color, roughness: 0.65 }));
      joint.position.set(...position); joint.castShadow = true; this.poseGroup.add(joint);
    }
    boneMaterial.dispose();
  }

  private updateMechanics() {
    this.clear(this.forceGroup); this.forceGroup.visible = this.showForces && !this.drag?.moved;
    if (!this.showForces || !this.candidate || !this.evaluation) return;
    const current = this.evaluation.mechanics_report?.states.find(item => item.state_id === this.candidate!.states[this.step]?.id);
    // Required forces for an infeasible capacity solve are diagnostics, never drawn as a valid equilibrium.
    if (!current || current.status !== 'feasible') return;
    const arrow = (point: Vec3, force: Vec3, color: number, label: string) => {
      if (!this.validJoint(point) || !this.validJoint(force)) return;
      const vector = new THREE.Vector3(...force), magnitude = vector.length();
      if (magnitude < 1e-8) return;
      const direction = vector.normalize(), origin = new THREE.Vector3(...point), length = magnitude * .001;
      const object = new THREE.ArrowHelper(direction, origin, length, color, Math.min(.075, length * .28), Math.min(.03, length * .12));
      object.userData.solvedForce = true; object.userData.forceNewton = magnitude;
      object.traverse(child => { child.renderOrder = 12; if (child instanceof THREE.Line || child instanceof THREE.Mesh) { const materials = Array.isArray(child.material) ? child.material : [child.material]; materials.forEach(material => { material.depthTest = false; material.transparent = true; material.opacity = .9; }); } });
      this.forceGroup.add(object);
      this.forceGroup.add(this.label(`${label} ${magnitude.toFixed(0)} N`, origin.clone().addScaledVector(direction, length + .055), 'force-label'));
    };
    current.contacts.forEach(contact => {
      if (contact.force_world_n) arrow(contact.point_world_m, contact.force_world_n, limbColors[contact.limb], contact.limb);
    });
    if (current.com_world_m && this.validJoint(current.com_world_m)) {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(.045, 16, 12), new THREE.MeshBasicMaterial({ color: 0x273c3c, depthTest: false }));
      marker.position.set(...current.com_world_m); marker.renderOrder = 13; this.forceGroup.add(marker);
      this.forceGroup.add(this.label('COM（假设）', new THREE.Vector3(...current.com_world_m).add(new THREE.Vector3(.1, .03, .035)), 'force-label centre-of-mass'));
      if (current.gravity_force_n) arrow(current.com_world_m, current.gravity_force_n, 0x52615b, '重力');
    }
  }

  private validJoint(p: Vec3 | undefined): p is Vec3 { return Array.isArray(p) && p.length === 3 && p.every(Number.isFinite); }

  private drawContacts(state: State) {
    const placementMap = new Map(this.candidate!.placements.map((p) => [p.id, p]));
    const holdMap = new Map(this.request!.scene.inventory.map((h) => [h.id, h]));
    const offsets = { LH: [-0.035, 0.065], RH: [0.035, 0.065], LF: [-0.035, -0.075], RF: [0.035, -0.075] };
    limbs.forEach((limb) => {
      const contact = state.contacts[limb]; if (!contact) return;
      const placement = placementMap.get(contact.placement_id); if (!placement) return;
      const hold = holdMap.get(placement.inventory_id); if (!hold) return;
      const frame = tryContactFrame(placement, hold, this.context(), contact.contact_id); if (!frame) return;
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.046, 0.007, 8, 30), new THREE.MeshBasicMaterial({ color: limbColors[limb], depthTest: false }));
      this.applyFrame(ring, frame); if (limb.endsWith('F')) ring.scale.set(.72, 1.2, 1); ring.renderOrder = 10;
      this.poseGroup.add(ring);
      const labelPosition = new THREE.Vector3(...transformPoint(frame, [offsets[limb][0], offsets[limb][1], .06]));
      const label = this.label(`${limb}${limb.endsWith('F') && contact.contact_id !== 'main' ? ' · 踩面' : ''}`, labelPosition, `contact-label ${limb.toLowerCase()}`);
      label.element.dataset.contactId = contact.contact_id; label.element.dataset.placement = contact.placement_id; this.poseGroup.add(label);
    });
  }

  private portraitRouteBounds(): THREE.Box3 | undefined {
    if (this.camera.aspect >= .85 || !this.candidate) return;
    const route = this.usedPlacements().visible;
    Object.values(this.request?.route_constraints?.allowed_contacts || {}).flat().forEach(id => route.add(id));
    // Include structural parents so fitted children remain visually attached to their volumes.
    for (const placement of this.candidate.placements) if (route.has(placement.id) && placement.mount) route.add(placement.mount.parent_id);
    const bounds = new THREE.Box3();
    for (const [id, group] of this.holdGroups) {
      if (!route.size || this.candidate.layout_report || route.has(id)) bounds.expandByObject(group);
    }
    if (bounds.isEmpty()) return;
    // Keep surrounding wall and room for start/top labels, even on a very short route.
    const centre = bounds.getCenter(new THREE.Vector3()), size = bounds.getSize(new THREE.Vector3());
    size.set(Math.max(size.x + .7, 1.35), Math.max(size.y + .9, 1.8), size.z + .3);
    return bounds.setFromCenterAndSize(centre, size);
  }
  private wallTarget() { return this.portraitRouteBounds()?.getCenter(new THREE.Vector3()) || this.panelBounds()?.getCenter(new THREE.Vector3()) || this.wallPosition(0, (this.request?.scene.height || 3) / 2, .08); }
  front() {
    this.cancelDrag(); const target = this.wallTarget(), direction = this.wallPosition(0, 0, 1).normalize();
    const distance = this.fitDistance(direction);
    this.controls.target.copy(target); this.camera.position.copy(target).addScaledVector(direction, distance); this.controls.update();
  }
  private fitDistance(direction = this.camera.position.clone().sub(this.controls.target).normalize()) {
    const routeBounds = this.portraitRouteBounds();
    if (routeBounds) {
      const target = routeBounds.getCenter(new THREE.Vector3()), right = new THREE.Vector3().crossVectors(this.camera.up, direction).normalize();
      const up = new THREE.Vector3().crossVectors(direction, right).normalize();
      const vertical = Math.tan(THREE.MathUtils.degToRad(this.camera.getEffectiveFOV() / 2)), horizontal = vertical * this.camera.aspect;
      let distance = this.controls.minDistance;
      for (const x of [routeBounds.min.x, routeBounds.max.x]) for (const y of [routeBounds.min.y, routeBounds.max.y]) for (const z of [routeBounds.min.z, routeBounds.max.z]) {
        const point = new THREE.Vector3(x, y, z).sub(target), depth = point.dot(direction);
        distance = Math.max(distance, depth + Math.abs(point.dot(right)) * 1.08 / horizontal, depth + Math.abs(point.dot(up)) * 1.08 / vertical);
      }
      return distance;
    }
    const dimensions = this.panelBounds()?.getSize(new THREE.Vector3());
    const width = dimensions?.x || this.request?.scene.width || 3, height = dimensions?.y || this.request?.scene.height || 3;
    return (dimensions?.z || 0) * .6 + Math.max(height + .75, (width + .6) / Math.max(this.camera.aspect, .4)) / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2))) * 1.08;
  }
  perspective() {
    this.cancelDrag();
    const target = this.wallTarget();
    const profile = this.request?.setting_design?.wall_profile;
    const direction = profile === 'roof' ? new THREE.Vector3(.5, -.1, .86)
      : profile === 'dihedral' || profile === 'arete' ? new THREE.Vector3(.42, .1, .9)
      : new THREE.Vector3(.28, .1, .955);
    direction.normalize(); const distance = this.fitDistance(direction);
    this.camera.position.copy(target).addScaledVector(direction, distance);
    this.controls.target.copy(target); this.controls.update();
  }
}
