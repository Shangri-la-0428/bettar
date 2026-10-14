import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { Hold } from './types';
import { createHoldModel, createGripOverlay, gripSurfaces, disposeObject } from './hold-models';
import type { GripSurfaceSpec } from './hold-models';

function studio(scene: THREE.Scene) {
  scene.add(new THREE.HemisphereLight(0xfffdf7, 0x737775, .85));
  const key = new THREE.DirectionalLight(0xfffdf7, 2.4); key.position.set(-2, 4, 5); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024); key.shadow.camera.near = .1; key.shadow.camera.far = 12;
  key.shadow.bias = -.00003; key.shadow.radius = 2; scene.add(key, key.target);
  const fill = new THREE.DirectionalLight(0xeef3ff, .45); fill.position.set(3, 1, 1); scene.add(fill);
  return key;
}
function fitStudioShadow(key: THREE.DirectionalLight, hold: Hold) {
  const extent = Math.max(hold.width, hold.height, hold.depth) * .85;
  key.target.position.set(0, 0, hold.depth * .4);
  key.shadow.camera.left = -extent; key.shadow.camera.right = extent;
  key.shadow.camera.top = extent; key.shadow.camera.bottom = -extent;
  key.shadow.normalBias = Math.max(.000015, Math.min(hold.width, hold.height, hold.depth) * .0008);
  key.shadow.camera.updateProjectionMatrix();
}
function cameraFor(camera: THREE.PerspectiveCamera, hold: Hold, surface?: GripSurfaceSpec) {
  const radius = Math.max(hold.width, hold.height, hold.depth * 1.5);
  if (surface) {
    // Reveal the chosen local face, including the opposite side of a pinch. This
    // view deliberately receives no wall/mount installation transform.
    camera.position.set(0, 0, hold.depth * .4)
      .addScaledVector(new THREE.Vector3(...surface.normal), radius * 2.65)
      .addScaledVector(new THREE.Vector3(...surface.u_axis), radius * .55)
      .addScaledVector(new THREE.Vector3(...surface.v_axis), radius * .35);
  } else camera.position.set(radius * 1.25, radius * .95, radius * 2.65);
  camera.lookAt(0, 0, hold.depth * .4); camera.near = .001; camera.far = 20; camera.updateProjectionMatrix();
}
/** Local contact/direction annotations describe the input assumptions, never forces. */
function annotateContact(model: THREE.Group, hold: Hold) {
  const point = new THREE.Vector3(...hold.contact.position), size = Math.max(hold.width, hold.height);
  const radius = hold.contact.radius;
  const ring = new THREE.Mesh(new THREE.RingGeometry(radius * .82, radius, 48), new THREE.MeshBasicMaterial({ color: 0xf7f9f3, side: THREE.DoubleSide }));
  ring.position.copy(point); ring.position.z += .001; model.add(ring);
  if (!hold.pull_direction) return;
  const direction = new THREE.Vector3(...hold.pull_direction);
  if (direction.lengthSq() < 1e-10) return;
  direction.normalize();
  const length = Math.max(.025, Math.min(.12, size * .24));
  const origin = point.clone().addScaledVector(direction, radius * 1.25); origin.z += .002;
  const arrow = new THREE.ArrowHelper(direction, origin, length, 0xf7f9f3, length * .24, length * .13);
  model.add(arrow);
}
export class HoldPreview {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(36, 1, .001, 20);
  private controls: OrbitControls;
  private key: THREE.DirectionalLight;
  private model?: THREE.Group;
  private observer: ResizeObserver;
  constructor(private host: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace; this.renderer.toneMapping = THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure = .95;
    this.renderer.shadowMap.enabled = true; this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.domElement.style.cssText = 'display:block;width:100%;height:100%;touch-action:none';
    this.renderer.domElement.setAttribute('aria-label', '岩点三维近看，拖动可旋转'); host.appendChild(this.renderer.domElement);
    this.key = studio(this.scene); this.controls = new OrbitControls(this.camera, this.renderer.domElement); this.controls.enableDamping = true; this.controls.enablePan = false; this.controls.minDistance = .08; this.controls.maxDistance = 1.5;
    this.observer = new ResizeObserver(() => this.resize()); this.observer.observe(host); this.resize();
    this.renderer.setAnimationLoop(() => { this.controls.update(); this.renderer.render(this.scene, this.camera); });
  }
  private resize() { const w = this.host.clientWidth, h = this.host.clientHeight; if (!w || !h) return; this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); }
  setHold(hold?: Hold, surfaceId?: string) {
    if (this.model) { this.scene.remove(this.model); disposeObject(this.model); this.model = undefined; }
    if (!hold) return;
    this.model = createHoldModel(hold);
    const surfaces = gripSurfaces(hold), legacy = !Array.isArray(hold.grip_surfaces);
    if (surfaces.length) this.model.add(createGripOverlay(hold, surfaceId, { all: true }));
    else if (legacy) annotateContact(this.model, hold);
    const selected = surfaceId === undefined ? surfaces[0] : surfaces.find(surface => surface.id === surfaceId);
    this.scene.add(this.model); cameraFor(this.camera, hold, selected); fitStudioShadow(this.key, hold);
    this.renderer.domElement.setAttribute('aria-label', surfaces.length ? '岩点局部三维近看，浅色粗糙区域为声明抓握面，青色箭头为面法线，暖色箭头为拉向；拖动可旋转' : legacy ? '岩点局部三维近看，圆环为假设接触点；拖动可旋转' : '岩点局部三维近看，未声明抓握面；拖动可旋转');
    const size = Math.max(hold.width, hold.height, hold.depth * 1.5);
    this.controls.minDistance = Math.max(.03, size * .6); this.controls.maxDistance = Math.max(1.5, size * 6);
    this.controls.target.set(0, 0, hold.depth * .4); this.controls.update(); this.resize();
  }
  dispose() { this.renderer.setAnimationLoop(null); this.observer.disconnect(); this.controls.dispose(); if (this.model) disposeObject(this.model); this.key.shadow.dispose(); this.renderer.dispose(); this.renderer.domElement.remove(); }
}
const thumbnails = new Map<string, string>();
const thumbnailLimit = 48;
let thumbnailRenderer: THREE.WebGLRenderer | undefined;
/** A shared offscreen renderer and bounded LRU cache, including custom route colors. */
export function holdThumbnail(hold: Hold): string {
  const key = JSON.stringify([hold.asset_id, hold.asset_geometry_sha256, hold.asset_record_sha256, hold.asset_scale, hold.template_id ?? hold.id, hold.type, hold.width, hold.height, hold.depth, hold.color, hold.grip_surfaces]);
  const cached = thumbnails.get(key);
  if (cached) { thumbnails.delete(key); thumbnails.set(key, cached); return cached; }
  thumbnailRenderer ||= new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  thumbnailRenderer.setSize(176, 144); thumbnailRenderer.setPixelRatio(1); thumbnailRenderer.outputColorSpace = THREE.SRGBColorSpace;
  thumbnailRenderer.toneMapping = THREE.ACESFilmicToneMapping; thumbnailRenderer.toneMappingExposure = .95;
  thumbnailRenderer.shadowMap.enabled = true; thumbnailRenderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(36, 176 / 144, .001, 20), keyLight = studio(scene);
  const model = createHoldModel(hold); scene.add(model); cameraFor(camera, hold); fitStudioShadow(keyLight, hold); thumbnailRenderer.render(scene, camera);
  const url = thumbnailRenderer.domElement.toDataURL('image/png'); disposeObject(model); keyLight.shadow.dispose();
  if (thumbnails.size >= thumbnailLimit) thumbnails.delete(thumbnails.keys().next().value!); thumbnails.set(key, url); return url;
}
