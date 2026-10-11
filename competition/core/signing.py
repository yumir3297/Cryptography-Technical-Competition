"""Restricted local C/X subprocesses. Same-user bootstrap is trusted, not an HSM."""
import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from research.reference_executor.wire import b64, raw, canonical, require, ProtocolError, digest, keyid
from competition.core.event_clock import DOMAIN, STAGES
from research.phase18.key_broker import PROFILE_SCOPES


class RestrictedProcess:
    def __init__(self, role, key_file, database):
        self.role = role
        self.lock = threading.Lock()
        self.answers = queue.Queue()
        self.proc = subprocess.Popen([sys.executable, '-m', __name__, role, str(key_file), str(database)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1)
        def read():
            for line in self.proc.stdout:
                self.answers.put(line)
            self.answers.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        self.info = self._answer()

    def _answer(self, timeout=5):
        try:
            line = self.answers.get(timeout=timeout)
            require(line is not None, 'SIGNER_UNAVAILABLE')
            result = json.loads(line)
            require('error' not in result, result.get('error', 'SIGNER_UNAVAILABLE'))
            return result
        except (queue.Empty, OSError, ValueError) as exc:
            self.close()
            raise ProtocolError('SIGNER_UNAVAILABLE') from exc

    def call(self, payload):
        with self.lock:
            require(self.proc.poll() is None, 'SIGNER_UNAVAILABLE')
            try:
                self.proc.stdin.write(json.dumps(payload) + '\n')
                self.proc.stdin.flush()
            except (OSError, ValueError) as exc:
                raise ProtocolError('SIGNER_UNAVAILABLE') from exc
            return self._answer(timeout=1.5)

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        if hasattr(self, 'reader'):
            self.reader.join(timeout=5)
        for pipe in (self.proc.stdin, self.proc.stdout):
            if pipe:
                pipe.close()


class ClockClient(RestrictedProcess):
    def __init__(self, key_file, database):
        super().__init__('C', key_file, database)
        self.instance_id = self.info['instance_id']

    def sample(self, profile, scope, operation_id, stage, request_ref):
        try:
            return self.call({'profile': profile, 'scope': scope, 'operation_id': operation_id, 'stage': stage, 'request_ref': request_ref})
        except ProtocolError as exc:
            if exc.code == 'SIGNER_UNAVAILABLE':
                raise ProtocolError('CLOCK_UNKNOWN') from exc
            raise


class ReceiptSigner(RestrictedProcess):
    def __init__(self, key_file, database):
        super().__init__('X', key_file, database)

    def sign_committed(self, operation_id, acceptance_ref):
        return self.call({'operation_id': operation_id, 'acceptance_ref': acceptance_ref})


def worker(role, key_file, database):
    sk = Ed25519PrivateKey.from_private_bytes(Path(key_file).read_bytes())
    pub = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    instance = b64(os.urandom(16))
    print(json.dumps({'kid': keyid(pub), 'public_key': b64(pub), 'instance_id': instance}), flush=True)
    origin_wall, origin_mono = time.time_ns(), time.monotonic_ns()
    if role == 'C':
        with closing(sqlite3.connect(database)) as c:
            c.execute('CREATE TABLE IF NOT EXISTS source_sequence(id INTEGER PRIMARY KEY CHECK(id=1),seq INTEGER NOT NULL)')
            c.execute('INSERT OR IGNORE INTO source_sequence VALUES(1,0)')
            c.commit()
    for line in sys.stdin:
        try:
            value = json.loads(line)
            if role == 'C':
                require(set(value) == {'profile', 'scope', 'operation_id', 'stage', 'request_ref'}, 'CLOCK_FIELDS')
                require(value['profile'] in PROFILE_SCOPES and value['scope'] == PROFILE_SCOPES[value['profile']] and value['stage'] in STAGES, 'CLOCK_BINDING')
                with closing(sqlite3.connect(database, isolation_level=None)) as c:
                    c.execute('BEGIN IMMEDIATE')
                    seq = c.execute('SELECT seq FROM source_sequence WHERE id=1').fetchone()[0] + 1
                    c.execute('UPDATE source_sequence SET seq=? WHERE id=1', (seq,))
                    c.execute('COMMIT')
                wall, mono = time.time_ns(), time.monotonic_ns()
                healthy = abs((wall - origin_wall) - (mono - origin_mono)) <= 12_500_000
                cl = {**value, 'provider_id': 'local-c', 'epoch': '1', 'instance_id': instance, 'sequence': str(seq), 'wall_ns': str(wall), 'monotonic_ns': str(mono), 'lo': str(wall // 1_000_000_000), 'hi': str(wall // 1_000_000_000), 'healthy': healthy}
                result = {'claim': cl, 'signature': b64(sk.sign(canonical([DOMAIN, cl])))}
            elif role == 'X':
                require(set(value) == {'operation_id', 'acceptance_ref'}, 'SIGNER_REQUEST')
                uri = Path(database).resolve().as_uri() + '?mode=ro'
                with closing(sqlite3.connect(uri, uri=True)) as c:
                    row = c.execute('SELECT frozen_json FROM comp_acceptance WHERE operation_id=?', (value['operation_id'],)).fetchone()
                    require(row is not None, 'NOT_COMMITTED')
                    frozen = json.loads(row[0]); core = frozen['core']; h, body = core['protected'], core['body']
                    require(frozen['acceptance_ref'] == value['acceptance_ref'] and h['kid'] == keyid(pub), 'SIGNER_BINDING')
                    now = time.time_ns() // 1_000_000_000
                    require(int(body['iat']) <= now < int(body['exp']), 'EXPIRED')
                    scope = body['scope']; rk = [scope[k] for k in ('domain', 'tenant', 'scenario')] + [h['issuer'], 'EXECUTOR']
                    for ns, key in (('KEY', [h['kid']]), ('ROLE', rk)):
                        credential = c.execute('SELECT record,active FROM current_row WHERE namespace=? AND key=?', (ns, json.dumps(key, sort_keys=True, separators=(',', ':')))).fetchone()
                        require(credential is not None and credential[1] == 1, 'REVOKED')
                        grant = json.loads(credential[0])['value']
                        require(grant['subject'] == h['issuer'] and int(grant['iat']) <= now < int(grant['exp']), 'NO_ROLE')
                        if ns == 'KEY':
                            require(grant['public_key'] == b64(pub) and 'Acceptance' in grant['purposes'], 'NO_ROLE')
                    result = {'signature': b64(sk.sign(canonical(['ZJJ-SIG-v1', h, body]))), 'generated_wall_ns': str(time.time_ns())}
            else:
                raise ProtocolError('SIGNER_ROLE')
            print(json.dumps(result), flush=True)
        except Exception as exc:
            print(json.dumps({'error': exc.code if isinstance(exc, ProtocolError) else 'SIGNER_UNAVAILABLE'}), flush=True)


if __name__ == '__main__':
    worker(*sys.argv[1:])
