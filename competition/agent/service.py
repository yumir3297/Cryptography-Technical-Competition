"""The agent-facing gateway: propose, read, and remember; never approve or execute.

The service is the only object the MCP tools touch.  It owns one caller
credential, calls exactly three trusted operations -- ``submit``, ``status`` and
``audit`` -- and turns the authenticated projection into redacted scalar views.
There is no method here that prepares, accepts, claims, executes, queries or
settles an operation.  Those words are absent from the class on purpose; the
operator and executor are separate processes with separate keys.
"""
import hashlib
import json
import threading
import time

from competition.agent import policy
from competition.agent.journal import JournalError, TERMINAL_STATES
from competition.caller.flow import Caller
from competition.support.wire import ProtocolError

# The only trusted method this class is allowed to reach.  It is a guard against
# a future edit, not a claim that the caller key is cryptographically limited to
# this method; the entry's H side still authorizes submit and read.
GATEWAY_STEPS = frozenset({'status'})

# Hints are only wake-ups: the gateway re-reads the authenticated projection and
# reports that, never the hint text.
HINT_STAGES = frozenset({'prepared', 'accepted', 'claimed', 'executed',
                         'settled', 'failed', 'unknown'})


class GatewayError(Exception):
    """A refusal or an unknown outcome at the agent boundary."""

    def __init__(self, code, message=None, *, detail=None):
        self.code = code
        self.message = message or code
        self.detail = detail
        super().__init__(self.message)


class Denied(GatewayError):
    """The trusted side explicitly refused the candidate."""


class SubmissionUnknown(GatewayError):
    """The trusted side may have created an operation; do not resubmit."""


class OperationUnknown(GatewayError):
    """No operation with that id is known to this gateway."""


def _fingerprint(status):
    scalar = {key: status.get(key) for key in
              ('acceptance_state', 'dispatch_state', 'effect_state', 'receipt_state',
               'attempt_id', 'exec_consumed', 'queries')}
    return hashlib.sha256(json.dumps(scalar, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True).encode('utf-8')).hexdigest()


def state_of(raw):
    """The one coarse state the agent needs, derived from the projection's dimensions."""
    dispatch = raw.get('dispatch_state')
    if dispatch in TERMINAL_STATES:
        return dispatch
    if dispatch == 'STARTED' or raw.get('attempt_id'):
        return 'STARTED'
    if raw.get('acceptance_state') == 'COMMITTED':
        return 'ACCEPTED'
    return 'SUBMITTED'


def redact_status(raw, *, read_at=None):
    """Keep scalar state and references; never the acceptance, COMMIT or payload.

    The full status dict carries the signed acceptance and, for industrial and
    medical profiles, business rows.  The agent boundary has no use for those
    bytes and the repository's boundary says the agent receives trimmed data.
    ``commit_record_ref`` is a reference, not a payload, and is useful evidence.
    """
    status = {
        'operation_id': raw.get('operation_id'),
        'profile': raw.get('profile'),
        'state': state_of(raw),
        'acceptance_state': raw.get('acceptance_state'),
        'dispatch_state': raw.get('dispatch_state'),
        'effect_state': raw.get('effect_state'),
        'receipt_state': raw.get('receipt_state'),
        'attempt_id': raw.get('attempt_id'),
        'exec_consumed': raw.get('exec_consumed'),
        'queries': raw.get('queries'),
        'view_kind': raw.get('view_kind'),
        'commit_record_ref': None,
        'read_at': time.time() if read_at is None else read_at,
    }
    acceptance = raw.get('acceptance')
    if type(acceptance) is dict:
        body = acceptance.get('body')
        payload = body.get('payload') if type(body) is dict else None
        ref = payload.get('commit_record_ref') if type(payload) is dict else None
        if type(ref) is str and 1 <= len(ref) <= 128 and ref.isprintable():
            status['commit_record_ref'] = ref
    return status


def summary_of(status):
    """One bounded line, generated only from the redacted scalar view."""
    state = status.get('state')
    if state == 'ACCEPTED':
        return ('accepted; receipt %s; dispatch %s; effect %s'
                % (status.get('receipt_state'), status.get('dispatch_state'),
                   status.get('effect_state')))
    if state == 'STARTED':
        return ('claimed; attempt %s; effect %s; exec_consumed=%s'
                % (status.get('attempt_id'), status.get('effect_state'),
                   status.get('exec_consumed')))
    if state == 'SETTLED':
        return 'settled; effect %s' % (status.get('effect_state'),)
    if state == 'HALTED':
        return 'halted by a trusted contradiction; historical facts retained'
    if state == 'CANCELED':
        return 'canceled; effect %s' % (status.get('effect_state'),)
    if state == 'UNAVAILABLE':
        return status.get('reason') or 'status unavailable'
    return 'submitted; waiting for independent approval'


class GatewayService:
    """One caller, one journal, and the three reads the agent is allowed."""

    def __init__(self, entry, key_path, endpoints, journal, *,
                 status_grace=None, now=time.time):
        self.caller = Caller(entry, key_path, endpoints)
        self.journal = journal
        self.now = now
        self.status_grace = (journal.grace if status_grace is None else status_grace)
        self._call_lock = threading.RLock()

    def start(self, timeout=600.0):
        """Open the caller's session, tolerating a list or entry that is still starting."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self.caller.start()
            except ProtocolError as exc:
                if exc.code not in ('ENTRY_UNAVAILABLE', 'SESSION_REQUIRED',
                                    'SESSION_CALLERS', 'SESSION_EXPIRED'):
                    raise
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)

    def close(self):
        self.journal.close()

    # -- propose ------------------------------------------------------------
    def propose(self, profile, intent):
        """Validate one business intent, submit it, and return its operation handle.

        A duplicate active intent returns the original operation.  A submission
        whose outcome is unknown is not silently retried: the caller is told to
        stop and ask an operator, which is the same conservative rule the
        repository applies to a lost submit answer.
        """
        clean = policy.validate_intent(profile, intent)
        digest = policy.intent_digest(profile, clean)
        row, should_submit = self.journal.begin_submission(profile, digest)
        if not should_submit:
            if row['state'] == 'SUBMITTED' and row.get('operation_id'):
                operation = self.journal.operation(row['operation_id'])
                return self._proposal(operation or {
                    'operation_id': row['operation_id'], 'profile': profile,
                    'state': 'SUBMITTED'}, deduplicated=True)
            if row['state'] == 'SUBMIT_UNKNOWN':
                raise SubmissionUnknown(
                    'SUBMISSION_UNKNOWN',
                    'a previous submission of this intent may have reached the trusted '
                    'side; do not resubmit; ask an operator to inspect it',
                    detail=row.get('detail'))
            raise SubmissionUnknown(
                'SUBMISSION_IN_FLIGHT',
                'an identical submission is in flight; wait for its result')
        try:
            submitted = self._trusted(lambda: self.caller.submit(profile, clean))
            operation_id = submitted['operation_id']
        except ProtocolError as exc:
            if exc.code in ('ENTRY_UNAVAILABLE', 'ENTRY_ANSWER'):
                self.journal.mark_submission_unknown(profile, digest, exc.code)
                raise SubmissionUnknown(
                    'SUBMISSION_UNKNOWN',
                    'the submit answer was not received; do not resubmit; ask an operator '
                    'to inspect the trusted side', detail=exc.code)
            self.journal.mark_submission_denied(profile, digest, exc.code)
            raise Denied(exc.code, _deny_hint(exc.code))
        except BaseException as exc:
            self.journal.mark_submission_unknown(profile, digest, type(exc).__name__)
            raise SubmissionUnknown(
                'SUBMISSION_UNKNOWN',
                'the submit call failed before an operation handle was known; do not '
                'resubmit', detail=type(exc).__name__)
        self.journal.mark_submitted(profile, digest, operation_id)
        status = {
            'operation_id': operation_id, 'profile': profile, 'state': 'SUBMITTED',
            'acceptance_state': None, 'dispatch_state': None, 'effect_state': None,
            'receipt_state': None, 'attempt_id': None, 'exec_consumed': None,
            'queries': None, 'view_kind': None, 'commit_record_ref': None,
            'read_at': self.now(),
        }
        self.journal.update_status(operation_id, 'SUBMITTED', 'submitted', status)
        self.journal.add_event(
            operation_id, 'SUBMITTED', 'SUBMITTED',
            'submitted; waiting for independent approval',
            dedupe_key='%s:SUBMITTED' % operation_id)
        return self._proposal({'operation_id': operation_id, 'profile': profile,
                               'state': 'SUBMITTED'}, deduplicated=False)

    @staticmethod
    def _proposal(operation, *, deduplicated):
        return {
            'operation_id': operation['operation_id'],
            'profile': operation.get('profile'),
            'state': operation.get('state') or 'SUBMITTED',
            'deduplicated': bool(deduplicated),
            'message': ('this intent already has an operation; use its status'
                        if deduplicated else
                        'submitted; acceptance and execution are decided elsewhere'),
        }

    # -- read ---------------------------------------------------------------
    def status(self, operation_id):
        """Return the current authenticated projection, redacted and possibly stale."""
        operation = self.journal.operation(operation_id)
        if operation is None:
            raise OperationUnknown('OPERATION_UNKNOWN', 'this gateway did not submit %r'
                                   % (operation_id,))
        if operation['terminal'] and operation.get('status'):
            return operation['status']
        try:
            raw = self._trusted(lambda: self.caller.step(operation_id, 'status'))
        except ProtocolError as exc:
            return self._status_failure(operation, exc.code)
        status = redact_status(raw, read_at=self.now())
        self._observe(operation, status)
        return status

    def refresh(self, operation_id):
        """One poll of one operation; the status call records any transition."""
        return self.status(operation_id)

    def poll_once(self):
        """Poll every non-terminal operation once, containing per-operation failures."""
        for operation in self.journal.active_operations():
            try:
                self.refresh(operation['operation_id'])
            except Exception:
                # The journal and the feedback stream must survive one bad read.
                continue

    def events(self, *, since=0, operation_id=None, limit=100):
        return self.journal.events(since=since, operation_id=operation_id, limit=limit)

    # -- operator / executor queue -----------------------------------------
    def queue_claim(self, role):
        row = self.journal.claim(role)
        return None if row is None else self._summary(row)

    def queue_release(self, role, operation_id):
        self.journal.release(role, operation_id)

    def hint(self, operation_id, stage):
        """A wake-up from operator/executor; the hint itself is never reported."""
        if stage not in HINT_STAGES:
            raise GatewayError('HINT_STAGE', 'unknown hint stage %r' % (stage,))
        self.journal.operation(operation_id) or _missing(operation_id)
        return self.status(operation_id)

    # -- internals ----------------------------------------------------------
    def _trusted(self, call):
        """Serialize trusted calls and reopen one expired session exactly once."""
        with self._call_lock:
            if self.caller.session.token is None:
                self.caller.start()
            try:
                return call()
            except ProtocolError as exc:
                if exc.code not in ('SESSION_REQUIRED', 'SESSION_EXPIRED'):
                    raise
                self.caller.session.token = None
                self.caller.start()
                return call()

    def _observe(self, operation, status):
        fingerprint = _fingerprint(status)
        previous, changed = self.journal.update_status(
            operation['operation_id'], status['state'], fingerprint, status)
        if not changed:
            return status
        kind = status['state']
        summary = summary_of(status)
        self.journal.add_event(
            operation['operation_id'], kind, status['state'], summary,
            detail={'read_at': status.get('read_at'),
                    'commit_record_ref': status.get('commit_record_ref'),
                    'exec_consumed': status.get('exec_consumed')},
            dedupe_key='%s:%s:%s' % (operation['operation_id'], kind, fingerprint))
        if kind in TERMINAL_STATES:
            self.journal.mark_terminal(operation['operation_id'], kind)
        return status

    def _status_failure(self, operation, code):
        """Keep the last known projection; only OPERATION_UNKNOWN can become terminal."""
        operation_id = operation['operation_id']
        if code == 'OPERATION_UNKNOWN':
            seen = operation.get('status') is not None and operation.get('fingerprint') not in (
                None, 'submitted')
            old_enough = (self.now() - float(operation['submitted_at'])) > self.status_grace
            if seen or old_enough:
                status = self._unavailable(operation, code)
                return status
            pending = {
                'operation_id': operation_id, 'profile': operation['profile'],
                'state': 'SUBMITTED', 'acceptance_state': None, 'dispatch_state': None,
                'effect_state': None, 'receipt_state': None, 'attempt_id': None,
                'exec_consumed': None, 'queries': None, 'view_kind': None,
                'commit_record_ref': None, 'read_at': self.now(),
                'read_error': 'OPERATION_UNKNOWN (not accepted yet)',
            }
            return pending
        failures = self.journal.record_read_failure(operation_id, code)
        last = operation.get('status') or {
            'operation_id': operation_id, 'profile': operation['profile'],
            'state': operation.get('state') or 'SUBMITTED',
            'acceptance_state': None, 'dispatch_state': None, 'effect_state': None,
            'receipt_state': None, 'attempt_id': None, 'exec_consumed': None,
            'queries': None, 'view_kind': None, 'commit_record_ref': None,
        }
        last = dict(last)
        last['read_at'] = self.now()
        last['read_error'] = code
        last['read_failures'] = failures
        if failures == 1 or failures % 10 == 0:
            self.journal.add_event(
                operation_id, 'READ_FAILED', last.get('state') or 'UNKNOWN',
                'status read failed (%s); last known state retained' % code,
                dedupe_key='%s:READ_FAILED:%d' % (operation_id, failures))
        return last

    def _unavailable(self, operation, code):
        previous = operation.get('status') or {}
        status = dict(previous)
        status.update({
            'operation_id': operation['operation_id'],
            'profile': operation['profile'],
            'state': 'UNAVAILABLE',
            'read_at': self.now(),
            'reason': ('status unavailable (%s); last known state retained; do not '
                       'infer success or failure' % code),
        })
        self.journal.update_status(operation['operation_id'], 'UNAVAILABLE',
                                   _fingerprint(status), status)
        self.journal.add_event(
            operation['operation_id'], 'UNAVAILABLE', 'UNAVAILABLE',
            status['reason'],
            dedupe_key='%s:UNAVAILABLE:%s' % (operation['operation_id'], code))
        self.journal.mark_terminal(operation['operation_id'], 'UNAVAILABLE')
        return status

    @staticmethod
    def _summary(row):
        status = row.get('status') or {}
        return {
            'operation_id': row['operation_id'],
            'profile': row['profile'],
            'state': row.get('state') or status.get('state') or 'SUBMITTED',
            'submitted_at': row.get('submitted_at'),
            'updated_at': row.get('updated_at'),
            'attempt_id': status.get('attempt_id'),
            'exec_consumed': status.get('exec_consumed'),
            'read_error': status.get('read_error'),
        }


def _missing(operation_id):
    raise OperationUnknown('OPERATION_UNKNOWN', 'this gateway did not submit %r'
                           % (operation_id,))


def _deny_hint(code):
    hints = {
        'PROFILE': 'choose one of IND-DEMO-1, PAY-1, MED-DEMO-1',
        'INTENT_FIELDS': 'send exactly the business fields named in the zjj_propose description',
        'INTENT_AMOUNT': 'amount_minor is a positive decimal string',
        'INTENT_ROUTE': 'route must be RELEASE, QUARANTINE or INSPECT',
        'BINDING': 'the trusted adapter could not bind these values; use a valid '
                   'unit/patient/order combination',
    }
    return hints.get(code, 'the trusted side refused this candidate; adjust the intent')
