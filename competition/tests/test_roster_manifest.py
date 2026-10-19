"""The roster manifest: public keys in, a working roster out.

Three claims:

* a manifest line is an endpoint's own keygen output, and every fact in it that
  can be re-derived is -- the key id, the curve point, the purposes -- so an
  endpoint can propose a name but never widen what it may do;
* the roster built from those lines carries the *same* actors the controlled
  bootstrap seeds, so every signature the black box asks for comes back from the
  endpoint byte for byte, and the black box cannot tell the difference;
* the transport really carries one request out and one answer back, over the same
  line protocol the client host serves.
"""
import copy
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from competition.client.host import answer, serve_unix
from competition.client.keys import generate, propose_purposes, propose_subject
from competition.client.signer import CHAIN_DOMAIN, SIGN_CALL_DOMAIN, RoleSigner, role_key_path
from competition.core.signer_broker import ScopedSignerBroker
from competition.core.trusted_state import PROFILE_SCOPES, PublicActor
from competition.server.roster import (
    ALIASES, ENTRY_FIELDS, SocketTransport, actors, describe, owner_purposes, read_entry,
    read_manifest,
)
from competition.support.wire import ProtocolError, b64, canonical, raw, sortset, strict_verify

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)


class ManifestEntryTests(unittest.TestCase):
    """One line, checked as arithmetic rather than taken on the endpoint's word."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.keys = Path(cls.work.name)
        cls.base = generate(cls.keys, 'IND-DEMO-1', 'U')

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def entry(self, **overrides):
        line = dict(self.base)
        line.update(overrides)
        return line

    def reject(self, value, code):
        with self.assertRaises(ProtocolError) as caught:
            read_entry(value)
        self.assertEqual(caught.exception.code, code)

    def test_a_keygen_line_is_a_manifest_line(self):
        entry = read_entry(self.entry())
        actor = PublicActor(entry.subject, entry.kid, entry.pub, frozenset(), frozenset(entry.purposes))
        self.assertEqual(actor.name, propose_subject('IND-DEMO-1', 'U'))
        self.assertEqual(list(entry.purposes), owner_purposes('U'))
        self.assertEqual(list(entry.purposes), propose_purposes('U'))

    def test_the_key_id_is_re_derived_not_read(self):
        self.reject(self.entry(kid=b64(bytes(32))), 'ROSTER_KEY')

    def test_the_public_key_must_be_a_real_curve_point(self):
        self.reject(self.entry(public_key=b64(bytes(32))), 'PUBLIC_KEY_POINT')
        self.reject(self.entry(public_key=b64(b'short')), 'BASE64')

    def test_an_alias_cannot_widen_its_own_purposes(self):
        self.reject(self.entry(purposes=owner_purposes('U') + ['SOURCE']), 'ROSTER_PURPOSES')
        self.reject(self.entry(purposes=[]), 'ROSTER_PURPOSES')

    def test_the_subject_must_be_a_well_formed_name(self):
        self.reject(self.entry(subject='Not An Id'), 'ROSTER_SUBJECT')

    def test_the_role_and_field_set_are_exact(self):
        self.reject(self.entry(role='C'), 'ROSTER_ROLE')
        missing = self.entry()
        del missing['subject']
        self.reject(missing, 'ROSTER_FIELDS')
        self.reject(self.entry(extra=1), 'ROSTER_FIELDS')
        self.reject(self.entry(profile='PAY-2'), 'ROSTER_PROFILE')

    def test_the_cross_profile_worker_carries_no_profile(self):
        line = generate(self.keys, None, 'worker')
        self.assertEqual(set(line), ENTRY_FIELDS)
        self.assertEqual(read_entry(line).profile, None)
        self.reject({**line, 'profile': 'PAY-1'}, 'ROSTER_FIELDS')


class ManifestFileTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.work.cleanup)
        self.keys = Path(self.work.name) / 'keys'
        self.keys.mkdir()
        self.path = Path(self.work.name) / 'roster.jsonl'

    def write(self, lines):
        self.path.write_text('\n'.join(json.dumps(line) for line in lines) + '\n', encoding='utf-8')
        return self.path

    def test_a_manifest_is_the_keygen_lines_in_order(self):
        lines = [generate(self.keys, 'PAY-1', role) for role in ALIASES]
        lines.append(generate(self.keys, None, 'worker'))
        lines.append(generate(self.keys, 'PAY-1', 'tool'))
        entries = read_manifest(self.write(lines))
        self.assertEqual(len(entries), len(ALIASES) + 2)
        self.assertEqual([row['role'] for row in describe(entries)],
                         ['E', 'G', 'H', 'U', 'V', 'X', 'tool', 'worker'])

    def test_a_duplicate_endpoint_is_refused(self):
        line = generate(self.keys, 'PAY-1', 'U')
        twice = [line, {**line, 'subject': 'another-u'}]
        with self.assertRaises(ProtocolError) as caught:
            read_manifest(self.write(twice))
        self.assertEqual(caught.exception.code, 'ROSTER_DUPLICATE')

    def test_a_malformed_line_is_refused(self):
        self.path.write_text('not json\n', encoding='utf-8')
        with self.assertRaises(ProtocolError) as caught:
            read_manifest(self.path)
        self.assertEqual(caught.exception.code, 'ROSTER_MANIFEST')

    def test_a_line_with_the_wrong_fields_is_refused(self):
        self.path.write_text('{"role": "U"}\n', encoding='utf-8')
        with self.assertRaises(ProtocolError) as caught:
            read_manifest(self.path)
        self.assertEqual(caught.exception.code, 'ROSTER_FIELDS')

    def test_blank_lines_are_skipped(self):
        line = generate(self.keys, 'PAY-1', 'U')
        self.path.write_text('\n' + json.dumps(line) + '\n\n', encoding='utf-8')
        self.assertEqual(len(read_manifest(self.path)), 1)


class ProxyRosterTests(unittest.TestCase):
    """The roster the black box reads, built only from published public keys."""

    @classmethod
    def setUpClass(cls):
        from competition.profiles.w_seed import initialize
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        cls.trusted = initialize(Path(cls.work.name) / 'w')

    @classmethod
    def tearDownClass(cls):
        cls.trusted.close()
        cls.work.cleanup()
        for name, value in cls.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def manifest(self):
        """A manifest line per seeded alias, carrying only published facts."""
        lines = []
        for profile, roster in self.trusted.actors.items():
            for alias, actor in roster.items():
                lines.append({'profile': profile, 'role': alias, 'subject': actor.name,
                              'public_key': b64(actor.pub), 'kid': actor.kid,
                              'purposes': sortset(list(actor.purposes))})
        return [read_entry(line) for line in lines]

    def proxy_roster(self):
        """The seeded key files stand in for the endpoints that would hold them."""
        return actors(self.manifest(),
                      lambda entry: _LocalTransport(self.trusted.folder, entry.profile, entry.role))

    def test_each_proxy_actor_is_the_actor_the_black_box_knows(self):
        roster = self.proxy_roster()
        for profile, entries in roster.items():
            for alias, actor in entries.items():
                with self.subTest(profile=profile, alias=alias):
                    public = PublicActor.from_actor(actor)
                    self.assertEqual(public.kid, self.trusted.actors[profile][alias].kid)
                    self.assertEqual(public.pub, self.trusted.actors[profile][alias].pub)
                    self.assertEqual(public.name, self.trusted.actors[profile][alias].name)
                    self.assertEqual(public.purposes, self.trusted.actors[profile][alias].purposes)

    def test_every_chain_signature_comes_back_from_the_endpoint_byte_for_byte(self):
        roster = self.proxy_roster()
        fields = (('reviews', 'V'), ('authorization', 'U'), ('issue', 'H'),
                  ('permit', 'G'), ('challenge', 'X'))
        for profile in PROFILE_SCOPES:
            op = self.trusted.operations[profile]
            for name, alias in fields:
                messages = op[name] if name == 'reviews' else [op[name]]
                for message in messages:
                    with self.subTest(profile=profile, field=name):
                        signed = roster[profile][alias].key.sign(
                            canonical([CHAIN_DOMAIN, message['protected'], message['body']]))
                        self.assertEqual(b64(signed), message['sig'])

    def test_the_black_box_broker_signs_through_the_proxies(self):
        profile = 'MED-DEMO-1'
        roster = self.proxy_roster()
        broker = ScopedSignerBroker(self.trusted.store, roster)
        op = self.trusted.fork_operation(profile)
        unsigned = {k: copy.deepcopy(op['authorization'][k]) for k in ('protected', 'body')}
        claim = broker.challenge(profile, 'U', unsigned, op['action'])
        proof = {'claim': claim,
                 'signature': b64(roster[profile]['U'].key.sign(
                     canonical([SIGN_CALL_DOMAIN, claim])))}
        message = broker.sign(profile, 'U', unsigned, op['action'], caller_proof=proof)
        self.assertEqual(message['sig'], op['authorization']['sig'])
        who = self.trusted.actors[profile]['U']
        strict_verify(who.pub, raw(message['sig'], 64),
                      canonical(['ZJJ-SIG-v1', message['protected'], message['body']]))


class _LocalTransport:
    """The line protocol, in process: the same ``answer`` the socket host uses."""

    def __init__(self, folder, profile, role):
        self.signer = RoleSigner.from_directory(folder, profile, role)

    def request(self, message):
        return answer(json.dumps(message, sort_keys=True).encode('utf-8') + b'\n', self.signer)


class SocketTransportTests(unittest.TestCase):
    """One request out, one answer back, over the endpoint's own socket."""

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.work.cleanup)
        generate(self.work.name, 'PAY-1', 'V')

    def serve(self, path):
        signer = RoleSigner.from_directory(self.work.name, 'PAY-1', 'V')
        outcome = []
        thread = threading.Thread(target=_capture, args=(outcome, serve_unix, path, signer),
                                  daemon=True)
        thread.start()
        self.addCleanup(thread.join, 30)
        deadline = time.monotonic() + 10
        while not path.exists():
            self.assertLess(time.monotonic(), deadline, 'signing socket never appeared')
            time.sleep(0.02)
        return outcome

    def test_the_transport_carries_one_signing_request(self):
        path = Path(self.work.name) / 'V.sign.sock'
        self.serve(path)
        signer = RoleSigner.from_directory(self.work.name, 'PAY-1', 'V')
        data = canonical([CHAIN_DOMAIN, {'profile': 'PAY-1'}, {'scope': PROFILE_SCOPES['PAY-1']}])
        answer_body = SocketTransport(path).request({'op': 'raw', 'profile': 'PAY-1',
                                                    'role': 'V', 'data': b64(data)})
        strict_verify(signer.public, raw(answer_body['signature'], 64), data)
        self.assertEqual(answer_body['kid'], signer.kid)

    def test_a_dead_endpoint_fails_the_call(self):
        with self.assertRaises(OSError):
            SocketTransport(Path(self.work.name) / 'nobody.sock').request(
                {'op': 'raw', 'profile': 'PAY-1', 'role': 'V', 'data': ''})


def _capture(sink, call, *args):
    try:
        call(*args)
    except BaseException as exc:  # noqa: BLE001 - the test asserts what came out
        sink.append(exc)


if __name__ == '__main__':
    unittest.main()
