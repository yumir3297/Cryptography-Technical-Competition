"""MED must enforce its current signed review and every applicable denial."""
import tempfile
import unittest
from pathlib import Path

from research.phase8.fixtures import build_scene, prepare_approved
from research.phase12.authority import HardenedSceneW
from research.phase14.verifier import VerifierOnlySceneW
from research.phase11.trusted_clock import seal
from research.phase6.trusted_final import Controller
from research.reference_executor.wire import ProtocolError


class MedRequiredReviewSafety(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        path = Path(self.folder.name) / "med.sqlite"
        self.issuer, action, task, scene, _ = build_scene(
            path, "MED-DEMO-1", authority_class=HardenedSceneW
        )
        self.op = prepare_approved(self.issuer, action, task, scene)
        self.assertEqual(self.op["required"], ["CLINICAL_REVIEW"])
        self.assertEqual(len(self.op["reviews"]), 1)
        self.w = VerifierOnlySceneW(
            path, "MED-DEMO-1", root_public=self.issuer.root_public,
            actors=self.issuer.actors
        )
        self.clock = seal(
            Controller(self.issuer.controller), "MED-DEMO-1", self.w.scope,
            action["operation_id"], "PREPARE", 1, 106, 106,
        )

    def test_omitted_mandatory_review_never_prepares(self):
        self.op["reviews"].clear()
        with self.assertRaises(ProtocolError) as cm:
            self.w.prepare_accept(self.op, clock=self.clock)
        self.assertIn(cm.exception.code, ("REVIEW_REQUIRED", "BINDING"))
        self.assertEqual(self.w.snapshot()["accepts"], 0)
        self.assertEqual(self.w.snapshot()["reserved"], 0)

    def test_stored_applicable_deny_blocks_valid_approval(self):
        self.issuer.review(
            self.op, purpose="CLINICAL_REVIEW", verdict="DENY"
        )
        with self.assertRaises(ProtocolError) as cm:
            self.w.prepare_accept(self.op, clock=self.clock)
        self.assertEqual(cm.exception.code, "REVIEW_DENY")
        self.assertEqual(self.w.snapshot()["accepts"], 0)
        self.assertEqual(self.w.snapshot()["reserved"], 0)


if __name__ == "__main__":
    unittest.main()
