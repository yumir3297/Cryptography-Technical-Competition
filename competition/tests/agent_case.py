"""A real trusted stack for the agent-boundary tests.

Not a test module: it starts the same served faces the deployment runs, with real
keys and real signatures, so the gateway's caller never talks to a stub.  The
agent tests are serial like the existing caller tests; the endpoint faces use the
roster's deterministic ports.
"""
import json
import os
import tempfile
from pathlib import Path

import competition.caller.flow as caller_flow

from competition.agent.app import make_app as gateway_app
from competition.agent.identity import enroll
from competition.agent.journal import Journal
from competition.agent.service import GatewayService
from competition.client.signer import RoleSigner
from competition.client.web import make_app as endpoint_app
from competition.profiles.w_seed import initialize
from competition.server.service import TrustedService
from competition.server.signer import LocalSigner
from competition.tests.helpers import Face, free_port
from competition.web.app import make_app as entry_app
from competition.web.session import Sessions, read_callers

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)

AGENT_TOKEN = 'agent-test-token'
INTERNAL_TOKEN = 'internal-test-token'


class AgentStack:
    """One initialized run, the endpoint faces the flow needs, the entry and the gateway."""

    def __init__(self, *, poll_interval=60.0, faces=None):
        faces = faces or (('PAY-1', 'H'), (None, 'worker'))
        self.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.trusted = initialize(Path(self.work.name) / 'w')
        self.faces = []
        # The caller resolves an endpoint URL from the roster's deterministic
        # port.  A test does not own ports 9100-9118, so it patches that one
        # function for the duration of the stack and serves the faces on free
        # ports instead.  Production code is untouched.
        self._original_endpoint_port = caller_flow.endpoint_port
        self._ports = {key: free_port() for key in faces}

        def port_of(profile, role):
            # The worker is one capability across profiles; the production
            # function ignores the profile for it too.
            if role == 'worker':
                return self._ports[(None, 'worker')]
            return self._ports[(profile, role)]

        try:
            caller_flow.endpoint_port = port_of
            for profile, role in faces:
                self.faces.append(Face(
                    endpoint_app(RoleSigner.from_directory(self.trusted.folder,
                                                           profile, role)),
                    port=self._ports[(profile, role)]))
            self.callers = Path(self.work.name) / 'callers'
            self.agent_key, self.agent_line = enroll(self.callers, 'zjj-agent', ['H'],
                                                     self.callers)
            self.operator_key, _ = enroll(self.callers, 'zjj-operator', ['H'],
                                          self.callers)
            self.executor_key, _ = enroll(self.callers, 'zjj-executor', ['worker'],
                                          self.callers)
            self.entry = Face(entry_app(
                TrustedService(self.trusted, LocalSigner(self.trusted)),
                Sessions(read_callers(self.callers / 'callers.jsonl'))))
            self.journal = Journal(Path(self.work.name) / 'agent.sqlite', now=self.now)
            self.service = GatewayService(self.entry.base, self.agent_key,
                                          'http://127.0.0.1', self.journal, now=self.now)
            self.service.start()
            self.gateway = Face(gateway_app(self.service, agent_token=AGENT_TOKEN,
                                            internal_token=INTERNAL_TOKEN,
                                            poll_interval=poll_interval))
        except BaseException:
            self.close()
            raise

    @staticmethod
    def now():
        import time
        return time.time()

    def caller(self, name):
        from competition.caller.flow import Caller
        key = {'operator': self.operator_key, 'executor': self.executor_key,
               'agent': self.agent_key}[name]
        caller = Caller(self.entry.base, key, 'http://127.0.0.1')
        caller.start()
        return caller

    def await_submission(self, handle, timeout=60.0):
        """Wait for the background submitter to resolve a handle.

        The submit is carried off the request thread, so a test that needs the
        operation id waits for it the way a client waits for the pushed notice.
        Returns the operation id, or raises on the two endings that have none.
        """
        import time
        deadline = time.monotonic() + timeout
        while True:
            row = self.journal.submission_by_digest(handle)
            if row is not None:
                if row['state'] == 'SUBMITTED' and row.get('operation_id'):
                    return row['operation_id']
                if row['state'] in ('SUBMIT_UNKNOWN', 'DENIED'):
                    raise AssertionError('submission ended %s (%s)'
                                         % (row['state'], row.get('detail')))
            if time.monotonic() >= deadline:
                raise AssertionError('submission %s did not resolve' % handle)
            time.sleep(0.05)

    def close(self):
        for name in ('gateway', 'entry'):
            face = getattr(self, name, None)
            if face is not None:
                face.close()
        for face in getattr(self, 'faces', []):
            face.close()
        original = getattr(self, '_original_endpoint_port', None)
        if original is not None:
            caller_flow.endpoint_port = original
        journal = getattr(self, 'journal', None)
        if journal is not None:
            journal.close()
        trusted = getattr(self, 'trusted', None)
        if trusted is not None:
            trusted.close()
        work = getattr(self, 'work', None)
        if work is not None:
            work.cleanup()
