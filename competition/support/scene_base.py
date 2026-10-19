"""Read-only scene derivation shared by the official competition adapters.

Extracted from the retired ``scene_authority`` research module.  These methods
only re-derive current authenticated business facts for the trusted
authorization gate; they never publish, sign, reserve or dispatch.  Names and
behaviour are preserved from the original source.
"""
from competition.support.scene_contract import PROFILES, EVID_FIELDS, MAPPING, TEMPLATES
from competition.support.wire import WINDOW, canonical, digest, raw, require, sortset, strict_verify


class SceneReadMixin:
    def scope_key(self): return [self.scope[x] for x in ('domain', 'tenant', 'scenario')]

    def role_key(self, who, role): return self.scope_key() + [who.name, role]

    def _state_ref(self, ns, key, revision, body):
        return digest(['ZJJ-STATE-v1', ns, key, str(revision), body])

    def _scene_current(self, c, key):
        ns = PROFILES[self.profile][2]; row = self.current(c, ns, key)
        value = row['record']['value']
        require(row['ref'] == self._state_ref(ns, key, row['revision'], value), 'SCENE_INTEGRITY')
        return row

    def _depend(self, c, ns, key):
        r = self.current(c, ns, key)
        return {'namespace': ns, 'key': key, 'revision': str(r['revision']), 'ref': r['ref']}

    def _deps(self, c, action, task_id, scene_key, roles):
        d = []; prefix = self.scope_key()
        for ns, key in [('POLICY', prefix), ('TASK', prefix + [task_id]),
                        (PROFILES[self.profile][2], scene_key), ('BEHAVIOR', prefix + [action['principal']])]:
            d.append(self._depend(c, ns, key))
        for alias, role in roles:
            actor = self.actors[alias]
            d.append(self._depend(c, 'KEY', [actor.kid])); d.append(self._depend(c, 'ROLE', self.role_key(actor, role)))
        return sortset({(x['namespace'], tuple(x['key'])): x for x in d}.values())

    def verify_evidence(self, c, record, at=101):
        kind = PROFILES[self.profile][1]
        require(set(record) == {'version', 'profile', 'kind', 'scope', 'value'} and
                (record['profile'], record['kind'], record['version'], record['scope']) == (self.profile, kind, '2.6', self.scope), 'OBJECT_KIND')
        v = record['value']; require(set(v) == {'data', 'attestation'} and set(v['data']) == EVID_FIELDS[self.profile], 'EVIDENCE_FIELDS')
        d, a = v['data'], v['attestation']; require(set(a) == {'issuer', 'kid', 'iat', 'exp', 'sig'}, 'EVIDENCE_FIELDS')
        e = self.actors['E']; require(a['issuer'] == e.name and a['kid'] == e.kid, 'WRONG_SOURCE')
        self._credential(c, 'E', 'SOURCE', 'SOURCE')
        # The attestation is one of the windows the scene reader collects, so its
        # bound follows the chain window (``support.wire.WINDOW``): a shorter one
        # here would cap the chain no matter what the rest of it said.
        require(0 < int(a['exp']) - int(a['iat']) <= WINDOW and int(a['iat']) <= at < int(a['exp']), 'EXPIRED')
        observed = int(d['sampled_at'] if self.profile == 'IND-DEMO-1' else d['event_at'])
        require(observed <= int(d['known_at']) <= int(a['iat']) and int(a['exp']) <= observed + WINDOW, 'EVIDENCE_TIME')
        if self.profile == 'IND-DEMO-1':
            require(d['quality_flag'] == 'VALID' and d['label'] in MAPPING, 'CLAIM_FALSE')
        else:
            require(d['record_status'] == 'AVAILABLE' and d['completeness'] == 'COMPLETE' and d['template_label'] in TEMPLATES, 'CLAIM_FALSE')
        to_sign = {k: a[k] for k in ('issuer', 'kid', 'iat', 'exp')}
        strict_verify(e.pub, raw(a['sig'], 64), canonical(['ZJJ-SOURCE-v1', '2.6', self.profile, kind, self.scope, d, to_sign]))
        return True

    def _role_constraints(self, alias, role):
        if self.profile == 'IND-DEMO-1':
            if role in ('CONTROLLER', 'SOURCE', 'ISSUER', 'EXECUTOR'):
                return {'line_set': ['demo-line-a'], 'station_set': ['demo-check-1'], 'route_set': ['RELEASE', 'QUARANTINE', 'INSPECT']}
            return {'line_set': ['demo-line-a'], 'station_set': ['demo-check-1'], 'unit_set': ['unit-a'],
                    'route_set': ['INSPECT'] if role == 'QUALITY_REVIEWER' else ['RELEASE', 'QUARANTINE', 'INSPECT']}
        return {'patient_set': ['patient-a'], 'encounter_set': ['encounter-a'], 'template_set': ['DEMO-ORDER-A', 'DEMO-ORDER-B']}
