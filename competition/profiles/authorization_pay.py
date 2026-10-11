"""PAY derivation from transaction-current authenticated core records.

The shared store owns C publication authentication and revisions. This adapter
does not treat a request's dependency/review/assessment claims as authority.
Source dependencies are checked against the current graph; historical v2.5
publication closure and real-world source truth are not asserted here.
"""
from pathlib import Path

from research.reference_executor.wire import require, number, rec_ref, digest, sortset, raw, keyid
from research.strict_v26.pay_dependencies import TrustedStore, required_pay_deps
from research.strict_v26.pay_history import (verify_pay_authoritative, parse_policy, parse_task,
    parse_history, record, fields, bound_time, legacy_dep_structure)
from research.strict_v26.upstream_schema import UpstreamSchema


class PayAuthorizationAdapter:
    def __init__(self, store, profile, actors):
        require(profile == 'PAY-1', 'PROFILE')
        require(set(actors) >= {'H', 'G', 'X', 'U', 'V', 'E'}, 'ACTOR_SET')
        self.store, self.profile, self.actors = store, profile, actors
        self.schema = UpstreamSchema(Path(__file__).resolve().parents[2], profile)

    @staticmethod
    def _event(event):
        lo = event['lo'] if isinstance(event, dict) else event.lo
        hi = event['hi'] if isinstance(event, dict) else event.hi
        require(number(str(lo)) and number(str(hi)) and int(lo) <= int(hi), 'TIME')
        return int(lo), int(hi)

    def derive(self, c, op, event):
        action = op['action']
        scope = action['scope']
        require(scope == {'domain': 'lab', 'tenant': 'tenant-1', 'scenario': 'payment'}, 'WRONG_SCOPE')
        lo, hi = self._event(event)
        cutoff = op['assessment']['value']['cutoff']
        require(number(cutoff) and int(cutoff) <= lo, 'ASSESSMENT_CUTOFF')
        prefix = [scope[k] for k in ('domain', 'tenant', 'scenario')]
        trusted = TrustedStore(scope)
        loaded = {}

        def load(namespace, key, supplied=None):
            index = namespace, tuple(key)
            if index in loaded:
                return loaded[index]
            row = supplied if supplied is not None else self.store.current(c, self.profile, namespace, key)
            require(type(row['revision']) is int and row['revision'] > 0, 'REVISION')
            document = row['record']
            require(document['scope'] == scope and document['profile'] == self.profile and document['version'] == '2.6', 'OBJECT_KIND')
            expected_kind = {'POLICY': 'POLICY', 'TASK': 'PAY_TASK', 'ORDER': 'PAY_EVIDENCE',
                             'EXPERIENCE': 'PAY_HISTORY', 'KEY': 'KEY_GRANT', 'ROLE': 'ROLE_GRANT',
                             'BEHAVIOR': 'BEHAVIOR_STATE'}
            require(namespace in expected_kind and document['kind'] == expected_kind[namespace], 'OBJECT_KIND')
            value = record(document, expected_kind[namespace], scope)
            if namespace == 'BEHAVIOR':
                fields(value, {'accepted_count', 'count_cap', 'inflight'})
                require(number(value['accepted_count']) and number(value['count_cap'], True) and
                        type(value['inflight']) is list, 'BEHAVIOR_FIELDS')
                expected_ref = digest(['ZJJ-STATE-v1', namespace, key, str(row['revision']), value])
                require(row['ref'] == expected_ref, 'SOURCE_REF')
                trusted._set(namespace, key, row['revision'], row['ref'], value, None)
            else:
                self.schema.validate(document, 'Record_' + expected_kind[namespace])
                require(row['ref'] == rec_ref(document), 'SOURCE_REF')
                trusted.publish_record(namespace, key, row['revision'], document, expected_kind[namespace])
                if 'iat' in value and 'exp' in value:
                    require(number(value['iat']) and number(value['exp']) and
                            int(value['iat']) <= lo and hi < int(value['exp']), 'AUTHORITY_EXPIRED')
            loaded[index] = row
            return row

        policyrow = load('POLICY', prefix)
        policy = parse_policy(policyrow['record'], scope, lo)
        parse_policy(policyrow['record'], scope, hi)
        taskrow = load('TASK', prefix + [op['task_id']])
        parse_task(taskrow['record'], scope, lo)
        parse_task(taskrow['record'], scope, hi)
        p = action['payload']
        require(op['scene_key'] == p['order_id'], 'SOURCE_BINDING')
        orderrow = load('ORDER', prefix + [p['order_id'], p['stage']])
        historyrow = load('EXPERIENCE', prefix + [policy['partition']])
        parse_history(historyrow['record'], scope, lo)
        parse_history(historyrow['record'], scope, hi)
        load('BEHAVIOR', prefix + [action['principal']])
        source = orderrow['record']['value']['source_envelope']
        for at in (lo, hi):
            bound_time(source['body']['iat'], source['body']['exp'], at, 900)
        E = self.actors['E']
        require(keyid(E.pub) == E.kid, 'SOURCE_KEY')
        risk, assessment = verify_pay_authoritative(
            scope=scope, action=action, policy_record=policyrow['record'], task_record=taskrow['record'],
            evidence_record=orderrow['record'], history_record=historyrow['record'],
            source_public_key=E.pub, source_subject=E.name, cutoff=int(cutoff),
            policy_rev=policyrow['revision'], task_rev=taskrow['revision'], order_rev=orderrow['revision'],
            history_rev=historyrow['revision'], witness_authenticated=True)
        consumers = ('H', 'G', 'X', 'U') + (('V',) if risk.required_reviews else ())
        require({self.actors[a].name for a in consumers} <= set(source['body']['aud']), 'SOURCE_AUDIENCE')
        actor_roles = {'E': ('SOURCE', 'SOURCE'), 'H': ('HOLDER', 'IssueRequest'),
                       'G': ('ISSUER', 'Permit'), 'X': ('EXECUTOR', 'Acceptance'),
                       'U': ('FINANCE', 'Authorization')}
        if risk.required_reviews:
            actor_roles['V'] = ('ANOMALY', 'Review')
        for alias, (role, purpose) in actor_roles.items():
            actor = self.actors[alias]
            require(actor.name in policy['readers'], 'READERS')
            keyrow, rolerow = self.store.credential(c, self.profile, alias, role, purpose, action, event)
            load('KEY', [actor.kid], keyrow)
            load('ROLE', prefix + [actor.name, role], rolerow)
            require(raw(keyrow['record']['value']['public_key'], 32) == actor.pub, 'KEY_BINDING')
        signers = {alias: (actor.name, actor.kid) for alias, actor in self.actors.items()}
        deps = required_pay_deps(trusted, action, op['task_id'], signers, bool(risk.required_reviews), lo)
        required_pay_deps(trusted, action, op['task_id'], signers, bool(risk.required_reviews), hi)
        base = [dep for dep in deps if dep['namespace'] in ('POLICY', 'TASK', 'ORDER', 'EXPERIENCE', 'BEHAVIOR') or
                (dep['namespace'] == 'KEY' and dep['key'] == [self.actors['H'].kid]) or
                (dep['namespace'] == 'KEY' and dep['key'] == [E.kid]) or
                (dep['namespace'] == 'ROLE' and dep['key'] in
                 (prefix + [self.actors['H'].name, 'HOLDER'], prefix + [E.name, 'SOURCE']))]
        # A bounded current graph check, never a claim of historical publication closure.
        queue, source_deps = list(source['body']['deps']), {}
        while queue:
            require(len(source_deps) < 64, 'SOURCE_DEPS_LIMIT')
            dep = queue.pop()
            legacy_dep_structure(dep)
            idx = dep['namespace'], tuple(dep['key'])
            if idx in source_deps:
                require(source_deps[idx] == dep, 'DEP_CONFLICT')
                continue
            current = load(dep['namespace'], dep['key'])
            expected = trusted.dep(dep['namespace'], dep['key'])
            require(dep == expected, 'STALE')
            source_deps[idx] = expected
            nested = current['record']['value'].get('source_envelope')
            if nested is not None:
                # The original strict E signature and whole window must be verified.
                require(nested == source, 'SOURCE_DEPS_UNSUPPORTED')
                queue.extend(nested['body']['deps'])
        def merged(values):
            unique = {}
            for dep in values:
                idx = dep['namespace'], tuple(dep['key'])
                require(idx not in unique or unique[idx] == dep, 'DEP_CONFLICT')
                unique[idx] = dep
            return sortset(list(unique.values()))
        return {'required_reviews': list(risk.required_reviews),
                'deps': merged(deps + list(source_deps.values())),
                'basis_deps': merged(base + list(source_deps.values())), 'assessment_value': assessment,
                'policy_ref': policyrow['ref'], 'task_ref': taskrow['ref'], 'evidence_refs': [orderrow['ref']],
                'evidence_records':[orderrow['record']]}
