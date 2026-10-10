"""Research codec: restricted JCS and strict points plus mature Ed25519 verify.

Point arithmetic here is a public-input rejection filter, not signing crypto.
This module does not validate historical authority or implement the R2 service.
"""
import base64
import hashlib
import json
import re
from functools import lru_cache
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MAX_OBJECT = 65536
MAX_PACKAGE = 1048576
P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P


class CheckError(ValueError):
    def __init__(self, code, truth='F'):
        self.code, self.truth = code, truth
        super().__init__(truth + '/' + code)


def require(ok, code='BINDING', truth='F'):
    if not ok:
        raise CheckError(code, truth)


def enc(value):
    def check(v, depth=0):
        require(depth <= 32, 'FORMAT')
        if isinstance(v, dict):
            require(all(isinstance(k, str) and k.isascii() for k in v), 'FORMAT')
            for item in v.values():
                check(item, depth + 1)
        elif isinstance(v, list):
            require(len(v) <= 256, 'FORMAT')
            for item in v:
                check(item, depth + 1)
        elif isinstance(v, str):
            require(len(v) <= 1024, 'FORMAT')
            try:
                v.encode('utf-8', 'strict')
            except UnicodeError:
                raise CheckError('FORMAT') from None
        else:
            require(type(v) is bool, 'FORMAT')
    check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def parse(wire, limit=MAX_PACKAGE):
    require(isinstance(wire, bytes) and len(wire) <= limit, 'FORMAT')
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'FORMAT')
            result[k] = v
        return result
    try:
        value = json.loads(wire.decode('utf-8', 'strict'), object_pairs_hook=pairs)
        require(enc(value) == wire, 'FORMAT')
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise CheckError('FORMAT') from None


def b64(raw):
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def unb64(value, length):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]+', value), 'FORMAT')
    try:
        raw = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
    except ValueError:
        raise CheckError('FORMAT') from None
    require(len(raw) == length and b64(raw) == value, 'FORMAT')
    return raw


def digest(value):
    return b64(hashlib.sha256(enc(value)).digest())


def key_id(pk):
    return digest(['ZJJ-KEY-v1', 'Ed25519', b64(pk)])


def core_ref(core):
    return digest(['ZJJ-OBJ-v1', core['protected'], core['body']])


def commit_ref(record):
    return digest(['ZJJ-RECORD-v1', '2.6', record['profile'], 'COMMIT', record['scope'], record['value']])


def action_hash(profile, action):
    return digest(['ZJJ-ACTION-v1', '2.6', profile, action])


def candidate_ref(obj):
    domain = {'AcceptanceObservationQuery': 'ZJJ-TIME-QUERY-PROPOSED-v2',
              'AcceptanceObservation': 'ZJJ-TIME-OBS-PROPOSED-v2'}[obj['protected']['type']]
    return digest([domain, obj['protected'], obj['body']])


def fact_id(fact):
    return digest(['ZJJ-ACCEPT-FACT-PROPOSED-v2', fact])


def to_sign(obj):
    return enc(['ZJJ-TIME-SIG-PROPOSED-v2', obj['protected'], obj['body']])


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % P
    bb = (y1 + x1) * (y2 + x2) % P
    cc = 2 * D * t1 * t2 % P
    dd = 2 * z1 * z2 % P
    e, f, g, h = (bb-aa) % P, (dd-cc) % P, (dd+cc) % P, (bb+aa) % P
    return e*f % P, g*h % P, f*g % P, e*h % P


@lru_cache(maxsize=1024)
def point_ok(raw):
    if len(raw) != 32:
        return False
    number = int.from_bytes(raw, 'little')
    sign, y = number >> 255, number & (2**255 - 1)
    if y >= P:
        return False
    yy = y*y % P
    den = (D*yy + 1) % P
    if den == 0:
        return False
    xx = (yy-1) * pow(den, P-2, P) % P
    x = pow(xx, (P+3)//8, P)
    if x*x % P != xx:
        x = x * pow(2, (P-1)//4, P) % P
    if x*x % P != xx or (x == 0 and sign):
        return False
    if x % 2 != sign:
        x = P-x
    if x == 0 and y == 1:
        return False
    q, r, n = (x, y, 1, x*y % P), (0, 1, 1, 0), L
    while n:
        if n & 1:
            r = _add(r, q)
        q = _add(q, q)
        n >>= 1
    return r[0] == 0 and (r[1]-r[2]) % P == 0


def verify_signature(obj, pk):
    require(point_ok(pk), 'SIGNATURE')
    require(obj['protected']['kid'] == key_id(pk), 'SIGNATURE')
    sig = unb64(obj['sig'], 64)
    require(point_ok(sig[:32]) and int.from_bytes(sig[32:], 'little') < L, 'SIGNATURE')
    try:
        Ed25519PublicKey.from_public_bytes(pk).verify(sig, to_sign(obj))
    except Exception:
        raise CheckError('SIGNATURE') from None
    return True
