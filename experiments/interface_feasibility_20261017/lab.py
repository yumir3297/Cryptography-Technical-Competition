"""TRUSTED EXPERIMENT HARNESS ONLY; never register this module as an Agent tool.

Synthetic C/participants approve through the baseline broker in a local lab.
This is not evidence of human approval, remote identity auth or real machinery.
"""
import copy
import json
import os
import sys
from competition.support.scene_authority import _rec
from competition.support.wire import action_hash, rec_ref
P='IND-DEMO-1'

def approve_in_trusted_lab(run,row):
    action=copy.deepcopy(row['action'])
    op={'action':action,'task_id':row['task_id'],'scene_key':row['scene_key'],
        'assessment':_rec(P,'ASSESSMENT',action['scope'],copy.deepcopy(row['assessment_value']))}
    with run.store.tx() as c:
        event=run.store.event(c,P,action['operation_id'],'AUTHZ_GUARD','')
        d=run.w.guard.adapters[P].derive(c,op,event)
    av=d['assessment_value'];op['required']=d['required_reviews'];op['deps']=d['deps']
    bv={'scope':action['scope'],'operation_id':action['operation_id'],'action':action,
        'action_hash':action_hash(P,action),'policy_ref':d['policy_ref'],'task_ref':d['task_ref'],
        'evidence_refs':d['evidence_refs'],'assessment_ref':rec_ref(op['assessment']),
        'required_reviews':op['required'],'deps':d['basis_deps'],'iat':av['iat'],'exp':av['exp']}
    op['basis']=_rec(P,'BASIS',action['scope'],bv)
    op['ctx']={k:copy.deepcopy(action[k]) for k in ('scope','operation_id','principal','holder','holder_kid','executor')}
    op['ctx'].update(action_hash=bv['action_hash'],policy_ref=bv['policy_ref'],basis_ref=rec_ref(op['basis']))
    signing=copy.copy(run.base);signing.operations={**run.operations,P:op}
    op['reviews']=[signing.sign(P,'V','Review',{'ctx':op['ctx'],'purpose':purpose,
        'verdict':'APPROVE','reason':'EXPLICIT TRUSTED SIMULATION APPROVAL'},deps=op['deps'],exp=int(av['exp'])) for purpose in op['required']]
    signing.resign_chain(P,op,keep_permit_deps=False)
    signing.coverage(P,op)
    return op

if __name__=='__main__':
    from competition.w_cases import recover_fixture
    from experiments.interface_feasibility_20261017.adapter import TrustedAdapter
    if len(sys.argv)!=4 or sys.argv[1] not in ('allocate-crash','freeze-crash'):raise SystemExit('lab command only')
    run=recover_fixture(sys.argv[2])
    data=json.loads(sys.stdin.read())
    adapter=TrustedAdapter(run.store,sys.argv[3])
    if sys.argv[1]=='freeze-crash':
        adapter.freeze(data['key'],data['op'])
        os._exit(95)
    adapter.submit(data['proposal'],data['auth'])
    os._exit(96) # committed map, lost response; no Python cleanup
