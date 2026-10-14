"""Setting loop contract: real geometry, unrestricted beta and evidence integrity."""
import copy
import unittest

from boulderlab.engine import default_request, generate, _bundle_digest, validate_bundle, evaluate
from boulderlab.setting import _mechanical_proposal, _sequence_search
from boulderlab.beta_audit import analyze_beta, _make_candidate


class SettingGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = default_request(profile="setting", setting_program="diagonal_balance", budget=1)
        cls.bundle = generate(cls.request)
        cls.candidate = cls.bundle["candidates"][0]

    def test_independent_generation_keeps_unused_installed_holds(self):
        candidate = self.candidate
        used = {r["placement_id"] for state in candidate["states"] for r in state["contacts"].values() if r}
        installed = {p["id"] for p in candidate["placements"]}
        self.assertLess(len(used), len(installed))
        self.assertNotEqual(sum(e["limb"].endswith("H") for e in candidate["events"]), self.request["hand_moves"])
        self.assertEqual(self.bundle["evaluations"][0]["summary"]["status"], "pass")
        self.assertGreaterEqual(candidate["setting_report"]["search"]["geometry_trials"], 1)
        self.assertIn("mechanics_report", self.bundle["evaluations"][0])

    def test_hand_count_hint_does_not_change_free_beta(self):
        request = copy.deepcopy(self.request)
        request["hand_moves"] = 2
        result = evaluate(request, self.candidate)
        conformance = next(c for c in result["checks"] if c["id"] == "request_conformance")
        self.assertEqual(conformance["status"], "pass")

    def test_geometry_budget_failure_is_explained(self):
        request = copy.deepcopy(self.request)
        request["setting_design"]["search"]["max_expansions"] = 1
        with self.assertRaisesRegex(ValueError, "no complete sequence"):
            generate(request)

    def test_alternatives_share_geometry_and_have_real_pose_evidence(self):
        alternatives = self.candidate["setting_report"]["allowed_alternatives"]
        self.assertTrue(alternatives)
        for entry in alternatives:
            self.assertEqual(entry["candidate"]["placements"], self.candidate["placements"])
            self.assertEqual(entry["evaluation"]["summary"]["status"], "pass")
            self.assertEqual(len(entry["evaluation"]["poses"]), len(entry["candidate"]["states"]))

    def test_opaque_ids_do_not_change_geometry_proposals(self):
        baseline = self.candidate["setting_report"]["baseline_candidate"]
        analysis = self.candidate["setting_report"]["baseline_analysis"]
        record = {"candidate": baseline, "analysis": analysis, "evaluation": self.candidate["setting_report"]["baseline_evaluation"]}
        expected = _mechanical_proposal(self.request, self.request["reference_layout"], record, .65)
        mapping = {p["id"]: f"opaque-{i}" for i,p in enumerate(self.request["reference_layout"])}
        def renamed(value):
            if isinstance(value, list): return [renamed(x) for x in value]
            if isinstance(value, dict): return {k:renamed(v) for k,v in value.items()}
            return mapping.get(value,value) if isinstance(value,str) else value
        request = renamed(self.request)
        actual = _mechanical_proposal(request, request["reference_layout"], renamed(record), .65)
        self.assertEqual(actual, renamed(expected))

    def test_report_tampering_rejected_after_outer_digest_updated(self):
        for field in ("summary", "character"):
            bundle = copy.deepcopy(self.bundle)
            data = bundle["candidates"][0]["setting_report"]["result"][field]
            key = "total_proxy_effort" if field == "summary" else "score"
            data[key] += 1
            bundle["manifest"]["bundle_digest"] = _bundle_digest(bundle)
            with self.assertRaisesRegex(ValueError, "setting report"):
                validate_bundle(bundle)

    def test_alternative_with_changed_geometry_is_rejected(self):
        bundle = copy.deepcopy(self.bundle)
        alternate = bundle["candidates"][0]["setting_report"]["allowed_alternatives"][0]
        alternate["candidate"]["placements"][0]["u"] += .01
        bundle["manifest"]["bundle_digest"] = _bundle_digest(bundle)
        with self.assertRaisesRegex(ValueError, "changed installed geometry"):
            validate_bundle(bundle)

    def test_audit_candidate_does_not_inherit_stale_setting_report(self):
        candidate = self.candidate
        steps = [(event["limb"], candidate["states"][2*i+2]["contacts"][event["limb"]]["placement_id"]) for i,event in enumerate(candidate["events"])]
        alternate = _make_candidate(candidate,steps,"fewer_transfers")
        self.assertNotIn("setting_report",alternate)

    def test_direction_and_support_changes_affect_measured_sequence(self):
        original = copy.deepcopy(self.candidate)
        before,_ = analyze_beta(self.request, original)
        target = next(p for p in original["placements"] if p["id"] == before["moves"][1]["to_placement_id"])
        target["rotation_deg"] += 20
        changed,_ = analyze_beta(self.request,original)
        self.assertNotEqual(before["moves"],changed["moves"])


if __name__ == "__main__": unittest.main()
