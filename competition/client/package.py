"""Reading the public package back: an endpoint checks its own registration.

The trusted side assembles the package (:mod:`competition.server.package`); this
is the other end of that hand-off.  An endpoint takes the document, its own public
key and what it announced, and checks the five things it is entitled to know:

* it is in the roster, under the public key and key id it actually holds;
* the subject is the name it proposed;
* the purposes are the ones this repository's own tables give that alias -- not
  widened, and not trimmed either;
* the key grant and every role grant carry C's ``COMP-APP-C-PUBLISH-v1``
  certificate, and it verifies against the ``root_public`` in the package;
* each record's namespace, key, profile and scope are the ones for *this* place,
  so another endpoint's record cannot be passed off as this one's.

Nothing here invents a signing domain: the checks are the repository's own, run in
reverse.  A failure raises :class:`~competition.support.wire.ProtocolError` with
the rule that failed, and the client host turns that into ``DENY:<code>``.
"""
import json
from pathlib import Path

from competition.core.common_w import WORKER_PURPOSES
from competition.core.trusted_state import PROFILE_SCOPES, prefix
from competition.server.roster import ALIASES, owner_purposes
from competition.support.final_fact import verify_certificate
from competition.support.wire import (
    ProtocolError, canonical, keyid, raw, require, sortset, strict_verify,
)

KIND = 'competition_public_package'
FIELDS = frozenset({'kind', 'root_public', 'actors', 'worker_certificate', 'tools',
                    'delivery_public'})
ENTRY_FIELDS = frozenset({'name', 'kid', 'public_key', 'purposes', 'roles',
                          'key_grant', 'role_grants'})
GRANT_FIELDS = frozenset({'record', 'certificate'})
CERTIFICATE_FIELDS = frozenset({'claim', 'signature'})
# The domains the trusted side signed these records under; the repository's own.
PUBLISH_DOMAIN = 'COMP-APP-C-PUBLISH-v1'
WORKER_GRANT_DOMAIN = 'COMP-W-WORKER-GRANT-v1'


def read_package(path):
    """Read one public package, refusing anything that is not exactly its shape."""
    try:
        package = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ProtocolError('PACKAGE_FORMAT')
    require(type(package) is dict and set(package) == FIELDS, 'PACKAGE_FORMAT')
    require(package['kind'] == KIND, 'PACKAGE_FORMAT')
    return package


def _root_public(package):
    return raw(package['root_public'], 32)


def _certificate(certificate, root_public, domain):
    """Verify one C-signed certificate and return the claim it covers."""
    require(type(certificate) is dict and set(certificate) == CERTIFICATE_FIELDS,
            'PACKAGE_CERTIFICATE')
    claim = certificate['claim']
    require(type(claim) is dict, 'PACKAGE_CERTIFICATE')
    strict_verify(root_public, raw(certificate['signature'], 64), canonical([domain, claim]))
    return claim


def _grant(grant, root_public, profile, namespace, key):
    """Check one published record and return its value."""
    require(type(grant) is dict and set(grant) == GRANT_FIELDS, 'PACKAGE_GRANT')
    claim = _certificate(grant['certificate'], root_public, PUBLISH_DOMAIN)
    require(claim.get('profile') == profile and claim.get('namespace') == namespace and
            claim.get('key') == key and claim.get('active') is True and
            claim.get('record') == grant['record'], 'PACKAGE_GRANT')
    record = grant['record']
    require(type(record) is dict and record.get('profile') == profile and
            record.get('scope') == PROFILE_SCOPES[profile], 'PACKAGE_GRANT')
    return record['value']


def _bound(entry, public, kid):
    """The entry must be about the key this endpoint actually holds."""
    require(entry['kid'] == kid and keyid(public) == kid and
            raw(entry['public_key'], 32) == public, 'PACKAGE_KEY_BINDING')


def check_actor(package, profile, role, *, public, kid, name=None, purposes=None):
    """Check one roster endpoint's registration and return its public facts."""
    require(profile in PROFILE_SCOPES and role in ALIASES, 'PACKAGE_ROLE')
    entry = package['actors'].get(profile, {}).get(role)
    require(type(entry) is dict and set(entry) == ENTRY_FIELDS, 'PACKAGE_MISSING')
    root_public = _root_public(package)
    _bound(entry, public, kid)
    if name is not None:
        require(entry['name'] == name, 'PACKAGE_SUBJECT')
    # The grant this repository gives that alias, not the one the package claims:
    # an endpoint must be able to see that nobody widened or trimmed it.
    require(entry['purposes'] == owner_purposes(role), 'PACKAGE_PURPOSES')
    if purposes is not None:
        require(sortset(list(purposes)) == entry['purposes'], 'PACKAGE_PURPOSES')
    grant = _grant(entry['key_grant'], root_public, profile, 'KEY', [kid])
    require(grant['kid'] == kid and grant['public_key'] == entry['public_key'] and
            grant['subject'] == entry['name'] and grant['purposes'] == entry['purposes'],
            'PACKAGE_KEY_BINDING')
    roles = []
    for role_grant in entry['role_grants']:
        require(type(role_grant) is dict and set(role_grant) == GRANT_FIELDS, 'PACKAGE_GRANT')
        value = role_grant['record']['value']
        require(type(value) is dict and type(value.get('role')) is str, 'PACKAGE_GRANT')
        _grant(role_grant, root_public, profile, 'ROLE',
               prefix(profile) + [entry['name'], value['role']])
        require(value['subject'] == entry['name'] and
                value['scope_set'] == [PROFILE_SCOPES[profile]], 'PACKAGE_ROLE_BINDING')
        roles.append(value['role'])
    require(sortset(roles) == entry['roles'], 'PACKAGE_ROLE_BINDING')
    return {'role': role, 'name': entry['name'], 'kid': entry['kid'],
            'public_key': entry['public_key'], 'purposes': list(entry['purposes']),
            'roles': list(entry['roles'])}


def check_worker(package, *, public, kid):
    """Check W's worker certificate: C-signed, and about this endpoint's key."""
    claim = _certificate(package['worker_certificate'], _root_public(package),
                         WORKER_GRANT_DOMAIN)
    require(claim.get('kid') == kid and raw(claim.get('public_key'), 32) == public,
            'PACKAGE_KEY_BINDING')
    profiles = claim.get('profiles')
    require(claim.get('subject') == 'competition-worker' and claim.get('active') is True and
            claim.get('revision') == '1' and claim.get('purposes') == list(WORKER_PURPOSES) and
            type(profiles) is list and set(profiles) == set(PROFILE_SCOPES) and
            claim.get('scopes') == [PROFILE_SCOPES[profile] for profile in profiles],
            'PACKAGE_WORKER_GRANT')
    return {'role': 'worker', 'name': claim['subject'], 'kid': claim['kid'],
            'public_key': claim['public_key'], 'purposes': list(WORKER_PURPOSES), 'roles': []}


def check_tool(package, profile, *, public, kid):
    """Check this profile's tool-trust certificate: C-signed, about this endpoint's key."""
    require(profile in PROFILE_SCOPES, 'PACKAGE_ROLE')
    certificate = package['tools'].get(profile, {}).get('certificate')
    require(certificate is not None, 'PACKAGE_MISSING')
    record = verify_certificate(certificate, _root_public(package), profile)
    require(record['scope'] == PROFILE_SCOPES[profile], 'PACKAGE_GRANT')
    value = record['value']
    require(value['kid'] == kid and keyid(public) == kid and
            raw(value['public_key'], 32) == public, 'PACKAGE_KEY_BINDING')
    return {'role': 'tool', 'name': value['issuer'], 'kid': value['kid'],
            'public_key': value['public_key'], 'purposes': [], 'roles': []}


def check(package, profile, role, *, public, kid, name=None, purposes=None):
    """Check whatever this kind of endpoint was registered as; one door for all three."""
    if role == 'worker':
        return check_worker(package, public=public, kid=kid)
    if role == 'tool':
        return check_tool(package, profile, public=public, kid=kid)
    return check_actor(package, profile, role, public=public, kid=kid,
                       name=name, purposes=purposes)
