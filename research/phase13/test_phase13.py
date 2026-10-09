"""Independent, replayable Phase13 witness + tamper regressions.
No unit test count is an official semantic PASS count.
"""
import copy
import unittest
from pathlib import Path
from research.reference_executor.wire import ProtocolError
from .process_flow import PROFILES,readonly_audit,read,HERE


class ProcessSeparatedCORE01(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=HERE/'evidence'/'core01_process'
        if not (cls.root/'phase13_process_report.json').is_file():
            raise RuntimeError('Run python -m research.phase13.process_flow first')

    def test_three_profiles_independent_readonly_reaudit(self):
        for p in PROFILES:
            with self.subTest(profile=p):
                a=readonly_audit(self.root/p)
                self.assertEqual(a['W_accept_count'],1)
                self.assertEqual(a['W_call_count'],1)
                self.assertEqual(a['W_settlement_count'],1)
                self.assertFalse(a['official_complete_pass'])

    def test_acceptance_signature_tamper_rejected(self):
        for p in PROFILES:
            with self.subTest(profile=p):
                d=self.root/p; witness=read(d/'witness.json')
                changed=copy.deepcopy(witness)
                changed['signed_messages']['acceptance']['body']['payload']['commit_record_ref']='forged-ref'
                with self.assertRaises(ProtocolError):readonly_audit(d,changed)

    def test_tool_final_effect_tamper_rejected(self):
        for p in PROFILES:
            with self.subTest(profile=p):
                d=self.root/p; witness=read(d/'witness.json')
                changed=copy.deepcopy(witness)
                changed['tool']['signed_final']['value']['effect_id']='forged-effect'
                with self.assertRaises(ProtocolError):readonly_audit(d,changed)

    def test_profile_substitution_rejected(self):
        for p in PROFILES:
            with self.subTest(profile=p):
                d=self.root/p; witness=read(d/'witness.json')
                witness['profile']='IND-DEMO-1' if p!='IND-DEMO-1' else 'MED-DEMO-1'
                with self.assertRaises(ProtocolError):readonly_audit(d,witness)

    def test_record_matches_official_and_not_a_fake_pass(self):
        report=read(self.root/'phase13_process_report.json')
        self.assertEqual(set(report['three_profiles']),set(PROFILES))
        self.assertFalse(report['official_complete_pass'])
        for p,trace in report['three_profiles'].items():
            self.assertEqual(len(trace['mutations']),3)
            self.assertTrue(all(x['rejected'] for x in trace['mutations']))
            self.assertEqual(trace['audit']['W_settlement_count'],1)

if __name__=='__main__':unittest.main()
