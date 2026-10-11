"""Controlled fresh IND bootstrap and real signed input chain, never acceptance fixtures."""
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
from research.reference_executor.wire import Identity, b64, keyid, rec_ref, action_hash, sortset, canonical, digest
from research.phase11.scene_r2 import SceneR2W
from research.phase8.scene_authority import ROLES, PURPOSES, DEST, MAPPING, _rec, _clone
from research.conformance39.enrollment_lab import EnrollmentLab
from competition.core.acceptance import CurrentTimeGuards, IndustrialAcceptanceW, objref
from competition.core.signing import ClockClient, ReceiptSigner


class FreshIdentity(Identity):
    def __init__(self, alias):
        self.name = 'demo-' + alias.lower()
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.kid = keyid(self.pub)
        self.roles = frozenset([ROLES['IND-DEMO-1'][alias]])
        self.purposes = frozenset(PURPOSES[alias])


class LiveInitializer(CurrentTimeGuards, SceneR2W):
    pass


@dataclass
class IndustrialRun:
    folder: Path
    issuer: LiveInitializer
    actors: dict
    clock: ClockClient
    x: ReceiptSigner
    w: IndustrialAcceptanceW
    op: dict

    def close(self):
        self.clock.close()
        self.x.close()

    def revoke(self, alias):
        actor = self.actors[alias]; role = ROLES['IND-DEMO-1'][alias]
        key = self.issuer.role_key(actor, role)
        self.issuer.publish('ROLE', key, self.issuer.current_record('ROLE', key), active=False)

    def expire_x_credential(self):
        key = self.issuer.role_key(self.actors['X'], 'EXECUTOR')
        record = self.issuer.current_record('ROLE', key)
        record['value']['exp'] = str(int(time.time()))
        self.issuer.publish('ROLE', key, record)

    def status_proof(self):
        claim = self.w.challenge_status(self.op['action']['operation_id'])
        return {'claim': claim, 'signature': b64(self.actors['H'].key.sign(canonical(['COMP-APP-READ-v1', claim])))}

    def accept_proof(self, ticket_id):
        claim = self.w.challenge_accept(ticket_id)
        return {'claim': claim, 'signature': b64(self.actors['H'].key.sign(canonical(['COMP-APP-ACCEPT-v1', claim])))}

    def save_public_checkpoint(self, path, ticket_id):
        value = {'database': str(self.folder / 'w.sqlite'), 'clock_database': str(self.folder / 'c-clock.sqlite'), 'clock_key_path': str(self.folder / 'C.key'), 'root_public': b64(self.issuer.root_public), 'actors': public_roster(self.actors), 'ticket_id': ticket_id, 'accept_proof': self.accept_proof(ticket_id)}
        path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def public_roster(actors):
    return {alias: {'name': who.name, 'kid': who.kid, 'pub': b64(who.pub), 'roles': sorted(who.roles), 'purposes': sorted(who.purposes)} for alias, who in actors.items()}


def initialize(folder, *, label='DEMO_NORMAL', proof_ttl=30):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    if (folder / 'w.sqlite').exists():
        raise ValueError('Initialization requires a new run; never clear an unresolved W')
    now = int(time.time()); exp = now + 1800; profile = 'IND-DEMO-1'
    root = Ed25519PrivateKey.generate(); actors = {alias: FreshIdentity(alias) for alias in ('H', 'G', 'X', 'U', 'V', 'E')}
    for alias, key in [('C', root), ('X', actors['X'].key)]:
        path = folder / (alias + '.key')
        path.write_bytes(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
        os.chmod(path, 0o600)
    issuer = LiveInitializer(folder / 'w.sqlite', profile, controller=root, actors=actors)
    scope = issuer.scope; prefix = issuer.scope_key()
    event = {'lo': now, 'hi': now}
    with issuer.event_guard(event):
        for alias, actor in actors.items():
            pending = issuer.begin_enrollment(alias, now=now, not_before=now, not_after=exp)
            proof = EnrollmentLab.possession(actor, pending, iat=now, exp=now + 30)
            grant = issuer.complete_enrollment(alias, proof, now=now)
            issuer.publish('KEY', [actor.kid], grant)
            for role in [ROLES[profile][alias]] + (['READER'] if alias in ('H', 'G', 'X', 'U', 'V') else []):
                value = {'subject': actor.name, 'role': role, 'epoch': '1', 'scope_set': [scope], 'tool_set': ['line-sort-sim'], 'destination_set': sortset(list(DEST.values())), 'constraints': issuer._role_constraints(alias, role), 'iat': str(now), 'exp': str(exp)}
                issuer.publish('ROLE', issuer.role_key(actor, role), _rec(profile, 'ROLE_GRANT', scope, value))
        pkg = _rec(profile, 'IND_PACKAGE', scope, {'package_id': 'ind-fixed-package-1', 'package_revision': '1', 'detector': 'SYNTHETIC-LABEL-1', 'preprocessing': 'IDENTITY-1', 'output_schema': 'IND-LABEL-V1', 'mapper': 'IND-ROUTE-V1', 'label_routes': {'normal': 'RELEASE', 'defect': 'QUARANTINE', 'uncertain': 'INSPECT'}, 'iat': str(now), 'exp': str(exp)})
        issuer.publish('PACKAGE', prefix, pkg)
        pv = {'profile': profile, 'policy_revision': '1', 'schema_version': 'ind-payload-v1', 'verifier_version': 'ind-fixed-v1', 'gateway': actors['G'].name, 'gateway_kid': actors['G'].kid, 'executor': actors['X'].name, 'executor_kid': actors['X'].kid, 'source': actors['E'].name, 'readers': sortset([a.name for a in actors.values()]), 'tool': 'line-sort-sim', 'tool_version': '1', 'controller': 'demo-controller', 'line_id': 'demo-line-a', 'station_id': 'demo-check-1', 'route_destinations': {'release': DEST['RELEASE'], 'quarantine': DEST['QUARANTINE'], 'inspect': DEST['INSPECT']}, 'decision_package_ref': rec_ref(pkg), 'history_mode': 'DISABLED', 'max_cycles': '2', 'evidence_ttl_seconds': '300', 'task_ttl_seconds': '900', 'behavior_count_cap': '32', 'capacity_per_destination': '8', 'iat': str(now), 'exp': str(exp)}
        issuer.publish('POLICY', prefix, _rec(profile, 'POLICY', scope, pv))
        unit = _rec(profile, 'IND_UNIT', scope, {'unit_id': 'unit-a', 'batch_id': 'batch-a', 'line_id': 'demo-line-a', 'station_id': 'demo-check-1', 'synthetic': True, 'iat': str(now), 'exp': str(exp)})
        issuer.publish('IDENTITY', prefix + ['unit-a'], unit)
        scene_key = prefix + ['demo-line-a', 'unit-a']
        issuer.init_scene(scene_key, {'unit_ref': rec_ref(unit), 'inspection_cycle': '1', 'phase': 'INITIAL', 'state': 'READY', 'evidence_ref': '', 'operation_id': '', 'predecessor_operation_id': '', 'predecessor_commit_ref': ''})
        data = {'evidence_id': b64(os.urandom(16)), 'evidence_revision': '1', 'unit_ref': rec_ref(unit), 'unit_id': 'unit-a', 'batch_id': 'batch-a', 'line_id': 'demo-line-a', 'station_id': 'demo-check-1', 'inspection_cycle': '1', 'phase': 'INITIAL', 'sampled_at': str(now), 'known_at': str(now), 'quality_flag': 'VALID', 'label': label}
        evidence = issuer.sign_evidence(data, at=now)
        issuer.import_evidence(evidence, scene_key, at=now)
        task_id = b64(os.urandom(16)); route = MAPPING[label]
        tv = {'task_id': task_id, 'task_revision': '1', 'principal': 'principal', 'holder': actors['H'].name, 'holder_kid': actors['H'].kid, 'executor': actors['X'].name, 'policy_ref': issuer._read_row('POLICY', prefix)['ref'], 'line_id': 'demo-line-a', 'station_id': 'demo-check-1', 'allowed_units': [{'unit_ref': rec_ref(unit), 'unit_id': 'unit-a', 'batch_id': 'batch-a', 'inspection_cycle': '1', 'phase': 'INITIAL'}], 'allowed_routes': sortset(list(DEST)), 'tool': 'line-sort-sim', 'tool_version': '1', 'route_destinations': pv['route_destinations'], 'max_inflight': '1', 'iat': str(now), 'exp': str(now + 900)}
        issuer.publish('TASK', prefix + [task_id], _rec(profile, 'IND_TASK', scope, tv))
        action = {'scope': scope, 'operation_id': b64(os.urandom(16)), 'principal': 'principal', 'holder': actors['H'].name, 'holder_kid': actors['H'].kid, 'executor': actors['X'].name, 'tool': 'line-sort-sim', 'tool_version': '1', 'destination': DEST[route], 'payload': {'line_id': 'demo-line-a', 'station_id': 'demo-check-1', 'unit_id': 'unit-a', 'batch_id': 'batch-a', 'inspection_cycle': '1', 'phase': 'INITIAL', 'route': route}}
        issuer.init_behavior(action['principal'])
    # The context below obtains no acceptance privileges; it only constructs signed inputs.
    with issuer.db() as c, issuer.event_guard(event):
        _, _, _, _, required, deps = issuer._bound(c, action, task_id, scene_key, now)
    expiry = now + 120; ah = action_hash(profile, action); policy_ref = tv['policy_ref']; er = rec_ref(evidence)
    av = {'scope': scope, 'operation_id': action['operation_id'], 'action_hash': ah, 'policy_ref': policy_ref, 'task_ref': rec_ref(_rec(profile, 'IND_TASK', scope, tv)), 'evidence_refs': [er], 'cutoff': str(now), 'history_mode': 'DISABLED', 'result': 'MATCH', 'required_reviews': required, 'iat': str(now), 'exp': str(expiry), 'decision_package_ref': rec_ref(pkg), 'method': 'ind-fixed-v1', 'label': label, 'proposed_route': route}
    assessment = _rec(profile, 'ASSESSMENT', scope, av)
    basis = _rec(profile, 'BASIS', scope, {'scope': scope, 'operation_id': action['operation_id'], 'action': action, 'action_hash': ah, 'policy_ref': policy_ref, 'task_ref': av['task_ref'], 'evidence_refs': [er], 'assessment_ref': rec_ref(assessment), 'required_reviews': required, 'deps': deps, 'iat': str(now), 'exp': str(expiry)})
    ctx = {'scope': scope, 'operation_id': action['operation_id'], 'principal': action['principal'], 'holder': action['holder'], 'holder_kid': action['holder_kid'], 'executor': action['executor'], 'action_hash': ah, 'policy_ref': policy_ref, 'basis_ref': rec_ref(basis)}
    def sign(alias, typ, payload, refs=(), aud=('H', 'G', 'X'), ttl=120):
        return actors[alias].sign(profile, typ, scope, payload, refs=refs, deps=deps, aud=[actors[a].name for a in aud], at=now, ttl=ttl, iid=b64(os.urandom(16)))
    reviews = [sign('V', 'Review', {'ctx': ctx, 'purpose': purpose, 'verdict': 'APPROVE', 'reason': 'scene checked'}) for purpose in required]
    rrs = sortset([objref(r) for r in reviews])
    authorization = sign('U', 'Authorization', {'ctx': ctx, 'review_refs': rrs, 'purpose': 'EXECUTE', 'verdict': 'APPROVE'}, refs=rrs)
    ar = objref(authorization); refs = sortset(rrs + [ar])
    issue = sign('H', 'IssueRequest', {'ctx': ctx, 'review_refs': rrs, 'authorization_ref': ar}, refs=refs, aud=('G',))
    permit = sign('G', 'Permit', {'ctx': ctx, 'review_refs': rrs, 'authorization_ref': ar, 'max_uses': '1', 'dispatch_before': str(expiry)}, refs=refs, aud=('H', 'X'))
    pref = objref(permit); attempt = b64(os.urandom(16)); session = b64(os.urandom(16)); nonce = b64(os.urandom(32))
    qr = sign('H', 'ChallengeRequest', {'purpose': 'COMMIT', 'operation_id': action['operation_id'], 'permit_ref': pref, 'action_hash': ah, 'attempt_id': attempt}, refs=[pref], aud=('X',), ttl=30)
    challenge = sign('X', 'Challenge', {'purpose': 'COMMIT', 'operation_id': action['operation_id'], 'permit_ref': pref, 'action_hash': ah, 'holder': action['holder'], 'holder_kid': action['holder_kid'], 'session_id': session, 'nonce': nonce, 'request_ref': objref(qr)}, refs=sortset([pref, objref(qr)]), aud=('H',), ttl=proof_ttl)
    proof = sign('H', 'CommitProof', {'ctx': ctx, 'permit_ref': pref, 'challenge_ref': objref(challenge), 'session_id': session, 'nonce': nonce, 'attempt_id': attempt}, refs=sortset([pref, objref(challenge)]), aud=('X',), ttl=proof_ttl)
    op = {'action': action, 'task_id': task_id, 'scene_key': scene_key, 'assessment': assessment, 'basis': basis, 'ctx': ctx, 'deps': deps, 'required': required, 'at': now, 'reviews': reviews, 'authorization': authorization, 'issue': issue, 'permit': permit, 'challenge_request': qr, 'challenge': challenge, 'proof': proof, 'acceptance': None, 'commit_record': None}
    clock = ClockClient(folder / 'C.key', folder / 'c-clock.sqlite')
    x = ReceiptSigner(folder / 'X.key', folder / 'w.sqlite')
    w = IndustrialAcceptanceW(folder / 'w.sqlite', root_public=issuer.root_public, actors=actors, clock=clock)
    coverage={'profile':profile,'scope':scope,'operation_id':action['operation_id'],'ctx':ctx,'action':action,'purposes':sortset(['EXECUTE']+required),'revision':'1','complete':True,'refs':[]}
    w.authorization_store.initialize_coverage({'claim':coverage,'signature':b64(root.sign(canonical(['COMP-APP-DENY-COVERAGE-v1',coverage])))})
    return IndustrialRun(folder, issuer, actors, clock, x, w, op)
