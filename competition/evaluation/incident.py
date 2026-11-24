"""Security-incident response workflow on the one CommonW core.

The official R2 wire profile for this workflow is IND-DEMO-1 (there is no fourth
official R2 profile).  The business layer is not a rename: C certifies a separate
INCIDENT record (severity, status, required actions), the workflow reserves
capacity for critical assets through the GoalFloor, and containment/restoration
use the signed simulator's QUARANTINE/RELEASE routes.  The report states this
wire reuse explicitly.
"""
import copy
import json
import os
import time

from competition.core.trusted_state import PROFILE_SCOPES, prefix
from competition.profiles.w_scenarios import register_ind_unit
from competition.support.scene_contract import _rec
from competition.support.wire import b64, canonical, keyid, require

IND = 'IND-DEMO-1'


def publish_incident(run, *, incident_id, asset, severity, status='TRIGGERED',
                     zone='demo-line-a'):
    value = {'incident_id': incident_id, 'zone': zone, 'asset': asset,
             'severity': severity, 'status': status,
             'required_actions': ['contain'], 'iat': '100', 'exp': '9999999999'}
    record = _rec(IND, 'INCIDENT', PROFILE_SCOPES[IND], value)
    run.base.publish(IND, 'INCIDENT', prefix(IND) + [incident_id], record)
    return value


def ensure_resource(run, op, capacity):
    """Register a second signed resource for a different action destination."""
    from competition.profiles.w_plans import TransactionPlans
    with run.store.db() as c:
        now = int(time.time())
        plan = TransactionPlans(run.store).plan(c, IND, op, {'lo': now, 'hi': now}, 1)
        key = json.dumps(plan['resource_key'], ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'))
        row = c.execute('SELECT certificate FROM w_resource WHERE profile=? AND key=?',
                        (IND, key)).fetchone()
        if row:
            return plan
    claim = {'profile': IND, 'scope': PROFILE_SCOPES[IND], 'key': plan['resource_key'],
             'unit': plan['unit'], 'capacity': str(capacity), 'revision': '1', 'active': True}
    run.w.register_resource({'claim': claim,
                             'signature': b64(run.root.sign(canonical(['COMP-W-RESOURCE-v1', claim])))})
    return plan


def install_incident_tool(run, *, destination='ind-quarantine-bin'):
    """Create a second signed simulator ledger for quarantine effects.

    The default IND tool cert is bound to the inspection destination.  This
    second tool has its own SQLite ledger, key and C certificate, so the
    containment effect is authenticated by the same tool-final-v2 path without
    reusing an inspection certificate.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
    from competition.support.final_fact import Controller
    from competition.tools.common_tool import create_tool_database, ledger_head, ToolGateway
    action = run.operations[IND]['action']
    folder = run.folder
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_path = folder / 'IND-quarantine-tool.key'
    with key_path.open('xb') as stream:
        stream.write(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
    database = folder / 'IND-quarantine-tool.sqlite'
    ledger_id = 'incident-containment-ledger'
    meta = create_tool_database(database, IND, ledger_id)
    now = int(time.time())
    value = {'issuer': 'competition-tool-ind-quarantine', 'tool': action['tool'],
             'tool_version': action['tool_version'], 'destination': destination,
             'ledger_id': ledger_id, 'evidence_method': 'tool-final-v2',
             'public_key': b64(public), 'kid': keyid(public), 'epoch': '1',
             'iat': str(now), 'exp': str(now + 1800)}
    certificate = Controller(run.root).certify(action['scope'], value, 1,
                                               ledger_head(ledger_id, []),
                                               meta['ledger_origin'], IND)
    config = {'database': str(database), 'profile': IND, 'certificate': certificate,
              'root_public': b64(run.store.root_public),
              'w_public': b64(run.delivery_public), 'tool_key_path': str(key_path),
              'clock_key_path': str(folder / 'C.key'),
              'clock_database': str(folder / 'c-clock.sqlite')}
    config_path = folder / 'IND-quarantine-tool.json'
    with config_path.open('x', encoding='utf-8') as stream:
        json.dump(config, stream, ensure_ascii=False, sort_keys=True)
    run.w.register_tool(IND, certificate)
    run.tool_gateways[IND] = ToolGateway(config_path)
    return certificate


def incident_action(run, *, incident, principal, route='QUARANTINE'):
    """Create and sign one asset action bound to a C-certified incident."""
    op = register_ind_unit(run, unit_id=incident['asset'], batch_id=incident['incident_id'],
                           principal=principal, route=route)
    ensure_resource(run, op, 2)
    return run.fork_operation(IND, op)


def set_incident_status(run, incident, status):
    value = copy.deepcopy(incident)
    value['status'] = status
    record = _rec(IND, 'INCIDENT', PROFILE_SCOPES[IND], value)
    run.base.publish(IND, 'INCIDENT', prefix(IND) + [incident['incident_id']], record)
    incident['status'] = status
