"""The role signing host: one line in, one line out, nothing else.

Modelled on the fixed-profile broker
(:func:`competition.support.broker_policy.serve`): a request names one
``{profile, role, domain, claim}`` and the answer carries the base64 signature of
``canonical([domain, claim])``.  Two more ops carry the rest of a role's real
work: ``raw`` signs the canonical bytes an in-chain caller hands over, and
``enrollment`` signs one possession proof.  Every op answers with the same
envelope, so the reader never has to know which door it knocked on.

:class:`~competition.client.signer.RoleSigner` decides what may be signed and the
owner/0600 check on the key file happens when that signer is built; this module
only carries the bytes and fails closed -- a malformed or refused request ends
the stream instead of being skipped.

``serve_connection`` answers request lines from any binary reader/writer pair, so
stdin, a socket and a test ``BytesIO`` all use the same protocol code.
"""
import base64
import json
import os
import socket
from pathlib import Path

from competition.client.signer import ENROLL_DOMAIN, split_message
from competition.support.wire import ProtocolError, b64, require

# One request line, generous for a challenge claim but far from unbounded.
MAX_REQUEST_LINE = 1 << 17

# One exact field set per op, without the ``op`` tag itself.  ``challenge`` keeps
# its original four-field shape, so a request written before the other ops existed
# still parses.
REQUEST_FIELDS = frozenset({'profile', 'role', 'domain', 'claim'})
RAW_FIELDS = frozenset({'profile', 'role', 'data'})
ENROLL_FIELDS = frozenset({'profile', 'role', 'pending', 'iat', 'exp'})
OPS = {'challenge': REQUEST_FIELDS, 'raw': RAW_FIELDS, 'enrollment': ENROLL_FIELDS}


def decode_request(line):
    """Parse one request line, refusing anything that is not exactly one op's fields."""
    require(len(line) < MAX_REQUEST_LINE or line.endswith(b'\n'), 'CLIENT_SIZE')
    try:
        request = json.loads(line)
    except (UnicodeError, json.JSONDecodeError):
        raise ProtocolError('CLIENT_MALFORMED')
    require(type(request) is dict, 'CLIENT_FIELDS')
    op = request.get('op', 'challenge')
    require(op in OPS, 'CLIENT_OP')
    require(set(request) - {'op'} == OPS[op], 'CLIENT_FIELDS')
    if op == 'challenge':
        require(type(request['claim']) is dict, 'CLIENT_CLAIM')
    elif op == 'raw':
        require(type(request['data']) is str, 'CLIENT_DATA')
    else:
        require(type(request['pending']) is dict, 'CLIENT_PENDING')
    request['op'] = op
    return request


def decode_data(text):
    """Base64-decode the one opaque signing payload, bounded in size."""
    require(len(text) <= MAX_REQUEST_LINE, 'CLIENT_SIZE')
    try:
        blob = base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
    except Exception:  # noqa: BLE001 - every decode failure is the same refusal
        raise ProtocolError('BASE64')
    require(b64(blob) == text, 'BASE64')
    return blob


def answer(line, signer):
    """Turn one request line into one response object, or raise a denial.

    ``signer`` is a :class:`~competition.client.signer.RoleSigner`: it supplies
    both the signature and the key id the response reports.
    """
    request = decode_request(line)
    op = request['op']
    if op == 'raw':
        blob = decode_data(request['data'])
        signature = signer.sign_raw(request['profile'], request['role'], blob)
        domain = split_message(blob)[0]
    elif op == 'enrollment':
        signature = signer.sign_enrollment(request['profile'], request['role'],
                                           request['pending'], request['iat'], request['exp'])
        domain = ENROLL_DOMAIN
    else:
        signature = signer.sign(request['profile'], request['role'],
                                request['domain'], request['claim'])
        domain = request['domain']
    return {'signature': signature, 'profile': request['profile'], 'role': request['role'],
            'domain': domain, 'kid': signer.kid,
            'pid': os.getpid(), 'euid': os.geteuid()}


def serve_connection(reader, writer, signer, *, once=False):
    """Answer request lines from ``reader`` until EOF; ``once`` stops after one.

    Each successful request writes exactly one response line and flushes it.  A
    refused request propagates: the host stops rather than serve around it.
    """
    while True:
        line = reader.readline(MAX_REQUEST_LINE)
        if not line:
            return
        response = answer(line, signer)
        writer.write(json.dumps(response, ensure_ascii=False, sort_keys=True).encode('utf-8') + b'\n')
        writer.flush()
        if once:
            return


def serve_unix(path, signer):
    """Listen on a 0600 unix socket, serving one connection at a time.

    The socket is the client's own endpoint, so it gets the same owner-only
    discipline as the key file.  Returns only on refusal or interrupt.
    """
    require(os.name == 'posix', 'LINUX_ONLY')
    path = Path(path)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        os.chmod(path, 0o600)
        listener.listen(1)
        try:
            while True:
                connection, _ = listener.accept()
                with connection:
                    stream = connection.makefile('rwb')
                    try:
                        serve_connection(stream, stream, signer)
                    finally:
                        stream.close()
        finally:
            path.unlink(missing_ok=True)
