"""Tests of a research abstraction, not wire/crypto or a product handler."""
import unittest
from dataclasses import replace
from model import Interval, State, commit, sign_original, attest, verify_attestation, claim, gate, explore, advance_sample


class TimeClosureTests(unittest.TestCase):
    def test_old_sample_must_age_to_current_interval(self):
        current = advance_sample(Interval(100, 100), Interval(10, 10))
        self.assertEqual(current, Interval(110, 110))
        self.assertEqual(gate(100, 105, current), 'F')

    def test_unbounded_clock_sample_age_is_unknown(self):
        self.assertEqual(gate(100, 120, advance_sample(Interval(100, 100), None)), 'U')

    def test_elapsed_uncertainty_can_exceed_clock_width(self):
        current = advance_sample(Interval(100, 101), Interval(2, 5))
        self.assertEqual(gate(100, 120, current), 'U')

    def test_monotonic_reset_cannot_supply_negative_elapsed_time(self):
        self.assertIsNone(advance_sample(Interval(100, 100), Interval(-1, 1)))

    def test_interval_boundaries(self):
        for iat, exp, lo, hi, expected in [
            (100, 120, 100, 100, 'T'), (100, 120, 118, 119, 'T'),
            (100, 120, 119, 120, 'U'), (100, 120, 120, 120, 'F'),
            (100, 120, 99, 100, 'U'), (100, 120, 100, 103, 'U'),
            (100, 120, 102, 101, 'U'), (100, 120, 121, 122, 'F')]:
            with self.subTest(iat=iat, exp=exp, lo=lo, hi=hi):
                self.assertEqual(gate(iat, exp, Interval(lo, hi)), expected)

    def test_commit_before_expiry_and_later_sign(self):
        s = commit(State(), Interval(100, 101), permit_exp=120)
        self.assertEqual(s.fact.accepted_at, 100)
        self.assertEqual(s.floor, 100)  # upper uncertainty bound is not a known time lower bound
        self.assertTrue(sign_original(s, Interval(100, 100), original_key_active=True))
        self.assertTrue(sign_original(s, Interval(125, 126), original_key_active=True))
        self.assertEqual(s.fact.accepted_at, 100)

    def test_expired_new_commit_refused(self):
        self.assertEqual(commit(State(), Interval(120, 120), permit_exp=120), State())

    def test_uncertain_expiry_new_commit_refused(self):
        self.assertEqual(commit(State(), Interval(119, 120), permit_exp=120), State())

    def test_changed_dependency_commit_refused(self):
        self.assertEqual(commit(State(), Interval(100, 100), deps_current=False), State())

    def test_resource_race_commit_refused(self):
        self.assertEqual(commit(State(), Interval(100, 100), resource_free=False), State())

    def test_retransmission_never_new_acceptance(self):
        s = commit(State(), Interval(100, 100))
        self.assertEqual(commit(s, Interval(2000, 2000)), s)

    def test_old_signing_deadline_gap_characterized(self):
        s = commit(State(), Interval(100, 100))
        self.assertFalse(sign_original(s, Interval(1000, 1000), original_key_active=True))
        self.assertFalse(sign_original(s, Interval(200, 200), original_key_active=False))
        self.assertEqual(s.accepts, 1)

    def test_new_proof_observes_same_old_fact(self):
        s = commit(State(), Interval(100, 100))
        proof = attest(s, Interval(1100, 1101), query='query-new')
        self.assertEqual(proof.fact, s.fact)
        self.assertEqual(proof.issued_at, 1100)
        self.assertEqual(proof.fact.accepted_at, 100)
        self.assertTrue(verify_attestation(s, proof, Interval(1102, 1102), query='query-new'))

    def test_reattest_preserves_accept_dispatch_and_reservation(self):
        s = commit(State(), Interval(100, 100))
        before = (s.accepts, s.calls, s.reserved, s.mode, s.fact)
        for t in (101, 900, 1100, 2000):
            self.assertIsNotNone(attest(s, Interval(t, t)))
        self.assertEqual(before, (s.accepts, s.calls, s.reserved, s.mode, s.fact))

    def test_no_fact_no_historical_proof(self):
        self.assertIsNone(attest(State(), Interval(100, 100)))

    def test_no_continuous_ledger_no_proof(self):
        s = commit(State(), Interval(100, 100))
        self.assertIsNone(attest(s, Interval(101, 101), ledger_continuous=False))

    def test_missing_historical_authority_no_proof(self):
        s = commit(State(), Interval(100, 100))
        self.assertIsNone(attest(s, Interval(101, 101), archive_verified=False))

    def test_no_current_signing_authority_no_proof(self):
        s = commit(State(), Interval(100, 100))
        self.assertIsNone(attest(s, Interval(101, 101), current_signer_active=False))

    def test_wrong_query_proof_rejected(self):
        s = commit(State(), Interval(100, 100))
        self.assertFalse(verify_attestation(s, attest(s, Interval(101, 101)), Interval(102, 102), query='other'))

    def test_changed_fact_proof_rejected(self):
        s = commit(State(), Interval(100, 100))
        p = attest(s, Interval(101, 101))
        self.assertFalse(verify_attestation(s, replace(p, fact=replace(p.fact, accepted_at=99)), Interval(102, 102)))

    def test_expired_or_uncertain_proof_rejected(self):
        s = commit(State(), Interval(100, 100))
        p = attest(s, Interval(101, 101))
        self.assertFalse(verify_attestation(s, p, Interval(131, 131)))
        self.assertFalse(verify_attestation(s, p, Interval(130, 131)))

    def test_history_proof_does_not_allow_expired_dispatch(self):
        s = commit(State(), Interval(100, 100))
        self.assertIsNotNone(attest(s, Interval(1100, 1100)))
        after = claim(s, Interval(1100, 1100))
        self.assertEqual(after.mode, 'CANCELLED')
        self.assertEqual(after.calls, 0)
        self.assertEqual(after.accepts, 1)

    def test_uncertain_dispatch_keeps_reservation(self):
        s = commit(State(), Interval(100, 100))
        self.assertEqual(claim(s, Interval(119, 120)), s)

    def test_started_never_reclaimed_or_released_by_timeout(self):
        s = claim(commit(State(), Interval(100, 100)), Interval(101, 101))
        self.assertEqual(claim(s, Interval(2000, 2000)), s)
        self.assertEqual(s.calls, 1)
        self.assertEqual(s.reserved, 1)

    def test_clock_floor_and_future_attestation(self):
        s = commit(State(), Interval(100, 101))
        self.assertIsNone(attest(s, Interval(99, 99)))
        self.assertFalse(verify_attestation(s, attest(s, Interval(102, 102)), Interval(101, 101)))

    def test_shared_resource_two_candidates(self):
        winner = commit(State(), Interval(100, 100))
        loser = commit(State(), Interval(100, 100), resource_free=(winner.reserved == 0))
        self.assertEqual(winner.accepts + loser.accepts, 1)

    def test_bounded_interleavings(self):
        r = explore()
        self.assertGreater(r['states'], 100)
        self.assertGreater(r['transitions'], r['states'])
        self.assertEqual(r['violations'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
