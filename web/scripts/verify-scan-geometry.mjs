import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import * as THREE from 'three';
import { STLExporter } from 'three/addons/exporters/STLExporter.js';
import { parseScan, normalizeScan, trianglePatch, demoJug, demoWall, validateScan } from '../src/scan-geometry.ts';

let checks = 0;
function test(name, fn) { fn(); checks++; console.log(`PASS ${name}`); }
const bytes = text => new TextEncoder().encode(text).buffer;
const near = (a,b,epsilon=1e-6) => assert.ok(Math.abs(a-b)<epsilon, `${a} != ${b}`);
const wall = demoWall(), jug = demoJug();
test('wall keeps real facet depth and physical dimensions', () => {
  wall.computeBoundingBox(); const s = wall.boundingBox.getSize(new THREE.Vector3()); near(s.x,4.8); near(s.y,4.2); assert.ok(s.z>1);
});
test('jug has an actual inward-facing lip beyond its backplane', () => {
  const inner = Array.from({length:jug.getAttribute('position').count/3},(_,i)=>trianglePatch(jug,i)).filter(p=>p.position_m[2]>.05 && p.normal[2]<-.3);
  assert.ok(inner.length>10, 'A front-only heightfield cannot satisfy this undercut test');
});
test('normalization preserves origin and converts millimetres', () => {
  const source = wall.clone().translate(10,20,30).scale(1000,1000,1000), normalized = normalizeScan(source,'mm','Y');
  const a = normalized.getAttribute('position'), b = wall.getAttribute('position');
  near(a.getX(0), b.getX(0)+10); near(a.getY(0), b.getY(0)+20); near(a.getZ(0),b.getZ(0)+30);
});
test('Z-up conversion is right-handed and points upward', () => {
  const source = wall.clone().rotateX(Math.PI/2), normalized = normalizeScan(source,'m','Z');
  const a=normalized.getAttribute('position'), b=wall.getAttribute('position'); for(let i=0;i<a.count;i++){near(a.getX(i),b.getX(i));near(a.getY(i),b.getY(i));near(a.getZ(i),b.getZ(i));}
});
test('patch centroid lies on triangle and frame is right handed', () => {
  const p=trianglePatch(wall,5), n=new THREE.Vector3(...p.normal),u=new THREE.Vector3(...p.u_axis),v=new THREE.Vector3(...p.v_axis);
  near(n.length(),1);near(u.dot(v),0);near(new THREE.Vector3().crossVectors(u,v).dot(n),1);
  const mean=p.vertices_m.reduce((a,b)=>a.map((x,i)=>x+b[i]/3),[0,0,0]);mean.forEach((x,i)=>near(x,p.position_m[i]));
});
test('manual normal flip preserves patch and handedness', () => {
  const a=trianglePatch(wall,5),b=trianglePatch(wall,5,true);assert.deepEqual(a.position_m,b.position_m);a.normal.forEach((n,i)=>near(n,-b.normal[i]));
  near(new THREE.Vector3(...b.u_axis).cross(new THREE.Vector3(...b.v_axis)).dot(new THREE.Vector3(...b.normal)),1);
});
test('OBJ geometry loads without fetching referenced materials', () => {
  const g=parseScan(bytes('mtllib https://invalid.test/material.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'),'local.obj');assert.equal(g.getAttribute('position').count,3);
});
test('STL binary round-trip preserves concave geometry', () => {
  const binary=new STLExporter().parse(new THREE.Mesh(jug),{binary:true});const g=parseScan(binary.buffer,'jug.stl');assert.equal(g.getAttribute('position').count,jug.getAttribute('position').count);
});
test('ASCII STL round-trip preserves wall geometry', () => {
  const g=parseScan(bytes(new STLExporter().parse(new THREE.Mesh(wall))),'wall.stl');assert.equal(g.getAttribute('position').count,wall.getAttribute('position').count);
});
test('malformed empty mesh rejected', () => assert.throws(()=>parseScan(bytes('no mesh'),'bad.stl')));
test('non-finite coordinates rejected', () => { const g=new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute([NaN,0,0,1,0,0,0,1,0],3));assert.throws(()=>validateScan(g)); });
test('wrong metre conversion is rejected instead of silently shrinking', () => assert.throws(()=>normalizeScan(wall.clone().scale(1000,1000,1000),'m','Y')));
test('degenerate triangle cannot become a contact normal', () => {const g=new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute([0,0,0,1,0,0,2,0,0],3));assert.throws(()=>trianglePatch(g,0));});
test('out of bounds patch and unknown formats rejected', () => { assert.throws(()=>trianglePatch(wall,999));assert.throws(()=>parseScan(bytes('v 0 0 0'),'mesh.glb')); });
const out = new URL('../../outputs/mechanics-study/',import.meta.url); mkdirSync(out,{recursive:true});
writeFileSync(new URL('synthetic-undercut-jug.stl',out),new Uint8Array(new STLExporter().parse(new THREE.Mesh(jug),{binary:true}).buffer));
writeFileSync(new URL('synthetic-faceted-wall.obj',out),'# Original synthetic wall, metres, Y-up\n'+Array.from({length:wall.getAttribute('position').count},(_,i)=>{const a=wall.getAttribute('position');return `v ${a.getX(i)} ${a.getY(i)} ${a.getZ(i)}`;}).join('\n')+'\n'+Array.from({length:18},(_,i)=>`f ${i*3+1} ${i*3+2} ${i*3+3}`).join('\n')+'\n');
writeFileSync(new URL('scan-verification.json',out),JSON.stringify({status:'pass',checks,source:'synthetic_reference',triangle_counts:{wall:18,jug:jug.getAttribute('position').count/3}},null,2));
console.log(`${checks} scan geometry checks passed.`);
