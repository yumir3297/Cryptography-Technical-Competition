"""The console's two callers: a holder side and a worker side, and a page in front.

A caller is what walks a flow: it opens a session, proposes an operation, reads
its state, and carries each step's challenge to the endpoint that owns that role
and the signature back.  The console needs two of them, because the flow has two
sides and the entry's caller list is what keeps each on its side -- one caller
listed for ``H`` cannot drive an ``exec``, and one listed for ``worker`` cannot
submit.

What this adds over a bare :class:`~competition.caller.flow.Caller` is only what
a page needs: the two sides in one process, a session that survives between
requests, and a status that says which sessions are open without ever handing the
page a token.
"""
import time
from pathlib import Path

from competition.caller import key_file_name, record
from competition.caller.flow import Caller
from competition.core.trusted_state import ROLES
from competition.server.roster import endpoint_port
from competition.server.service import INTENT_FIELDS
from competition.support import trace
from competition.support.wire import ProtocolError, is_id, require

# The two sides of the flow, named the way :mod:`competition.web.session` names
# them: the same names the entry's caller list decides against.
SIDES = ('H', 'worker')
HOLDER, WORKER = 'H', 'worker'
# Every role a flow needs, in the order a page shows them.  The two that drive
# steps come first; the four that sign *inside* the assembled chain come after,
# and they have no steps of their own -- what a page shows them is what waits.
ROLE_ORDER = ('H', 'worker', 'G', 'U', 'V', 'X')
# The roles whose signatures wait for a person: the ones a page does not drive
# step by step.  These are the endpoints a page polls for what is waiting.
WAITING_ROLES = ('G', 'U', 'V', 'X')
# The worker is one capability rather than a scenario-bound role, so the trusted
# side's role table has no name for it; this is the one it is shown under.
WORKER_NAME = 'WORKER'
# The profile a first run proposes.  A page may ask for another; the entry is what
# decides whether a profile is real.
DEFAULT_PROFILE = 'PAY-1'
# A page waits for a deployment to come up, and the endpoints it drives initialize
# after the console starts; this is how long it waits before it says the entry was
# never there.
START_TIMEOUT = 600.0


# The lifecycle states a candidate row may show, in the core's own words.  An
# event may carry another label -- a tool's effect outcome, say -- and that is not
# where the operation is, so it is not a word the row shows: only these are.
LIFECYCLE = frozenset({'SUBMITTED', 'PENDING', 'STARTED', 'SETTLED', 'CANCELED',
                       'HALTED', 'DENIED'})


def _candidates(events, limit):
    """The submitted candidates, each with its latest state, newest first.

    A row exists as soon as somebody submits: the entry publishes
    ``CANDIDATE_SUBMITTED`` for its own page and for the agent gateway alike, and
    that is the only signal that reaches the read-only face before anybody
    accepts.  Acceptance, execution and settlement are later events for the same
    operation, and the core is what labels them -- ``status_label`` is its own
    word, where the entry's own events leave it empty.

    Only a lifecycle word is taken as the row's state.  An event that carries
    something else -- the tool's own ``SUCCEEDED``, which is an effect outcome and
    not a place in the flow -- leaves the last lifecycle word standing, so a row
    cannot read as finished before it is.
    """
    submitted, latest, labels, stages = {}, {}, {}, {}
    for event in events:
        operation_id = event.get('operation_id')
        if not operation_id:
            continue
        if event.get('kind') == 'CANDIDATE_SUBMITTED':
            submitted[operation_id] = event
        latest[operation_id] = event
        if event.get('status_label') in LIFECYCLE:
            labels[operation_id] = event['status_label']
            stages[operation_id] = event.get('stage') or ''
    rows = []
    for operation_id, first in submitted.items():
        event = latest.get(operation_id, first)
        rows.append({
            'operation_id': operation_id,
            'profile': event.get('profile') or first.get('profile') or '',
            'state': labels.get(operation_id, 'SUBMITTED'),
            'stage': stages.get(operation_id) or event.get('stage') or '',
            'seq': int(event.get('seq') or 0),
        })
    rows.sort(key=lambda row: row['seq'], reverse=True)
    return rows[:max(1, min(int(limit), 200))]


class Console:
    """The holder and worker callers behind one page.

    ``enroll`` makes each side's credential and lists it; ``start`` opens both
    sessions against the entry.  After that a page calls ``submit`` and ``step``,
    which are one :class:`~competition.caller.flow.Caller` call each.
    """

    def __init__(self, folder, entry, endpoints, *, observe=None, profile=DEFAULT_PROFILE,
                 holder='console-h', worker='console-worker', timeout=START_TIMEOUT):
        self.folder = Path(folder)
        self.entry = str(entry).rstrip('/')
        self.endpoints = None if endpoints is None else str(endpoints).rstrip('/')
        self.observe = None if observe is None else str(observe).rstrip('/')
        self.profile = profile
        self.timeout = timeout
        self.names = {HOLDER: holder, WORKER: worker}
        for side, name in self.names.items():
            require(side in SIDES and is_id(name), 'CONSOLE_NAME')
        self._callers = {}
        self._opened = {}

    # -- what the deployment asks for --------------------------------------
    def enroll(self):
        """Make each side's key if it has none, and list its public line.

        Idempotent, because a deployment restarts its containers: an existing
        credential is announced from the key itself, so the line and the key
        cannot drift, and a second run appends nothing.
        """
        path = self.folder / 'callers.jsonl'
        for side in SIDES:
            record(self.folder, self.names[side], [side])
        return path

    def start(self, timeout=None):
        """Open both sessions, waiting for the entry rather than racing it.

        The entry may not be up when the console is: a deployment starts its
        services at once, and the entry is what has to initialize against the
        endpoints first.  So an entry that is not there yet is waited for, while
        any other refusal is raised, because a credential problem does not fix
        itself by waiting.
        """
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        for side in SIDES:
            caller = Caller(self.entry, self.folder / key_file_name(self.names[side]),
                            self.endpoints)
            self._opened[side] = self._opened_session(caller, deadline)
            self._callers[side] = caller
        return self.status()

    @staticmethod
    def _opened_session(caller, deadline):
        while True:
            try:
                return caller.start()
            except ProtocolError as exc:
                if exc.code != 'ENTRY_UNAVAILABLE' or time.monotonic() > deadline:
                    raise
                time.sleep(0.5)

    # -- what the page asks for --------------------------------------------
    def submit(self, profile=None, intent=None):
        """Propose an operation on the side that proposes."""
        with trace.span('console.submit', profile=profile or self.profile):
            return self._caller(HOLDER).submit(profile or self.profile, intent)

    def step(self, side, operation_id, step):
        """Drive one step on the side the page named.

        Which side may drive which step is not decided here: the entry's caller
        list decides, and a caller reaching across its side comes back refused
        under the entry's own rule name.
        """
        with trace.span('console.step', side=side, step=step):
            return self._caller(side).step(operation_id, step)

    def package(self):
        """The published package, so a page can show what the roster bound."""
        return self._caller(HOLDER).package

    def scenarios(self):
        """The scenarios the trusted side fixes, what each takes, and its roles.

        The field list is the trusted side's own ``INTENT_FIELDS`` and the role
        names are its own ``ROLES``, both read rather than copied: a page builds
        its form and its role panels from this instead of keeping a table that
        could drift.  It is a description, not an authority -- a profile the entry
        does not know is refused there.
        """
        return {'profiles': [{'profile': profile, 'intents': list(fields),
                              'roles': self._roles(profile)}
                             for profile, fields in INTENT_FIELDS.items()]}

    def _roles(self, profile):
        """One scenario's roles, each as the alias a page keys on and its name."""
        table = ROLES.get(profile, {})
        out = []
        for alias in ROLE_ORDER:
            if alias == WORKER:
                out.append({'alias': alias, 'name': WORKER_NAME})
            elif alias in table:
                out.append({'alias': alias, 'name': table[alias]})
        return out

    def pending(self, profile=None):
        """What waits on the roles that sign inside the chain.

        ``G``, ``U``, ``V`` and ``X`` have no step a page can drive: their
        signatures are made while the chain is assembled, in one pass.  What the
        page owes them is therefore a view -- what is waiting, and a yes or a no.

        Each of those roles answers on its own port, so this is one direct read
        per role, at the port the roster's own rule implies: no discovery, and no
        trip through the entry -- which matters, because the entry is exactly what
        is blocked while a chain waits for one of these answers.
        """
        profile = profile or self.profile
        if self.endpoints is None:
            return {'profile': profile, 'todos': []}
        todos = []
        with trace.span('pending.roles', roles=list(WAITING_ROLES)) as entry:
            for role in WAITING_ROLES:
                with trace.span('pending.role', role=role) as role_entry:
                    found = self._waiting(profile, role)
                    role_entry['tickets'] = len(found)
                for ticket in found:
                    todos.append({'role': role, **ticket})
            entry['todos'] = len(todos)
        return {'profile': profile, 'todos': todos}

    def _waiting(self, profile, role):
        """The unanswered requests parked at one endpoint; empty if it is not there.

        A role that is still starting, or one started without a waiting room, has
        nothing to show -- which is not an error a page should report, so it is
        read as "nothing waiting".
        """
        import httpx
        url = '%s:%d/awaiting' % (self.endpoints, endpoint_port(profile, role))
        with trace.span('endpoint.awaiting', role=role) as entry:
            try:
                reply = httpx.get(url, timeout=2.0)
                entry['status'] = reply.status_code
                if reply.status_code != 200:
                    return []
                parked = reply.json().get('tickets', [])
            except (httpx.HTTPError, ValueError) as exc:
                entry['error'] = type(exc).__name__
                return []
        return [ticket for ticket in parked if not ticket.get('answered')]

    def decide(self, profile, role, ticket, approve):
        """Answer one parked request, at the endpoint that parked it.

        The answer is handed to the role's own endpoint, so the decision and the
        signature stay in the same process: this carries a yes or a no, and never
        a signature of its own.
        """
        import httpx
        require(self.endpoints is not None, 'CONSOLE_ENDPOINTS')
        require(role in WAITING_ROLES, 'CONSOLE_ROLE')
        require(type(ticket) is str and ticket.isdigit(), 'CONSOLE_TICKET')
        require(type(approve) is bool, 'CONSOLE_DECIDE')
        url = '%s:%d/decide' % (self.endpoints, endpoint_port(profile, role))
        with trace.span('endpoint.decide', role=role, ticket=ticket, approve=approve):
            reply = httpx.post(url, json={'id': ticket, 'approve': approve}, timeout=10.0)
        require(reply.status_code == 200, 'CONSOLE_DECIDE')
        return reply.json()

    def operations(self, limit=50):
        """Every candidate this instance has been asked to consider, newest first.

        The entry has one pool: a candidate submitted from this page and one the
        agent submitted over MCP are the same kind of row.  What makes the agent's
        visible here before anybody accepts it is the read-only observation face
        -- the same projection the display page reads -- where a submission shows
        up as an event.  It is a read: no payload, and no way to drive a step.

        The event routes only walk forward, so the log is read from the start; at
        a demonstration's scale that is a few pages.  A viewer that is not up yet
        reads as an empty list rather than as an error a page has to report.
        """
        if self.observe is None:
            return {'operations': []}
        import httpx
        events, after = [], 0
        with trace.span('observe.events', observe=self.observe) as entry:
            try:
                for _ in range(20):
                    reply = httpx.get(self.observe + '/api/observe/events',
                                      params={'after': after, 'limit': 500}, timeout=3.0)
                    if reply.status_code != 200:
                        return {'operations': []}
                    page = reply.json()
                    got = page.get('events', [])
                    events.extend(got)
                    last = int(page.get('last') or after)
                    if not got or last <= after:
                        break
                    after = last
            except (httpx.HTTPError, ValueError) as exc:
                entry['error'] = type(exc).__name__
                return {'operations': []}
            entry['events'] = len(events)
            entry['pages'] = after
        return {'operations': _candidates(events, limit)}

    def status(self):
        """What a page needs before it can act: the two sessions, no tokens."""
        return {'entry': self.entry, 'profile': self.profile,
                'sessions': [self._session(side) for side in SIDES]}

    # -- the one place a side becomes a caller -----------------------------
    def _caller(self, side):
        require(side in SIDES, 'CONSOLE_SIDE')
        require(side in self._callers, 'CONSOLE_START')
        return self._callers[side]

    def _session(self, side):
        opened = self._opened.get(side)
        if opened is None:
            return {'side': side, 'open': False}
        # The token is a credential and stays in this process; the page is told
        # only that the session is open, and for which sides.
        return {'side': side, 'open': True, 'caller': opened['caller'],
                'sides': opened['sides'], 'expires': opened['expires']}
