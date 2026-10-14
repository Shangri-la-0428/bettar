// Cross-check the actual renderer's pure transforms against the Python evaluator.
// Run from the repository: node web/scripts/verify-placement-geometry.mjs
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { contactFrame, installationFrame, inversePoint, panelFrame, placementFrame, transformDirection, transformPoint, wallFrame, tryPlacementFrame, wallHeightMeasures } from '../src/placement-geometry.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));
const localPython = fileURLToPath(new URL('../../.venv/bin/python', import.meta.url));
const python = process.env.BETAR_PYTHON || (existsSync(localPython) ? localPython : 'python3');
const fixture = JSON.parse(execFileSync(python, ['-c', String.raw`
import copy, gzip, json
from pathlib import Path
import numpy as np
from boulderlab.geometry import mounting_faces, grip_surfaces, placement_frames, contact_world, selected_contact, panel_frame, wall_basis

def hold(id, kind, w, h, d):
    item = dict(id=id, type=kind, width=w, height=h, depth=d,
                contact=dict(id='main', position=[0,0,d], radius=.02, limbs=['LH','RH']))
    item['grip_surfaces'] = grip_surfaces(item)
    if kind == 'volume': item['mounting_faces'] = mounting_faces(item)
    return item
inventory = [hold('volume','volume',.88,.72,.31), hold('edge','directional_edge',.12,.07,.035)]
placements = [
    dict(id='parent',inventory_id='volume',u=-.42,v=1.37,rotation_deg=37,contact_surface_id='face_1_grip'),
    dict(id='child',inventory_id='edge',u=.028,v=-.013,rotation_deg=-23,contact_surface_id='alternate',mount=dict(parent_id='parent',face_id='face_2')),
    dict(id='wall-hold',inventory_id='edge',u=.69,v=1.84,rotation_deg=19,contact_surface_id='working'),
    dict(id='legacy',inventory_id='edge',u=.33,v=.46,rotation_deg=-44),
]
cases = []
panels = [dict(id='lower', label='Lower folded panel', origin=[-.44,.05,.19], rotation_deg=[21,-19,7], width=2.7,height=2.3), dict(id='upper',label='Upper return',origin=[.8,1.9,.65],rotation_deg=[-13,23,-9],width=2.1,height=2.1)]
for name, shift, rotation, use_panels in [('initial',0,0,False),('parent-translate',.21,0,False),('parent-rotate',0,-58,False),('panel-initial',0,0,True),('panel-parent-translate',.21,0,True),('panel-parent-rotate',0,-58,True)]:
    layout = copy.deepcopy(placements)
    layout[0]['u'] += shift
    layout[0]['v'] -= shift*.4
    layout[0]['rotation_deg'] += rotation
    if use_panels:
        for p in layout:
            if 'mount' not in p: p['wall_panel_id'] = 'lower' if p['id'] in ('parent','legacy') else 'upper'
    request = dict(scene=dict(angle_deg=10,inventory=inventory,wall_panels=panels if use_panels else []),reference_layout=layout)
    items = {h['id']:h for h in inventory}
    frames = placement_frames(layout,items,10,panels if use_panels else [])
    expected = {}
    for p in layout:
        origin,axes = frames[p['id']]
        contact = selected_contact(p,items[p['inventory_id']])
        expected[p['id']] = dict(origin=origin.tolist(),u=axes[:,0].tolist(),v=axes[:,1].tolist(),normal=axes[:,2].tolist(),
            contact=contact_world(request,p,items[p['inventory_id']],layout,frames).tolist(),
            contact_normal=(axes @ np.asarray(contact.get('normal',[0,0,1]))).tolist())
    top_y = max([0]+[(panel_frame(panel,10)[0]+panel_frame(panel,10)[1] @ [u,v,0])[1] for panel in panels for u in [-panel['width']/2,panel['width']/2] for v in [0,panel['height']]]) if use_panels else (wall_basis(10) @ [0,4.2,0])[1]
    cases.append(dict(name=name,vertical_height=float(top_y),context=dict(angleDeg=10,inventory=inventory,placements=layout,wallPanels=panels if use_panels else []),expected=expected))

# Read saved wall experiments, including honest layout-only results. This does
# not invoke generation or change any fixture. Full meshes live in the registry;
# these transforms only need the inventory's declared local contact frames.
for profile in ('overhang','roof','dihedral','arete'):
    path = Path('fixtures') / f'wall-{profile}-bundle.json'
    if not path.exists(): continue
    bundle = json.loads(path.read_text())
    request = bundle['request']; scene = request['scene']
    assert request['setting_design']['wall_profile'] == profile, path
    items = {h['id']:h for h in scene['inventory']}
    panels = scene['wall_panels']; angle = scene['angle_deg']
    panel_expected = {}
    for panel in panels:
        origin, axes = panel_frame(panel,angle)
        panel_expected[panel['id']] = dict(origin=origin.tolist(),u=axes[:,0].tolist(),v=axes[:,1].tolist(),normal=axes[:,2].tolist(),
            corners=[(origin+axes @ [u,v,0]).tolist() for u in [-panel['width']/2,panel['width']/2] for v in [0,panel['height']]])
    top_y = max([0]+[point[1] for frame in panel_expected.values() for point in frame['corners']])
    for candidate in bundle['candidates']:
        layout = candidate['placements']
        frames = placement_frames(layout,items,angle,panels)
        expected = {}
        for placement in layout:
            origin,axes = frames[placement['id']]
            contact = selected_contact(placement,items[placement['inventory_id']])
            expected[placement['id']] = dict(origin=origin.tolist(),u=axes[:,0].tolist(),v=axes[:,1].tolist(),normal=axes[:,2].tolist(),
                contact=contact_world(request,placement,items[placement['inventory_id']],layout,frames).tolist(),
                contact_normal=(axes @ np.asarray(contact.get('normal',[0,0,1]))).tolist())
        cases.append(dict(name=f'wall-fixture/{profile}/{candidate["id"]}',wall_profile=profile,
            layout_only=candidate.get('layout_report',{}).get('status')=='no_sequence',
            scene_height=scene['height'],vertical_height=float(top_y),panel_expected=panel_expected,
            context=dict(angleDeg=angle,inventory=scene['inventory'],placements=layout,wallPanels=panels),expected=expected))
# A route's concrete contact_id selects the actual hand or standing surface.
# Verify every limb at every state; selected placement defaults are insufficient.
study_path = Path('outputs/own-routes-study/study.json')
if study_path.exists():
    study = json.loads(study_path.read_text())
    for route in study['routes']:
        data = (study_path.parent / route['bundle_file']).read_bytes()
        bundle = json.loads(gzip.decompress(data) if route['bundle_file'].endswith('.gz') else data)
        request = bundle['request']; scene = request['scene']
        items = {h['id']: h for h in scene['inventory']}
        for candidate in bundle['candidates']:
            layout = candidate['placements']; placements = {p['id']: p for p in layout}
            frames = placement_frames(layout, items, scene['angle_deg'], scene.get('wall_panels'))
            contacts = []
            for state in candidate['states']:
                for limb, ref in state['contacts'].items():
                    if ref is None: continue
                    placement = placements[ref['placement_id']]; hold = items[placement['inventory_id']]
                    selected = selected_contact(placement, hold, ref['contact_id'])
                    origin, axes = frames[placement['id']]
                    contacts.append(dict(state_id=state['id'],limb=limb,placement_id=placement['id'],contact_id=ref['contact_id'],
                        point=contact_world(request,placement,hold,layout,frames,ref['contact_id']).tolist(),
                        normal=(axes @ np.asarray(selected.get('normal',[0,0,1]))).tolist()))
            cases.append(dict(name=f'own-route/{route["id"]}/{candidate["id"]}',own_route=True,state_contacts=contacts,
                context=dict(angleDeg=scene['angle_deg'],inventory=scene['inventory'],placements=layout,wallPanels=scene.get('wall_panels'))))
print(json.dumps(cases))
`], { cwd: root, encoding: 'utf8' }));

let comparisons = 0;
const near = (actual, expected, label) => {
  assert.equal(actual.length, expected.length, label);
  assert.ok(actual.every((value, i) => Math.abs(value - expected[i]) < 1e-10), `${label}: ${JSON.stringify(actual)} vs ${JSON.stringify(expected)}`);
  comparisons++;
};
let ownRouteContacts = 0, explicitFootContacts = 0;
for (const { name, context, expected, vertical_height, scene_height = 4.2, panel_expected, state_contacts } of fixture) {
  if (state_contacts) {
    for (const ref of state_contacts) {
      const placement = context.placements.find(item => item.id === ref.placement_id);
      const hold = context.inventory.find(item => item.id === placement.inventory_id);
      const frame = contactFrame(placement, hold, context, ref.contact_id);
      near(frame.origin, ref.point, `${name}/${ref.state_id}/${ref.limb}/${ref.contact_id}/point`);
      near(frame.normal, ref.normal, `${name}/${ref.state_id}/${ref.limb}/${ref.contact_id}/normal`);
      ownRouteContacts++;
      if (ref.limb.endsWith('F') && ref.contact_id !== 'main') explicitFootContacts++;
    }
    continue;
  }
  const heights = wallHeightMeasures({ height: scene_height, angle_deg: context.angleDeg, wall_panels: context.wallPanels });
  near([heights.unfolded, heights.vertical], [scene_height, vertical_height], `${name}/unfolded vs vertical height`);
  if (panel_expected) for (const panel of context.wallPanels) {
    const actual = panelFrame(context.angleDeg, panel), target = panel_expected[panel.id];
    for (const component of ['origin', 'u', 'v', 'normal']) near(actual[component], target[component], `${name}/${panel.id}/${component}`);
    const corners = [-panel.width / 2, panel.width / 2].flatMap(u => [0, panel.height].map(v => transformPoint(actual, [u, v, 0])));
    corners.forEach((corner, index) => near(corner, target.corners[index], `${name}/${panel.id}/corner-${index}`));
  }
  for (const placement of context.placements) {
    const hold = context.inventory.find(item => item.id === placement.inventory_id);
    const actual = placementFrame(placement, context), target = expected[placement.id];
    for (const component of ['origin', 'u', 'v', 'normal']) near(actual[component], target[component], `${name}/${placement.id}/${component}`);
    const contact = contactFrame(placement, hold, context, 'main');
    near(contact.origin, target.contact, `${name}/${placement.id}/contact`);
    near(contact.normal, target.contact_normal, `${name}/${placement.id}/contact normal`);
    // Drag coordinates belong to the unrotated installation plane, never the child's rotated axes.
    const plane = installationFrame(placement, context);
    for (const uv of [[placement.u, placement.v, 0], [.137, -.049, 0], [-.071, .082, .031]]) {
      near(inversePoint(plane, transformPoint(plane, uv)), uv, `${name}/${placement.id}/drag inverse`);
    }
    if (placement.contact_surface_id) {
      near(contactFrame(placement, hold, context, placement.contact_surface_id).origin, contact.origin, `${name}/${placement.id}/legacy main alias`);
    }
  }
}
const initial = fixture[0].context, child = initial.placements.find(item => item.id === 'child');
const original = placementFrame(child, initial);
for (const changed of fixture.slice(1, 3)) {
  assert.notDeepEqual(placementFrame(child, changed.context).origin, original.origin, `${changed.name}: child follows parent`);
  assert.deepEqual(placementFrame(child, initial), original, `${changed.name}: cancelled preview restores original`);
}
const panelContext = fixture.find(item => item.name === 'panel-initial').context;
const panelParent = panelContext.placements.find(item => item.id === 'parent');
assert.equal(tryPlacementFrame({ ...panelParent, wall_panel_id: 'missing' }, panelContext), undefined, 'unknown panel must not fall back to legacy wall');
const missingPanel = { ...panelParent }; delete missingPanel.wall_panel_id;
assert.equal(tryPlacementFrame(missingPanel, panelContext), undefined, 'panel-backed root requires a panel');
const panelChild = panelContext.placements.find(item => item.id === 'child');
assert.equal(tryPlacementFrame({ ...panelChild, wall_panel_id: 'lower' }, panelContext), undefined, 'mounted child inherits its parent panel');
near(transformDirection(wallFrame(10), [0, 0, 1]), [0, -Math.sin(Math.PI / 18), Math.cos(Math.PI / 18)], 'wall normal angle sign');
const wallFixtures = fixture.filter(item => item.wall_profile).map(item => ({ profile: item.wall_profile, placements: item.context.placements.length, panels: item.context.wallPanels.length, layout_only: item.layout_only }));
if (process.argv.includes('--require-wall-fixtures')) assert.deepEqual([...new Set(wallFixtures.map(item => item.profile))].sort(), ['arete', 'dihedral', 'overhang', 'roof'], 'all four saved wall profiles required');
if (process.argv.includes('--require-own-routes')) { assert.ok(fixture.filter(item => item.own_route).length >= 3, 'three own rule routes required'); assert.ok(explicitFootContacts > 0, 'own routes include explicit standing surfaces'); }
console.log(JSON.stringify({ status: 'pass', comparisons, own_route_contacts: ownRouteContacts, explicit_foot_contacts: explicitFootContacts, cases: fixture.map(item => item.name), wall_fixtures: wallFixtures, checks: ['Python frame/contact/normal parity', 'wall and face inverse drag', 'selected-surface main alias', 'legacy contact preserved', 'parent translation and rotation inheritance', 'cancelled preview restoration', 'multi-axis panel rotation and translated origin', 'panel-mounted volume child inherits transform', 'invalid panel mount omitted', 'front corner elevation measured above y=0 separately from layout height', 'saved wall profile panel corners, placement axes and selected mesh contact frames'] }, null, 2));
