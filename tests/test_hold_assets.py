"""External geometry binding: source hashes, real mesh anchors and uniform scale."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from boulderlab import hold_assets
from boulderlab.engine import default_request, validate_request, fingerprint
from boulderlab.geometry import contact_world, grip_surfaces, height_at, mounting_faces, panel_frame, rotation_z


def rehash(asset):
    asset['geometry_sha256'] = hold_assets.asset_hash(asset['geometry'])
    asset['asset_record_sha256'] = hold_assets.asset_hash({k:v for k,v in asset.items() if k != 'asset_record_sha256'})
    return asset


def mesh_asset(family='jug'):
    # A deliberately non-height-field tetrahedral solid. The chosen working
    # patch is exactly on the outward upper triangle, never a template formula.
    vertices = [[-.1,-.1,0],[.1,-.1,0],[0,.1,0],[0,0,.1]]
    faces = [[0,2,1],[0,1,3],[1,2,3],[2,0,3]]
    triangle = np.array(vertices)[faces[2]]
    normal = np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0]); normal /= np.linalg.norm(normal)
    u = triangle[1]-triangle[0]; u /= np.linalg.norm(u)
    v = np.cross(normal,u)
    return rehash({'id':'test-'+family,'family':family,'label':'External '+family,
      'geometry':{'positions':vertices,'triangles':faces},'width':.2,'height':.2,'depth':.1,
      'source':{'url':'https://example.test/source','author':'Test fixture','license':'CC0','license_url':'https://creativecommons.org/publicdomain/zero/1.0/','original_sha256':'sha256:'+'0'*64},
      'scale':{'basis':'synthetic test fixture; no measurement','verified':False},
      'installation':{'kind':'backplate','origin':[0,0,0],'normal':[0,0,-1],'basis':'known fixture back triangle','verified':False},
      'grip_surfaces':[{'id':'working','label':'Triangle patch','position':triangle.mean(axis=0).tolist(),'normal':normal.tolist(),'u_axis':u.tolist(),'v_axis':v.tolist(),'radii':[.06,.025],'limbs':['LH','RH'],'pull_direction':(-v).tolist(),'mesh_anchor':{'triangle_index':2,'barycentric':[1/3,1/3,1/3]},'annotations':{'triangle_indices':[2]}}]})


class HoldAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'library.json'
        self.assets = [mesh_asset(family) for family in sorted(hold_assets.FAMILIES)]
        self.path.write_text(json.dumps({'schema_version':'hold-assets/1','assets':self.assets}))
        self.patch = patch.object(hold_assets,'LIBRARY_PATH',self.path); self.patch.start()

    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()

    def test_real_anchor_and_uniform_dimensions_are_used(self):
        req = default_request(profile='setting',hold_source='assets')
        hold = req['scene']['inventory'][0]
        asset = next(a for a in self.assets if a['id']==hold['asset_id'])
        scale = hold['asset_scale']
        self.assertAlmostEqual(hold['width'],.23)
        for dim in ('width','height','depth'):
            self.assertAlmostEqual(hold[dim],asset[dim]*scale)
        self.assertTrue(np.allclose(hold['contact']['position'],np.array(asset['grip_surfaces'][0]['position'])*scale))
        self.assertEqual(hold['grip_surfaces'],grip_surfaces(hold))
        self.assertNotIn('mounting_faces',hold)
        validate_request(req)
        with self.assertRaisesRegex(ValueError,'height field'):height_at(hold,0,0)
        with self.assertRaisesRegex(ValueError,'backplate'):mounting_faces(hold)

    def test_each_setting_has_all_five_families_and_template_mode_is_preserved(self):
        for program in ('diagonal_balance','opposing_sidepulls','roof_exit'):
            req = default_request(profile='setting',setting_program=program,hold_source='assets')
            used = {h['type'] for h in req['scene']['inventory'] if 'asset_id' in h}
            self.assertEqual(used,hold_assets.FAMILIES)
            self.assertFalse(any(h['type']=='rail' for h in req['scene']['inventory']))
        original = default_request(profile='setting',hold_source='templates')
        self.assertTrue(any(h['type']=='rail' for h in original['scene']['inventory']))
        self.assertFalse(any('asset_id' in h for h in original['scene']['inventory']))

    def test_swap_preserves_projected_contact_positions_not_fake_depth(self):
        req = default_request(profile='setting',hold_source='templates')
        before = contact_world(req,req['reference_layout'][0],req['scene']['inventory'][0])
        hold_assets.apply_setting_assets(req)
        after = contact_world(req,req['reference_layout'][0],req['scene']['inventory'][0])
        self.assertTrue(np.allclose(before[:2],after[:2]))
        self.assertNotAlmostEqual(before[2],after[2])

    def test_mesh_or_annotation_or_source_tamper_rejected(self):
        for change in (lambda a:a['geometry']['positions'][0].__setitem__(0,-.11),lambda a:a['source'].__setitem__('author','Someone else'),lambda a:a['grip_surfaces'][0]['position'].__setitem__(2,.5)):
            asset = copy.deepcopy(self.assets[0]); change(asset)
            with self.assertRaisesRegex(ValueError,'hash mismatch'):hold_assets.validate_asset(asset)

    def test_rehashed_off_mesh_barycentric_and_flipped_normal_rejected(self):
        for change, message in ((lambda s:s['position'].__setitem__(2,.5),'off mesh'),(lambda s:s['mesh_anchor'].__setitem__('barycentric',[-.1,.5,.6]),'outside triangle'),(lambda s:(s.__setitem__('normal',(-np.array(s['normal'])).tolist()),s.__setitem__('v_axis',(-np.array(s['v_axis'])).tolist())),'winding')):
            asset = copy.deepcopy(self.assets[0]);change(asset['grip_surfaces'][0]);rehash(asset)
            with self.assertRaisesRegex(ValueError,message):hold_assets.validate_asset(asset)

    def test_unknown_asset_stale_record_and_derived_contact_rejected(self):
        req = default_request(profile='setting',hold_source='assets')
        for change,message in ((lambda h:h.__setitem__('asset_id','absent'),'unknown'),(lambda h:h.__setitem__('asset_record_sha256','sha256:'+'0'*64),'hash mismatch'),(lambda h:h['contact']['position'].__setitem__(2,.5),'differs'),(lambda h:h['grip_surfaces'][0]['radii'].__setitem__(0,.19),'differs'),(lambda h:h.__setitem__('width',h['width']*2),'differs')):
            changed = copy.deepcopy(req);change(changed['scene']['inventory'][0])
            with self.assertRaisesRegex(ValueError,message):validate_request(changed)

    def test_stripping_all_binding_fields_cannot_turn_mesh_into_template(self):
        original=default_request(profile='setting',hold_source='assets')
        for keep_declaration in ('all','template_namespace','mesh_anchor','triangle_annotation'):
            req=copy.deepcopy(original);item=req['scene']['inventory'][0]
            for key in hold_assets.ASSET_FIELDS:item.pop(key,None)
            if keep_declaration not in ('all','template_namespace'):
                item['template_id']='setting-jug'
            for surface in item['grip_surfaces']:
                if keep_declaration in ('template_namespace','triangle_annotation'):surface.pop('mesh_anchor')
                if keep_declaration in ('template_namespace','mesh_anchor'):surface.pop('annotations')
            with self.assertRaisesRegex(ValueError,'incomplete external asset'):
                validate_request(req)

    def test_changed_registry_is_checked_without_restart(self):
        req = default_request(profile='setting',hold_source='assets')
        self.assets[0]['source']['author']='Edited source';rehash(self.assets[0])
        self.path.write_text(json.dumps({'schema_version':'hold-assets/1','assets':self.assets}))
        with self.assertRaisesRegex(ValueError,'hash mismatch'):validate_request(req)

    def test_no_silent_fallback_for_invalid_registry(self):
        self.path.write_text('{"schema_version":"bad","assets":[]}')
        with self.assertRaisesRegex(ValueError,'registry'):default_request(profile='setting',hold_source='auto')
        self.path.unlink()
        self.assertEqual(default_request(profile='setting',hold_source='auto')['setting_design']['hold_source'],'templates')
        with self.assertRaisesRegex(ValueError,'unavailable'):default_request(profile='setting',hold_source='assets')

    def test_top_matching_thresholds_do_not_expand_to_fit_asset(self):
        jug = next(a for a in self.assets if a['family']=='jug');jug['grip_surfaces'][0]['radii']=[.001,.001];rehash(jug)
        self.path.write_text(json.dumps({'schema_version':'hold-assets/1','assets':self.assets}))
        req = default_request(profile='setting',hold_source='assets')
        top=next(h for h in req['scene']['inventory'] if h['id']=='top')
        self.assertNotIn('asset_id',top);self.assertIn('TOP matching',top['asset_fallback_reason'])
        self.assertTrue(any('asset_id' in h and h['type']=='jug' for h in req['scene']['inventory']))

    def test_record_binding_participates_in_solver_fingerprint(self):
        req=default_request(profile='setting',hold_source='assets')
        candidate={'placements':req['reference_layout'],'states':[],'events':[]}
        first=fingerprint(req,candidate)
        changed=copy.deepcopy(req);changed['scene']['inventory'][0]['asset_record_sha256']='sha256:'+'0'*64
        self.assertNotEqual(first,fingerprint(changed,candidate))

    def test_mesh_anchor_transforms_through_panel_and_hold_rotation(self):
        req=default_request(profile='setting',setting_program='roof_exit',hold_source='assets')
        hold=next(h for h in req['scene']['inventory'] if h['id']=='hand-5')
        placement=next(p for p in req['reference_layout'] if p['inventory_id']==hold['id'])
        placement['rotation_deg']=37
        panel=next(p for p in req['scene']['wall_panels'] if p['id']==placement['wall_panel_id'])
        origin,rotation=panel_frame(panel,req['scene']['angle_deg'])
        asset=next(a for a in self.assets if a['id']==hold['asset_id'])
        surface=asset['grip_surfaces'][0];anchor=surface['mesh_anchor']
        triangle=np.array(asset['geometry']['positions'])[asset['geometry']['triangles'][anchor['triangle_index']]]
        mesh_point=np.array(anchor['barycentric'])@triangle*hold['asset_scale']
        expected=origin+rotation@(np.array([placement['u'],placement['v'],0])+rotation_z(37)@mesh_point)
        self.assertTrue(np.allclose(contact_world(req,placement,hold),expected,atol=1e-10))

    def test_footprint_repair_is_bounded_and_keeps_anchor_geometry(self):
        req=default_request(profile='setting',hold_source='templates')
        points={p['id']:p for p in req['reference_layout']}
        anchor=copy.deepcopy(points['start-left'])
        foot=points['foot-3'];foot.update(u=anchor['u']-.145,v=anchor['v'])
        original=copy.deepcopy(foot)
        report=hold_assets._clear_footprint_collisions(req)
        self.assertEqual(points['start-left'],anchor)
        self.assertEqual(len(report['changes']),1)
        self.assertFalse(report['unresolved_collisions'])
        self.assertLessEqual(np.linalg.norm([foot['u']-original['u'],foot['v']-original['v']]),report['max_displacement_m'])

    def test_unrepairable_overlap_is_reported_without_expanding_bound(self):
        req=default_request(profile='setting',hold_source='templates')
        points={p['id']:p for p in req['reference_layout']}
        foot=points['foot-3'];foot.update(u=points['start-left']['u'],v=points['start-left']['v'])
        original=copy.deepcopy(foot)
        report=hold_assets._clear_footprint_collisions(req)
        self.assertEqual(foot,original)
        self.assertTrue(report['unresolved_collisions'])


def test_shipped_closed_scans_do_not_gain_texture_seam_cracks():
    from collections import Counter
    assets = hold_assets.load_registry()
    for asset_id in ('setrsoft-12-jug', 'setrsoft-25-crimp', 'setrsoft-11-sloper'):
        asset = assets[asset_id]
        edges = Counter(tuple(sorted((a, b)))
                        for triangle in asset['geometry']['triangles']
                        for a, b in zip(triangle, triangle[1:]+triangle[:1]))
        assert edges and set(edges.values()) == {2}, asset_id
        assert asset['preparation']['watertight_before_simplification']
        assert asset['preparation']['watertight_after_simplification']
    # The source pinch has genuine open boundaries. This test deliberately
    # does not demand invented surfaces to close those holes.


if __name__=='__main__':unittest.main()
