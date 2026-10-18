"""One W-owned request mapping with immutable authority and versioned short proofs."""
import copy
import json
import os
from competition.core.trusted_state import enc
from competition.support.wire import b64, digest, require

APPROVAL_FIELDS = frozenset(('reviews', 'authorization', 'issue', 'permit',
                             'challenge_request', 'challenge', 'proof'))
SHORT_FIELDS = frozenset(('challenge_request', 'challenge', 'proof'))

def short_tokens(op):
    """Remember all short-chain identifiers, not just the last packet digest."""
    try:
        ids = [op[k]['body']['id'] for k in ('challenge_request','challenge','proof')]
        challenge = op['challenge']['body']['payload']
        values = ['id:'+v for v in ids] + ['session:'+challenge['session_id'],
            'nonce:'+challenge['nonce'],
            'attempt:'+op['challenge_request']['body']['payload']['attempt_id']]
        require(len(set(values)) == len(values), 'SUBMISSION_REPLAY')
        return values
    except (KeyError,TypeError):
        require(False, 'INPUT_FIELDS')

def request_ref(profile, op):
    return digest(['COMP-APP-CALL-v1', profile, op])

class RequestStore:
    def __init__(self, state):
        self.state = state
        with state.tx() as c:
            require(c.execute("SELECT 1 FROM sqlite_master WHERE name='w_operation'").fetchone()
                    is not None, 'W_NOT_INITIALIZED')
            c.execute('''CREATE TABLE IF NOT EXISTS app_request(
                request_key TEXT PRIMARY KEY, proposal_ref TEXT NOT NULL,
                oid TEXT NOT NULL UNIQUE, construction TEXT NOT NULL,
                construction_ref TEXT NOT NULL, full_op TEXT, request_ref TEXT)''')
            columns = {r[1] for r in c.execute('PRAGMA table_info(app_request)')}
            if 'submission_version' not in columns:
                c.execute('ALTER TABLE app_request ADD COLUMN submission_version INTEGER NOT NULL DEFAULT 0')
            if 'submission_history' not in columns:
                c.execute("ALTER TABLE app_request ADD COLUMN submission_history TEXT NOT NULL DEFAULT '[]'")
            # Upgrade only authentic V1 saved rows. No new allocations or W facts.
            for row in c.execute('SELECT * FROM app_request WHERE full_op IS NOT NULL AND submission_version=0').fetchall():
                op = json.loads(row['full_op'])
                construction = self._check_op(row, op)
                profile = construction['approval_request']['basis']['profile']
                require(request_ref(profile, op) == row['request_ref'], 'OUTBOX_INTEGRITY')
                history = [{'ref':row['request_ref'],'tokens':short_tokens(op)}]
                c.execute('UPDATE app_request SET submission_version=1,submission_history=? WHERE request_key=?',
                          (enc(history),row['request_key']))

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
        c.execute('INSERT INTO app_request(request_key,proposal_ref,oid,construction,construction_ref,full_op,request_ref) VALUES(?,?,?,?,?,NULL,NULL)', (
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
            self._save(c, row, profile, op, ref, [])
        return ref

    @staticmethod
    def _history(row, op):
        history = json.loads(row['submission_history'])
        require(type(history) is list and len(history) == row['submission_version'] and
                bool(history) and history[-1] == {'ref':row['request_ref'],'tokens':short_tokens(op)},
                'OUTBOX_INTEGRITY')
        return history

    def _save(self, c, row, profile, op, ref, history):
        history = history + [{'ref':ref,'tokens':short_tokens(op)}]
        changed = c.execute('''UPDATE app_request SET full_op=?,request_ref=?,submission_version=?,
            submission_history=? WHERE request_key=? AND submission_version=?''',
            (enc(op),ref,len(history),enc(history),row['request_key'],row['submission_version']))
        require(changed.rowcount == 1, 'SUBMISSION_VERSION_CONFLICT')
        c.execute('INSERT INTO a_journal(kind,profile,operation_id,blob) VALUES(?,?,?,?)',
            ('APP_SUBMISSION',profile,row['oid'],enc({'version':str(len(history)),
             'request_ref':ref,'op':op})))

    def _replacement(self, c, key, profile, op, version, previous_ref):
        """Validate CAS and immutable authority; caller still verifies the chain/time."""
        require(type(version) is int and version >= 1 and type(previous_ref) is str,
                'SUBMISSION_VERSION_CONFLICT')
        row = self._row(c,key); require(row is not None,'REQUEST_UNKNOWN')
        self._check_op(row,op); require(row['full_op'] is not None,'APPROVAL_PENDING')
        original = json.loads(row['full_op']); history = self._history(row,original)
        require(not c.execute('SELECT 1 FROM w_operation WHERE profile=? AND oid=?',
                (profile,row['oid'])).fetchone(),'ALREADY_ACCEPTED')
        require({k:v for k,v in original.items() if k not in SHORT_FIELDS} ==
                {k:v for k,v in op.items() if k not in SHORT_FIELDS},'FROZEN_AUTHORITY_CONFLICT')
        ref = request_ref(profile,op)
        # A lost response can retry its exact committed transition, never an older one.
        if row['request_ref'] == ref:
            require((version == row['submission_version'] and previous_ref == ref) or
                (version == row['submission_version']-1 and history[-2]['ref'] == previous_ref),
                'SUBMISSION_VERSION_CONFLICT')
            return row,history,ref,False
        require(version == row['submission_version'] and previous_ref == row['request_ref'],
                'SUBMISSION_VERSION_CONFLICT')
        require(ref not in {x['ref'] for x in history},'SUBMISSION_REPLAY')
        tokens = short_tokens(op)
        require(not set(tokens) & {token for item in history for token in item['tokens']},
                'SUBMISSION_REPLAY')
        return row,history,ref,True

    def check_current(self, c, profile, op):
        row = c.execute('SELECT * FROM app_request WHERE oid=?',
                        (op['action']['operation_id'],)).fetchone()
        require(row is not None,'ALLOCATION_UNKNOWN')
        construction = self._check_op(row,op)
        require(construction['approval_request']['basis']['profile'] == profile,'ALLOCATION_BINDING')
        require(row['full_op'] is not None and row['request_ref'] == request_ref(profile,op)
                and json.loads(row['full_op']) == op,'SUBMISSION_SUPERSEDED')
        self._history(row,op)

    def _loaded(self,row):
        require(row is not None, 'REQUEST_UNKNOWN')
        require(row['full_op'] is not None, 'APPROVAL_PENDING')
        op = json.loads(row['full_op'])
        construction = self._check_op(row, op)
        profile = construction['approval_request']['basis']['profile']
        require(request_ref(profile, op) == row['request_ref'], 'OUTBOX_INTEGRITY')
        self._history(row,op)
        return {'op':copy.deepcopy(op),'request_ref':row['request_ref'],
                'version':row['submission_version']}

    def load(self, key):
        """Internal host recovery, not an unauthenticated Agent lookup endpoint."""
        with self.state.db() as c:
            row = self._row(c, key)
        return self._loaded(row)
