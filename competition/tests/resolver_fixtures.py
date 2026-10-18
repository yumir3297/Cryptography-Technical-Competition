"""Trusted tests only. Never import into application code or register as a tool."""
import copy
from competition.support.wire import rec_ref

P='IND-DEMO-1'

def approve_in_lab(run, resolved):
    """Explicit synthetic participant approvals via the existing real broker."""
    op=copy.deepcopy(resolved['approval_request'])
    signing=copy.copy(run.base)
    signing.operations={**run.operations,P:op}
    exp=int(op['basis']['value']['exp'])
    op['reviews']=[signing.sign(P,'V','Review',{'ctx':op['ctx'],'purpose':purpose,
        'verdict':'APPROVE','reason':'TRUSTED TEST APPROVAL'},deps=op['deps'],exp=exp)
        for purpose in op['required']]
    signing.resign_chain(P,op,keep_permit_deps=False)
    signing.coverage(P,op)
    return op
