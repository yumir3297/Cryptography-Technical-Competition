"""Independent boundary vectors for the candidate codec, not R2 conformance."""
import importlib.util
import unittest
import copy


class CandidateCodecTests(unittest.TestCase):
    def test_noncanonical_duplicate_and_invalid_scalar_rejected(self):
        from codec import parse, CheckError
        for raw in (b'{"a":"x","a":"y"}', b'{ "a":"x"}', b'{"a":1}',
                    b'{"a":null}', b'{"a":"\\ud800"}', b'\xef\xbb\xbf{}', b'{"a":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(CheckError):
                parse(raw)

    def test_canonical_unicode_and_domain_separation(self):
        from codec import enc, parse, digest
        value = {'b': ['hello', '\U0001f642', True], 'a': '\n'}
        self.assertEqual(parse(enc(value)), value)
        self.assertNotEqual(digest(['ZJJ-TIME-SIG-PROPOSED-v2', value]), digest(['ZJJ-SIG-v1', value]))

    def test_base64_alias_and_padding_rejected(self):
        from codec import b64, unb64, CheckError
        s = b64(bytes(32))
        self.assertEqual(unb64(s, 32), bytes(32))
        for alias in (s + '=', s[:-1] + 'B', s + '\n'):
            with self.assertRaises(CheckError):
                unb64(alias, 32)

    def test_strict_point_rejections(self):
        from codec import point_ok, P
        self.assertFalse(point_ok(bytes(32)))  # order-four point
        self.assertFalse(point_ok(bytes([1]) + bytes(31)))  # identity
        self.assertFalse(point_ok((P + 1).to_bytes(32, 'little')))

    def test_real_signature_tamper_wrong_key_and_noncanonical_s(self):
        from codec import b64, key_id, to_sign, verify_signature, CheckError, unb64, L
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        sk = Ed25519PrivateKey.from_private_bytes(bytes([17])*32)  # PUBLIC TEST KEY ONLY
        pk = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        obj = {'protected': {'kid': key_id(pk)}, 'body': {'x': 'test'}}
        obj['sig'] = b64(sk.sign(to_sign(obj)))
        self.assertTrue(verify_signature(obj, pk))
        altered = copy.deepcopy(obj)
        altered['body']['x'] = 'tampered'
        with self.assertRaises(CheckError):
            verify_signature(altered, pk)
        s = unb64(obj['sig'], 64)
        altered = copy.deepcopy(obj)
        altered['sig'] = b64(s[:32] + L.to_bytes(32, 'little'))
        with self.assertRaises(CheckError):
            verify_signature(altered, pk)
        with self.assertRaises(CheckError):
            verify_signature(obj, bytes([1]) + bytes(31))


if __name__ == '__main__':
    unittest.main()
