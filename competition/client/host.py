"""The role signing host: one line in, one line out, nothing else.

Modelled on the fixed-profile broker
(:func:`competition.support.broker_policy.serve`): a request names one
``{profile, role, domain, claim}`` and the answer carries the base64 signature of
``canonical([domain, claim])``.  :class:`~competition.client.signer.RoleSigner`
decides what may be signed and the owner/0600 check on the key file happens when
that signer is built; this module only carries the bytes and fails closed -- a
malformed or refused request ends the stream instead of being skipped.

``serve_connection`` answers request lines from any binary reader/writer pair, so
stdin, a socket and a test ``BytesIO`` all use the same protocol code.
"""
import json
import os
import socket
from pathlib import Path

from competition.support.wire import ProtocolError, require

# One request line, generous for a challenge claim but far from unbounded.
MAX_REQUEST_LINE = 1 << 17
REQUEST_FIELDS = frozenset({'profile', 'role', 'domain', 'claim'})


def decode_request(line):
    """Parse one request line, refusing anything that is not exactly the four fields."""
    require(len(line) < MAX_REQUEST_LINE or line.endswith(b'\n'), 'CLIENT_SIZE')
    try:
        request = json.loads(line)
    except (UnicodeError, json.JSONDecodeError):
        raise ProtocolError('CLIENT_MALFORMED')
    require(type(request) is dict and set(request) == REQUEST_FIELDS, 'CLIENT_FIELDS')
    require(type(request['claim']) is dict, 'CLIENT_CLAIM')
    return request


def answer(line, signer):
    """Turn one request line into one response object, or raise a denial.

    ``signer`` is a :class:`~competition.client.signer.RoleSigner`: it supplies
    both the signature and the key id the response reports.
    """
    request = decode_request(line)
    signature = signer.sign(request['profile'], request['role'],
                            request['domain'], request['claim'])
    return {'signature': signature, 'profile': request['profile'], 'role': request['role'],
            'domain': request['domain'], 'kid': signer.kid,
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
