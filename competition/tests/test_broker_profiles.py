"""Broker parsing must enforce correct profile, issuer, scope and key."""
import base64
import json
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from research.phase18.key_broker import (
    decode_packet, canonical, keyid, ProtocolError,
    PROFILE_SCOPES, SOURCE_TYPES,
)


def packet(value):
    data = canonical(value)
    return json.dumps({"message": base64.b64encode(data).decode("ascii")}).encode(), data


class RoleBrokerProfiles(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def message(self, profile, role="X", msg_type="Acceptance"):
        issuer = "executor" if profile == "PAY-1" else "pilot-" + role.lower()
        header = {"proto": "ZJJ-AAP", "version": "2.6", "profile": profile,
                  "alg": "Ed25519", "type": msg_type, "issuer": issuer,
                  "kid": keyid(self.pub)}
        body = {"scope": PROFILE_SCOPES[profile], "payload": {},
                "refs": [], "deps": []}
        return ["ZJJ-SIG-v1", header, body]

    def assert_allowed(self, role, value):
        raw, expected = packet(value)
        self.assertEqual(decode_packet(raw, role, self.pub), expected)

    def assert_denied(self, role, value):
        with self.assertRaises(ProtocolError):
            decode_packet(packet(value)[0], role, self.pub)

    def test_ind_and_med_and_pay_x_accepted_with_real_keys(self):
        for profile in PROFILE_SCOPES:
            with self.subTest(profile=profile):
                self.assert_allowed("X", self.message(profile))

    def test_cross_profile_scope_rejected(self):
        msg = self.message("MED-DEMO-1")
        msg[2]["scope"] = PROFILE_SCOPES["IND-DEMO-1"]
        self.assert_denied("X", msg)

    def test_wrong_role_and_kid_rejected(self):
        msg = self.message("IND-DEMO-1")
        self.assert_denied("G", msg)
        msg[1]["kid"] = keyid(b"x" * 32)
        self.assert_denied("X", msg)

    def test_result_only_for_pay_x(self):
        self.assert_allowed("X", self.message("PAY-1", msg_type="Result"))
        self.assert_denied("X", self.message("IND-DEMO-1", msg_type="Result"))
        self.assert_denied("X", self.message("MED-DEMO-1", msg_type="Result"))

    def test_pay_unenrolled_issuer_rejected(self):
        # Role bindings are deliberately NOT guessed for PAY H/G/U/V.
        self.assert_denied("H", self.message("PAY-1", role="H", msg_type="IssueRequest"))

    def test_ind_and_med_source_attestations(self):
        for profile, source_type in SOURCE_TYPES.items():
            att = {"issuer": "pilot-e", "kid": keyid(self.pub),
                   "iat": "100", "exp": "200"}
            self.assert_allowed("E", ["ZJJ-SOURCE-v1", "2.6", profile,
                                      source_type, PROFILE_SCOPES[profile], {}, att])

    def test_control_clock_scope_for_all_profiles(self):
        for profile in PROFILE_SCOPES:
            claim = {"profile": profile, "scope": PROFILE_SCOPES[profile],
                     "operation_id": "op", "purpose": "PREPARE",
                     "sequence": "1", "lo": "100", "hi": "100"}
            self.assert_allowed("C", ["ZJJ-C-TRUSTED-CLOCK-RESEARCH-v1", claim])
            altered = dict(claim, scope=PROFILE_SCOPES["PAY-1" if profile != "PAY-1" else "MED-DEMO-1"])
            self.assert_denied("C", ["ZJJ-C-TRUSTED-CLOCK-RESEARCH-v1", altered])

    def test_unknown_domain_denied(self):
        self.assert_denied("C", ["ZJJ-UNAPPROVED-v1", {"profile": "PAY-1"}])


if __name__ == "__main__":
    unittest.main()
