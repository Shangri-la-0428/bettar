"""Shared physical holds use declared per-limb surfaces, never family shortcuts."""
from copy import deepcopy
import json

import numpy as np
import pytest

from boulderlab.engine import (default_request, evaluate, fingerprint, make_bundle,
                              validate_bundle, validate_request, _bundle_digest)
from boulderlab.geometry import (contact_world, grip_surfaces, placement_frames,
                                 selected_contact, height_at)
from boulderlab.hold_assets import load_registry, materialize_item, validate_asset
from boulderlab.route_constraints import allowed_contact_ids, allowed_contact_refs, constraint_errors
from boulderlab.statics import DEFAULT_PARAMETERS, _contact_model


def pocket_request():
    request = default_request(profile='route', hold_source='templates')
    item = next(item for item in request['scene']['inventory'] if item['type'] == 'pocket')
    placement = next(p for p in request['reference_layout'] if p['inventory_id'] == item['id'])
    return request, item, placement


def test_main_alias_stays_hand_only_while_pocket_exterior_is_foot_usable():
    request, item, placement = pocket_request()
    assert selected_contact(placement, item) is selected_contact(placement, item, 'working')
    assert selected_contact(placement, item)['limbs'] == ['LH', 'RH']
    assert selected_contact(placement, item, 'alternate')['limbs'] == ['LH', 'RH']
    refs = allowed_contact_refs(request, request['reference_layout'])
    assert {'placement_id': placement['id'], 'contact_id': 'main'} in refs['LH']
    assert {'placement_id': placement['id'], 'contact_id': 'working'} not in refs['LH']
    assert {'placement_id': placement['id'], 'contact_id': 'standing'} in refs['LF']
    assert {'placement_id': placement['id'], 'contact_id': 'main'} not in refs['LF']
    assert placement['id'] in allowed_contact_ids(request, request['reference_layout'])['LF']
    # Explicitly naming the default face is valid on import even though the
    # search enumerator avoids duplicating it beside its legacy main alias.
    from boulderlab.route_design import _context, _contact_key
    context = _context(request, request['reference_layout'], all_surfaces=True)
    explicit = _contact_key({'placement_id': placement['id'], 'contact_id': 'working'})
    np.testing.assert_allclose(context[explicit]['position'], context[placement['id']]['position'])
    with pytest.raises(ValueError, match='unknown contact_surface_id'):
        selected_contact(placement, item, 'invented-foothold')


def test_contact_reference_cannot_use_inside_pocket_as_foot_even_with_mask():
    request, item, placement = pocket_request()
    request['route_constraints'] = {'allowed_contacts': {
        limb: sorted(ids) for limb, ids in allowed_contact_ids(request, request['reference_layout']).items()}}
    state = {'id': 'probe', 'contacts': {'LH': None, 'RH': None,
             'LF': {'placement_id': placement['id'], 'contact_id': 'main'}, 'RF': None}}
    assert any('surface permissions' in error for error in constraint_errors(request, request['reference_layout'], states=[state]))
    state['contacts']['LF']['contact_id'] = 'standing'
    assert constraint_errors(request, request['reference_layout'], states=[state]) == []
    request['route_constraints']['allowed_contacts']['LF'].remove(placement['id'])
    assert any('excluded' in error for error in constraint_errors(request, request['reference_layout'], states=[state]))


def test_explicit_surface_transforms_and_statics_use_its_normal_not_main():
    request, item, placement = pocket_request()
    request['scene']['angle_deg'] = 27
    placement['rotation_deg'] = 63
    inventory = {item['id']: item for item in request['scene']['inventory']}
    frames = placement_frames(request['reference_layout'], inventory, request['scene']['angle_deg'], request['scene'].get('wall_panels'))
    origin, rotation = frames[placement['id']]
    surface = selected_contact(placement, item, 'standing')
    position = contact_world(request, placement, item, frames=frames, contact_id='standing')
    np.testing.assert_allclose(position, origin + rotation @ surface['position'])
    assert not np.allclose(position, contact_world(request, placement, item, frames=frames))
    model = _contact_model(request, placement, item, 'LF', frames, DEFAULT_PARAMETERS, request['reference_layout'], 'standing')
    assert model['mode'] == 'unilateral_friction'
    np.testing.assert_allclose(model['normal'], rotation @ surface['normal'])
    np.testing.assert_allclose(model['position'], position)
    assert model['capacity_n'] == DEFAULT_PARAMETERS['foot_normal_capacity_n']
    with pytest.raises(ValueError, match='disallowed'):
        _contact_model(request, placement, item, 'LF', frames, DEFAULT_PARAMETERS, request['reference_layout'])


@pytest.mark.parametrize('kind', ['jug', 'rail', 'directional_edge', 'sloper', 'pinch', 'pocket'])
def test_template_standing_is_external_heightfield_surface(kind):
    item = {'type': kind, 'width': .24, 'height': .18, 'depth': .08}
    surfaces = {surface['id']: surface for surface in grip_surfaces(item)}
    standing = surfaces['standing']
    assert standing['limbs'] == ['LF', 'RF']
    assert surfaces['working']['limbs'] == ['LH', 'RH']
    x, y, z = standing['position']
    assert z == height_at(item, x, y)
    assert y > 0 and standing['normal'][1] > 0


def test_shipped_foot_surfaces_are_bound_to_exterior_mesh_triangles():
    assets = load_registry()
    for asset_id, triangle in [('setrsoft-12-jug', 1490), ('setrsoft-25-crimp', 2560), ('setrsoft-11-sloper', 1993)]:
        asset = assets[asset_id]
        validate_asset(asset)
        surface = next(s for s in asset['grip_surfaces'] if s['id'] == 'standing')
        assert surface['limbs'] == ['LF', 'RF']
        assert surface['mesh_anchor']['triangle_index'] == triangle
        assert surface['normal'][1] > .75 and surface['position'][1] > 0
        vertices = np.asarray(asset['geometry']['positions'])[asset['geometry']['triangles'][triangle]]
        np.testing.assert_allclose(surface['position'], np.asarray(surface['mesh_anchor']['barycentric']) @ vertices)
    pinch = assets['setrsoft-17-pinch']
    assert all(set(s['limbs']) == {'LH', 'RH'} for s in pinch['grip_surfaces'])


def test_explicit_surface_roundtrip_and_fingerprint_including_unevaluated_import(example):
    request, candidate = example
    placement = next(p for p in candidate['placements'] if p['id'] == 'f1')
    item = next(item for item in request['scene']['inventory'] if item['id'] == placement['inventory_id'])
    item['grip_surfaces'] = [{'id': 'standing', 'label': 'Explicit fixture surface',
        'position': item['contact']['position'], 'normal': [0, 0, 1], 'u_axis': [1, 0, 0],
        'v_axis': [0, 1, 0], 'radii': [.02, .02], 'limbs': ['LF', 'RF'], 'pull_direction': [0, -1, 0]}]
    old_fingerprint = fingerprint(request, candidate)
    for refs in [request['start_contacts'], request['end_contacts']] + [state['contacts'] for state in candidate['states']]:
        for ref in refs.values():
            if ref and ref['placement_id'] == 'f1':
                ref['contact_id'] = 'standing'
    validate_request(request)
    assert fingerprint(request, candidate) != old_fingerprint
    evaluation = evaluate(request, candidate)
    bundle = make_bundle(request, [candidate], evaluations=[evaluation])
    assert validate_bundle(json.loads(json.dumps(bundle))) == bundle
    altered = deepcopy(bundle)
    altered['evaluations'] = []
    altered['candidates'][0]['states'][1]['contacts']['RH']['contact_id'] = 'missing-surface'
    altered['manifest']['bundle_digest'] = _bundle_digest(altered)
    with pytest.raises(ValueError, match='unknown contact_surface_id'):
        validate_bundle(altered)


def test_live_mesh_foot_annotation_tamper_rejected():
    request = default_request(profile='setting', hold_source='assets')
    item = next(item for item in request['scene']['inventory'] if item.get('asset_id') == 'setrsoft-12-jug')
    next(s for s in item['grip_surfaces'] if s['id'] == 'standing')['limbs'].append('LH')
    with pytest.raises(ValueError, match='differs from registry'):
        validate_request(request)
