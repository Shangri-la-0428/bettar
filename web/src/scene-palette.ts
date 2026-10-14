import type { Hold } from './types';

/** Presentation only. Never write these colours into a request or result bundle. */
export interface ScenePalette {
  id: string; label: string; wall: number[]; seam: number; holes: number;
  route: number; volume: number; unused: number; floor: number; mat: number; background: string;
}
export const scenePalettes: ScenePalette[] = [
  { id: 'chalk-yellow', label: '浅灰墙 · 柠黄', wall: [0xdde1dd, 0xcbd3d0, 0xe4e7e3, 0xc1cbc7], seam: 0x7e8986, holes: 0x687571, route: 0xddd942, volume: 0x637a8d, unused: 0x9ca7a1, floor: 0xe0e2dc, mat: 0x46514e, background: '#e8eae4' },
  { id: 'chalk-green', label: '灰白墙 · 青绿', wall: [0xe6e8e4, 0xd1dad3, 0xecede8, 0xc3d0c8], seam: 0x7f9186, holes: 0x5e7569, route: 0x8dcd5b, volume: 0x4d5c60, unused: 0xa6b0a6, floor: 0xe2e6df, mat: 0x4d5e59, background: '#e9ede6' },
  { id: 'slate-graphite', label: '冷灰墙 · 石墨', wall: [0xcad3d8, 0xb7c4cd, 0xd9dfe0, 0xaebfc8], seam: 0x788e9b, holes: 0x5b7584, route: 0x303a43, volume: 0xf3f1e7, unused: 0x9caab2, floor: 0xdbe1e3, mat: 0x46545c, background: '#e4e9ec' },
];
export const defaultPaletteId = 'chalk-yellow';
export function getScenePalette(id: string): ScenePalette { return scenePalettes.find(palette => palette.id === id) || scenePalettes[0]; }
export function presentationHold(hold: Hold, palette: ScenePalette): Hold {
  const color = hold.type === 'volume' ? palette.volume : palette.route;
  return { ...hold, color: `#${color.toString(16).padStart(6, '0')}` };
}
export const wallProfileNames: Record<string, string> = { default: '原场景墙形', overhang: '25° 仰角', roof: '水平屋檐 + 出口', dihedral: '凹角 · 110°', arete: '凸角 · 外棱' };
