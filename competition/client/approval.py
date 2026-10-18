"""The waiting room: the signatures that wait for a person.

``G``, ``U``, ``V`` and ``X`` sign *inside* the assembled chain, and each of those
signatures is the record of a decision a person is meant to make -- a Permit
issued, an EXECUTE approved, a review written, a challenge answered.  A deployment
that wants that decision to be a person's, rather than a script's, puts this room
in front of those endpoints' signing point: a request parks here until someone
answers it, and then the same single signing point answers it -- once, either way.

**Only the chain's own signing domain parks.**  An endpoint answers more than the
chain: an enrollment's possession proof, and the challenge a step hands over.  Those
are mechanical answers, and parking one of them would stop a deployment from coming
up at all -- the run is initialized, and every role enrolled, before anybody has a
page to look at.  So the rule is a whitelist on the chain's domain, decided by the
request itself rather than by who is knocking.

Nothing here signs, and nothing here certifies anything.  It holds a request,
hands a page enough to show *what* is being asked, and takes a yes or a no.  A
refusal is the page's answer, not a protocol fact: the caller is told nobody
answered, and it is the caller's rule name that travels, not this room's.

The room is deliberately not authority.  It cannot make a signature valid that the
signer would refuse, and an unanswered request does not become an approval.
"""
import threading

from competition.client.host import decode_data, decode_request
from competition.client.signer import split_message
from competition.support.wire import ProtocolError, WINDOW, require

# The one domain whose signatures are a person's decision: the chain's own signing
# call.  A Permit, an approval, a review and an effect-side challenge all travel
# under it.
CHAIN_DOMAIN = 'COMP-APP-SIGN-CALL-v1'
# How many requests this endpoint lets park at once.  A chain asks one role at a
# time, so a handful is already generous; the bound is here so a page that never
# answers cannot grow the room without limit.
MAX_PARKED = 16
# How long one request waits for an answer.  A page takes a while to open and a
# person longer, so this is minutes rather than seconds; past it the caller is
# told, not left hanging.
#
# Derived from the chain's own window (``support.wire.WINDOW``) rather than
# chosen: the chain asks four roles in sequence, so four waits plus the rest of
# assembly have to fit inside that one window, and a sixth of it leaves two
# thirds for the asking.  Set ``ZJJ_WINDOW=30`` and this follows to five seconds
# by itself -- too short for a person, which is the point of that setting.
DEFAULT_TIMEOUT = WINDOW / 6


def needs_a_person(line):
    """Whether one request line parks in the waiting room.

    The domain decides, and the trusted side is what set it: a person is asked
    about the chain's signatures and about nothing else.  A line that cannot be
    read is not parked -- the signing point refuses it under its own rule name,
    which is where that judgement belongs.
    """
    try:
        request = decode_request(line)
    except ProtocolError:
        return False
    if request.get('op', 'challenge') == 'raw':
        try:
            return split_message(decode_data(request['data']))[0] == CHAIN_DOMAIN
        except (ProtocolError, KeyError, TypeError, ValueError):
            return False
    return request.get('domain') == CHAIN_DOMAIN


class Ticket:
    """One parked request, and the one answer it will take."""

    def __init__(self, tid, request):
        self.id = tid
        self.request = request
        self._lock = threading.Lock()
        self._answered = threading.Event()
        self._verdict = None

    def view(self):
        """What a page needs to show: what is asked, where from, and its answer.

        ``claim`` is what would be signed -- the page shows it so a person can see
        what they are agreeing to, rather than agreeing to a request id.  A
        ``raw`` request carries canonical bytes instead of fields, so it is split
        the way the signing point splits it; the page then sees the domain and the
        message, not an opaque blob.
        """
        domain, claim = self._shown()
        return {'id': self.id,
                'answered': self._verdict is not None,
                'verdict': self._verdict,
                'op': self.request.get('op', 'challenge'),
                'profile': self.request.get('profile'),
                'role': self.request.get('role'),
                'domain': domain,
                'claim': claim}

    def _shown(self):
        """The domain and the message this request would sign, decoded if it can be."""
        if self.request.get('op', 'challenge') != 'raw':
            return self.request.get('domain'), self.request.get('claim')
        try:
            blob = decode_data(self.request['data'])
            domain, claim = split_message(blob)
            return domain, claim
        except (ProtocolError, KeyError, TypeError, ValueError):
            return 'raw', self.request.get('data')

    def wait(self, timeout):
        """Block until answered.  ``True`` approved, ``False`` refused, ``None``
        if nobody answered in time -- which is not an approval."""
        if not self._answered.wait(timeout):
            return None
        return self._verdict == 'APPROVE'

    def decide(self, approve):
        """Take the answer.  The first one wins; a second changes nothing."""
        with self._lock:
            if self._verdict is not None:
                return False
            self._verdict = 'APPROVE' if approve else 'REJECT'
        self._answered.set()
        return True


class WaitingRoom:
    """The room requests park in, and a page's window onto it."""

    def __init__(self, *, limit=MAX_PARKED, timeout=DEFAULT_TIMEOUT):
        self.limit = limit
        self.timeout = timeout
        self._lock = threading.Lock()
        self._tickets = {}
        self._counter = 0

    def park(self, line):
        """Parse one request line and park it; returns the ticket to wait on.

        The line is parsed here with the signing point's own parser, so a request
        this room accepts is one that point will accept -- and a malformed one is
        refused under the same rule name it would have been refused under.
        """
        request = decode_request(line)
        with self._lock:
            if len(self._tickets) >= self.limit:
                raise ProtocolError('CLIENT_ROOM_FULL')
            self._counter += 1
            ticket = Ticket(str(self._counter), request)
            self._tickets[ticket.id] = ticket
        return ticket

    def list(self):
        """Every parked request, oldest first, answered ones included.

        Answered tickets stay until their caller has come back for the answer, so
        a page that polls late still sees what happened rather than a gap.
        """
        with self._lock:
            tickets = [self._tickets[key] for key in sorted(self._tickets, key=int)]
        return [ticket.view() for ticket in tickets]

    def decide(self, tid, approve):
        """Answer one parked request by id.  Refuses an id that is not parked."""
        with self._lock:
            ticket = self._tickets.get(str(tid))
        require(ticket is not None, 'CLIENT_NO_TICKET')
        return ticket.decide(approve)

    def drop(self, tid):
        """Forget one ticket: its caller has what it came for."""
        with self._lock:
            self._tickets.pop(str(tid), None)
