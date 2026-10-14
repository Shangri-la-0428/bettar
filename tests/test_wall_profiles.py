"""Actual panel seams, contact transforms and honest no-sequence layouts."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from boulderlab.engine import default_request, _schema, evaluate, make_bundle
from boulderlab.geometry import panel_frame, panel_fit, contact_world, placement_frames
from boulderlab.setting import search_settings, _shell
from boulderlab.wall_profiles import panels_for
from boulderlab.server import wall_examples, generate_setting_comparison


def point(panel, xyz, base_angle=0):
    origin,rotation=panel_frame(panel,base_angle)
    return origin+rotation@xyz


class WallProfileTests(unittest.TestCase):
    def test_roof_has_two_continuous_seams_and_actual_horizontal_underside(self):
        lower,roof,upper=panels_for('roof')
        for angle in (0,17):
            for x in (-2.4,0,2.4):
                self.assertTrue(np.allclose(point(lower,[x,lower['height'],0],angle),point(roof,[x,0,0],angle),atol=1e-10))
                self.assertTrue(np.allclose(point(roof,[x,roof['height'],0],angle),point(upper,[x,0,0],angle),atol=1e-10))
        _,rotation=panel_frame(roof,0)
        self.assertTrue(np.allclose(rotation[:,2],[0,-1,0],atol=1e-10))
        self.assertTrue(np.allclose(point(roof,[0,.6,0])-point(roof,[0,.2,0]),[0,0,.4],atol=1e-10))

    def test_both_corners_share_full_vertical_edge_and_have_opposite_normal_senses(self):
        for profile,sign in (('dihedral',1),('arete',-1)):
            left,right=panels_for(profile)
            for angle in (0,13):
                for y in (0,1.7,4.2):
                    self.assertTrue(np.allclose(point(left,[left['width']/2,y,0],angle),point(right,[-right['width']/2,y,0],angle),atol=1e-10))
            _,a=panel_frame(left,0);_,b=panel_frame(right,0)
            self.assertGreater(a[0,2]*sign,0)
            self.assertLess(b[0,2]*sign,0)
            self.assertAlmostEqual(float(a[:,2]@b[:,2]),np.cos(np.deg2rad(70)))

    def test_all_twelve_asset_layouts_fit_panels_after_recorded_adaptation(self):
        for profile in ('overhang','roof','dihedral','arete'):
            for program in ('diagonal_balance','opposing_sidepulls','roof_exit'):
                req=default_request(profile='setting',setting_program=program,wall_profile=profile,hold_source='assets')
                inventory={h['id']:h for h in req['scene']['inventory']}
                self.assertEqual(panel_fit(req['reference_layout'],inventory,req['scene']),[])
                self.assertFalse(req['setting_design']['wall_application']['spacing_adjustment']['unresolved_collisions'])
                self.assertTrue(all(p.get('wall_panel_id') for p in req['reference_layout']))

    def test_world_contact_follows_real_roof_normal_and_rotated_selected_patch(self):
        req=default_request(profile='setting',wall_profile='roof',hold_source='templates')
        placement=next(p for p in req['reference_layout'] if p['wall_panel_id']=='roof')
        inventory={h['id']:h for h in req['scene']['inventory']};item=inventory[placement['inventory_id']]
        surface=next(s for s in item['grip_surfaces'] if s['id']==placement['contact_surface_id'])
        f=placement_frames(req['reference_layout'],inventory,0,req['scene']['wall_panels'])
        origin,rotation=f[placement['id']]
        actual=contact_world(req,placement,item,req['reference_layout'],f)
        self.assertTrue(np.allclose(actual,origin+rotation@surface['position']))
        self.assertLess(actual[1],2.1)  # hold projects below the horizontal ceiling
        self.assertAlmostEqual(float(rotation[:,2]@np.array([0,-1,0])),1.)

    def test_default_preserves_existing_wall_and_unknown_choices_fail(self):
        req=default_request(profile='setting',setting_program='roof_exit',wall_profile='default',hold_source='templates')
        self.assertEqual([p['rotation_deg'][0] for p in req['scene']['wall_panels']],[18,4])
        for kwargs in ({'profile':'setting','wall_profile':'fake'},{'profile':'basic','wall_profile':'roof'}):
            with self.assertRaises(ValueError):default_request(**kwargs)

    def test_failed_search_exports_only_real_layout_and_never_fabricates_events(self):
        req=default_request(profile='setting',wall_profile='roof',hold_source='templates',seed=1299)
        with patch('boulderlab.setting._sequence_search',return_value=([],[{'expanded':1,'budget_exhausted':True}])):
            candidate=search_settings(req)[0]
        self.assertEqual(candidate['layout_report']['status'],'no_sequence')
        self.assertEqual(candidate['events'],[]);self.assertEqual(len(candidate['states']),1)
        self.assertEqual(candidate['placements'],req['reference_layout'])
        self.assertNotIn('setting_report',candidate)
        evaluation=evaluate(req,candidate,deadline=time.perf_counter()-1)
        bundle=make_bundle(req,[candidate],[evaluation])
        self.assertEqual(bundle['evaluations'][0]['summary']['status'],'fail')
        self.assertIsNone(evaluation['design_analysis'])
        self.assertTrue(any(c['id']=='request_conformance' and c['status']=='fail' for c in evaluation['checks']))
        stripped=copy.deepcopy(candidate);stripped.pop('layout_report')
        with self.assertRaises(ValueError):_schema(stripped,'candidate')

    def test_default_search_still_rejects_missing_complete_sequence(self):
        req=default_request(profile='setting',wall_profile='default',hold_source='templates',seed=1300)
        with patch('boulderlab.setting._sequence_search',return_value=([],[])):
            with self.assertRaisesRegex(ValueError,'no complete sequence'):search_settings(req)

    def test_wall_endpoint_selects_and_checks_profile_with_missing_as_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'fixtures').mkdir()
            with patch('boulderlab.server.ROOT',root),patch('boulderlab.server.validate_bundle',side_effect=lambda b:b):
                with self.assertRaises(FileNotFoundError):wall_examples('roof')
                for profile in ('overhang','roof','dihedral','arete'):
                    (root/'fixtures'/f'wall-{profile}-bundle.json').write_text(json.dumps({'request':{'setting_design':{'wall_profile':profile}}}))
                self.assertEqual([e['id'] for e in wall_examples('roof')['examples']],['roof'])
                self.assertEqual(len(wall_examples()['examples']),4)
                with self.assertRaises(ValueError):wall_examples('default')
                (root/'fixtures'/'wall-roof-bundle.json').write_text(json.dumps({'request':{'setting_design':{'wall_profile':'overhang'}}}))
                with self.assertRaisesRegex(ValueError,'profile does not match'):wall_examples('roof')

    def test_setting_comparison_forwards_wall_and_hold_sources(self):
        with patch('boulderlab.server.default_request',return_value={}) as make,patch('boulderlab.server.generate',return_value={}),patch('boulderlab.server.save_run'):
            result=generate_setting_comparison({'wall_profile':'arete','hold_source':'templates'})
        self.assertEqual(len(result['examples']),3)
        for call in make.call_args_list:
            self.assertEqual(call.kwargs['wall_profile'],'arete')
            self.assertEqual(call.kwargs['hold_source'],'templates')


if __name__=='__main__':unittest.main()
