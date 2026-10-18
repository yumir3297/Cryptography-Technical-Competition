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
from competition.server.service import INTENT_FIELDS
from competition.support.wire import ProtocolError, is_id, require

# The two sides of the flow, named the way :mod:`competition.web.session` names
# them: the same names the entry's caller list decides against.
SIDES = ('H', 'worker')
HOLDER, WORKER = 'H', 'worker'
# The profile a first run proposes.  A page may ask for another; the entry is what
# decides whether a profile is real.
DEFAULT_PROFILE = 'PAY-1'
# A page waits for a deployment to come up, and the endpoints it drives initialize
# after the console starts; this is how long it waits before it says the entry was
# never there.
START_TIMEOUT = 600.0


class Console:
    """The holder and worker callers behind one page.

    ``enroll`` makes each side's credential and lists it; ``start`` opens both
    sessions against the entry.  After that a page calls ``submit`` and ``step``,
    which are one :class:`~competition.caller.flow.Caller` call each.
    """

    def __init__(self, folder, entry, endpoints, *, profile=DEFAULT_PROFILE,
                 holder='console-h', worker='console-worker', timeout=START_TIMEOUT):
        self.folder = Path(folder)
        self.entry = str(entry).rstrip('/')
        self.endpoints = None if endpoints is None else str(endpoints).rstrip('/')
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
        return self._caller(HOLDER).submit(profile or self.profile, intent)

    def step(self, side, operation_id, step):
        """Drive one step on the side the page named.

        Which side may drive which step is not decided here: the entry's caller
        list decides, and a caller reaching across its side comes back refused
        under the entry's own rule name.
        """
        return self._caller(side).step(operation_id, step)

    def package(self):
        """The published package, so a page can show what the roster bound."""
        return self._caller(HOLDER).package

    def scenarios(self):
        """The scenarios the trusted side fixes, and the intent each one takes.

        The field list is the trusted side's own ``INTENT_FIELDS``, read rather
        than copied: a page builds its form from this instead of keeping a table
        that could drift from what the entry will accept.  It is a description,
        not an authority -- a profile the entry does not know is refused there.
        """
        return {'profiles': [{'profile': profile, 'intents': list(fields)}
                             for profile, fields in INTENT_FIELDS.items()]}

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
