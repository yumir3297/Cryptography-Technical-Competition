"""W-owned request mapping and immutable full-request outbox; trusted host only."""
import copy
import json
import os
from competition.core.trusted_state import enc
from competition.support.wire import b64, digest, require

APPROVAL_FIELDS = frozenset(('reviews', 'authorization', 'issue', 'permit',
                             'challenge_request', 'challenge', 'proof'))

def request_ref(profile, op):
    return digest(['COMP-APP-CALL-v1', profile, op])

class RequestStore:
    def __init__(self, state):
        self.state = state
        with state.db() as c:
            require(c.execute("SELECT 1 FROM sqlite_master WHERE name='w_operation'").fetchone()
                    is not None, 'W_NOT_INITIALIZED')
            c.execute('''CREATE TABLE IF NOT EXISTS app_request(
                request_key TEXT PRIMARY KEY, proposal_ref TEXT NOT NULL,
                oid TEXT NOT NULL UNIQUE, construction TEXT NOT NULL,
                construction_ref TEXT NOT NULL, full_op TEXT, request_ref TEXT)''')

    def _row(self, c, key):
        return c.execute('SELECT * FROM app_request WHERE request_key=?', (key,)).fetchone()

    @staticmethod
    def _construction(row):
        value = json.loads(row['construction'])
        require(digest(['ZJJ-APP-CONSTRUCTION-v1', value]) == row['construction_ref']
                and value['action']['operation_id'] == row['oid'], 'OUTBOX_INTEGRITY')
        return value

    def _existing(self, c, key, proposal_ref):
        row = self._row(c, key)
        if row is None:
            return None
        require(row['proposal_ref'] == proposal_ref, 'REQUEST_CONFLICT')
        return self._construction(row)

    @staticmethod
    def _new_id(c):
        require(c.in_transaction, 'AUTH_TRANSACTION_REQUIRED')
        for _ in range(8):
            oid = b64(os.urandom(16))
            if not c.execute('SELECT 1 FROM app_request WHERE oid=?', (oid,)).fetchone() and not c.execute(
                    'SELECT 1 FROM w_operation WHERE oid=?', (oid,)).fetchone():
                return oid
        require(False, 'ID_ALLOCATION_FAILED')

    def _insert(self, c, proposal_ref, construction):
        require(c.in_transaction, 'AUTH_TRANSACTION_REQUIRED')
        c.execute('INSERT INTO app_request VALUES(?,?,?,?,?,NULL,NULL)', (
            construction['key'], proposal_ref, construction['action']['operation_id'],
            enc(construction), digest(['ZJJ-APP-CONSTRUCTION-v1', construction])))

    def _check_op(self, row, op):
        construction = self._construction(row)
        template = construction['approval_request']
        require(type(op) is dict and all(op.get(k) == v for k, v in template.items()),
                'FROZEN_ACTION_CONFLICT')
        require(set(op) == set(template) | APPROVAL_FIELDS, 'APPROVAL_FIELDS')
        return construction

    def _freeze(self, c, key, profile, op):
        """Called only after the orchestrator's current full-chain verification."""
        row = self._row(c, key)
        require(row is not None, 'REQUEST_UNKNOWN')
        self._check_op(row, op)
        ref = request_ref(profile, op)
        if row['full_op'] is not None:
            require(row['request_ref'] == ref and json.loads(row['full_op']) == op,
                    'FROZEN_REQUEST_CONFLICT')
        else:
            c.execute('UPDATE app_request SET full_op=?,request_ref=? WHERE request_key=?',
                      (enc(op), ref, key))
        return ref

    def load(self, key):
        """Internal host recovery, not an unauthenticated Agent lookup endpoint."""
        with self.state.db() as c:
            row = self._row(c, key)
        require(row is not None, 'REQUEST_UNKNOWN')
        require(row['full_op'] is not None, 'APPROVAL_PENDING')
        op = json.loads(row['full_op'])
        construction = self._check_op(row, op)
        profile = construction['approval_request']['basis']['profile']
        require(request_ref(profile, op) == row['request_ref'], 'OUTBOX_INTEGRITY')
        return {'op': copy.deepcopy(op), 'request_ref': row['request_ref']}
