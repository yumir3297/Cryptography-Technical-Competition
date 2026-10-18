"""Fresh common W initialization with independently generated worker/tool keys.

This controlled demonstration owns C setup and participant signing helpers.
CommonW receives public authority state, worker transport capability, and isolated
X/tool process clients. Initialization never resets an existing W or tool ledger.
"""
import copy
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

from competition.core.trusted_state import PROFILE_SCOPES
from competition.profiles.authorization_seed import initialize as initialize_authorization
from competition.profiles.w_plans import TransactionPlans
from competition.support.final_fact import Controller
from competition.support.scene_contract import _rec
from competition.support.wire import WINDOW, action_hash, b64, canonical, keyid, rec_ref, require, sortset


def _public(key):
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _write_key(path, key):
    # Exclusive creation prevents replacement of an existing process credential.
    with Path(path).open('xb') as stream:
        stream.write(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
    os.chmod(path, 0o600)


@dataclass
class WRun:
    base: object
    w: object
    worker_key: object
    worker_certificate: dict
    x_signers: dict
    tool_gateways: dict
    tools: dict
    tool_keys: dict
    configs: dict
    delivery_public: bytes
    delivery_key_path: str

    @property
    def folder(self): return self.base.folder
    @property
    def actors(self): return self.base.actors
    @property
    def root(self): return self.base.root
    @property
    def store(self): return self.base.store
    @property
    def clock(self): return self.base.clock
    @property
    def operations(self): return self.base.operations
    @property
    def signer(self): return self.base.signer
    @signer.setter
    def signer(self, value): self.base.signer = value

    def close(self):
        try:
            for signer in self.x_signers.values(): signer.close()
        finally:
            self.base.close()

    def clone(self, profile): return self.base.clone(profile)
    def identity_proof(self, profile, op, stage='GUARD'):
        return self.base.identity_proof(profile, op, stage)

    def accept_proof(self, profile, ticket):
        claim = self.w.challenge_accept(profile, ticket)
        return {'claim': claim, 'signature': b64(self.actors[profile]['H'].key.sign(
            canonical(['COMP-APP-ACCEPT-v1', claim])))}

    def worker_proof(self, profile, oid, purpose):
        claim = self.w.challenge_worker(profile, oid, purpose)
        return {'claim': claim, 'signature': b64(self.worker_key.sign(canonical(['COMP-W-WORKER-v1', claim])))}

    def read_proof(self, profile, oid, purpose='STATUS'):
        claim = self.w.challenge_read(profile, oid, purpose)
        return {'claim': claim, 'signature': b64(self.actors[profile]['H'].key.sign(
            canonical(['COMP-W-READ-v1', claim])))}

    def fork_operation(self, profile, op=None):
        """Re-derive current business facts and sign a fresh genuine full chain.

        Source records and their iat/exp are retained. A fork keeps the original
        assessment cutoff and expiry, so it cannot extend E's authority window.
        """
        op = copy.deepcopy(op if op is not None else self.operations[profile])
        op['action']['operation_id'] = b64(os.urandom(16))
        now = int(time.time())
        frozen = op['assessment']['value']
        op['assessment'] = {'value': {'cutoff': frozen['cutoff'], 'iat': str(now), 'exp': frozen['exp']}}
        with self.store.tx() as c:
            event = self.store.event(c, profile, op['action']['operation_id'], 'AUTHZ_GUARD', '')
            derived = self.w.guard.adapters[profile].derive(c, op, event)
        scope = op['action']['scope']; av = derived['assessment_value']
        op['assessment'] = _rec(profile, 'ASSESSMENT', scope, av)
        op['required'] = derived['required_reviews']; op['deps'] = derived['deps']
        bv = {'scope': scope, 'operation_id': op['action']['operation_id'], 'action': op['action'],
              'action_hash': action_hash(profile, op['action']), 'policy_ref': derived['policy_ref'],
              'task_ref': derived['task_ref'], 'evidence_refs': derived['evidence_refs'],
              'assessment_ref': rec_ref(op['assessment']), 'required_reviews': op['required'],
              'deps': derived['basis_deps'], 'iat': av['iat'], 'exp': av['exp']}
        op['basis'] = _rec(profile, 'BASIS', scope, bv)
        op['ctx'] = {k: copy.deepcopy(op['action'][k]) for k in
                     ('scope', 'operation_id', 'principal', 'holder', 'holder_kid', 'executor')}
        op['ctx'].update(action_hash=bv['action_hash'], policy_ref=bv['policy_ref'], basis_ref=rec_ref(op['basis']))
        # Reuse the real participant/broker path with an isolated operations map.
        # No temporary replacement of the base's caller-visible operation occurs.
        signing = copy.copy(self.base)
        signing.operations = {**self.operations, profile: op}
        op['reviews'] = [signing.sign(profile, 'V', 'Review', {
            'ctx': op['ctx'], 'purpose': purpose, 'verdict': 'APPROVE',
            'reason': 'authenticated required review'}, deps=op['deps'], exp=int(av['exp']))
            for purpose in op['required']]
        signing.resign_chain(profile, op, keep_permit_deps=False)
        signing.coverage(profile, op)
        return op


def initialize(folder, *, resource_capacity=None, fleet=None, **authorization_kwargs):
    """Create one fresh authenticated three-profile W and three tool ledgers.

    With no ``fleet`` the controlled bootstrap makes every key and keeps it: the
    local fallback, unchanged.  With a ``fleet`` the endpoints made the keys and
    published only the public halves, so nothing is generated for them here and no
    role, worker or tool key file is written.  ``W-delivery.key`` is generated
    either way -- the delivery key is W's own, and W is the trusted side.
    """
    from competition.core.common_w import CommonW
    from competition.core.common_receipt import CommonReceiptSigner
    from competition.tools.common_tool import create_tool_database, ledger_head, ToolGateway

    folder = Path(folder).resolve()
    require(resource_capacity is None or (type(resource_capacity) is dict and
            set(resource_capacity) <= set(PROFILE_SCOPES)), 'RESOURCE_SCOPE')
    require(fleet is None or 'roster' not in authorization_kwargs, 'INIT_FLEET')
    resource_capacity = {} if resource_capacity is None else resource_capacity
    if fleet is not None:
        authorization_kwargs['roster'] = fleet.roster()
    names = ['W-worker.key', 'W-delivery.key'] + [profile + suffix for profile in PROFILE_SCOPES
                              for suffix in ('-tool.key', '-tool.sqlite', '-tool.json')]
    if (folder / 'auth-w.sqlite').exists() or any((folder / name).exists() for name in names):
        raise ValueError('New initialization must never reset an existing W or tool ledger')
    base = initialize_authorization(folder, **authorization_kwargs)
    x_signers = {}
    try:
        if fleet is None:
            # Local fallback (default path): the bootstrap makes the worker key too.
            worker = Ed25519PrivateKey.generate(); worker_public = _public(worker)
            _write_key(folder / 'W-worker.key', worker)
        else:
            # External mode: the worker endpoint owns the key; only the public and
            # the way to reach it cross over.
            worker_entry = fleet.worker()
            worker = fleet.remote_key(worker_entry); worker_public = worker_entry.pub
        delivery = Ed25519PrivateKey.generate(); delivery_public = _public(delivery)
        _write_key(folder / 'W-delivery.key', delivery)
        now = int(time.time()); exp = now + WINDOW
        worker_claim = {'subject': 'competition-worker', 'kid': keyid(worker_public),
                        'public_key': b64(worker_public), 'profiles': sortset(list(PROFILE_SCOPES)),
                        'scopes': sortset(list(PROFILE_SCOPES.values())),
                        'purposes': ['AUDIT', 'CANCEL', 'CLAIM', 'EXECUTE', 'QUERY', 'RECEIPT', 'SETTLE'],
                        'iat': str(now), 'exp': str(exp), 'revision': '1', 'active': True}
        worker_certificate = {'claim': worker_claim, 'signature': b64(base.root.sign(
            canonical(['COMP-W-WORKER-GRANT-v1', worker_claim])))}
        tools, gateways, tool_keys, configs = {}, {}, {}, {}
        controller = Controller(base.root)
        for profile, op in base.operations.items():
            if fleet is None:
                tool_key = Ed25519PrivateKey.generate(); public = _public(tool_key)
                key_path = folder / (profile + '-tool.key')
                _write_key(key_path, tool_key)
                x_key_path = folder / (profile + '-X.key')
            else:
                # The tool process and the X receipt child each read their own
                # credential from their own endpoint directory; the trusted side
                # keeps only the path and the published public key.  Nothing here
                # ever signs with a tool key: the tool signs inside its own
                # process, so there is no key object to hand out.
                tool_entry = fleet.find('tool', profile)
                tool_key = None; public = tool_entry.pub
                key_path = Path(fleet.key_path(tool_entry))
                x_key_path = fleet.key_path(fleet.find('X', profile))
            database = folder / (profile + '-tool.sqlite')
            ledger_id = 'competition-ledger-' + profile.lower()
            meta = create_tool_database(database, profile, ledger_id)
            action = op['action']
            value = {'issuer': 'competition-tool-' + profile.lower(), 'tool': action['tool'],
                     'tool_version': action['tool_version'], 'destination': action['destination'],
                     'ledger_id': ledger_id, 'evidence_method': 'tool-final-v2',
                     'public_key': b64(public), 'kid': keyid(public), 'epoch': '1',
                     'iat': str(now), 'exp': str(exp)}
            certificate = controller.certify(action['scope'], value, 1, ledger_head(ledger_id, []),
                                             meta['ledger_origin'], profile)
            base.store.schemas[profile].validate(certificate['claim']['record'], 'Record_TOOL_TRUST')
            config = {'database': str(database), 'profile': profile, 'certificate': certificate,
                      'root_public': b64(base.store.root_public), 'w_public': b64(delivery_public),
                      'tool_key_path': str(key_path), 'clock_key_path': str(folder / 'C.key'),
                      'clock_database': str(folder / 'c-clock.sqlite')}
            config_path = folder / (profile + '-tool.json')
            with config_path.open('x', encoding='utf-8') as stream:
                json.dump(config, stream, ensure_ascii=False, sort_keys=True)
            tools[profile] = {'database': str(database), 'config_path': str(config_path),
                              'key_path': str(key_path), 'certificate': certificate}
            tool_keys[profile] = tool_key
            configs[profile] = str(config_path)
            gateways[profile] = ToolGateway(config_path)
            x_signers[profile] = CommonReceiptSigner(x_key_path, base.store.path,
                                                    base.store.root_public, profile)
        w = CommonW(base.store, delivery, worker_certificate, x_signers, gateways)
        planner = TransactionPlans(base.store)
        for profile, op in base.operations.items():
            w.register_tool(profile, tools[profile]['certificate'])
            with base.store.db() as c:
                at = int(time.time())
                plan = planner.plan(c, profile, op, {'lo': at, 'hi': at}, 1)
            capacity = resource_capacity.get(profile, plan['limit'])
            require(type(capacity) is int and 0 < capacity <= plan['limit'], 'RESOURCE_CAPACITY')
            resource_claim = {'profile': profile, 'scope': PROFILE_SCOPES[profile],
                              'key': plan['resource_key'], 'unit': plan['unit'],
                              'capacity': str(capacity), 'revision': '1', 'active': True}
            w.register_resource({'claim': resource_claim, 'signature': b64(base.root.sign(
                canonical(['COMP-W-RESOURCE-v1', resource_claim])))})
        return WRun(base, w, worker, worker_certificate, x_signers, gateways, tools, tool_keys, configs,
                    delivery_public, str(folder / 'W-delivery.key'))
    except BaseException:
        try:
            for signer in x_signers.values(): signer.close()
        finally:
            base.close()
        raise
