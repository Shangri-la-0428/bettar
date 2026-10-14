"""Search must not reject poses allowed by the evaluator's necessary bound."""
import copy
import unittest
import numpy as np
from boulderlab.engine import default_request
from boulderlab.kinematics import contact_distance_bound
from boulderlab.route_design import _valid_contact_geometry


class ContactBoundTests(unittest.TestCase):
    def setUp(self):
        self.request=default_request()
        self.body=copy.deepcopy(self.request["body"])
        self.contacts={limb:{"placement_id":limb,"contact_id":"main"} for limb in ("LH","RH","LF","RF")}

    def context(self,hands,feet):
        return {limb:{"position":np.array(point)} for limb,point in zip(("LH","RH","LF","RF"),hands+feet)}

    def test_hand_endpoint_offsets_are_included_by_search(self):
        context=self.context([[-.75,1,0],[.75,1,0]],[[-.2,0,0],[.2,0,0]])
        self.assertFalse(_valid_contact_geometry(context,self.contacts,self.body))
        self.body["endpoint_offsets"]["LH"]=[-.06,0,0]
        self.body["endpoint_offsets"]["RH"]=[.06,0,0]
        self.assertTrue(_valid_contact_geometry(context,self.contacts,self.body))
        self.assertAlmostEqual(contact_distance_bound(self.body,"LH","RH"),1.52)

    def test_contact_tolerance_and_geometry_epsilon_are_shared(self):
        bound=contact_distance_bound(self.body,"LH","RH")
        context=self.context([[-(bound+.0200005)/2,1,0],[(bound+.0200005)/2,1,0]],[[-.2,0,0],[.2,0,0]])
        self.assertFalse(_valid_contact_geometry(context,self.contacts,self.body))
        solver={"contact_tolerance_m":.01,"epsilon_geometry_m":1e-6}
        self.assertTrue(_valid_contact_geometry(context,self.contacts,self.body,solver))
        self.assertFalse(_valid_contact_geometry(context,self.contacts,self.body,{**solver,"epsilon_geometry_m":0}))

    def test_feet_receive_the_same_offset_tolerance_rule(self):
        context=self.context([[-.2,1,0],[.2,1,0]],[[-.96,0,0],[.96,0,0]])
        self.assertFalse(_valid_contact_geometry(context,self.contacts,self.body))
        self.body["endpoint_offsets"]["LF"]=[-.04,0,0]
        self.body["endpoint_offsets"]["RF"]=[.04,0,0]
        self.assertTrue(_valid_contact_geometry(context,self.contacts,self.body,{"contact_tolerance_m":.01,"epsilon_geometry_m":1e-6}))

    def test_cross_limb_bound_uses_declared_rigid_anchor_distance(self):
        actual=contact_distance_bound(self.body,"LH","RF")
        expected=self.body["upper_arm"]+self.body["forearm"]+self.body["thigh"]+self.body["shin"]+np.hypot(self.body["torso"],(self.body["shoulder_width"]+self.body["hip_width"])/2)
        self.assertAlmostEqual(actual,expected)


if __name__=="__main__":unittest.main()
