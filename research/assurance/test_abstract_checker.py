"""Tests for the bounded abstraction, NOT the 39 full protocol semantic cases."""
import unittest
from abstract_checker import State, ModelFlags, MUTANTS, explore, successors, violations


def take(state, event, flags=ModelFlags()):
    matches = [nxt for name, nxt in successors(state, flags) if name == event]
    if len(matches) != 1:
        raise AssertionError(f'{event} not enabled (found {len(matches)}) in {state}')
    return matches[0]


def enabled(state, name):
    return any(n == name for n, _ in successors(state))


class CoreSafetyAbstractionTests(unittest.TestCase):
    def test_positive_authorized_commit(self):
        s = take(State(), 'independent_U_approve')
        s = take(s, 'G_issue_permit_0')
        s = take(s, 'W_accept_0')
        self.assertTrue(s.accepted[0])
        self.assertTrue(s.legitimate_at_accept[0])
        self.assertEqual(violations(s), [])

    def test_compromised_g_alone_cannot_accept(self):
        s = take(State(), 'G_issue_permit_0')
        self.assertFalse(enabled(s, 'W_accept_0'))

    def test_stale_approval_rejected(self):
        s = take(State(), 'independent_U_approve')
        s = take(s, 'G_issue_permit_0')
        s = take(s, 'new_basis_revision')
        self.assertFalse(enabled(s, 'W_accept_0'))

    def test_deny_cannot_be_omitted(self):
        s = take(State(), 'independent_U_approve')
        s = take(s, 'G_issue_permit_0')
        s = take(s, 'publish_V_deny')
        self.assertFalse(enabled(s, 'W_accept_0'))

    def test_revoke_blocks_future_acceptance(self):
        s = take(State(), 'independent_U_approve')
        s = take(s, 'G_issue_permit_0')
        s = take(s, 'revoke_role')
        self.assertFalse(enabled(s, 'W_accept_0'))

    def test_stable_intent_blocks_second_candidate(self):
        s = take(State(), 'independent_U_approve')
        s = take(s, 'G_issue_permit_0')
        s = take(s, 'G_issue_permit_1')
        s = take(s, 'W_accept_0')
        self.assertFalse(enabled(s, 'W_accept_1'))

    def test_no_automatic_redispatch(self):
        s = take(State(), 'independent_U_approve')
        s = take(s, 'G_issue_permit_0')
        s = take(s, 'W_accept_0')
        s = take(s, 'claim_and_dispatch_0')
        self.assertFalse(enabled(s, 'claim_and_dispatch_0'))

    def test_rotate_requires_current_proof_and_does_not_repeat_effect(self):
        s = take(State(), 'independent_U_approve')
        for name in ('G_issue_permit_0','W_accept_0','claim_and_dispatch_0',
                     'tool_finalizes_0','reattest_final_0',
                     'rotate_tool_key_with_continuity'):
            s = take(s, name)
        self.assertFalse(enabled(s, 'W_settle_0'))
        s = take(s, 'reattest_final_0')
        s = take(s, 'W_settle_0')
        self.assertEqual(s.calls[0], 1)
        self.assertEqual(s.settled[0], 1)
        self.assertFalse(enabled(s, 'W_settle_0'))

    def test_lost_ledger_does_not_fabricate_final(self):
        s = take(State(), 'independent_U_approve')
        for name in ('G_issue_permit_0','W_accept_0','claim_and_dispatch_0',
                     'lose_tool_ledger_continuity', 'tool_finalizes_0'):
            s = take(s, name)
        self.assertFalse(enabled(s, 'reattest_final_0'))
        self.assertFalse(enabled(s, 'W_settle_0'))

    def test_lost_continuity_after_attestation_blocks_first_settlement(self):
        s = take(State(), 'independent_U_approve')
        for name in ('G_issue_permit_0','W_accept_0','claim_and_dispatch_0',
                     'tool_finalizes_0','reattest_final_0',
                     'lose_tool_ledger_continuity'):
            s = take(s, name)
        self.assertFalse(enabled(s, 'W_settle_0'))
        self.assertEqual(s.settled[0],0)

    def test_subject_separation_required(self):
        cfg = ModelFlags(separate_subjects=False)
        s = State()
        # Approval event is an abstract U signature; its accept guard still rejects same-subject.
        s = take(s, 'independent_U_approve', cfg)
        s = take(s, 'G_issue_permit_0', cfg)
        self.assertFalse(any(n == 'W_accept_0' for n,_ in successors(s,cfg)))

    def test_bounded_baseline_has_no_counterexample(self):
        result = explore(max_depth=18)
        self.assertIsNone(result['first_violation'])
        self.assertTrue(result['fully_explored_finite_model'])
        self.assertGreater(result['visited_states'], 1000)

    def test_all_mutants_have_concrete_counterexamples(self):
        expected = {
            'ignore_u':'NO_UNAUTHORIZED_ACCEPT',
            'ignore_revision':'NO_UNAUTHORIZED_ACCEPT',
            'ignore_deny':'NO_UNAUTHORIZED_ACCEPT',
            'ignore_intent':'INTENT_AT_MOST_ONCE',
            'allow_redispatch':'NO_REDISPATCH',
            'allow_double_settle':'SETTLE_AT_MOST_ONCE',
            'ignore_revocation':'NO_UNAUTHORIZED_ACCEPT',
            'same_subject':'NO_UNAUTHORIZED_ACCEPT',
        }
        for name, cfg in MUTANTS.items():
            with self.subTest(mutant=name):
                result=explore(cfg,max_depth=18)
                self.assertIn(expected[name],result['first_violation']['properties'])
                self.assertTrue(result['first_violation']['trace'])

if __name__=='__main__': unittest.main()
