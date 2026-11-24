"""Offline evidence verifier: signatures, refs and the GoalFloor decision.

It deliberately does not open a W database or call CommonW.  It recomputes every
hash/ref from the package bytes and the externally pinned trust anchor.  It can
prove cryptographic binding; it cannot prove that W's stored totals were honest
or that a simulated tool affected the physical world.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from competition.core.goal_floor import (action_selector, evaluate as evaluate_goal,
                                         goal_ref, state_digest, validate_claim)
from competition.support.final_fact import final_fact_id, final_sign_bytes, verify_certificate
from competition.support.schema import CompetitionSchema
from competition.support.wire import (ProtocolError, action_hash, b64, canonical,
    digest, keyid, msgref, raw, rec_ref, require, sortset, strict_verify)

ROOT = Path(__file__).resolve().parents[2]
NS_STATE = {'UNIT', 'ENCOUNTER', 'BEHAVIOR'}


class Report:
    def __init__(self):
        self.checks = []

    def run(self, name, fn, kind='cryptographic'):
        try:
            detail = fn()
            self.checks.append({'check': name, 'status': 'PASS', 'kind': kind,
                                'detail': detail if isinstance(detail, (str, int, bool, dict, list)) else None})
            return True
        except ProtocolError as exc:
            self.checks.append({'check': name, 'status': 'FAIL', 'kind': kind,
                                'error': exc.code})
            return False
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            self.checks.append({'check': name, 'status': 'FAIL', 'kind': kind,
                                'error': type(exc).__name__ + ': ' + str(exc)[:160]})
            return False

    def result(self):
        return {'status': 'PASS' if all(c['status'] == 'PASS' for c in self.checks) else 'FAIL',
                'checks': self.checks, 'passed': sum(c['status'] == 'PASS' for c in self.checks),
                'failed': sum(c['status'] == 'FAIL' for c in self.checks),
                'skipped': sum(c['status'] == 'SKIP' for c in self.checks)}

    def skip(self, name, reason):
        self.checks.append({'check': name, 'status': 'SKIP', 'kind': 'scope',
                            'detail': reason})


def _row_ref(namespace, key, revision, record):
    if namespace in NS_STATE:
        return digest(['ZJJ-STATE-v1', namespace, key, str(revision), record['value']])
    return rec_ref(record)


def _verify_message(message, actor, profile, scope):
    require(type(message) is dict and set(message) == {'protected', 'body', 'sig'}, 'MESSAGE_FIELDS')
    protected, body = message['protected'], message['body']
    require(set(protected) == {'proto', 'version', 'profile', 'alg', 'type', 'issuer', 'kid'},
            'PROTECTED_FIELDS')
    require((protected['proto'], protected['version'], protected['profile'], protected['alg']) ==
            ('ZJJ-CORE-COMP-1', '2.6', profile, 'Ed25519'), 'PROTECTED_BINDING')
    require((protected['issuer'], protected['kid']) == (actor['name'], actor['kid']), 'ISSUER_BINDING')
    require(set(body) == {'id', 'scope', 'iat', 'exp', 'aud', 'refs', 'deps', 'payload'},
            'BODY_FIELDS')
    require(body['scope'] == scope, 'SCOPE_BINDING')
    require(int(body['iat']) <= int(body['exp']), 'TIME_ORDER')
    require(body['aud'] == sortset(body['aud']), 'AUDIENCE_ORDER')
    require(body['refs'] == sortset(body['refs']), 'REF_ORDER')
    require(body['deps'] == sortset(body['deps']), 'DEP_ORDER')
    strict_verify(raw(actor['public_key'], 32), raw(message['sig'], 64),
                  canonical(['ZJJ-SIG-v1', protected, body]))
    return body


class Verifier:
    def __init__(self, package, anchor):
        self.package = package
        self.anchor = anchor
        self.profile = package['profile']
        self.actors = anchor['actors'][self.profile]
        self.scope = self.package['commit']['scope'] if self.package.get('commit') else None
        self.root = raw(anchor['root_public'], 32)
        self.controls = {}
        self.schema = CompetitionSchema(ROOT, self.profile)
        self.report = Report()
        self.op = package['frozen']['op']
        self.action = self.op['action']

    def verify(self):
        r = self.report
        stages = ['anchor_matches_package_root', 'anchor_actor_keys',
                  'control_certificates_and_refs', 'control_history_certificates',
                  'tool_trust_certificate', 'resource_certificate_and_sums',
                  'authorization_chain', 'commit_record_ref', 'x_acceptance_signature',
                  'unique_attempt_and_delivery_signature', 'goal_floor_recomputation',
                  'tool_final_fact_signature', 'settlement_binding']
        if not r.run('anchor_matches_package_root', self._anchor_root):
            return self._finish(stages[1:], 'anchor root failed')
        if not r.run('anchor_actor_keys', self._anchor_actors):
            return self._finish(stages[2:], 'anchor actors failed')
        if not r.run('control_certificates_and_refs', self._controls):
            return self._finish(stages[3:], 'control records failed')
        if not r.run('control_history_certificates', self._control_history):
            return self._finish(stages[4:], 'control history failed')
        if not r.run('tool_trust_certificate', self._tool_trust):
            return self._finish(stages[5:], 'tool trust failed')
        if not r.run('resource_certificate_and_sums', self._resource):
            return self._finish(stages[6:], 'resource certificate failed')
        if not r.run('authorization_chain', self._chain):
            return self._finish(stages[7:], 'authorization chain failed')
        if not r.run('commit_record_ref', self._commit):
            return self._finish(stages[8:], 'commit ref failed')
        if not r.run('x_acceptance_signature', self._acceptance):
            return self._finish(stages[9:], 'acceptance failed')
        if self.package.get('outbox') and self.package['outbox'].get('attempt_id'):
            if not r.run('unique_attempt_and_delivery_signature', self._attempt):
                return self._finish(stages[10:], 'attempt failed')
        else:
            r.checks.append({'check': 'unique_attempt_not_yet_issued', 'status': 'PASS',
                             'kind': 'scope',
                             'detail': 'Accepted but not claimed; no execution qualification claimed.'})
        if not r.run('goal_floor_recomputation', self._goal):
            return self._finish(stages[11:], 'goal floor failed')
        if self.package.get('settlement'):
            if not r.run('tool_final_fact_signature', self._final):
                return self._finish(stages[12:], 'tool final failed')
            r.run('settlement_binding', self._settlement)
        else:
            r.checks.append({'check': 'settlement_not_claimed', 'status': 'PASS',
                             'kind': 'scope',
                             'detail': 'No settlement in package; UNKNOWN is retained, not treated as failure.'})
        return self._result()

    def _finish(self, remaining, reason):
        for name in remaining:
            self.report.skip(name, reason)
        return self._result()

    def _result(self):
        result = self.report.result()
        result['limitations'] = [
            'W ledger totals (spent/reserved) are a trusted W assertion; the package checks their arithmetic, not physical truth.',
            'Offline time checks prove internal iat/exp ordering, not that the evidence is current at audit time.',
            'The simulated tool ledger proves the simulator effect, not a real industrial/payment/medical effect.',
            'A complete absence of evidence cannot be distinguished from evidence withheld outside this package.',
        ]
        result['trust_anchor_sha256'] = digest(['ANCHOR-FILE', self.anchor])
        return result

    def _anchor_root(self):
        require(self.anchor['root_public'] == self.package['root_public'], 'ANCHOR_ROOT')
        require(self.anchor['delivery_public'] == self.package['delivery_public'], 'ANCHOR_DELIVERY')
        require(len(self.root) == 32 and b64(self.root) == self.anchor['root_public'], 'ROOT_KEY')
        return True

    def _anchor_actors(self):
        for alias, actor in self.actors.items():
            require(keyid(raw(actor['public_key'], 32)) == actor['kid'], 'ACTOR_KEY')
        return {'actors': len(self.actors)}

    def _controls(self):
        for control in self.package['controls']:
            self._verify_control(control)
            self.controls[(control['namespace'], tuple(control['key']))] = control
        return {'controls': len(self.controls)}

    def _control_history(self):
        for control in self.package.get('control_history', []):
            self._verify_control(control)
        return {'history_records': len(self.package.get('control_history', []))}

    def _verify_control(self, control):
        cert = control['certificate']
        require(set(cert) == {'claim', 'signature'}, 'CONTROL_FIELDS')
        claim = cert['claim']
        require(set(claim) == {'profile', 'scope', 'namespace', 'key', 'previous_revision',
                               'record', 'active', 'enrollment'}, 'CONTROL_FIELDS')
        require(claim['profile'] == self.profile and claim['scope'] == self.scope,
                'CONTROL_SCOPE')
        strict_verify(self.root, raw(cert['signature'], 64),
                      canonical(['COMP-APP-C-PUBLISH-v1', claim]))
        record = control['record']
        require(claim['record'] == record, 'CONTROL_RECORD')
        require(claim['namespace'] == control['namespace'] and claim['key'] == control['key'],
                'CONTROL_KEY')
        require(int(claim['previous_revision']) + 1 == int(control['revision']),
                'CONTROL_REVISION')
        require(_row_ref(control['namespace'], control['key'], control['revision'], record) ==
                control['ref'], 'CONTROL_REF')
        if control['namespace'] in ('UNIT', 'ENCOUNTER'):
            self.schema.validate(record['value'], 'SceneRow')
        elif control['namespace'] == 'BEHAVIOR':
            self.schema.validate(record['value'], 'BehaviorRow')
        else:
            self.schema.validate(record, 'Record_' + record['kind'])
        if control['namespace'] == 'GOAL':
            validate_claim(self.profile, record['value'])
        if control['namespace'] == 'KEY':
            self._key_control(claim, record)
        if control['namespace'] == 'ROLE':
            self._role_control(control, record)
        return True

    def _key_control(self, claim, record):
        value = record['value']
        require(claim['key'] == [value['kid']], 'KEY_GRANT_KEY')
        require(raw(value['public_key'], 32) and keyid(raw(value['public_key'], 32)) == value['kid'],
                'KEY_GRANT')
        if claim['active']:
            proof = claim['enrollment']
            require(type(proof) is dict and set(proof) == {'tuple', 'enrollment_id', 'nonce',
                                                           'iat', 'exp', 'signature'}, 'POP')
            t = proof['tuple']
            require(t == {'scope': self.scope, 'subject': value['subject'],
                          'public_key': value['public_key'], 'kid': value['kid'],
                          'purposes': value['purposes'], 'key_not_before': value['iat'],
                          'key_not_after': value['exp'],
                          'root_generation': value['root_generation']}, 'POP_BINDING')
            strict_verify(raw(value['public_key'], 32), raw(proof['signature'], 64),
                          canonical(['ZJJ-ENROLL-v1', '2.6', t, proof['enrollment_id'],
                                     proof['nonce'], proof['iat'], proof['exp']]))
            require(value['enrollment_ref'] == digest(['COMP-APP-POP-v1', proof]), 'POP_REF')

    def _role_control(self, control, record):
        value = record['value']
        require(control['key'][-1] == value['role'], 'ROLE_KEY')
        require(value['epoch'] == str(control['revision']), 'ROLE_EPOCH')
        require(value['scope_set'] == [self.scope], 'ROLE_SCOPE')

    def _tool_trust(self):
        cert = self.package['tool_certificate']
        record = verify_certificate(cert, self.root, self.profile)
        row = self.package['tool_trust_row']
        require(row is not None and row['origin'] == cert['claim']['ledger_origin'], 'TOOL_ORIGIN')
        require(record['value']['kid'] == keyid(raw(record['value']['public_key'], 32)), 'TOOL_KEY')
        self.tool_record = record
        return {'ledger': record['value']['ledger_id'], 'kid': record['value']['kid']}

    def _resource(self):
        cert = self.package['resource']['certificate']
        # resource certificates use the W resource domain, not the C publish domain
        require(type(cert) is dict and set(cert) == {'claim', 'signature'}, 'RESOURCE_FIELDS')
        claim = cert['claim']
        require(set(claim) == {'profile', 'scope', 'key', 'unit', 'capacity', 'revision', 'active'},
                'RESOURCE_FIELDS')
        strict_verify(self.root, raw(cert['signature'], 64), canonical(['COMP-W-RESOURCE-v1', claim]))
        row = self.package['resource']
        require(claim['profile'] == self.profile and claim['scope'] == self.scope, 'RESOURCE_SCOPE')
        require(claim['key'] == self.package['frozen']['plan']['resource_key'], 'RESOURCE_KEY')
        require(claim['unit'] == row['unit'] and claim['unit'] == self.package['frozen']['plan']['unit'],
                'RESOURCE_UNIT')
        require(int(claim['capacity']) == row['capacity'], 'RESOURCE_CAPACITY')
        require(int(row['capacity']) == int(self.package['commit']['value']['goal']['capacity'])
                if self.package['commit']['value'].get('goal') else True, 'GOAL_CAPACITY')
        reserved = sum(int(r['amount']) for r in self.package['reservations'] if r['state'] == 'RESERVED')
        spent = sum(int(r['amount']) for r in self.package['reservations'] if r['state'] == 'SPENT')
        require((reserved, spent) == (row['reserved'], row['spent']), 'RESOURCE_SUM')
        require(0 <= reserved + spent <= row['capacity'], 'RESOURCE_BOUND')
        return {'capacity': row['capacity'], 'reserved': reserved, 'spent': spent}

    def _chain(self):
        op = self.op
        action = self.action
        self.schema.validate(action, 'Action')
        scope = op['ctx']['scope']
        require(scope == self.scope, 'CHAIN_SCOPE')
        require(op['ctx']['action_hash'] == action_hash(self.profile, action), 'ACTION_HASH')
        policy = self.controls[('POLICY', tuple(self._policy_key()))]
        task = self.controls[('TASK', tuple(self._task_key()))]
        require(policy['active'] and task['active'], 'CONTROL_ACTIVE')
        require(op['ctx']['policy_ref'] == policy['ref'], 'POLICY_REF')
        basis = op['basis']
        assessment = op['assessment']
        require(rec_ref(basis) == op['ctx']['basis_ref'], 'BASIS_REF')
        require(basis['value']['action'] == action, 'BASIS_ACTION')
        require(basis['value']['action_hash'] == op['ctx']['action_hash'], 'BASIS_HASH')
        require(basis['value']['policy_ref'] == policy['ref'], 'BASIS_POLICY')
        require(basis['value']['task_ref'] == task['ref'], 'BASIS_TASK')
        require(basis['value']['assessment_ref'] == rec_ref(assessment), 'ASSESSMENT_REF')
        require(basis['value']['iat'] == assessment['value']['iat'], 'ASSESSMENT_TIME')
        require(int(basis['value']['exp']) <= int(assessment['value']['exp']), 'ASSESSMENT_WINDOW')
        require(basis['value']['scope'] == self.scope, 'BASIS_SCOPE')
        require(basis['value']['operation_id'] == action['operation_id'], 'BASIS_OID')
        require(all(dep in op['deps'] for dep in basis['value']['deps']), 'BASIS_DEPS')
        require(basis['value']['required_reviews'] == op['required'], 'BASIS_REVIEWS')
        require(basis['value']['evidence_refs'] == sortset(basis['value']['evidence_refs']),
                'EVIDENCE_ORDER')
        self.schema.validate(basis, 'Record_BASIS')
        self.schema.validate(assessment, 'Record_ASSESSMENT')
        refs = {}
        messages = list(op['reviews']) + [op['authorization'], op['issue'], op['permit'],
                                          op['challenge_request'], op['challenge'], op['proof']]
        for message in messages:
            protected = message['protected']
            alias = self._alias_for(protected['type'], protected['issuer'])
            body = _verify_message(message, self.actors[alias], self.profile, self.scope)
            refs[protected['type'] + ':' + msgref(message)] = body
        auth = op['authorization']
        permit = op['permit']
        qr = op['challenge_request']
        ch = op['challenge']
        proof = op['proof']
        issue = op['issue']
        expected = {'scope': self.scope, 'operation_id': action['operation_id'], 'action': action,
                    'action_hash': op['ctx']['action_hash'], 'policy_ref': policy['ref'],
                    'task_ref': task['ref'], 'assessment_ref': rec_ref(assessment),
                    'iat': basis['value']['iat'], 'exp': basis['value']['exp']}
        for key, value in expected.items():
            require(basis['value'][key] == value, 'BASIS_BINDING')
        rr = sortset([msgref(r) for r in op['reviews']])
        pr = msgref(permit)
        require(auth['body']['payload'] == {'ctx': op['ctx'], 'review_refs': rr,
                                           'purpose': 'EXECUTE', 'verdict': 'APPROVE'}, 'AUTH_PAYLOAD')
        require(issue['body']['payload'] == {'ctx': op['ctx'], 'review_refs': rr,
                                            'authorization_ref': msgref(auth)}, 'ISSUE_PAYLOAD')
        require(permit['body']['payload'] == {'ctx': op['ctx'], 'review_refs': rr,
                                             'authorization_ref': msgref(auth),
                                             'max_uses': '1',
                                             'dispatch_before': permit['body']['exp']}, 'PERMIT_PAYLOAD')
        q = qr['body']['payload']
        require(q == {'purpose': 'COMMIT', 'operation_id': action['operation_id'],
                      'permit_ref': pr, 'action_hash': op['ctx']['action_hash'],
                      'attempt_id': q['attempt_id']}, 'CHALLENGE_REQUEST')
        h = ch['body']['payload']
        require(h['purpose'] == 'COMMIT' and h['operation_id'] == action['operation_id'] and
                h['permit_ref'] == pr and h['action_hash'] == op['ctx']['action_hash'] and
                h['request_ref'] == msgref(qr), 'CHALLENGE')
        f = proof['body']['payload']
        require(f == {'ctx': op['ctx'], 'permit_ref': pr, 'challenge_ref': msgref(ch),
                      'session_id': h['session_id'], 'nonce': h['nonce'],
                      'attempt_id': q['attempt_id']}, 'PROOF')
        require(proof['body']['refs'] == sortset([pr, msgref(ch)]), 'PROOF_REFS')
        require(int(proof['body']['iat']) >= int(ch['body']['iat']) and
                int(proof['body']['exp']) <= min(int(ch['body']['exp']), int(permit['body']['exp'])),
                'PROOF_WINDOW')
        require(len(op['reviews']) == len(op['required']) and
                sorted(r['body']['payload']['purpose'] for r in op['reviews']) ==
                sorted(op['required']), 'REVIEW_SET')
        for review in op['reviews']:
            require(review['body']['payload']['ctx'] == op['ctx'] and
                    review['body']['payload']['verdict'] == 'APPROVE', 'REVIEW_PAYLOAD')
        require(auth['body']['refs'] == rr, 'AUTH_REFS')
        require(issue['body']['refs'] == sortset(rr + [msgref(auth)]), 'ISSUE_REFS')
        require(permit['body']['refs'] == sortset(rr + [msgref(auth)]), 'PERMIT_REFS')
        require(qr['body']['refs'] == [pr], 'CHALLENGE_REQUEST_REFS')
        require(ch['body']['refs'] == sortset([pr, msgref(qr)]), 'CHALLENGE_REFS')
        audiences = [(issue, ['G']), (permit, ['H', 'X']), (qr, ['X']), (ch, ['H']),
                     (proof, ['X']), (auth, ['H', 'G', 'X'])] + \
                    [(review, ['H', 'G', 'X']) for review in op['reviews']]
        for message, recipients in audiences:
            require(message['body']['aud'] ==
                    sortset([self.actors[a]['name'] for a in recipients]), 'AUDIENCE_BINDING')
        self.msg_refs = {'permit': pr, 'proof': msgref(proof), 'authorization': msgref(auth),
                         'reviews': rr, 'challenge_request': msgref(qr), 'challenge': msgref(ch),
                         'issue': msgref(issue)}
        return {'messages': len(messages), 'reviews': len(op['reviews'])}

    def _alias_for(self, typ, issuer):
        for alias, actor in self.actors.items():
            if actor['name'] == issuer:
                return alias
        raise ProtocolError('UNKNOWN_ISSUER')

    def _policy_key(self):
        return [self.scope[k] for k in ('domain', 'tenant', 'scenario')]

    def _task_key(self):
        return self._policy_key() + [self.op['task_id']]

    def _commit(self):
        commit = self.package['commit']
        require(rec_ref(commit) == self.package['commit_ref'], 'COMMIT_REF')
        self.schema.validate(commit, 'Record_COMMIT')
        value = commit['value']
        require(value['action'] == self.action and value['ctx'] == self.op['ctx'], 'COMMIT_ACTION')
        require(value['permit_ref'] == self.msg_refs['permit'], 'COMMIT_PERMIT')
        require(value['proof_ref'] == self.msg_refs['proof'], 'COMMIT_PROOF')
        require(value['authorization_ref'] == self.msg_refs['authorization'], 'COMMIT_AUTH')
        require(value['review_refs'] == self.msg_refs['reviews'], 'COMMIT_REVIEWS')
        require(value['frozen_tool_request'] == self.action, 'COMMIT_TOOL_REQUEST')
        require(value['signing_public_key'] == self.actors['X']['public_key'], 'COMMIT_X_KEY')
        require(value['dispatch_before'] == self.op['permit']['body']['payload']['dispatch_before'],
                'COMMIT_DISPATCH')
        return {'commit_ref': self.package['commit_ref']}

    def _acceptance(self):
        core = self.package['acceptance_core']
        signed = self.package['acceptance']
        require(signed is not None, 'ACCEPTANCE_MISSING')
        require({k: v for k, v in signed.items() if k != 'sig'} == core, 'FROZEN_RECEIPT_CONFLICT')
        protected, body = signed['protected'], signed['body']
        actor = self.actors['X']
        require((protected['type'], protected['issuer'], protected['kid']) ==
                ('Acceptance', actor['name'], actor['kid']), 'ACCEPTANCE_ISSUER')
        require(body['payload']['commit_record_ref'] == self.package['commit_ref'], 'ACCEPTANCE_COMMIT')
        require(body['scope'] == self.scope, 'ACCEPTANCE_SCOPE')
        require(body['refs'] == sortset(self.msg_refs['reviews'] +
                                       [self.msg_refs['permit'], self.msg_refs['proof'],
                                        self.msg_refs['authorization']]), 'ACCEPTANCE_REFS')
        strict_verify(raw(actor['public_key'], 32), raw(signed['sig'], 64),
                      canonical(['ZJJ-SIG-v1', protected, body]))
        require(int(body['iat']) == int(core['body']['iat']) and
                int(body['exp']) == int(core['body']['exp']), 'ACCEPTANCE_TIME')
        return {'acceptance_ref': msgref(signed)}

    def _attempt(self):
        outbox = self.package['outbox']
        require(outbox and outbox['attempt_id'], 'ATTEMPT_MISSING')
        packet = json.loads(outbox['packet'])
        require(set(packet) == {'claim', 'signature'}, 'PACKET_FIELDS')
        claim = packet['claim']
        strict_verify(raw(self.anchor['delivery_public'], 32), raw(packet['signature'], 64),
                      canonical(['COMP-W-TOOL-EXEC-v1', claim]))
        require(claim['attempt_id'] == outbox['attempt_id'], 'ATTEMPT_ID')
        require(claim['operation_id'] == self.package['operation_id'], 'ATTEMPT_OID')
        require(claim['action'] == self.action and claim['action_hash'] == action_hash(self.profile, self.action),
                'ATTEMPT_ACTION')
        require(claim['commit_ref'] == self.package['commit_ref'], 'ATTEMPT_COMMIT')
        require(claim['acceptance_ref'] == msgref(self.package['acceptance']), 'ATTEMPT_ACCEPTANCE')
        require(claim['tool_trust_ref'] == rec_ref(self.tool_record), 'ATTEMPT_TRUST')
        require(claim['ledger_origin'] == self.package['tool_certificate']['claim']['ledger_origin'],
                'ATTEMPT_ORIGIN')
        self.exec_claim = claim
        return {'attempt_id': claim['attempt_id']}

    def _goal(self):
        witness = self.package['commit']['value'].get('goal')
        resource_key = self.package['frozen']['plan']['resource_key']
        goals = []
        for control in self.package['controls']:
            if control['namespace'] != 'GOAL' or not control['active']:
                continue
            claim = control['record']['value']
            if claim['resource_key'] != resource_key:
                continue
            goals.append({'ref': goal_ref(self.profile, claim), 'claim': claim})
        if not witness:
            require(not goals, 'GOAL_WITNESS_MISSING')
            return 'No GoalFloor applies to this operation.'
        if not goals:
            require(witness['decision'] == 'F' and witness['reason'] == 'GOAL_INACTIVE_PENDING',
                    'GOAL_UNKNOWN')
            require(any(link['state'] == 'PENDING' for link in self.package['goal_links_all']),
                    'GOAL_INACTIVE_PENDING')
            check = digest(['ZJJ-GOAL-CHECK-v1',
                            {k: witness[k] for k in ('capacity', 'spent', 'reserved',
                                                     'candidate_cost', 'remaining_floor',
                                                     'total', 'matched')} |
                            {'decision': 'F', 'reason': 'GOAL_INACTIVE_PENDING'}])
            require(check == witness['check_ref'], 'GOAL_CHECK_REF')
            return {'decision': 'F', 'reason': 'GOAL_INACTIVE_PENDING'}
        require(goals, 'GOAL_UNKNOWN')
        goal_deps = {}
        for goal in goals:
            for dep in goal['claim']['deps']:
                goal_deps[(dep['namespace'], tuple(dep['key']))] = dep
        if 'deps' in witness:
            require(sortset(witness['deps']) == sortset(list(goal_deps.values())),
                    'GOAL_DEPS')
        own_incident = self.action['payload'].get('batch_id')
        for dep in goal_deps.values():
            # A post-settlement status change of this very incident is a
            # postcondition, not a prerequisite of this acceptance.  Other
            # incidents remain prerequisites and must still be current.
            if (dep['namespace'] == 'INCIDENT' and own_incident is not None and
                    dep['key'][-1] == own_incident):
                continue
            control = self.controls.get((dep['namespace'], tuple(dep['key'])))
            if (control is None or not control['active'] or
                    str(control['revision']) != dep['revision'] or
                    control['ref'] != dep['ref']):
                require(witness['decision'] == 'F' and
                        witness['reason'] in ('GOAL_DEPS_STALE', 'GOAL_DEPS_UNKNOWN'),
                        'GOAL_DEPS')
                require(witness['goal_refs'] == sortset([g['ref'] for g in goals]),
                        'GOAL_REFS')
                return {'decision': 'F', 'reason': witness['reason']}
        statuses = {}
        for link in self.package['goal_links_all']:
            if link['oid'] == self.package['operation_id']:
                # the decision was taken before this operation's own link existed
                continue
            statuses[(link['goal_group'], link['obligation'])] = link['state']
        resource = self.package['resource']
        reservation = self.package['reservation'] or {}
        amount = int(reservation.get('amount', 0))
        spent = int(resource['spent'])
        reserved = int(resource['reserved'])
        if reservation.get('state') == 'RESERVED':
            reserved -= amount
        elif reservation.get('state') == 'SPENT':
            spent -= amount
        require(spent >= 0 and reserved >= 0, 'GOAL_PRE_STATE')
        state_ref = state_digest(resource['capacity'], spent=spent, reserved=reserved,
                                 statuses=statuses)
        require(state_ref == witness['state_ref'], 'GOAL_STATE_REF')
        candidate = {'cost': self.package['frozen']['plan']['amount'],
                     'resource_key': self.package['frozen']['plan']['resource_key'],
                     'unit': self.package['frozen']['plan']['unit'],
                     'selector': action_selector(self.profile, self.action)}
        decision = evaluate_goal(self.profile, goals, statuses, capacity=resource['capacity'],
                                 spent=spent, reserved=reserved, candidate=candidate)
        require(decision['check_ref'] == witness['check_ref'], 'GOAL_CHECK_REF')
        require((decision['decision'], decision['reason'], decision['remaining_floor'],
                 decision['total'], decision['headroom']) ==
                (witness['decision'], witness['reason'], witness['remaining_floor'],
                 witness['total'], witness['headroom']), 'GOAL_DECISION')
        require(witness['goal_refs'] == sortset([g['ref'] for g in goals]), 'GOAL_REFS')
        return {'decision': decision['decision'], 'reason': decision['reason'],
                'remaining_floor': decision['remaining_floor'], 'total': decision['total']}

    def _final(self):
        response = self.package['settlement_evidence']
        require(type(response) is dict and response.get('record') is not None, 'FINAL_MISSING')
        record = response['record']
        self.schema.validate(record, 'Record_TOOL_FINAL')
        value = record['value']
        trust = self.tool_record['value']
        require(value['method'] == 'tool-final-v2' and value['ledger_id'] == trust['ledger_id'],
                'FINAL_LEDGER')
        require(value['operation_id'] == self.package['operation_id'], 'FINAL_OID')
        require(value['action_hash'] == action_hash(self.profile, self.action), 'FINAL_ACTION')
        require(value['dispatch_attempt'] == self.package['outbox']['attempt_id'], 'FINAL_ATTEMPT')
        for field in ('tool', 'tool_version', 'destination'):
            require(value[field] == trust[field], 'FINAL_TOOL')
        require((value['attestation']['issuer'], value['attestation']['kid']) ==
                (trust['issuer'], trust['kid']), 'FINAL_ISSUER')
        strict_verify(raw(trust['public_key'], 32), raw(value['attestation']['sig'], 64),
                      final_sign_bytes(record))
        require(int(value['finalized_at']) >= int(self.package['frozen']['accepted_at']), 'FINAL_TIME')
        require(int(value['finalized_at']) <= int(value['iat']) and int(value['exp']) <= int(trust['exp']),
                'FINAL_WINDOW')
        require((value['outcome'] == 'SUCCEEDED' and value['effect_id'] != '' and
                 value['no_late_effect'] is False) or
                (value['outcome'] == 'FAILED_CONFIRMED' and value['effect_id'] == '' and
                 value['no_late_effect'] is True), 'FINAL_OUTCOME')
        checkpoint = response.get('checkpoint')
        require(type(checkpoint) is dict and set(checkpoint) == {'claim', 'signature'},
                'CHECKPOINT_FIELDS')
        claim = checkpoint['claim']
        from competition.tools.common_tool import request_hash
        required = {'profile': self.profile, 'scope': self.scope,
                    'operation_id': self.package['operation_id'],
                    'attempt_id': self.package['outbox']['attempt_id'],
                    'ledger_id': trust['ledger_id'],
                    'ledger_origin': self.package['tool_certificate']['claim']['ledger_origin'],
                    'request_hash': request_hash(self.exec_claim),
                    'final_fact_id': final_fact_id(record)}
        require(set(claim) == set(required) | {'high_water', 'ledger_head'}, 'CHECKPOINT_FIELDS')
        require(all(claim[k] == v for k, v in required.items()), 'CHECKPOINT_BINDING')
        strict_verify(raw(trust['public_key'], 32), raw(checkpoint['signature'], 64),
                      canonical(['COMP-TOOL-CHECKPOINT-v1', claim]))
        self.final_fact_id = final_fact_id(record)
        return {'final_fact_id': self.final_fact_id, 'outcome': value['outcome']}

    def _settlement(self):
        settlement = self.package['settlement']
        require(settlement['fact_id'] == self.final_fact_id, 'SETTLEMENT_FACT')
        require(settlement['ledger'] == self.tool_record['value']['ledger_id'], 'SETTLEMENT_LEDGER')
        require(settlement['outcome'] == self.package['settlement_evidence']['record']['value']['outcome'],
                'SETTLEMENT_OUTCOME')
        require(settlement['effect_id'] == self.package['settlement_evidence']['record']['value']['effect_id'],
                'SETTLEMENT_EFFECT')
        return {'final_fact_id': settlement['fact_id'], 'outcome': settlement['outcome']}


def verify_package(package, anchor):
    return Verifier(package, anchor).verify()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print('usage: python -m competition.evaluation.verify <package.json> <anchor.json>')
        return 2
    package = json.loads(Path(argv[0]).read_text(encoding='utf-8'))
    anchor = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
    result = verify_package(package, anchor)
    print(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
