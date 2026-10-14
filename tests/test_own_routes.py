"""Surface-aware contact search and rules-only support completion contracts."""
from copy import deepcopy

from boulderlab.beta_audit import _audit_context, _key, _contacts, _search, _make_candidate, _occupancy_error
from boulderlab.engine import default_request
from boulderlab.own_routes import BRIEFS, initial_contact_mask, make_spatial_request, metrics, contact_signature
from boulderlab.route_constraints import allowed_contact_ids
from boulderlab.route_design import _contact_key, _ref
from boulderlab.setting import _shell


def request():
    return make_spatial_request(BRIEFS[1])


def test_contact_search_identity_preserves_surface_and_legacy_main():
    refs={"LH":_ref("start-left"),"RH":_ref("start-right"),"LF":_ref(("hand-2","standing")),"RF":_ref("start-foot-right")}
    assert _contacts(_key(refs))==refs
    assert _contact_key(refs['LH'])=='start-left'
    assert _contact_key(refs['LF'])==('hand-2','standing')


def test_all_surface_context_resolves_explicit_primary_and_standing():
    r=request(); context=_audit_context(r,r['reference_layout'],all_surfaces=True)
    assert (context[('start-left','working')]['position']==context['start-left']['position']).all()
    assert (context[('start-left','standing')]['position']!=context['start-left']['position']).any()
    assert 'LF' in context[('start-left','standing')]['limbs']
    assert 'LH' not in context[('start-left','standing')]['limbs']


def test_initial_feet_use_legal_hand_surfaces_but_do_not_invent_permissions():
    r=request(); mask,pool=initial_contact_mask(r); legal=allowed_contact_ids(r,r['reference_layout'])
    for limb in mask: assert set(mask[limb]) <= legal[limb]
    assert 'start-left' in mask['LF']
    assert 'start-foot-left' in mask['LF']
    assert not set(pool)&set(mask['LF'])
    assert len(pool)==8


def test_independent_search_reuses_a_hand_hold_as_foot_without_order_requirement():
    r=request(); allowed=allowed_contact_ids(r,r['reference_layout'])
    r['route_constraints']={'allowed_contacts':{l:sorted(ids-{'foot-3','foot-4'} if l.endswith('F') else ids) for l,ids in allowed.items()}}
    sequences,_=_search(r,_shell(r,r['reference_layout']),'fewer_transfers',dict(max_expansions=16000,beam_width=22,max_transfers=26,max_ik_candidates=3))
    assert sequences
    candidate=_make_candidate(_shell(r,r['reference_layout']),sequences[0],'fewer_transfers')
    assert any(limb.endswith('F') and isinstance(key,tuple) and key[1]=='standing' for limb,key in sequences[0])
    summary=metrics(r,candidate,{'summary':{'status':'not_checked'}})
    assert summary['hand_then_foot_ids']
    assert summary['complete']
    assert summary['hand_moves']!=r['hand_moves']  # no prescribed count
    assert summary['skipped_hold_ids']
    assert any(surface=='standing' for _,_,surface in contact_signature(candidate))


def test_separate_surfaces_do_not_silently_grant_simultaneous_hand_foot_capacity():
    r=request(); context=_audit_context(r,r['reference_layout'],all_surfaces=True)
    assert _occupancy_error(context,('start-left','start-right',('start-left','standing'),'start-foot-right'))=='simultaneous_hand_foot_same_point'
    assert _occupancy_error(context,('top','top',('start-left','standing'),'start-foot-right')) is None


def test_spatial_briefs_are_distinct_geometry_not_renamed_same_wall():
    layouts=[[(p['u'],p['v'],p['rotation_deg']) for p in make_spatial_request(b)['reference_layout']] for b in BRIEFS]
    assert len({str(layout) for layout in layouts})==3
    for brief in BRIEFS:
        r=make_spatial_request(brief)
        assert len(r['reference_layout'])==18
        assert r['scene']['wall_panels'][0]['rotation_deg'][0]==25


def test_budget_exhaustion_preserves_failed_layout_without_fabricated_sequence():
    from boulderlab.own_routes import generate_route
    from boulderlab.engine import validate_bundle
    bundle,row=generate_route(BRIEFS[0],seconds=.0001)
    assert row['status']=='search_unresolved'
    assert row['search']['budget_exhausted']
    assert bundle['candidates'][0]['events']==[]
    assert not row['metrics']['complete']
    validate_bundle(bundle)


def test_explicit_finish_surface_is_searchable_and_alias_cannot_bypass_matching():
    r=request()
    r['end_contacts']['LH']['contact_id']='working'
    r['end_contacts']['RH']['contact_id']='working'
    context=_audit_context(r,r['reference_layout'],all_surfaces=True)
    assert _occupancy_error(context,('hand-2',('hand-2','working'),'start-foot-left','start-foot-right'))=='hand_match_not_supported_by_selected_patch'
    sequences,_=_search(r,_shell(r,r['reference_layout']),'fewer_transfers',dict(max_expansions=16000,beam_width=22,max_transfers=26,max_ik_candidates=3))
    assert sequences
    candidate=_make_candidate(_shell(r,r['reference_layout']),sequences[0],'fewer_transfers')
    assert candidate['states'][-1]['contacts']['LH']==r['end_contacts']['LH']
    assert candidate['states'][-1]['contacts']['RH']==r['end_contacts']['RH']


def test_retained_hand_orientation_uses_explicit_surface_direction():
    import numpy as np
    from boulderlab.beta_audit import orientation_support
    r=request(); refs=deepcopy(r['start_contacts']); refs['LH']['contact_id']='alternate'
    context=_audit_context(r,r['reference_layout'],all_surfaces=True)
    # Deliberately opposite pull on the explicit hand surface; a default-face
    # fallback would produce the old alignment despite the changed contact.
    key=('start-left','alternate'); context[key]['pull']=-context['start-left']['pull']
    actual=orientation_support(context,refs,'RH')['retained_hand_pull_alignment']['LH']
    hand_mid=np.mean([context[_contact_key(refs[l])]['position'] for l in ('LH','RH')],axis=0)
    foot_mid=np.mean([context[_contact_key(refs[l])]['position'] for l in ('LF','RF')],axis=0)
    direction=(hand_mid+foot_mid)/2-context[key]['position']; pull=context[key]['pull']
    expected=float(np.dot(direction,pull)/(np.linalg.norm(direction)*np.linalg.norm(pull)))
    assert abs(actual-expected)<1e-12


def test_saved_stage_evidence_is_recomputed_not_trusted(tmp_path):
    import pytest
    from boulderlab.own_routes import generate_route, _verify_row
    from boulderlab.learned_experiment import write_json
    bundle,row=generate_route(BRIEFS[0],seconds=.0001)
    for name,proof in row.pop('_evidence_bundles').items():
        digest=proof['manifest']['bundle_digest']; relative='bundles/'+digest.split(':')[-1]+'.json.gz'
        row['completion'][name].update(bundle_file=relative,bundle_digest=digest)
        write_json(tmp_path/relative,proof)
    digest=bundle['manifest']['bundle_digest']; relative='bundles/'+digest.split(':')[-1]+'.json.gz'
    row.update(bundle_file=relative,bundle_digest=digest); write_json(tmp_path/relative,bundle)
    _verify_row(tmp_path,row)
    row['completion']['before']['metrics']['hand_moves']=999
    with pytest.raises(ValueError,match='阶段指标'):
        _verify_row(tmp_path,row)


def test_unknown_route_and_escaped_bundle_path_fail_as_input_errors(tmp_path):
    import pytest
    from boulderlab.own_routes import load_route, _bundle
    with pytest.raises(ValueError,match='未知'):
        load_route(tmp_path,'../other')
    with pytest.raises(ValueError,match='超出'):
        _bundle(tmp_path,{'bundle_file':'../outside.json','bundle_digest':'not-used'})


def test_resigned_index_does_not_allow_duplicate_briefs_or_invented_pairwise(tmp_path,monkeypatch):
    import pytest
    from boulderlab import own_routes
    from boulderlab.engine import canonical_hash,code_hash
    from boulderlab.learned_experiment import write_json
    rows=[dict(b,geometry_digest=b['id'],sequence_digest=b['id'],metrics={'used_hold_ids':['a']}) for b in BRIEFS]
    data={'schema_version':own_routes.FORMAT,'engine_code_hash':code_hash(),'generator_code_hash':own_routes.generator_hash(),
          'routes':rows,'pairwise':own_routes.pairwise(rows)}
    def save():
        data.pop('index_digest',None);data['index_digest']=canonical_hash(data);write_json(tmp_path/'study.json',data)
    monkeypatch.setattr(own_routes,'_verify_row',lambda *args:None)
    save();own_routes.load_study(tmp_path)
    data['pairwise'][0]['geometry_same']=True;save()
    with pytest.raises(ValueError,match='差异记录'):
        own_routes.load_study(tmp_path)
    data['routes'][1]=deepcopy(data['routes'][0]);save()
    with pytest.raises(ValueError,match='不重复'):
        own_routes.load_study(tmp_path)
