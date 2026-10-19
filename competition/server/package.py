"""The public package: what W registered each endpoint as, in public facts only.

An endpoint generated its own key and published only the public half, so after
initialization it has every right to ask what W decided about it.  This assembles
one document that answers that, and nothing more:

* the roster entry W holds for every ``(profile, alias)`` -- subject, key id,
  public key and purposes;
* the *signed* records behind those entries: the key grant and every role grant,
  each with C's ``COMP-APP-C-PUBLISH-v1`` certificate exactly as W stores it;
* W's worker certificate, each profile's tool-trust certificate and W's delivery
  public key.

Nothing new is signed and no new domain is invented: an endpoint re-checks the
records with the repository's own verification rules, which is the whole point of
sending the certificates along instead of a fresh signature over the document.

The rule the result face established for exported artifacts holds here too --
private keys, the run's SQLite ledgers and every local path stay out -- and
:func:`competition.server.export.forbidden_secrets` is the check that enforces it.
"""
import json
from pathlib import Path

from competition.server.export import forbidden_secrets
from competition.support.wire import b64, canonical, require, sortset

KIND = 'competition_public_package'


def _active(store, profile, namespace):
    with store.db() as c:
        return [dict(row) for row in c.execute(
            'SELECT key, record FROM a_current WHERE profile=? AND namespace=? AND active=1',
            (profile, namespace))]


def _grant(store, profile, namespace, key):
    """One current record with C's certificate, as :meth:`TrustedState.current` verifies it."""
    with store.db() as c:
        row = store.current(c, profile, namespace, key)
    return {'record': row['record'], 'certificate': row['certificate']}


def _role_keys(store, profile, subject):
    return [json.loads(row['key']) for row in _active(store, profile, 'ROLE')
            if json.loads(row['record'])['value']['subject'] == subject]


def _actor(store, profile, who):
    """One roster entry: its public facts plus the signed records behind them."""
    grants = [_grant(store, profile, 'ROLE', key) for key in _role_keys(store, profile, who.name)]
    return {'name': who.name, 'kid': who.kid, 'public_key': b64(who.pub),
            'purposes': sortset(list(who.purposes)),
            'roles': sortset([grant['record']['value']['role'] for grant in grants]),
            'key_grant': _grant(store, profile, 'KEY', [who.kid]),
            'role_grants': grants}


def public_package(run):
    """Assemble the public package for one initialized W.

    ``run`` is an initialized ``WRun``: the roster, the worker certificate, the
    tool certificates and the delivery public come from it, and every grant comes
    from the current, certificate-verified records in W itself.
    """
    require(all(hasattr(run, name) for name in ('store', 'actors', 'worker_certificate',
                                                'tools', 'delivery_public')), 'PACKAGE_WRUN')
    store = run.store
    package = {'kind': KIND,
               'root_public': b64(store.root_public),
               'actors': {profile: {alias: _actor(store, profile, who)
                                    for alias, who in roster.items()}
                          for profile, roster in run.actors.items()},
               'worker_certificate': run.worker_certificate,
               'tools': {profile: {'certificate': info['certificate']}
                         for profile, info in run.tools.items()},
               'delivery_public': b64(run.delivery_public)}
    violations = forbidden_secrets(package)
    require(not violations, 'PACKAGE_SECRET')
    return package


def write_package(package, path):
    """Write the package to a new file, refusing to replace an existing one."""
    path = Path(path)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(package, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')
    return {'kind': KIND, 'path': str(path), 'size': path.stat().st_size}
