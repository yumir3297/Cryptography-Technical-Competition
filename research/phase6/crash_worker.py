"""Real-process kill immediately after durable tool final or after W settlement."""
from __future__ import annotations
import os,sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.phase5.test_durable_w import ready
from research.phase6.trusted_final import Controller,ToolLedger,FinalW,_pub
from research.reference_executor.wire import b64,keyid,sid

def main():
    dest=Path(sys.argv[1]);point=sys.argv[2]
    controller=Controller.fixture();tool=ToolLedger(dest/'tool.sqlite')
    w=FinalW(dest/'w.sqlite',controller.public_key)
    sk=Ed25519PrivateKey.from_private_bytes(b'\x51'*32)
    scope={'domain':'lab','tenant':'tenant-1','scenario':'payment'}
    v={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
       'ledger_id':'ledger1','evidence_method':'tool-final-v2','public_key':b64(_pub(sk)),
       'kid':keyid(_pub(sk)),'epoch':'1','iat':'90','exp':'2000'}
    w.activate(controller.certify(scope,v,1,tool.head(),tool.origin),tool)
    f,op=ready();w.accept(f,op);attempt=sid(501)
    w.claim_bound(op.action['operation_id'],attempt)
    fact=tool.freeze(scope,op.action,attempt,at=105)
    if point=='after_tool_final':os._exit(79)
    record=tool.reattest(scope,fact,sk,'tool-issuer',108,'2000')
    w.settle(record,now=110)
    if point=='after_w_settlement':os._exit(79)
    raise ValueError(point)

if __name__=='__main__':main()
