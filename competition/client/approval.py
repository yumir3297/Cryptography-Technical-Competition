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

**It is off unless a deployment asks for it.**  The controlled initialization is
scripted approval, and the project's own boundary notes say what that means: the
signatures it produces simulate the roles and are not collected human consent.  A
deployment exercised end to end by an agent therefore leaves this room out
entirely, and the four endpoints answer their reports at once.  A deployment that
does want somebody at the page turns it on (`ZJJ_AWAIT_APPROVAL=1`) and those
endpoints park each report until an answer comes.

Nothing here signs, and nothing here certifies anything.  It holds a request,
hands a page enough to show *what* is being asked, and takes a yes or a no.  A
refusal is the page's answer, not a protocol fact: the caller is told nobody
answered, and it is the caller's rule name that travels, not this room's.

The room is deliberately not authority.  It cannot make a signature valid that the
signer would refuse, and an unanswered request does not become an approval.

**Two ways in, and the difference is when the signing call opens.**

A request may *park*: it has already reached the signing point, the signing call
is already open with its thirty seconds running, and the room only gets to hold
it for as long as that call would still accept the answer.  That is
:meth:`WaitingRoom.park`, and it is the fallback -- what an endpoint does when
somebody asks it to sign without having asked here first.

Or a caller may *report first*: it hands over the message it is about to have
signed, before opening anything, and waits for a person with no deadline but the
person's own patience.  Only when it has an answer does it open the signing call,
and that call is then answered immediately.  That is
:meth:`WaitingRoom.preapprove`, and it is the path a deployment should take --
because a person cannot be asked to decide inside thirty seconds they did not
know were running.
"""
import threading

from competition.client.host import decode_data, decode_request
from competition.client.signer import split_message
from competition.core.signer_broker import ScopedSignerBroker
from competition.support.wire import ProtocolError, WINDOW, require

# The one domain whose signatures are a person's decision: the chain's own signing
# call.  A Permit, an approval, a review and an effect-side challenge all travel
# under it.
CHAIN_DOMAIN = 'COMP-APP-SIGN-CALL-v1'
# How many requests this endpoint lets park at once.  A chain asks one role at a
# time, so a handful is already generous; the bound is here so a page that never
# answers cannot grow the room without limit.
MAX_PARKED = 16
# How long one request waits for a person's answer.
#
# It is not derived from the chain window, because a chain signature is not
# bounded by that: ``core/signer_broker.py`` opens a signing call with thirty
# seconds on it (``INSERT INTO a_sign_call ... event['lo']+30``), and the endpoint
# is asked for its caller proof *inside* that window -- so a person has to answer
# while it is open.  Waiting longer than this would only park the request past the
# moment core stops accepting the answer, and the failure would read as an expired
# clock rather than as nobody answering.
#
# So this is deliberately below that thirty, and short enough that the endpoint
# gives up first and says so.
DEFAULT_TIMEOUT = 25.0
# How long a *preapproval* waits for a person.  This one is not bounded by the
# signing call, because nothing has been opened yet: the caller is asking before
# it opens anything, and will only open the call once it has an answer.  So this
# is the room's own patience, and it follows the one window the way the rest of
# the deployment's waits do -- a caller with no page in front of it is told
# rather than left hanging.  With ``ZJJ_WINDOW=30`` it comes back to a length
# that no person could answer, which is the point of that setting.
PREAPPROVAL_TIMEOUT = WINDOW


def chain_request_ref(line):
    """The reference of the chain message one request would sign, or ``None``.

    One answer to two questions at once: whether this request is the chain's own
    signing call, and which message it is about.  A request that is not that
    domain, or whose bytes cannot be read, has no reference and is not something
    a person was asked about -- so it is not a preapproval, and the caller is
    answered the way it always was.

    The reference is the black box's own (``ScopedSignerBroker.request_ref``),
    recomputed here rather than kept, so the endpoint and the trusted side are
    agreeing on one definition and not on a copy of it.
    """
    try:
        request = decode_request(line)
        if request.get('op', 'challenge') != 'raw':
            return None
        # ``split_message`` hands back the whole ``[domain, ...]`` list, and the
        # signing call's claim is its second element.
        domain, value = split_message(decode_data(request['data']))
        if domain != CHAIN_DOMAIN or type(value) is not list or len(value) != 2 \
                or type(value[1]) is not dict:
            return None
        ref = value[1].get('request_ref')
        return ref if type(ref) is str else None
    except (ProtocolError, KeyError, TypeError, ValueError, AttributeError):
        return None


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
        if self.request.get('op') == 'preapprove':
            # A preapproval is shown as the message itself.  It is in hand -- the
            # caller handed it over before opening anything -- and it is what a
            # person is being asked about, where the signing call's own claim
            # would only carry a reference to it.
            unsigned = self.request['unsigned']
            return {'id': self.id,
                    'answered': self._verdict is not None,
                    'verdict': self._verdict,
                    'op': 'preapprove',
                    'profile': self.request.get('profile'),
                    'role': self.request.get('role'),
                    'domain': CHAIN_DOMAIN,
                    'type': unsigned.get('protected', {}).get('type'),
                    'request_ref': self.request.get('request_ref'),
                    'claim': unsigned}
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

    def __init__(self, *, limit=MAX_PARKED, timeout=DEFAULT_TIMEOUT,
                 preapproval_timeout=PREAPPROVAL_TIMEOUT):
        self.limit = limit
        self.timeout = timeout
        self.preapproval_timeout = preapproval_timeout
        self._lock = threading.Lock()
        self._tickets = {}
        self._counter = 0
        # The references a person has approved ahead of the signing call.  A
        # reference is spent by the one signature it was an answer to, so this is
        # taken from, not read -- the same one-shot the signing call's own nonce
        # is.
        self._approved = {}

    def preapprove(self, *, profile, role, unsigned, action, timeout):
        """Ask a person about one chain message *before* it is signed.

        The caller hands over what it is about to have signed and waits for an
        answer.  Nothing is opened here -- the caller's signing call, and the
        thirty seconds on it, only begin once this returns -- so the wait is
        bounded by a person's patience rather than by that call.  That is the
        whole point: the person decides first, and the signature that follows is
        immediate.

        An approval is remembered against the message's own reference, which is
        the black box's, so the signing call that follows is recognised as the one
        that was agreed to rather than matched loosely.
        """
        ref = ScopedSignerBroker.request_ref(profile, role, unsigned, action)
        with self._lock:
            if len(self._tickets) >= self.limit:
                raise ProtocolError('CLIENT_ROOM_FULL')
            self._counter += 1
            ticket = Ticket(str(self._counter),
                            {'op': 'preapprove', 'profile': profile, 'role': role,
                             'unsigned': unsigned, 'request_ref': ref})
            self._tickets[ticket.id] = ticket
        try:
            approved = ticket.wait(timeout)
        finally:
            # The page stops showing it either way; a late answer changes nothing.
            self.drop(ticket.id)
        if approved:
            with self._lock:
                self._approved[ref] = True
        return approved

    def remember(self, *, profile, role, unsigned, action):
        """Record an approval for one message without asking anybody.

        The trusted side reports every chain message it is about to have signed,
        and says whether that one is a person's decision.  When it is not --
        initialization is the scripted boundary, and the documented rule says so
        -- the signing call that follows still needs an answer, so one is
        recorded here rather than parked and waited on.  What is recorded is
        keyed the same way a person's answer is, so the call that follows is
        answered, not held.
        """
        ref = ScopedSignerBroker.request_ref(profile, role, unsigned, action)
        with self._lock:
            self._approved[ref] = True
        return ref

    def take_approved(self, ref):
        """Spend the approval for one reference, if there is one.

        One reference is answered by one signature, so this removes what it
        returns: a second signing call carrying the same reference is not the one
        a person agreed to, and is not preapproved.
        """
        with self._lock:
            return self._approved.pop(ref, None) is not None

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
