"""IND R2 durable-accept/frozen-receipt vertical slice; historical sources unchanged."""
import copy
import json
import os
import threading
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from jsonschema import Draft202012Validator
from research.phase14.verifier import VerifierOnlySceneW
from research.phase8.scene_authority import SceneAuthority, ROLES, PROFILES, _json, _rec
from research.reference_executor.wire import require, ProtocolError, b64, canonical, digest, rec_ref, sortset, envelope, raw, action_hash, strict_verify
from research.strict_v26.upstream_schema import UpstreamSchema
from competition.core.event_clock import checked_event_clock, require_window, MAX_AGE_NS, AGE_MARGIN_NS
from competition.profiles.scene_bindings import bound_scene

ROOT = Path(__file__).resolve().parents[2]


def objref(value):
    return digest(['ZJJ-OBJ-v1', value['protected'], value['body']])


class CurrentTimeGuards:
    @contextmanager
    def event_guard(self, event):
        if not hasattr(self, '_events'):
            self._events = threading.local()
        prior = getattr(self._events, 'current', None)
        self._events.current = event
        try:
            yield
        finally:
            self._events.current = prior

    def _credential(self, c, alias, role, purpose, action=None):
        event = getattr(getattr(self, '_events', None), 'current', None)
        require(event is not None, 'CLOCK_UNKNOWN')
        k, r = SceneAuthority._credential(self, c, alias, role, purpose, action)
        for row in (k, r):
            require_window(row['record']['value'], event)
        # Retain the real registered proof of possession, without Phase11's 106 constant.
        saved = c.execute('SELECT grant FROM verified_enrollment WHERE kid=?', (self.actors[alias].kid,)).fetchone()
        require(saved is not None and json.loads(saved[0]) == k['record'], 'POP_REQUIRED')
        return k, r

    def _state_ref(self, ns, key, revision, body):
        return digest(['ZJJ-STATE-v1', ns, key, str(revision), body])


class IndustrialAcceptanceW(CurrentTimeGuards, VerifierOnlySceneW):
    _bound = bound_scene
    def __init__(self, path, *, root_public, actors, clock):
        super().__init__(path, 'IND-DEMO-1', root_public=root_public, actors=actors)
        self.clock = clock
        require(raw(clock.info['public_key'], 32) == root_public, 'CLOCK_ROOT')
        self.schema = UpstreamSchema(ROOT, self.profile)
        with self.db() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS comp_ticket(ticket_id TEXT PRIMARY KEY,operation_id TEXT NOT NULL,
                  request_ref TEXT NOT NULL UNIQUE,op_json TEXT NOT NULL,prepared_at INTEGER NOT NULL,
                  expires INTEGER NOT NULL,time_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS comp_acceptance(operation_id TEXT PRIMARY KEY,ticket_id TEXT UNIQUE NOT NULL,
                  request_ref TEXT UNIQUE NOT NULL,frozen_json TEXT NOT NULL,receipt_json TEXT,
                  receipt_witness_json TEXT,receipt_error TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS comp_consumed(permit_ref TEXT PRIMARY KEY,proof_ref TEXT UNIQUE NOT NULL,
                  session_id TEXT UNIQUE NOT NULL,nonce TEXT UNIQUE NOT NULL,operation_id TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS comp_read_nonce(nonce TEXT PRIMARY KEY,operation_id TEXT NOT NULL,expires INTEGER NOT NULL,used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS comp_accept_nonce(nonce TEXT PRIMARY KEY,ticket_id TEXT NOT NULL,expires INTEGER NOT NULL,used INTEGER NOT NULL DEFAULT 0);
            ''')
        from competition.core.industrial_authorization_bridge import IndustrialAuthorizationState
        from competition.core.authorization import AuthorizationService
        self.authorization_store=IndustrialAuthorizationState(self)
        self.authorization_service=AuthorizationService(self.authorization_store)

    def publish_review(self, message):
        return self.authorization_service.publish_review(self.profile,message)

    def _disabled(self, *args, **kwargs):
        raise ProtocolError('LEGACY_ENTRY_DISABLED')

    prepare_accept = finalize_accept = claim_r2 = cancel_r2 = settle_r2 = _disabled
    activate_tool = rotate_root_epoch = init_scene = init_behavior = _disabled
    begin_enrollment = complete_enrollment = import_evidence = audit_r2 = _disabled
    review = authorize = issue = challenge = proof = _disabled

    def _event(self, c, operation_id, stage, request_ref):
        packet = self.clock.sample(self.profile, self.scope, operation_id, stage, request_ref)
        return checked_event_clock(c, packet, self.root_public, self.clock.instance_id, self.profile, self.scope, operation_id, stage, request_ref)

    def _verify_signed_chain(self, c, op, now):
        event = self._events.current
        self.authorization_service.verifier.verify(c,self.profile,op,event)
        action = op['action']; ah = action_hash(self.profile, action)
        policy = self.current(c, 'POLICY', self.scope_key())['record']
        task = self.current(c, 'TASK', self.scope_key() + [op['task_id']])['record']
        evidence = self.current(c, 'EVIDENCE', op['scene_key'])['record']
        ctx = {k: action[k] for k in ('scope', 'operation_id', 'principal', 'holder', 'holder_kid', 'executor')}
        ctx.update({'action_hash': ah, 'policy_ref': rec_ref(policy), 'basis_ref': rec_ref(op['basis'])})
        require(op['ctx'] == ctx, 'BINDING')
        self.schema.validate(op['basis'], 'Record_BASIS')
        self.schema.validate(op['assessment'], 'Record_ASSESSMENT')
        bv = op['basis']['value']; av = op['assessment']['value']
        for value in (bv, av):
            require(all(value[k] == v for k, v in {'scope': self.scope, 'operation_id': action['operation_id'], 'action_hash': ah, 'policy_ref': rec_ref(policy), 'task_ref': rec_ref(task), 'evidence_refs': [rec_ref(evidence)], 'required_reviews': op['required']}.items()), 'BINDING')
        require(bv['action'] == action and bv['assessment_ref'] == rec_ref(op['assessment']) and bv['deps'] == op['deps'], 'BINDING')
        require(av['result'] == 'MATCH' and av['history_mode'] == 'DISABLED' and av['decision_package_ref'] == policy['value']['decision_package_ref'] and av['method'] == 'ind-fixed-v1' and av['label'] == evidence['value']['data']['label'] and av['proposed_route'] == action['payload']['route'], 'BINDING')
        messages = [('H', 'IssueRequest', op['issue']), ('G', 'Permit', op['permit']), ('H', 'ChallengeRequest', op['challenge_request']), ('X', 'Challenge', op['challenge']), ('H', 'CommitProof', op['proof']), ('U', 'Authorization', op['authorization'])]
        messages += [('V', 'Review', r) for r in op['reviews']]
        for alias, typ, msg in messages:
            require(msg is not None, 'MISSING_OBJECT')
            require_window(msg['body'], event)
            who = self.actors[alias]
            envelope(msg, {who.kid: who}, now=now)
            self.schema.validate(msg, typ)
            require(msg['protected']['profile'] == self.profile and msg['protected']['type'] == typ and msg['protected']['issuer'] == who.name and msg['body']['scope'] == self.scope, 'BINDING')
            self._credential(c, alias, ROLES[self.profile][alias], typ, op['action'])
        ctx = op['ctx']; reviews = sortset([objref(r) for r in op['reviews']]); auth = objref(op['authorization']); permit = objref(op['permit'])
        require(len(reviews) == len(op['required']) and sorted(r['body']['payload']['purpose'] for r in op['reviews']) == sorted(op['required']), 'REVIEW_REQUIRED')
        for r in op['reviews']:
            require(r['body']['payload']['ctx'] == ctx and r['body']['payload']['verdict'] == 'APPROVE', 'REVIEW_DENY')
        require(op['authorization']['body']['payload'] == {'ctx': ctx, 'review_refs': reviews, 'purpose': 'EXECUTE', 'verdict': 'APPROVE'}, 'AUTH_DENY')
        require(op['issue']['body']['payload'] == {'ctx': ctx, 'review_refs': reviews, 'authorization_ref': auth}, 'BINDING')
        require(op['permit']['body']['payload'] == {'ctx': ctx, 'review_refs': reviews, 'authorization_ref': auth, 'max_uses': '1', 'dispatch_before': op['permit']['body']['exp']}, 'BINDING')
        require(op['permit']['body']['deps'] == op['deps'], 'DEP_CONFLICT')
        qr = op['challenge_request']['body']['payload']; ch = op['challenge']['body']['payload']; proof = op['proof']['body']['payload']
        require(qr['purpose'] == 'COMMIT' and qr['operation_id'] == ctx['operation_id'] and qr['permit_ref'] == permit and qr['action_hash'] == ctx['action_hash'], 'BINDING')
        require(ch['purpose'] == 'COMMIT' and ch['request_ref'] == objref(op['challenge_request']) and ch['operation_id'] == ctx['operation_id'] and ch['permit_ref'] == permit and ch['action_hash'] == ctx['action_hash'] and ch['holder'] == ctx['holder'] and ch['holder_kid'] == ctx['holder_kid'], 'BINDING')
        require(proof == {'ctx': ctx, 'permit_ref': permit, 'challenge_ref': objref(op['challenge']), 'session_id': ch['session_id'], 'nonce': ch['nonce'], 'attempt_id': qr['attempt_id']}, 'BINDING')
        require(int(op['proof']['body']['iat']) >= int(op['challenge']['body']['iat']) and int(op['proof']['body']['exp']) <= min(int(op['challenge']['body']['exp']), int(op['permit']['body']['exp'])), 'BINDING')

    def _windows(self, c, op, event):
        for name in ('basis', 'assessment'):
            require_window(op[name]['value'], event)
        for ns, key in [('POLICY', self.scope_key()), ('TASK', self.scope_key() + [op['task_id']]), ('PACKAGE', self.scope_key()), ('IDENTITY', self.scope_key() + [op['action']['payload']['unit_id']])]:
            require_window(self.current(c, ns, key)['record']['value'], event)
        require_window(self.current(c, 'EVIDENCE', op['scene_key'])['record']['value']['attestation'], event)
        for msg in [op[k] for k in ('issue', 'permit', 'challenge_request', 'challenge', 'proof', 'authorization')] + op['reviews']:
            require_window(msg['body'], event)
        for alias in self._required_aliases(op['action'], self.profile):
            self._credential(c, alias, ROLES[self.profile][alias], {'H': 'CommitProof', 'G': 'Permit', 'X': 'Acceptance', 'U': 'Authorization', 'V': 'Review', 'E': 'SOURCE'}[alias], op['action'])
            if alias != 'E':
                self._read_permission(c, alias, op['action'], self.current(c, 'POLICY', self.scope_key())['record']['value'])

    def prepare(self, op):
        op = copy.deepcopy(op); oid = op['action']['operation_id']; request_ref = objref(op['proof'])
        with self.tx() as c:
            existing = c.execute('SELECT * FROM comp_ticket WHERE request_ref=?', (request_ref,)).fetchone()
            event = self._event(c, oid, 'PREPARE', request_ref)
            if existing:
                require(json.loads(existing['op_json']) == op, 'ID_CONFLICT')
                with self.event_guard(event):
                    self._credential(c, 'H', 'HOLDER', 'CommitProof', op['action'])
                return {'ticket_id': existing['ticket_id'], 'prepared_at': existing['prepared_at'], 'expires': existing['expires'], 'request_ref': request_ref}
            with self.event_guard(event):
                self._windows(c, op, event)
                self._verify_signed_chain(c, op, event['lo'])
                self._fresh(c, op, event['lo'])
            ticket = b64(os.urandom(16)); exp = min(event['lo'] + 30, int(op['proof']['body']['exp']))
            c.execute('INSERT INTO comp_ticket VALUES(?,?,?,?,?,?,?)', (ticket, oid, request_ref, _json(op), event['lo'], exp, _json(event)))
        return {'ticket_id': ticket, 'prepared_at': event['lo'], 'expires': exp, 'request_ref': request_ref, 'time_witness': event}

    def challenge_accept(self, ticket_id):
        with self.tx() as c:
            ticket = c.execute('SELECT * FROM comp_ticket WHERE ticket_id=?', (ticket_id,)).fetchone()
            require(ticket is not None, 'NO_PREPARE')
            event = self._event(c, ticket['operation_id'], 'ACCEPT_GUARD', ticket['request_ref'])
            nonce = b64(os.urandom(32))
            c.execute('INSERT INTO comp_accept_nonce VALUES(?,?,?,0)', (nonce, ticket_id, event['lo'] + 30))
            return {'profile': self.profile, 'scope': self.scope, 'operation_id': ticket['operation_id'], 'ticket_id': ticket_id, 'nonce': nonce}

    def _accept_identity(self, c, ticket, proof, event):
        require(type(proof) is dict and set(proof) == {'claim', 'signature'}, 'ACCEPT_AUTH_REQUIRED')
        claim = proof['claim']
        expected = {'profile': self.profile, 'scope': self.scope, 'operation_id': ticket['operation_id'], 'ticket_id': ticket['ticket_id']}
        require(type(claim) is dict and set(claim) == set(expected) | {'nonce'} and all(claim[k] == v for k, v in expected.items()), 'BINDING')
        strict_verify(self.actors['H'].pub, raw(proof['signature'], 64), canonical(['COMP-APP-ACCEPT-v1', claim]))
        nonce = c.execute('SELECT * FROM comp_accept_nonce WHERE nonce=?', (claim['nonce'],)).fetchone()
        require(nonce is not None and nonce['ticket_id'] == ticket['ticket_id'] and nonce['used'] == 0, 'REPLAY')
        require_window({'iat': '0', 'exp': str(nonce['expires'])}, event)
        op = json.loads(ticket['op_json'])
        with self.event_guard(event):
            self._credential(c, 'H', 'HOLDER', 'CommitProof', op['action'])
            policy = self.current(c, 'POLICY', self.scope_key())['record']['value']
            task = self.current(c, 'TASK', self.scope_key() + [op['task_id']])['record']['value']
            require_window(policy, event); require_window(task, event)
            self._read_permission(c, 'H', op['action'], policy)
            require(task['holder'] == self.actors['H'].name and task['holder_kid'] == self.actors['H'].kid, 'WRONG_HOLDER')
        c.execute('UPDATE comp_accept_nonce SET used=1 WHERE nonce=?', (claim['nonce'],))

    def accept(self, ticket_id, signer=None, *, proof=None):
        require(proof is not None, 'ACCEPT_AUTH_REQUIRED')
        with self.tx() as c:
            ticket = c.execute('SELECT * FROM comp_ticket WHERE ticket_id=?', (ticket_id,)).fetchone()
            require(ticket is not None, 'NO_PREPARE')
            event = self._event(c, ticket['operation_id'], 'ACCEPT_GUARD', ticket['request_ref'])
            self._accept_identity(c, ticket, proof, event)
            old = c.execute('SELECT * FROM comp_acceptance WHERE operation_id=?', (ticket['operation_id'],)).fetchone()
            if old:
                require(old['request_ref'] == ticket['request_ref'], 'ID_CONFLICT')
                original = json.loads(ticket['op_json'])
                with self.event_guard(event):
                    self._credential(c, 'H', 'HOLDER', 'CommitProof', original['action'])
                    who = self.actors['H']
                    # Original bytes may be historical; new retrieval identity must be current.
                    envelope(original['proof'], {who.kid: who}, now=int(original['proof']['body']['iat']))
            else:
                op = json.loads(ticket['op_json']); oid = ticket['operation_id']
                require_window({'iat': str(ticket['prepared_at']), 'exp': str(ticket['expires'])}, event)
                with self.event_guard(event):
                    self._windows(c, op, event)
                    plan = self._plan(c, op, event['lo'])
                # Rebind the final logical time after expensive pure signature validation.
                final_event = self._event(c, oid, 'ACCEPT_GUARD', ticket['request_ref'])
                require_window({'iat': str(ticket['prepared_at']), 'exp': str(ticket['expires'])}, final_event)
                with self.event_guard(final_event):
                    self._windows(c, op, final_event)
                    authorization = self.authorization_service.verifier.verify(c,self.profile,op,final_event)
                event = final_event
                commit = plan['commit']; cv = commit['value']; deadline = op['permit']['body']['payload']['dispatch_before']
                cv.update({'accepted_at': str(event['lo']), 'trusted_time': {'lo': str(event['lo']), 'hi': str(event['hi'])}, 'dispatch_before': deadline})
                plan['payload'].update({'accepted_at': str(event['lo']), 'commit_record_ref': rec_ref(commit), 'dispatch_before': deadline})
                core = {'protected': {'proto': 'ZJJ-AAP', 'version': '2.6', 'profile': self.profile, 'alg': 'Ed25519', 'type': 'Acceptance', 'issuer': self.actors['X'].name, 'kid': self.actors['X'].kid}, 'body': {'id': b64(os.urandom(16)), 'scope': self.scope, 'iat': str(event['lo']), 'exp': str(event['lo'] + 900), 'aud': sortset([self.actors[x].name for x in ('H', 'G', 'U')]), 'refs': sortset([cv['permit_ref'], cv['proof_ref'], cv['authorization_ref']] + cv['review_refs']), 'deps': [], 'payload': plan['payload']}}
                core_schema = copy.deepcopy(self.schema.defs['Acceptance']); core_schema['required'].remove('sig'); del core_schema['properties']['sig']
                Draft202012Validator({'$defs': self.schema.defs, **core_schema}).validate(core)
                self.schema.validate(commit, 'Record_COMMIT')
                authorization['w_seq']=c.execute('INSERT INTO a_journal(kind,profile,operation_id,blob) VALUES(?,?,?,?)',('ACCEPT_AUTHORIZATION',self.profile,oid,_json(authorization))).lastrowid
                frozen = {'commit': commit, 'core': core, 'acceptance_ref': objref(core), 'commit_ref': rec_ref(commit), 'accept_time_witness': event, 'authorization_witness':authorization}
                self._write_accept(c, op, plan, frozen)
                c.execute('INSERT INTO comp_acceptance(operation_id,ticket_id,request_ref,frozen_json) VALUES(?,?,?,?)', (oid, ticket_id, ticket['request_ref'], _json(frozen)))
        # A durable fact already exists here; no signing failure can roll it back.
        if signer is not None:
            self.complete_receipt(ticket['operation_id'], signer)
        return self._view(ticket['operation_id'])

    def _write_accept(self, c, op, plan, frozen):
        action = op['action']; p = action['payload']; oid = action['operation_id']; dest = action['destination']
        intent = _json(self.scope_key() + [p['line_id'], p['unit_id'], p['inspection_cycle'], p['phase']])
        require(c.execute('SELECT 1 FROM accept_intent WHERE intent=? OR operation_id=?', (intent, oid)).fetchone() is None, 'DUPLICATE_INTENT')
        proof = op['proof']['body']['payload']
        try:
            c.execute('INSERT INTO comp_consumed VALUES(?,?,?,?,?)', (frozen['commit']['value']['permit_ref'], objref(op['proof']), proof['session_id'], proof['nonce'], oid))
        except sqlite3.IntegrityError as exc:
            raise ProtocolError('REPLAY') from exc
        scene = plan['commit']['value']['scene_after']; bf = plan['freeze']['behavior_after']
        self._scene_update(c, op['scene_key'], plan['scene_revision'], scene['row'])
        self._behavior_update(c, action['principal'], plan['behavior_revision'], bf['row'])
        require(c.execute('UPDATE behavior SET accepted_count=accepted_count+1,revision=revision+1,inflight=? WHERE principal=? AND revision=?', (_json(bf['row']['inflight']), action['principal'], plan['behavior_revision'])).rowcount == 1, 'BEHAVIOR_RACE')
        c.execute('INSERT OR IGNORE INTO resource(destination) VALUES(?)', (dest,))
        require(c.execute('UPDATE resource SET reserved=reserved+1,revision=revision+1 WHERE destination=? AND revision=? AND reserved=? AND spent=? AND reserved+spent+1<=capacity', (dest, plan['resource_revision'], plan['resource_reserved'], plan['resource_spent'])).rowcount == 1, 'RESOURCE_RACE')
        c.execute('INSERT INTO flight VALUES(?,?)', (op['task_id'], oid))
        info = {**plan['freeze'], 'commit_record': frozen['commit'], 'acceptance': None}
        c.execute('INSERT INTO accept_intent(intent,operation_id,scene_namespace,scene_key,accepted_blob) VALUES(?,?,?,?,?)', (intent, oid, PROFILES[self.profile][2], _json(op['scene_key']), _json(info)))
        c.execute('INSERT INTO journal(kind,key,blob) VALUES(?,?,?)', ('ACCEPT', intent, _json(frozen)))

    def complete_receipt(self, operation_id, signer):
        try:
            with self.tx() as c:
                row = c.execute('SELECT * FROM comp_acceptance WHERE operation_id=?', (operation_id,)).fetchone()
                require(row is not None, 'NOT_ACCEPTED')
                if row['receipt_json']:
                    return json.loads(row['receipt_json'])
                frozen = json.loads(row['frozen_json']); core = frozen['core']; action = frozen['commit']['value']['action']
                event = self._event(c, operation_id, 'RECEIPT_SIGN_GUARD', frozen['acceptance_ref'])
                with self.event_guard(event):
                    self._credential(c, 'X', 'EXECUTOR', 'Acceptance', action)
                    require_window(core['body'], event)
                require(signer.info['kid'] == core['protected']['kid'], 'SIGNER_BINDING')
                signed = signer.sign_committed(operation_id, frozen['acceptance_ref'])
                age = time.monotonic_ns() - int(event['sample']['claim']['monotonic_ns'])
                require(0 <= age <= MAX_AGE_NS - AGE_MARGIN_NS, 'CLOCK_UNKNOWN')
                generated = int(signed['generated_wall_ns'])
                sampled = int(event['sample']['claim']['wall_ns'])
                require(sampled - AGE_MARGIN_NS <= generated <= sampled + age + AGE_MARGIN_NS, 'CLOCK_UNKNOWN')
                publish = self._event(c, operation_id, 'RECEIPT_PUBLISH', frozen['acceptance_ref'])
                with self.event_guard(publish):
                    self._credential(c, 'X', 'EXECUTOR', 'Acceptance', action)
                    require_window(core['body'], publish)
                receipt = {**core, 'sig': signed['signature']}
                envelope(receipt, {self.actors['X'].kid: self.actors['X']}, now=publish['lo'])
                self.schema.validate(receipt, 'Acceptance')
                witness = {'sign_guard': event, 'publish_guard': publish, 'generated_wall_ns': signed['generated_wall_ns'], 'control_seq': c.execute('SELECT MAX(seq) FROM journal').fetchone()[0]}
                c.execute('UPDATE comp_acceptance SET receipt_json=?,receipt_witness_json=?,receipt_error=? WHERE operation_id=?', (_json(receipt), _json(witness), '', operation_id))
                info = json.loads(c.execute('SELECT accepted_blob FROM accept_intent WHERE operation_id=?', (operation_id,)).fetchone()[0]); info['acceptance'] = receipt
                c.execute('UPDATE accept_intent SET accepted_blob=? WHERE operation_id=?', (_json(info), operation_id))
                c.execute('INSERT INTO journal(kind,key,blob) VALUES(?,?,?)', ('RECEIPT', operation_id, _json(witness)))
                return receipt
        except ProtocolError as exc:
            with self.tx() as c:
                c.execute('UPDATE comp_acceptance SET receipt_error=? WHERE operation_id=? AND receipt_json IS NULL', (exc.code, operation_id))
            return None

    def _view(self, operation_id):
        with self.db() as c:
            row = c.execute('SELECT * FROM comp_acceptance WHERE operation_id=?', (operation_id,)).fetchone()
            require(row is not None, 'NOT_ACCEPTED')
            return self._project(row, c.execute('SELECT COALESCE(MAX(seq),0) FROM journal').fetchone()[0])

    @staticmethod
    def _project(row, status_seq):
        return {'observation_code': 'ACCEPTED_WITH_RECEIPT' if row['receipt_json'] else 'COMMITTED_RECEIPT_PENDING', 'acceptance_state': 'COMMITTED', 'status_seq': status_seq, 'frozen': json.loads(row['frozen_json']), 'acceptance': json.loads(row['receipt_json']) if row['receipt_json'] else None, 'receipt_error': row['receipt_error'], 'receipt_witness': json.loads(row['receipt_witness_json']) if row['receipt_witness_json'] else None}

    def claim(self, operation_id):
        # The time patch supplies the conservative gate, not PR3's delivery engine.
        with self.db() as c:
            row = c.execute('SELECT receipt_json FROM comp_acceptance WHERE operation_id=?', (operation_id,)).fetchone()
            require(row is not None and row[0] is not None, 'RECEIPT_PENDING')
        raise ProtocolError('DISPATCH_NOT_IMPLEMENTED')

    def challenge_status(self, operation_id):
        nonce = b64(os.urandom(32))
        with self.tx() as c:
            event = self._event(c, operation_id, 'STATUS_READ', '')
            c.execute('INSERT INTO comp_read_nonce VALUES(?,?,?,0)', (nonce, operation_id, event['lo'] + 30))
        return {'profile': self.profile, 'scope': self.scope, 'operation_id': operation_id, 'nonce': nonce}

    def status(self, operation_id, proof):
        require(type(proof) is dict and set(proof) == {'claim', 'signature'}, 'READ_AUTH_REQUIRED')
        claim = proof['claim']; who = self.actors['H']
        require(type(claim) is dict and set(claim) == {'profile', 'scope', 'operation_id', 'nonce'} and (claim['profile'], claim['scope'], claim['operation_id']) == (self.profile, self.scope, operation_id), 'BINDING')
        strict_verify(who.pub, raw(proof['signature'], 64), canonical(['COMP-APP-READ-v1', claim]))
        with self.tx() as c:
            event = self._event(c, operation_id, 'STATUS_READ', digest(claim))
            nonce = c.execute('SELECT * FROM comp_read_nonce WHERE nonce=?', (claim['nonce'],)).fetchone()
            require(nonce is not None and nonce['operation_id'] == operation_id and nonce['used'] == 0, 'REPLAY')
            require_window({'iat': '0', 'exp': str(nonce['expires'])}, event)
            ticket = c.execute('SELECT op_json FROM comp_ticket WHERE operation_id=?', (operation_id,)).fetchone()
            require(ticket is not None, 'STATE_UNAVAILABLE')
            action = json.loads(ticket[0])['action']
            with self.event_guard(event):
                policy = self.current(c, 'POLICY', self.scope_key())['record']['value']
                require_window(policy, event)
                self._read_permission(c, 'H', action, policy)
                task = self.current(c, 'TASK', self.scope_key() + [json.loads(ticket[0])['task_id']])['record']['value']
                require_window(task, event)
                require(task['holder'] == who.name and task['holder_kid'] == who.kid, 'WRONG_HOLDER')
            c.execute('UPDATE comp_read_nonce SET used=1 WHERE nonce=?', (claim['nonce'],))
            row = c.execute('SELECT * FROM comp_acceptance WHERE operation_id=?', (operation_id,)).fetchone()
            require(row is not None, 'NOT_ACCEPTED')
            return self._project(row, c.execute('SELECT COALESCE(MAX(seq),0) FROM journal').fetchone()[0])
