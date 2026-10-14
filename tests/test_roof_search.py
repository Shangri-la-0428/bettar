"""Roof search regressions: 3-D progress, truthful poses and retained effort."""
import copy
import numpy as np

from boulderlab.beta_audit import _setting_contact_corridor, _audit_context, _search, _make_candidate
from boulderlab.engine import default_request, evaluate
from boulderlab.full_route import _contact_valid, _history
from boulderlab.route_design import _metrics
from boulderlab.setting import _shell, _mechanical_proposal
from boulderlab.wall_clearance import wall_clearance_report


def test_ceiling_corridor_uses_depth_instead_of_assuming_hands_above_feet():
    request = default_request(profile='setting', wall_profile='roof', hold_source='templates')
    body = request['body']; contacts = request['start_contacts']
    positions = [(-.2, 2., .8), (.2, 2., .8), (-.2, 2., 0.), (.2, 2., 0.)]
    context = {ref['placement_id']: {'position': np.array(p), 'uv': np.array(p[:2]), 'inclination': 1.}
               for ref, p in zip(contacts.values(), positions)}
    assert not _contact_valid(context, contacts, body, request['solver'])
    assert _setting_contact_corridor(context, contacts, body, request['solver'])
    context[contacts['RH']['placement_id']]['position'][0] = 1.2
    assert not _setting_contact_corridor(context, contacts, body, request['solver'])


def test_vertical_corridor_keeps_existing_bounds():
    request = default_request(profile='setting', hold_source='templates')
    context = _audit_context(request, request['reference_layout'])
    assert _setting_contact_corridor(context, request['start_contacts'], request['body'], request['solver']) == _contact_valid(context, request['start_contacts'], request['body'], request['solver'])


def test_no_rest_does_not_erase_incoming_effort_with_cheap_shuffles():
    context = {'left': {'attrs': {'grip_accessibility': 1., 'force_demand': .1}},
               'right': {'attrs': {'grip_accessibility': 1., 'force_demand': .1}}}
    after = {'LH': {'placement_id': 'left'}, 'RH': {'placement_id': 'right'}}
    prior = 200.
    for load in (0., 2., 0., 4.):
        next_load, rest, recovery, burden = _history(prior, {'load': load, 'attributes': {'foot_support': 1., 'inclination': 1.}}, context, after)
        assert rest == recovery == 0.
        assert next_load >= prior
        assert burden == load+.17*prior
        prior = next_load


def test_downward_roof_tread_cannot_grant_standing_recovery():
    request = default_request(profile='setting', hold_source='templates')
    context = _audit_context(request, request['reference_layout'])
    before = request['start_contacts']; target = 'hand-1'
    # Same locations, grasp attributes and move; only the two foot normals vary.
    for hand in ('LH', 'RH'):
        context[before[hand]['placement_id']]['attrs'].update(grip_accessibility=.95, force_demand=.1)
    context[target]['attrs'].update(grip_accessibility=.95, force_demand=.1)
    for foot in ('LF', 'RF'):
        context[before[foot]['placement_id']]['normal'] = np.array([0., 1., 0.])
    up = _metrics(request, context, before, 'LH', target)
    after = dict(before, LH={'placement_id': target})
    _, rest_up, _, _ = _history(150., up, context, after)
    for foot in ('LF', 'RF'):
        context[before[foot]['placement_id']]['normal'] *= -1
    down = _metrics(request, context, before, 'LH', target)
    _, rest_down, recovery_down, _ = _history(150., down, context, after)
    assert rest_up > 0.
    assert down['attributes']['foot_support'] == down['attributes']['standing_foot_support'] == 0.
    assert rest_down == recovery_down == 0.
    assert down['load'] > up['load']


def test_real_roof_search_has_no_prescribed_sequence_and_checks_every_pose():
    request = default_request(profile='setting', wall_profile='roof', hold_source='assets')
    original = _shell(request, request['reference_layout'])
    options = {'beam_width': 22, 'max_expansions': 16000, 'max_transfers': 26, 'max_ik_candidates': 3}
    sequences, evidence = _search(request, original, 'fewer_transfers', options)
    assert sequences and evidence['complete_sequences'] >= 2
    evaluated = []
    for steps in sequences:
        candidate = _make_candidate(original, steps, 'fewer_transfers')
        result = evaluate(request, candidate)
        if result['summary']['status'] == 'pass':
            evaluated.append((candidate, result))
    assert len(evaluated) >= 2
    candidate, result = evaluated[0]
    assert len(candidate['events']) >= 10
    panel = {p['id']: p['wall_panel_id'] for p in candidate['placements']}
    assert any(panel[s['contacts'][limb]['placement_id']] == 'roof' for s in candidate['states'] for limb in ('LH', 'RH') if s['contacts'][limb])
    assert all(candidate['states'][-1]['contacts'][limb]['placement_id'] == 'top' for limb in ('LH', 'RH'))
    used = {ref['placement_id'] for state in candidate['states'] for ref in state['contacts'].values() if ref}
    assert used < set(panel)  # no requirement to use the whole installation
    for pose in result['poses']:
        assert pose['status'] == 'pass'
        assert wall_clearance_report(request['scene'], pose['joints'])['status'] == 'pass'
    # Every actual load value comes from that searched sequence, with incoming
    # load propagated through the roof exit rather than reset at a panel seam.
    moves = result['design_analysis']['moves']
    assert all(m['effective_burden'] >= m['fresh_burden'] for m in moves)
    first_exit = next(m for m in moves if m['limb'].endswith('H') and panel[m['to_placement_id']] == 'upper-wall')
    assert first_exit['prior_load'] > 0.
    assert first_exit['effective_burden'] > first_exit['fresh_burden']


def test_ik_cannot_accept_a_contact_fit_when_exact_wall_check_rejects_it(monkeypatch):
    from boulderlab.kinematics import solve_pose
    request = default_request(profile='setting', wall_profile='roof', hold_source='templates')
    context = _audit_context(request, request['reference_layout'])
    targets = {limb: context[ref['placement_id']]['position'] for limb, ref in request['start_contacts'].items()}
    monkeypatch.setattr('boulderlab.wall_clearance.wall_clearance_report', lambda *a, **kw: {'status': 'fail', 'violations': [{'reason': 'test_exact_crossing'}]})
    pose = solve_pose(request['body'], targets, dict(request['solver'], restarts=1), scene=request['scene'])
    assert pose['status'] == 'unknown'
    assert pose['evidence']['attempts'][0]['wall_clearance']['status'] == 'fail'


def test_exit_window_includes_release_before_first_exit_grasp():
    from boulderlab.setting import roof_exit_support
    candidate = {
        'placements': [{'id': 'under', 'wall_panel_id': 'roof'}, {'id': 'exit', 'wall_panel_id': 'upper-wall'}],
        'states': [
            {'id': 'b0', 'contacts': {'LH': {'placement_id': 'under'}}},
            {'id': 'b1', 'contacts': {'LH': None}},
            {'id': 'b2', 'contacts': {'LH': {'placement_id': 'exit'}}}],
        'events': [{'limb': 'LH', 'from_state': 'b0', 'release_state': 'b1', 'to_state': 'b2'}]}
    evaluation = {'mechanics_report': {'states': [
        {'state_id': 'b0', 'is_release': False, 'status': 'feasible'},
        {'state_id': 'b1', 'is_release': True, 'status': 'infeasible'},
        {'state_id': 'b2', 'is_release': False, 'status': 'feasible'}]}}
    result = roof_exit_support(candidate, evaluation)
    assert result['state_ids'] == ['b1', 'b2']
    assert result['release_states'] == 1 and result['release_feasible_states'] == 0
    assert result['feasible_fraction'] == .5
    assert result['finish_status'] == 'feasible'


def test_roof_spatial_proposal_moves_used_ceiling_foot_without_prescribing_beta():
    request = default_request(profile='setting', wall_profile='roof', hold_source='assets')
    candidate = _shell(request, request['reference_layout'])
    candidate['states'].append({'id': 'probe', 'contacts': dict(request['start_contacts'], RF={'placement_id': 'foot-8'})})
    record = {'candidate': candidate, 'evaluation': {'mechanics_report': {'states': []}}}
    proposal = _mechanical_proposal(request, request['reference_layout'], record, .65)
    old = {p['id']: p for p in request['reference_layout']}; new = {p['id']: p for p in proposal}
    assert old['foot-8']['wall_panel_id'] == 'roof'
    assert new['foot-8']['wall_panel_id'] == 'upper-wall'
    for pid in ('start-left', 'start-right', 'start-foot-left', 'start-foot-right', 'top'):
        assert old[pid] == new[pid]
    assert candidate['events'] == []  # proposal is spatial, never a move list
