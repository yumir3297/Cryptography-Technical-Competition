"""The candidate edge accepts data, never agent-generated code or credentials."""
import importlib
import unittest
from pathlib import Path
from competition.profiles.pay_seed import build_pay
from competition.support.wire import Identity, canonical, ProtocolError
from competition.support.broker_policy import PROFILE_SCOPES

class CandidateIngressTests(unittest.TestCase):
    def setUp(self):
        try: module=importlib.import_module('competition.core.candidate_ingress')
        except ModuleNotFoundError: self.fail('Missing data-only candidate ingress')
        self.ingress=module.CandidateIngress(Path(__file__).resolve().parents[2])
        actors={a:Identity('actor-'+a.lower(),i+1) for i,a in enumerate(('H','U','G','X','V','E'))}
        self.action=build_pay(actors,PROFILE_SCOPES['PAY-1'],100)['action']

    def test_action_round_trip_contains_no_new_authority(self):
        self.assertEqual(self.ingress.parse('PAY-1',canonical(self.action)),self.action)
        self.assertFalse(hasattr(self.ingress,'store'))
        self.assertFalse(hasattr(self.ingress,'broker'))

    def test_code_credentials_paths_and_duplicates_are_not_candidates(self):
        cases=[{'code':'import os'}, {'execute':True}, {'key_path':'C:/C.key'},
               {'authorization':{'verdict':'APPROVE'}}, {'callback':'eval'},
               dict(self.action,worker_proof={})]
        for value in cases:
            with self.subTest(value=value),self.assertRaises(ProtocolError):
                self.ingress.parse('PAY-1',canonical(value))
        with self.assertRaises(ProtocolError):self.ingress.parse('PAY-1',b'{"x":"a","x":"b"}')
        with self.assertRaises(ProtocolError):self.ingress.parse('PAY-1',b'x'*65537)
        with self.assertRaises(ProtocolError):self.ingress.parse('PAY-1',lambda:None)

    def test_wrong_profile_scope_rejected(self):
        for p in ('IND-DEMO-1','MED-DEMO-1'):
            with self.assertRaises(ProtocolError):self.ingress.parse(p,canonical(self.action))

    def test_parser_limits_are_protocol_errors(self):
        for blob in (b'['*20000+b'"x"'+b']'*20000,b'1'*5000):
            with self.subTest(size=len(blob)),self.assertRaises(ProtocolError):
                self.ingress.parse('PAY-1',blob)
        with self.assertRaises(ProtocolError):self.ingress.parse({},canonical(self.action))
