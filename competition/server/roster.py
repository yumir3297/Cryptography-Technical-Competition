"""The roster manifest: the public keys the endpoints made for themselves.

An endpoint generates its own key and prints exactly one manifest line --
``python -m competition.client --keygen`` writes the entry to stdout and nothing
else.  A manifest is those lines, in order.  The trusted side reads them, checks
each one against its own tables, and builds the roster the empty W is bound to.
Private halves never appear here, and no code in this module could use one.

An endpoint proposes, the roster decides.  The key id is re-derived from the
public key rather than read from the line, the public key must be a real curve
point, and the purposes are recomputed from this repository's own ``TYPES``
table, so an alias cannot announce more than it is entitled to.

:class:`RemoteActor` has the shape the black box already reads -- ``name``,
``pub``, ``kid``, ``roles``, ``purposes`` and a ``key`` -- with the private half
replaced by :class:`RemoteKey`, which forwards ``sign(bytes)`` to the endpoint
over a :class:`Transport`.  That is the whole trick: the black box cannot tell
the difference, and the key never left the machine that made it.
"""
import json
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from competition.core.trusted_state import PROFILE_SCOPES, ROLES, TYPES
from competition.support.wire import (
    ProtocolError, b64, good_point, is_id, keyid, raw, require, sortset,
)

# Which endpoints hold a credential.  A roster alias carries a business role and
# exists per profile; the worker is one cross-profile capability; the tool exists
# per profile.  Only the aliases name actors in the roster the black box reads.
ALIASES = tuple(sorted(TYPES))
ENDPOINTS = ALIASES + ('tool', 'worker')
ENTRY_FIELDS = frozenset({'role', 'subject', 'public_key', 'kid', 'purposes'})
# One answer line carries one signature and its envelope: generous, not unbounded.
MAX_REPLY = 1 << 16
# The endpoint's HTTP face refuses a request with this status and a
# ``{"deny": <rule>}`` body, naming the same rule the line protocol refuses
# under.  Shared by both sides of that wire, so there is one definition of it.
DENY_STATUS = 403


def key_file_name(profile, role):
    """The key file an endpoint of this kind owns."""
    require(role in ENDPOINTS, 'ROSTER_ROLE')
    require(role == 'worker' or profile in PROFILE_SCOPES, 'ROSTER_PROFILE')
    if role == 'worker':
        return 'W-worker.key'
    if role == 'tool':
        return profile + '-tool.key'
    return profile + '-' + role + '.key'


def owner_purposes(alias):
    """What this repository lets a roster alias do; an endpoint may not widen it."""
    require(alias in ALIASES, 'ROSTER_ALIAS')
    return sortset(list(TYPES[alias] + ('READ',)))


# The base port each endpoint's HTTP face is reached on.  The port is derived
# from the endpoint's own place in the roster instead of being published in a
# hand-kept table, so the endpoint and the trusted side compute the same number
# from the same rule and nothing has to be discovered or configured.
HTTP_PORT_BASE = 9100


def endpoint_port(profile, role):
    """The port an endpoint listens on: one deterministic number, no table.

    The tool has no face of its own -- the trusted side runs it as a child
    process against its own ledger -- so it has no port here.
    """
    require(role in ALIASES or role == 'worker', 'ROSTER_ROLE')
    if role == 'worker':
        # One worker capability serves every profile, so it names no profile and
        # takes the one slot before the per-profile aliases.
        return HTTP_PORT_BASE
    require(profile in PROFILE_SCOPES, 'ROSTER_PROFILE')
    return (HTTP_PORT_BASE + 1 + sorted(PROFILE_SCOPES).index(profile) * len(ALIASES)
            + ALIASES.index(role))


@dataclass(frozen=True)
class Endpoint:
    """One validated manifest line: a public key and the name that goes with it."""

    role: str
    subject: str
    pub: bytes
    kid: str
    purposes: tuple
    # ``None`` for the single worker, which is one capability across all profiles.
    profile: object = None


def read_entry(value):
    """Validate one manifest line, re-deriving every fact that can be re-derived."""
    require(type(value) is dict, 'ROSTER_ENTRY')
    role = value.get('role')
    require(role in ENDPOINTS, 'ROSTER_ROLE')
    require(set(value) == (ENTRY_FIELDS if role == 'worker' else ENTRY_FIELDS | {'profile'}),
            'ROSTER_FIELDS')
    profile = value.get('profile')
    if role != 'worker':
        require(profile in PROFILE_SCOPES, 'ROSTER_PROFILE')
    require(is_id(value['subject']), 'ROSTER_SUBJECT')
    pub = raw(value['public_key'], 32)
    require(good_point(pub), 'PUBLIC_KEY_POINT')
    kid = keyid(pub)
    require(value['kid'] == kid, 'ROSTER_KEY')
    purposes = value['purposes']
    require(type(purposes) is list and purposes == (owner_purposes(role) if role in ALIASES else []),
            'ROSTER_PURPOSES')
    return Endpoint(role, value['subject'], pub, kid, tuple(purposes), profile)


def read_manifest(path):
    """Read a JSON-lines manifest, refusing a malformed line or a duplicate endpoint."""
    endpoints, seen = [], set()
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            raise ProtocolError('ROSTER_MANIFEST')
        entry = read_entry(value)
        key = ('worker',) if entry.role == 'worker' else (entry.profile, entry.role)
        require(key not in seen, 'ROSTER_DUPLICATE')
        seen.add(key)
        endpoints.append(entry)
    return endpoints


def describe(endpoints):
    """The manifest as sorted public facts, for a CLI listing."""
    return [{'profile': entry.profile, 'role': entry.role, 'subject': entry.subject,
             'kid': entry.kid, 'purposes': list(entry.purposes)}
            for entry in sorted(endpoints,
                                key=lambda entry: (entry.profile is None, entry.profile or '',
                                                   entry.role))]


@runtime_checkable
class Transport(Protocol):
    """How the trusted side reaches one endpoint's signing host."""

    def request(self, message: dict) -> dict:
        """Send one line-protocol request and return the parsed answer."""
        ...


class SocketTransport:
    """Reach one endpoint over its own unix socket, one request per connection.

    One connection per call keeps the trusted side free of any endpoint lifetime:
    a refused or dead endpoint fails the call, and the next one reconnects.
    """

    def __init__(self, path, *, timeout=30.0):
        self.path = str(path)
        self.timeout = timeout

    def request(self, message):
        payload = json.dumps(message, ensure_ascii=False, sort_keys=True).encode('utf-8') + b'\n'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(self.path)
            stream = connection.makefile('rwb')
            try:
                stream.write(payload)
                stream.flush()
                line = stream.readline(MAX_REPLY)
            finally:
                stream.close()
        require(line, 'ENDPOINT_UNAVAILABLE')
        try:
            answer = json.loads(line)
        except (UnicodeError, json.JSONDecodeError):
            raise ProtocolError('ENDPOINT_ANSWER')
        require(type(answer) is dict and type(answer.get('signature')) is str, 'ENDPOINT_ANSWER')
        return answer


class HTTPTransport:
    """Reach one endpoint over its own HTTP face, one request per call.

    The same discipline as :class:`SocketTransport`: the call connects, asks and
    disconnects, so the trusted side holds no endpoint lifetime and a refused or
    dead endpoint simply fails this call.  The request body is the line
    protocol's own object, so an endpoint answers with the same envelope
    whichever transport carried it.

    A refusal comes back under the endpoint's own rule name -- carried through
    unchanged rather than flattened into one code -- because "this endpoint
    refused that domain" and "this endpoint did not answer" are different facts
    and the trusted side acts on both.
    """

    def __init__(self, url, *, timeout=30.0):
        self.url = str(url).rstrip('/')
        self.timeout = timeout

    def request(self, message):
        # Imported here so the roster itself stays free of an HTTP client; the
        # trusted side only needs one when it actually speaks this transport.
        import httpx
        payload = json.dumps(message, ensure_ascii=False, sort_keys=True).encode('utf-8')
        try:
            reply = httpx.post(self.url + '/sign', content=payload, timeout=self.timeout)
        except httpx.HTTPError:
            raise ProtocolError('ENDPOINT_UNAVAILABLE')
        if reply.status_code == DENY_STATUS:
            try:
                code = reply.json().get('deny')
            except (ValueError, AttributeError):
                raise ProtocolError('ENDPOINT_ANSWER')
            raise ProtocolError(code if type(code) is str else 'ENDPOINT_ANSWER')
        require(reply.status_code == 200, 'ENDPOINT_ANSWER')
        try:
            answer = reply.json()
        except ValueError:
            raise ProtocolError('ENDPOINT_ANSWER')
        require(type(answer) is dict and type(answer.get('signature')) is str, 'ENDPOINT_ANSWER')
        return answer


class RemoteKey:
    """The private half of a roster actor, replaced by one call to its endpoint.

    The black box only ever calls ``sign(bytes)`` on an actor's key, so an object
    with that one method is indistinguishable from a local ``Ed25519PrivateKey``
    at every call site in ``core``.  The answer must come from the key the roster
    holds; whether the signature is valid is still the black box's own check.
    """

    def __init__(self, endpoint, transport):
        self._endpoint = endpoint
        self._transport = transport

    def sign(self, data):
        require(type(data) is bytes, 'ROSTER_MESSAGE')
        answer = self._transport.request({'op': 'raw', 'profile': self._endpoint.profile,
                                          'role': self._endpoint.role, 'data': b64(data)})
        require(answer.get('kid') == self._endpoint.kid, 'ENDPOINT_BINDING')
        return raw(answer['signature'], 64)


class RemoteActor:
    """``Identity``-shaped: the roster's decisions, and a key that lives elsewhere."""

    def __init__(self, endpoint, transport):
        require(endpoint.profile in PROFILE_SCOPES and endpoint.role in ALIASES, 'ROSTER_ALIAS')
        self.name = endpoint.subject
        self.pub = endpoint.pub
        self.kid = endpoint.kid
        self.roles = frozenset([ROLES[endpoint.profile][endpoint.role]])
        self.purposes = frozenset(endpoint.purposes)
        self.key = RemoteKey(endpoint, transport)


def actors(endpoints, transport_for):
    """The six-alias roster the black box is bound to.

    ``transport_for(entry)`` returns the :class:`Transport` that reaches that
    endpoint.  A manifest naming only part of the roster builds only that part;
    the black box's own ``ROSTER_SET`` refusal reports what is still missing.
    """
    roster = {profile: {} for profile in PROFILE_SCOPES}
    for entry in endpoints:
        if entry.role in ALIASES:
            roster[entry.profile][entry.role] = RemoteActor(entry, transport_for(entry))
    return roster


class Fleet:
    """Every endpoint the trusted side talks to, and how.

    A manifest is only public keys.  A fleet adds the two deployment facts a
    public key cannot carry: where each endpoint keeps the file it generated --
    the X receipt child process and each tool process read their own credential
    straight off disk, so the trusted side needs a *path*, never a key -- and how
    to reach each endpoint for a signature.

    ``base_url`` decides that last fact.  With one, each endpoint is reached over
    HTTP at the port its roster place implies; without one, over the unix socket
    beside its key file.  Everything else is shared, so a deployment picks a
    transport and no other rule changes.
    """

    def __init__(self, entries, root, transport_for=None, base_url=None):
        self.entries = list(entries)
        self.root = Path(root)
        self.base_url = None if base_url is None else str(base_url).rstrip('/')
        if transport_for is not None:
            self._transport_for = transport_for
        elif self.base_url is not None:
            self._transport_for = self.http_transport
        else:
            self._transport_for = self.socket_transport

    @classmethod
    def read(cls, root, manifest, transport_for=None, base_url=None):
        """Read a manifest and the directory the endpoints wrote their keys into."""
        return cls(read_manifest(manifest), root, transport_for, base_url)

    def find(self, role, profile=None):
        """The one endpoint with this role, and this profile unless it is the worker."""
        found = [entry for entry in self.entries
                 if entry.role == role and (profile is None or entry.profile == profile)]
        require(len(found) == 1, 'FLEET_ENDPOINT')
        return found[0]

    def key_path(self, entry):
        """Where that endpoint keeps the key it generated: a path, never a key."""
        return str(self.root / key_file_name(entry.profile, entry.role))

    def socket_path(self, entry):
        return str(self.root / key_file_name(entry.profile, entry.role).replace('.key', '.sock'))

    def socket_transport(self, entry):
        """The endpoint's own signing socket, at the convention beside its key."""
        return SocketTransport(self.socket_path(entry))

    def endpoint_url(self, entry):
        """Where that endpoint's HTTP face answers, from the one port rule."""
        require(self.base_url is not None, 'FLEET_TRANSPORT')
        return '%s:%d' % (self.base_url, endpoint_port(entry.profile, entry.role))

    def http_transport(self, entry):
        """The endpoint's own HTTP face, at the port its roster place implies."""
        return HTTPTransport(self.endpoint_url(entry))

    def transport_for(self, entry):
        return self._transport_for(entry)

    def remote_key(self, entry):
        return RemoteKey(entry, self.transport_for(entry))

    def roster(self):
        return actors(self.entries, self.transport_for)

    def worker(self):
        return self.find('worker')
