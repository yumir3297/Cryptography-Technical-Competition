"""Export one operation's result with independently verifiable evidence.

A caller that has driven an operation to a committed state can ask the trusted
side for everything a third party needs to re-check the result *without* the
trusted host's private material:

* the named run identity (commit + source digests + dirty list),
* the public roster (subject / kid / public key only),
* the signed chain messages, so an independent verifier can re-run every
  Ed25519 check from the package alone,
* the authenticated ``status`` / ``audit`` read projections,
* the independent tool-ledger snapshot.

Private keys and the run's SQLite ledgers never enter the bundle.  ``write_bundle``
lays the package out as ``bundle.json`` + ``chain.json`` + ``manifest.json`` and
``verify_bundle`` re-checks the manifest hashes, the public-only rule and the
signed chain from the exported bytes.
"""
import base64
import hashlib
import json
from pathlib import Path

from competition.core.trusted_state import PROFILE_SCOPES
from competition.support import artifact
from competition.support.wire import b64, canonical, raw, require, strict_verify
from competition import w_cases

KIND = 'competition_operation_export'
MANIFEST_KIND = 'competition_operation_export_manifest'
VERIFY_KIND = 'competition_operation_export_verification'
# Evidence files the bundle directory is allowed to contain.
EVIDENCE_FILES = ('bundle.json', 'chain.json', 'manifest.json')

# One signed chain message each, with the roster alias that signed it.  This is
# the same mapping ``artifact.signed_messages_valid`` re-verifies.
CHAIN_ALIASES = (('issue', 'H'), ('permit', 'G'), ('authorization', 'U'),
                 ('challenge_request', 'H'), ('challenge', 'X'), ('proof', 'H'))
REVIEW_ALIAS = 'V'

# Field names that are public by design and must not be mistaken for secrets.
_PUBLIC_NAMES = ('public_key', 'kid', 'keyid', 'key_id', 'public')
# A field named exactly one of these holds private material whatever its shape.
_ALWAYS_SECRET = ('private_key', 'privkey', 'private', 'secret', 'secret_key',
                  'seed', 'password')
# Substrings that only appear in a field name if private material leaked out.
_SECRET_PARTS = ('private', 'secret', 'seed', 'password', 'privkey')
# A 32-byte Ed25519 private key base64url-encoded is this many characters.
_PRIVATE_KEY_LENGTH = 43


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def _row(path, file):
    """One manifest row for a file already written under ``path``."""
    data = file.read_bytes()
    return {'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


# -- public projections -----------------------------------------------------
def public_roster(run):
    """The roster with only the public half of every actor (never ``.key``)."""
    return {profile: {alias: {'subject': actor.name, 'kid': actor.kid,
                              'public_key': b64(actor.pub)}
                      for alias, actor in roster.items()}
            for profile, roster in run.store.actors.items()}


def chain_projection(profile, op):
    """The signed chain messages, enough to re-verify every signature."""
    return {'profile': profile,
            'operation_id': op['action']['operation_id'],
            'messages': {name: op[name] for name, _ in CHAIN_ALIASES},
            'reviews': list(op['reviews'])}


def operation_bundle(run, profile, op, status, audit):
    """Pure assembly of the export bundle for one committed operation.

    ``status`` and ``audit`` are the authenticated read projections the caller
    just obtained; ``op`` is the assembled, signed operation the trusted service
    held for it.  Nothing here reads a private key or opens a ledger file.
    """
    operation_id = op['action']['operation_id']
    bundle = {'kind': KIND,
              'build': artifact.build_identity(),
              'profile': profile,
              'operation_id': operation_id,
              'roster': public_roster(run),
              'root_public': b64(run.store.root_public),
              'worker_certificate': run.worker_certificate,
              'status': status,
              'audit': audit,
              'chain_valid': artifact.signed_messages_valid(run, profile, op),
              'tools': {p: w_cases.tool_snapshot(run, p) for p in PROFILE_SCOPES},
              'chain': chain_projection(profile, op)}
    violations = forbidden_secrets(bundle)
    require(not violations, 'EXPORT_SECRET')
    return bundle


# -- leaked-secret detection ------------------------------------------------
def _looks_like_private_key(value):
    """A 32-byte Ed25519 private key base64url-encoded is 43 characters."""
    if type(value) is not str or len(value) != _PRIVATE_KEY_LENGTH:
        return False
    try:
        return len(base64.urlsafe_b64decode(value + '=')) == 32
    except Exception:
        return False


def _credential_path(value):
    return type(value) is str and value.lower().endswith(('.key', '.sqlite'))


def _secret_field(name, value):
    """True when a field name/value pair looks like leaked private key material.

    ``public_key``/``kid`` and the protocol's dependency/resource ``key`` lists
    are public and never flagged; only a private-key-shaped value under a
    key-named field (or a field that is secret by name alone) counts.
    """
    low = name.lower()
    if low in _PUBLIC_NAMES or 'public' in low:
        return False
    if low in _ALWAYS_SECRET:
        return True
    if low == 'key' or any(part in low for part in _SECRET_PARTS):
        return _looks_like_private_key(value) or _credential_path(value)
    return False


def forbidden_secrets(value, where='$'):
    """Return every spot that looks like private material leaked into ``value``.

    Flags a private-key-shaped value under a key-named field, a secret-named
    field, or any string naming a ``*.key`` / ``*.sqlite`` file.  The protocol's
    public ``public_key`` / ``kid`` / ref values and its dependency ``key`` lists
    are not flagged.
    """
    bad = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = '%s.%s' % (where, key)
            if isinstance(key, str) and _secret_field(key, item):
                bad.append('%s (private key material)' % path)
            bad.extend(forbidden_secrets(item, path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            bad.extend(forbidden_secrets(item, '%s[%d]' % (where, index)))
    elif _credential_path(value):
        bad.append('%s (credential path)' % where)
    return bad


def _verify_chain(bundle, chain):
    """Re-run every signed-chain check from the exported public material alone."""
    profile = bundle['profile']
    roster = bundle['roster'][profile]
    for name, alias in CHAIN_ALIASES:
        message = chain['messages'][name]
        strict_verify(raw(roster[alias]['public_key'], 32), raw(message['sig'], 64),
                      canonical(['ZJJ-SIG-v1', message['protected'], message['body']]))
    for message in chain['reviews']:
        strict_verify(raw(roster[REVIEW_ALIAS]['public_key'], 32), raw(message['sig'], 64),
                      canonical(['ZJJ-SIG-v1', message['protected'], message['body']]))
    return True


def _check_row(out_dir, row):
    require(isinstance(row, dict) and set(row) == {'path', 'size', 'sha256'}, 'EXPORT_MANIFEST')
    require(row['path'] in EVIDENCE_FILES, 'EXPORT_MANIFEST')
    path = out_dir / row['path']
    require(path.is_file(), 'EXPORT_MISSING')
    data = path.read_bytes()
    require(len(data) == row['size'], 'EXPORT_SIZE')
    require(hashlib.sha256(data).hexdigest() == row['sha256'], 'EXPORT_SHA256')


# -- write / verify ---------------------------------------------------------
def write_bundle(bundle, out_dir):
    """Write ``bundle`` as a self-describing evidence package under ``out_dir``.

    Layout: ``chain.json`` (signed chain), ``bundle.json`` (projections plus a
    manifest of the evidence files) and ``manifest.json`` (hashes over every
    exported file, including ``bundle.json`` itself).
    """
    out = Path(out_dir)
    if out.exists():
        require(out.is_dir() and not any(out.iterdir()), 'EXPORT_DIR_NOT_EMPTY')
    else:
        out.mkdir(parents=True)
    require(bundle.get('kind') == KIND and 'chain' in bundle, 'EXPORT_BUNDLE')
    chain = bundle['chain']
    chain_path = out / 'chain.json'
    chain_path.write_bytes(_json_bytes(chain))
    manifest = [_row('chain.json', chain_path)]
    body = {key: value for key, value in bundle.items() if key != 'chain'}
    body['manifest'] = manifest
    bundle_path = out / 'bundle.json'
    bundle_path.write_bytes(_json_bytes(body))
    files = [_row('bundle.json', bundle_path)] + manifest
    total = {'kind': MANIFEST_KIND,
             'profile': bundle['profile'],
             'operation_id': bundle['operation_id'],
             'build': bundle['build'],
             'files': files}
    (out / 'manifest.json').write_bytes(_json_bytes(total))
    return {'kind': KIND, 'out_dir': str(out), 'profile': bundle['profile'],
            'operation_id': bundle['operation_id'],
            'files': [row['path'] for row in files] + ['manifest.json'],
            'manifest': files, 'chain_valid': bundle['chain_valid']}


def verify_bundle(out_dir):
    """Independently verify an exported package from its own bytes.

    Checks that the directory holds only the expected evidence files, that every
    manifest hash matches, that no private material leaked in, and that the whole
    signed chain re-verifies against the bundle's own public roster.
    """
    out = Path(out_dir)
    require(out.is_dir(), 'EXPORT_DIR')
    require(sorted(p.name for p in out.iterdir()) == sorted(EVIDENCE_FILES), 'EXPORT_FILES')
    total = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    require(total.get('kind') == MANIFEST_KIND, 'EXPORT_MANIFEST')
    rows = total.get('files')
    require(isinstance(rows, list) and sorted(row.get('path') for row in rows)
            == ['bundle.json', 'chain.json'], 'EXPORT_MANIFEST')
    for row in rows:
        _check_row(out, row)
    bundle = json.loads((out / 'bundle.json').read_text(encoding='utf-8'))
    chain = json.loads((out / 'chain.json').read_text(encoding='utf-8'))
    require(bundle.get('kind') == KIND, 'EXPORT_BUNDLE')
    require(bundle.get('manifest') == [row for row in rows if row['path'] == 'chain.json'],
            'EXPORT_MANIFEST')
    require(bundle.get('operation_id') == total.get('operation_id')
            == chain.get('operation_id'), 'EXPORT_BINDING')
    require(bundle.get('profile') == total.get('profile') == chain.get('profile'), 'EXPORT_BINDING')
    violations = forbidden_secrets(bundle) + forbidden_secrets(chain) + forbidden_secrets(total)
    require(not violations, 'EXPORT_SECRET')
    _verify_chain(bundle, chain)
    return {'kind': VERIFY_KIND, 'passed': True, 'profile': bundle['profile'],
            'operation_id': bundle['operation_id'], 'files_checked': len(total['files']),
            'chain_valid': True,
            'scope': 'Manifest, public-only and signed-chain check over the exported bytes; '
                     'not a re-run of the operation.'}
