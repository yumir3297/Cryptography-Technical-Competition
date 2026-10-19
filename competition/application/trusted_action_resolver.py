"""IND V1 resolver: authenticated proposal -> complete Action + unsigned approvals.

Trusted startup fixes the profile and Task. No participant signer or seed is
imported. The caller must separately obtain actual H/U/V/G/X approval messages.
"""
import copy
import json
from competition.application.candidate_proposal import CandidateProposal
from competition.application.request_store import RequestStore
from competition.core.trusted_state import prefix, enc, ROLES, PROFILE_SCOPES
from competition.core.event_clock import require_window
from competition.core.w_state import WState
from competition.profiles.authorization_scene import SceneAuthorizationAdapter
from competition.support.final_fact import verify_certificate
from competition.support.wire import require, raw, canonical, strict_verify, digest, rec_ref, action_hash

PROFILE = 'IND-DEMO-1'
AUTH_DOMAIN = 'ZJJ-APP-PROPOSAL-v1'

class TrustedActionResolver:
    def __init__(self, state, task_id, *, profile=PROFILE):
        require(profile == PROFILE, 'PROFILE')
        raw(task_id, 16)
        self.state, self.task_id, self.profile = state, task_id, profile
        self.requests = RequestStore(state)
        self.business = SceneAuthorizationAdapter(WState(state), profile, state.actors[profile])

    def _authenticate(self, c, proposal, auth, event):
        require(type(auth) is dict and set(auth) == {'claim', 'signature'}, 'IDENTITY_REQUIRED')
        claim = auth['claim']
        require(type(claim) is dict and set(claim) == {'profile', 'task_id', 'proposal', 'iat', 'exp'},
                'AUTH_FIELDS')
        require((claim['profile'], claim['task_id'], claim['proposal']) ==
                (self.profile, self.task_id, proposal), 'AUTH_BINDING')
        holder = self.state.actors[self.profile]['H']
        strict_verify(holder.pub, raw(auth['signature'], 64), canonical([AUTH_DOMAIN, claim]))
        require_window(claim, event)
        self.state.credential(c, self.profile, 'H', ROLES[self.profile]['H'], 'IssueRequest', None, event)
        self.state.credential(c, self.profile, 'H', 'READER', 'READ', None, event)
        return holder

    def _record(self, kind, value):
        return {'version': '2.6', 'profile': self.profile, 'kind': kind,
                'scope': copy.deepcopy(PROFILE_SCOPES[self.profile]), 'value': value}

    def _approval_request(self, action, scene_key, derived):
        av = derived['assessment_value']
        assessment = self._record('ASSESSMENT', copy.deepcopy(av))
        basis = self._record('BASIS', {
            'scope': action['scope'], 'operation_id': action['operation_id'], 'action': action,
            'action_hash': action_hash(self.profile, action), 'policy_ref': derived['policy_ref'],
            'task_ref': derived['task_ref'], 'evidence_refs': derived['evidence_refs'],
            'assessment_ref': rec_ref(assessment), 'required_reviews': derived['required_reviews'],
            'deps': derived['basis_deps'], 'iat': av['iat'], 'exp': av['exp']})
        ctx = {k: copy.deepcopy(action[k]) for k in
               ('scope', 'operation_id', 'principal', 'holder', 'holder_kid', 'executor')}
        ctx.update(action_hash=basis['value']['action_hash'], policy_ref=derived['policy_ref'],
                   basis_ref=rec_ref(basis))
        return {'action': copy.deepcopy(action), 'task_id': self.task_id, 'scene_key': scene_key,
                'assessment': assessment, 'basis': basis, 'ctx': ctx,
                'required': derived['required_reviews'], 'deps': derived['deps']}

    def resolve(self, value, auth):
        proposal = CandidateProposal.parse(value)
        p = self.profile
        proposal_ref = digest(['ZJJ-APP-PROPOSAL-INTENT-v1', p, self.task_id, proposal])
        with self.state.tx() as c:
            event = self.state.event(c, p, '', 'AUTHZ_READ', proposal_ref)
            holder = self._authenticate(c, proposal, auth, event)
            key = digest(['ZJJ-APP-REQUEST-KEY-v1', p, holder.name, self.task_id, proposal['request_id']])
            old = self.requests._existing(c, key, proposal_ref)
            if old is not None:
                self.state.read_permission(c, p, 'H', old['action'], event)
                return copy.deepcopy(old)
            taskrow = self.state.current(c, p, 'TASK', prefix(p) + [self.task_id])
            policyrow = self.state.current(c, p, 'POLICY', prefix(p))
            task, policy = taskrow['record']['value'], policyrow['record']['value']
            require_window(task, event); require_window(policy, event)
            require(task['policy_ref'] == policyrow['ref'], 'STALE')
            require((task['holder'], task['holder_kid']) == (holder.name, holder.kid), 'WRONG_HOLDER')
            units = [u for u in task['allowed_units'] if u['unit_id'] == proposal['unit_id']]
            route = proposal['route']
            require(len(units) == 1 and route in task['allowed_routes'], 'TASK_SCOPE')
            unit = units[0]
            require(task['route_destinations'][route.lower()] == policy['route_destinations'][route.lower()]
                    and task['tool'] == policy['tool'] and task['tool_version'] == policy['tool_version'],
                    'TOOL_BINDING')
            executor = self.state.actors[p]['X']
            require(task['executor'] == policy['executor'] == executor.name and
                    policy['executor_kid'] == executor.kid, 'KEY_BINDING')
            action = {'scope': copy.deepcopy(PROFILE_SCOPES[p]),
                      'operation_id': self.requests._new_id(c), 'principal': task['principal'],
                      'holder': holder.name, 'holder_kid': holder.kid, 'executor': executor.name,
                      'tool': policy['tool'], 'tool_version': policy['tool_version'],
                      'destination': policy['route_destinations'][route.lower()], 'payload': {
                          'line_id': task['line_id'], 'station_id': task['station_id'],
                          'unit_id': unit['unit_id'], 'batch_id': unit['batch_id'],
                          'inspection_cycle': unit['inspection_cycle'], 'phase': unit['phase'], 'route': route}}
            self.state.schemas[p].validate(action, 'Action')
            self.state.credential(c, p, 'H', ROLES[p]['H'], 'IssueRequest', action, event)
            self.state.credential(c, p, 'X', ROLES[p]['X'], 'Acceptance', action, event)
            self.state.read_permission(c, p, 'H', action, event)
            toolkey = enc([action[k] for k in ('tool', 'tool_version', 'destination')])
            tool = c.execute('SELECT * FROM w_tool WHERE profile=? AND key=?', (p, toolkey)).fetchone()
            require(tool is not None, 'TOOL_TRUST_UNKNOWN')
            require(not tool['halted'], 'TRUSTED_CONTRADICTION')
            cert = json.loads(tool['certificate'])
            trust = verify_certificate(cert, self.state.root_public, p)
            require(trust['scope'] == action['scope'] and tool['origin'] == cert['claim']['ledger_origin'] and
                    toolkey == enc([trust['value'][k] for k in ('tool', 'tool_version', 'destination')]),
                    'TOOL_BINDING')
            require_window(trust['value'], event)
            scene_key = prefix(p) + [task['line_id'], unit['unit_id']]
            evidence = self.state.current(c, p, 'EVIDENCE', scene_key)['record']['value']
            identity = self.state.current(c, p, 'IDENTITY', prefix(p) + [unit['unit_id']])['record']['value']
            package = self.state.current(c, p, 'PACKAGE', prefix(p))['record']['value']
            business_windows = (task, policy, identity, package, evidence['attestation'])
            for window in business_windows:
                require_window(window, event)
            exp = min(event['lo'] + 90, *(int(window['exp']) for window in business_windows))
            draft = {'action': action, 'task_id': self.task_id, 'scene_key': scene_key,
                     'assessment': {'value': {'cutoff': str(event['lo']), 'iat': str(event['lo']), 'exp': str(exp)}}}
            derived = self.business.derive(c, draft, event)
            row = {'key': key, 'action': action, 'task_id': self.task_id, 'scene_key': scene_key,
                   'approval_request': self._approval_request(action, scene_key, derived),
                   'sources': {'task_ref': taskrow['ref'], 'policy_ref': policyrow['ref'],
                               'holder_kid': holder.kid, 'executor_kid': executor.kid, 'tool_ref': rec_ref(trust)}}
            self.requests._insert(c, proposal_ref, row)
            return copy.deepcopy(row)
