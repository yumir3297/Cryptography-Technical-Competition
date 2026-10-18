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


class OperationUnknown(GatewayError):
    """No operation and no submission with that id is known to this gateway."""


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
        self.entry = entry
        self.key_path = key_path
        self.endpoints = endpoints
        self.caller = Caller(entry, key_path, endpoints)
        self.journal = journal
        self.now = now
        self.status_grace = (journal.grace if status_grace is None else status_grace)
        self._call_lock = threading.RLock()

    def start(self, timeout=600.0, caller=None):
        """Open one caller's session, tolerating a list or entry that is still starting.

        The session this service reads and signs with is opened on first use; a
        submitter opens its own, so that a submit waiting on a person cannot hold
        the lock the reads need.
        """
        caller = self.caller if caller is None else caller
        deadline = time.monotonic() + timeout
        while True:
            try:
                return caller.start()
            except ProtocolError as exc:
                if exc.code not in ('ENTRY_UNAVAILABLE', 'SESSION_REQUIRED',
                                    'SESSION_CALLERS', 'SESSION_EXPIRED'):
                    raise
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)

    def close(self):
        """Close the journal.

        A submit still in flight is carried by a daemon thread on its own caller:
        it ends with the process, and whatever it had already written stays.  A
        submit whose outcome never arrived is the same fact the trusted side
        leaves behind -- unknown -- and the next reader is told to inspect it.
        """
        self.journal.close()

    # -- propose ------------------------------------------------------------
    def propose(self, profile, intent):
        """Validate one business intent, reserve it, and let a submitter carry it.

        The submit itself is not done here.  The trusted side answers a submit
        only after it has gathered a whole approval chain, and with the waiting
        room on that chain the answer waits for a person -- longer than any tool
        call should block.  So this returns what is already known, which is that
        the intent was taken, and the outcome arrives later on the same feedback
        channel every other transition uses.

        The handle returned is the intent's own digest: stable, unique across
        profiles, and the same one a repeat call gets.  Until the trusted side
        answers it is all the agent has; once it has, the accepted event carries
        the operation id and the handle resolves to it.
        """
        clean = policy.validate_intent(profile, intent)
        digest = policy.intent_digest(profile, clean)
        row, should_submit = self.journal.begin_submission(profile, digest)
        if should_submit:
            self._start_submit(profile, digest, clean)
            return self._proposal({'operation_id': digest, 'profile': profile,
                                   'state': 'PENDING'}, deduplicated=False)
        if row['state'] == 'SUBMITTED' and row.get('operation_id'):
            return self._proposal({'operation_id': row['operation_id'], 'profile': profile,
                                   'state': 'SUBMITTED'}, deduplicated=True)
        state = 'UNKNOWN' if row['state'] == 'SUBMIT_UNKNOWN' else 'PENDING'
        return self._proposal({'operation_id': digest, 'profile': profile, 'state': state},
                              deduplicated=True)

    def _start_submit(self, profile, digest, clean):
        """Carry one submit off the request thread, on a caller of its own."""
        thread = threading.Thread(target=self._submit, args=(profile, digest, clean),
                                  name='zjj-submit-%s' % digest[:8], daemon=True)
        thread.start()

    def _submit(self, profile, digest, clean):
        """One background submit; its outcome becomes an event either way."""
        caller = Caller(self.entry, self.key_path, self.endpoints)
        try:
            self.start(caller=caller)
            operation_id = caller.submit(profile, clean)['operation_id']
        except ProtocolError as exc:
            unknown = exc.code in ('ENTRY_UNAVAILABLE', 'ENTRY_ANSWER')
            self._submission_ended(profile, digest,
                                   'SUBMIT_UNKNOWN' if unknown else 'DENIED', exc.code)
            return
        except BaseException as exc:
            self._submission_ended(profile, digest, 'SUBMIT_UNKNOWN', type(exc).__name__)
            return
        self.journal.mark_submitted(profile, digest, operation_id)
        self.journal.add_event(
            digest, 'SUBMISSION_ACCEPTED', 'SUBMITTED',
            'submitted; waiting for independent approval',
            detail={'profile': profile, 'operation_id': operation_id},
            dedupe_key='%s:SUBMISSION_ACCEPTED' % digest)

    def _submission_ended(self, profile, digest, state, detail):
        """Record how a submit ended and say so on the feedback channel.

        A refusal is the trusted side's own rule name and the agent may correct
        the intent.  Anything else leaves the same unknown the trusted side does:
        the submit may have been taken, so the intent may not be proposed again,
        and a person has to look.
        """
        if state == 'DENIED':
            self.journal.mark_submission_denied(profile, digest, detail)
            summary = 'the trusted side refused this candidate (%s)' % detail
        else:
            self.journal.mark_submission_unknown(profile, digest, detail)
            summary = ('the submit outcome is unknown (%s); do not resubmit; '
                       'ask an operator to inspect the trusted side' % detail)
        self.journal.add_event(digest, state, state, summary,
                               detail={'profile': profile, 'code': detail},
                               dedupe_key='%s:%s' % (digest, state))

    @staticmethod
    def _proposal(operation, *, deduplicated):
        state = operation.get('state') or 'SUBMITTED'
        if state == 'PENDING':
            message = ('the intent is taken; this id is a temporary id (a submission '
                       'handle), not the operation id; the trusted side is gathering its '
                       'approval chain and the pushed status notice carries both ids')
        elif state == 'UNKNOWN':
            message = ('a previous submission of this intent may have reached the trusted '
                       'side; this id is a temporary id, not the operation id; do not '
                       'resubmit; ask an operator to inspect it')
        elif deduplicated:
            message = 'this intent already has an operation; use its status'
        else:
            message = 'submitted; acceptance and execution are decided elsewhere'
        return {
            'operation_id': operation['operation_id'],
            'profile': operation.get('profile'),
            'state': state,
            'deduplicated': bool(deduplicated),
            'message': message,
        }

    # -- read ---------------------------------------------------------------
    def status(self, operation_id):
        """Return the current authenticated projection, redacted and possibly stale.

        The id may be a submission handle as well as an operation id.  Until the
        trusted side has answered, the handle is all the agent has, and it should
        not have to wait for the pushed notice to read what is already known --
        nor should an operation the handle has resolved to become unreadable.
        """
        operation = self.journal.operation(operation_id)
        if operation is None:
            return self._submission_status(operation_id)
        if operation['terminal'] and operation.get('status'):
            return operation['status']
        try:
            raw = self._trusted(lambda: self.caller.step(operation_id, 'status'))
        except ProtocolError as exc:
            return self._status_failure(operation, exc.code)
        status = redact_status(raw, read_at=self.now())
        self._observe(operation, status)
        return status

    def _submission_status(self, handle):
        """What is known about a submission whose handle is all the caller has."""
        submission = self.journal.submission_by_digest(handle)
        if submission is None:
            raise OperationUnknown('OPERATION_UNKNOWN', 'this gateway did not submit %r'
                                   % (handle,))
        if submission['state'] == 'SUBMITTED' and submission.get('operation_id'):
            # The trusted side answered while nobody was reading; follow the
            # handle to the operation it became.
            return self.status(submission['operation_id'])
        if submission['state'] == 'DENIED':
            state, reason = 'DENIED', ('the trusted side refused this candidate (%s); '
                                       'correct the intent and propose it again'
                                       % (submission.get('detail') or 'REFUSED'))
        elif submission['state'] == 'SUBMIT_UNKNOWN':
            state, reason = 'UNKNOWN', ('the submit outcome is unknown; do not resubmit; '
                                        'ask an operator to inspect the trusted side')
        else:
            state, reason = 'PENDING', ('this id is a temporary id, not the operation id; '
                                        'the trusted side is gathering the approval chain '
                                        'and the outcome arrives as a pushed status notice')
        return {
            'operation_id': handle, 'profile': submission['profile'], 'state': state,
            'acceptance_state': None, 'dispatch_state': None, 'effect_state': None,
            'receipt_state': None, 'attempt_id': None, 'exec_consumed': None,
            'queries': None, 'view_kind': None, 'commit_record_ref': None,
            'read_at': self.now(), 'reason': reason,
        }

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
