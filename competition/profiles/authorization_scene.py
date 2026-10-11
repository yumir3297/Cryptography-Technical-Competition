"""Read-only IND/MED business derivation for the shared trusted authorization gate.

Original finite SceneAuthority business bindings are copied with conditional
V subject separation and explicit E action scope in competition only. H and U
may share a subject. This adapter inherits no mutation or signing entry points.
Unsupported IDENTITY/PACKAGE/EVIDENCE Dep namespaces stay out of wire objects;
their current authenticated originals and transitive references are rechecked.
"""
from pathlib import Path

from competition.core.event_clock import require_window
from research.phase8.scene_authority import SceneAuthority, PROFILES, ROLES
from research.reference_executor.wire import action_hash, rec_ref, require, sortset
from research.strict_v26.upstream_schema import UpstreamSchema
from competition.profiles.scene_bindings import bound_scene


class _BoundReader:
    """Bind only original read/verify methods; never initialize a legacy W."""
    _bound = bound_scene
    _deps = SceneAuthority._deps
    _depend = SceneAuthority._depend
    _scene_current = SceneAuthority._scene_current
    _state_ref = SceneAuthority._state_ref
    scope_key = SceneAuthority.scope_key
    role_key = SceneAuthority.role_key

    def __init__(self, store, profile, actors, scope, event, schema):
        self.store, self.profile, self.actors = store, profile, actors
        self.scope, self.event, self.schema = scope, event, schema
        self.windows = []

    def current(self, c, namespace, key):
        row = self.store.current(c, self.profile, namespace, key)
        record = row['record']
        kinds = {
            'POLICY': 'POLICY', 'TASK': PROFILES[self.profile][3],
            'IDENTITY': PROFILES[self.profile][4], 'PACKAGE': 'IND_PACKAGE',
            'EVIDENCE': PROFILES[self.profile][1], 'KEY': 'KEY_GRANT', 'ROLE': 'ROLE_GRANT',
            'BEHAVIOR': 'BEHAVIOR', PROFILES[self.profile][2]: PROFILES[self.profile][2],
        }
        require(namespace in kinds and record['kind'] == kinds[namespace], 'OBJECT_KIND')
        require((record['version'], record['profile'], record['scope']) == ('2.6', self.profile, self.scope), 'WRONG_SCOPE')
        definition = 'Record_' + record['kind']
        if definition in self.schema.defs:
            self.schema.validate(record, definition)
        value = record['value']
        if 'iat' in value and 'exp' in value:
            require_window(value, self.event)
            if namespace not in ('KEY','ROLE'):
                self.windows.append(value)
        return row

    def _credential(self, c, alias, role, purpose, action=None):
        rows = self.store.credential(c, self.profile, alias, role, purpose, action, self.event)
        for row in rows:
            require_window(row['record']['value'], self.event)
            # Qualification is current at each event, not a promised grant for
            # the whole Basis lifetime. Recheck at acceptance/publication/read.
        return rows

    def _read_permission(self, c, alias, action, policy):
        require(self.actors[alias].name in policy['readers'], 'NO_ROLE')
        self._credential(c, alias, 'READER', 'READ', action)

    def verify_evidence(self, c, record, at):
        require_window(record['value']['attestation'], self.event)
        self.windows.append(record['value']['attestation'])
        return SceneAuthority.verify_evidence(self, c, record, at)


class SceneAuthorizationAdapter:
    def __init__(self, store, profile, actors):
        require(profile in PROFILES, 'PROFILE')
        self.store, self.profile, self.actors = store, profile, actors
        self.schema = UpstreamSchema(Path(__file__).resolve().parents[2], profile)

    def derive(self, c, op, event):
        action = op['action']
        scope = action['scope']
        require(scope['scenario'] == PROFILES[self.profile][0], 'WRONG_SCOPE')
        require(type(event['lo']) is int and type(event['hi']) is int and 0 <= event['lo'] <= event['hi'], 'TIME_INTERVAL')
        reader = _BoundReader(self.store, self.profile, self.actors, scope, event, self.schema)
        prefix = reader.scope_key()
        policy_record = reader.current(c, 'POLICY', prefix)['record']
        policy = policy_record['value']
        # Authorize every participant before the original _bound reads E material.
        aliases = ('H', 'G', 'X', 'U')
        if self.profile == 'MED-DEMO-1' or action['payload'].get('route') == 'INSPECT':
            aliases += ('V',)
        for alias in aliases:
            reader._read_permission(c, alias, action, policy)
        policy, task, evidence, scene, required, deps = reader._bound(
            c, action, op['task_id'], op['scene_key'], event['lo'],
        )
        task_record = reader.current(c, 'TASK', prefix + [op['task_id']])['record']
        # Check original mutable behavior state integrity as well as scene state.
        behavior_key = prefix + [action['principal']]
        behavior = reader.current(c, 'BEHAVIOR', behavior_key)
        require(behavior['ref'] == reader._state_ref('BEHAVIOR', behavior_key, behavior['revision'], behavior['record']['value']), 'BEHAVIOR_INTEGRITY')
        frozen = op['assessment']['value']
        cutoff, iat, exp = (int(frozen[k]) for k in ('cutoff', 'iat', 'exp'))
        require(0 <= cutoff <= iat <= event['lo'] and event['hi'] < exp, 'EXPIRED')
        data = evidence['value']['data']
        require(int(data['known_at']) <= cutoff, 'EVIDENCE_TIME')
        require(exp <= min(int(value['exp']) for value in reader.windows), 'EXPIRED')
        assessment_value = {
            'scope': scope, 'operation_id': action['operation_id'],
            'action_hash': action_hash(self.profile, action),
            'policy_ref': rec_ref(policy_record), 'task_ref': rec_ref(task_record),
            'evidence_refs': [rec_ref(evidence)], 'cutoff': str(cutoff),
            'history_mode': 'DISABLED', 'result': 'MATCH', 'required_reviews': required,
            'iat': str(iat), 'exp': str(exp),
        }
        if self.profile == 'IND-DEMO-1':
            assessment_value.update({
                'decision_package_ref': policy['decision_package_ref'], 'method': 'ind-fixed-v1',
                'label': data['label'], 'proposed_route': action['payload']['route'],
            })
        else:
            assessment_value.update({
                'method': 'med-fixed-v1', 'template_label': data['template_label'],
                'proposed_template': action['payload']['template_id'],
            })
        deps = sortset(deps)
        return {
            'required_reviews': required, 'deps': deps, 'basis_deps': deps,
            'assessment_value': assessment_value, 'policy_ref': rec_ref(policy_record),
            'task_ref': rec_ref(task_record), 'evidence_refs': [rec_ref(evidence)],
            'policy_record': policy_record, 'task_record': task_record, 'evidence_records': [evidence],
        }
