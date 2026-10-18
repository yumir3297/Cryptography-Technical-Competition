"""Identity face: enrollment / proof-of-possession over the trusted W.

The caller supplies only a ``subject``.  Everything else that names the
principal -- the public key, the key id and the purposes -- is read from the
profile roster, so a caller can never self-report a role or a key it does not
hold.  All hard constraints (POP signature, proof/key windows, root generation,
monotonic row version, ``ROSTER_BINDING``) stay in the black box: this module
only keeps the in-memory pending table and assembles the ``KEY_GRANT`` /
``ROLE_GRANT`` records that ``AuthorizationRun.publish`` publishes unchanged.

The two-stage shape mirrors ``competition.support.enrollment``: :meth:`begin`
hands out a pending tuple plus a nonce, the applicant signs the possession
proof, and :meth:`register` publishes the grant.  The proof shape and the signed
message are the core's, never redefined here.

The assembled record values are kept byte-for-byte with the bootstrap's own
pre-registration (``competition.profiles.authorization_seed.initialize``, the
``tup``/``kv``/``rv`` block); enrollment is a *reachable* seam, not a
replacement for that bootstrap.
"""
import os
import time

from competition.core.trusted_state import PROFILE_SCOPES, ROLES, prefix
from competition.support.scene_base import SceneReadMixin
from competition.support.scene_contract import _rec
from competition.support.wire import ProtocolError, b64, canonical, digest, require, sortset

# The key window and pending lifetime the bootstrap pre-registration uses.
KEY_LIFETIME = 1800
PENDING_TTL = 60


class _RoleView:
    """The minimal view ``SceneReadMixin._role_constraints`` reads its profile from."""

    def __init__(self, profile):
        self.profile = profile


def _line(key):
    """The exact text ``TrustedState`` stores a list key under (its ``enc``)."""
    return canonical(key).decode('utf-8')


def _tool_set(profile):
    return ['pay-sim' if profile == 'PAY-1' else 'line-sort-sim' if profile == 'IND-DEMO-1' else 'med-order-sim']


def _destination_set(profile):
    return (['pay-sim-dest'] if profile == 'PAY-1'
            else ['med-demo-ledger'] if profile == 'MED-DEMO-1'
            else sortset(['ind-release-bin', 'ind-quarantine-bin', 'ind-inspection-bay']))


def _constraints(profile, alias, role):
    if profile == 'PAY-1':
        return {'payer_set': ['payer'], 'max_amount_minor': '100000'}
    return SceneReadMixin._role_constraints(_RoleView(profile), alias, role)


class IdentityRegistry:
    """In-memory pending enrollments plus the grants they publish.

    ``run`` is an initialized run (``WRun`` or ``AuthorizationRun``); only its
    roster, ``store`` and ``publish`` are used.
    """

    def __init__(self, run):
        self.run = run
        self.base = getattr(run, 'base', run)
        self._pending = {}

    # -- stage 1: hand out a pending tuple for a roster subject -------------
    def begin(self, profile, subject):
        who = self._actor(profile, subject)
        now = int(time.time())
        tup = {'scope': PROFILE_SCOPES[profile], 'subject': subject,
               'public_key': b64(who.pub), 'kid': who.kid,
               'purposes': sortset(list(who.purposes)),
               'key_not_before': str(now), 'key_not_after': str(now + KEY_LIFETIME),
               'root_generation': '1'}
        enrollment_id = b64(os.urandom(16))
        nonce = b64(os.urandom(32))
        self._pending[enrollment_id] = {'profile': profile, 'tuple': tup, 'nonce': nonce,
                                        'created_at': now, 'expires': now + PENDING_TTL,
                                        'consumed': False, 'grant': None}
        return {'tuple': tup, 'enrollment_id': enrollment_id, 'nonce': nonce}

    # -- local fallback: the host signs the POP for a roster subject --------
    def possession(self, profile, subject, pending, iat, exp):
        """Sign the possession proof with the roster's own key for ``subject``.

        This is the trusted-side fallback that lets enrollment run before
        external role clients are connected; a real applicant signs the same
        message with the same key.
        """
        who = self._actor(profile, subject)
        message = canonical(['ZJJ-ENROLL-v1', '2.6', pending['tuple'], pending['enrollment_id'],
                             pending['nonce'], str(iat), str(exp)])
        return {'tuple': pending['tuple'], 'enrollment_id': pending['enrollment_id'],
                'nonce': pending['nonce'], 'iat': str(iat), 'exp': str(exp),
                'signature': b64(who.key.sign(message))}

    # -- stage 2: accept the POP and publish the grants ---------------------
    def register(self, profile, proof):
        """Publish ``KEY_GRANT`` and ``ROLE_GRANT`` for a possession proof."""
        require(type(proof) is dict and set(proof) ==
                {'tuple', 'enrollment_id', 'nonce', 'iat', 'exp', 'signature'}, 'ENROLL_FIELDS')
        pending = self._pending.get(proof['enrollment_id'])
        require(pending is not None, 'NO_PENDING')
        require(pending['profile'] == profile, 'PROFILE_BINDING')
        require(not pending['consumed'], 'ENROLLMENT_CONSUMED')
        require(int(time.time()) < pending['expires'], 'ENROLLMENT_EXPIRED')
        require(pending['nonce'] == proof['nonce'], 'NONCE_BINDING')
        tup = pending['tuple']
        alias = self._alias(profile, tup['subject'])
        enrollment_ref = digest(['COMP-APP-POP-v1', proof])
        grant = self._publish_key(profile, tup, enrollment_ref, proof)
        for role in self._roles(profile, alias):
            self._publish_role(profile, alias, tup, role)
        pending['consumed'] = True
        pending['grant'] = grant
        return grant

    # -- record assembly ----------------------------------------------------
    def _publish_key(self, profile, tup, enrollment_ref, proof):
        record = _rec(profile, 'KEY_GRANT', PROFILE_SCOPES[profile], {
            'subject': tup['subject'], 'public_key': tup['public_key'], 'kid': tup['kid'],
            'epoch': str(self._revision(profile, 'KEY', [tup['kid']]) + 1),
            'purposes': tup['purposes'], 'iat': tup['key_not_before'], 'exp': tup['key_not_after'],
            'root_generation': tup['root_generation'], 'enrollment_ref': enrollment_ref})
        self.base.publish(profile, 'KEY', [tup['kid']], record, active=True, enrollment=proof)
        return record

    def _publish_role(self, profile, alias, tup, role):
        key = prefix(profile) + [tup['subject'], role]
        record = _rec(profile, 'ROLE_GRANT', PROFILE_SCOPES[profile], {
            'subject': tup['subject'], 'role': role,
            'epoch': str(self._revision(profile, 'ROLE', key) + 1),
            'scope_set': [PROFILE_SCOPES[profile]], 'tool_set': _tool_set(profile),
            'destination_set': _destination_set(profile),
            'constraints': _constraints(profile, alias, role),
            'iat': tup['key_not_before'], 'exp': tup['key_not_after']})
        self.base.publish(profile, 'ROLE', key, record)
        return record

    def _roles(self, profile, alias):
        roles = [ROLES[profile][alias]]
        if profile != 'PAY-1' and alias != 'E':
            roles.append('READER')
        return roles

    # -- roster / store lookups --------------------------------------------
    def _actor(self, profile, subject):
        roster = self.run.actors.get(profile)
        require(roster is not None, 'PROFILE')
        who = next((a for a in roster.values() if a.name == subject), None)
        require(who is not None, 'ROSTER_BINDING')
        return who

    def _alias(self, profile, subject):
        for alias, actor in self.run.actors[profile].items():
            if actor.name == subject:
                return alias
        raise ProtocolError('ROSTER_BINDING')

    def _revision(self, profile, namespace, key):
        with self.run.store.db() as c:
            row = c.execute('SELECT revision FROM a_current WHERE profile=? AND namespace=? AND key=?',
                            (profile, namespace, _line(key))).fetchone()
        return row[0] if row else 0
