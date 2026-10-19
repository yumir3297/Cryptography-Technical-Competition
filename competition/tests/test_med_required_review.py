"""MED must enforce its current signed review and every applicable denial.

Rewritten for the shared competition core: the case is driven through the real
``AuthorizationService`` over a signed MED corpus, not the retired scene W.
"""
import tempfile
import unittest
from pathlib import Path

from competition.profiles.authorization_seed import initialize
from competition.support.wire import ProtocolError

ROOT = Path(__file__).resolve().parents[2]


class MedRequiredReviewSafety(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.folder.cleanup)
        self.run = initialize(Path(self.folder.name) / 'med')
        self.addCleanup(self.run.close)
        self.profile = 'MED-DEMO-1'
        self.assertEqual(self.run.operations[self.profile]['required'], ['CLINICAL_REVIEW'])

    def test_omitted_mandatory_review_never_authorizes(self):
        op = self.run.clone(self.profile)
        op['reviews'] = []
        proof = self.run.identity_proof(self.profile, op)
        before = self.run.service.counts()
        with self.assertRaises(ProtocolError) as cm:
            self.run.service.guard(self.profile, op, proof)
        self.assertIn(cm.exception.code, ('REVIEW_REQUIRED', 'BINDING'))
        self.assertEqual(self.run.service.counts(), before)

    def test_stored_applicable_deny_blocks_valid_approval(self):
        op = self.run.clone(self.profile)
        self.run.deny(self.profile, op, purpose='CLINICAL_REVIEW')
        proof = self.run.identity_proof(self.profile, op)
        before = self.run.service.counts()
        with self.assertRaises(ProtocolError) as cm:
            self.run.service.guard(self.profile, op, proof)
        self.assertEqual(cm.exception.code, 'REVIEW_DENY')
        self.assertEqual(self.run.service.counts(), before)


if __name__ == '__main__':
    unittest.main()
