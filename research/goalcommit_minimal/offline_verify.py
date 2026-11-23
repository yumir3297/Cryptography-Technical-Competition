"""Independent, bounded verification of a signed GoalCommit evidence package.

Requires public keys pinned independently; keys shipped *inside* a report
cannot establish trust on their own. This verifies cryptographic bindings and
a resource-floor calculation, NOT real-world execution truth or complete W state.
"""
import argparse
import base64
import json
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from goal_commit import (GOAL_DOM,COMMIT_DOM,RECEIPT_DOM,FINAL_DOM,
                         Reject,check_sig,digest,evaluate_goal,validate_goal,require)


def key_from_b64(s):
    return Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(s+'='*(-len(s)%4)))


def verify_bundle(bundle,c_public,x_public,e_public):
    cert=bundle['c_certificate'];goal=validate_goal(cert['claim'])
    check_sig(c_public,GOAL_DOM,goal,cert['signature'])
    pre=bundle['before'];dec=bundle['decision'];commit=bundle['w_commit']
    profile=bundle['action']['profile'];action=bundle['action']['name'];oid=bundle['action']['oid']
    state={'spent':int(pre['spent']),'reserved':int(pre['reserved']),'status':pre['status']}
    calculated=evaluate_goal(goal,state,action,profile)
    require(dec==calculated,'DECISION_MISMATCH')
    expected={'group':goal['group'],'oid':oid,'goal_ref':digest(GOAL_DOM,goal),
              'deps_ref':digest('ZJJ-GOAL-DEPS-v1',goal['deps']),
              'state_ref':digest('ZJJ-GOAL-STATE-v1',pre),
              'action_ref':digest('ZJJ-GOAL-ACTION-v1',[profile,action,oid]),
              'check_ref':digest('ZJJ-GOAL-CHECK-v1',dec),
              'epoch':goal['epoch'],'accept_seq':str(int(pre['revision'])+1)}
    require(commit==expected,'COMMIT_FIELDS_MISMATCH')
    cref=digest(COMMIT_DOM,commit)
    receipt=bundle['x_receipt'];check_sig(x_public,RECEIPT_DOM,receipt['claim'],receipt['signature'])
    require(receipt['claim']=={'oid':oid,'commit_ref':cref},'RECEIPT_BINDING')
    fact=bundle.get('e_final')
    if fact is not None:
        check_sig(e_public,FINAL_DOM,fact['claim'],fact['signature'])
        require(fact['claim']['oid']==oid and fact['claim']['commit_ref']==cref,'FINAL_BINDING')
    return {'verified':True,'goal_ref':expected['goal_ref'],'commit_ref':cref,
            'cost':dec['cost'],'minimum_remaining':dec['remaining_floor'],
            'has_signed_final':fact is not None,
            'scope':'synthetic witness; no verification of latest W ledger or physical effect'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('package');p.add_argument('--c-public',required=True)
    p.add_argument('--x-public',required=True);p.add_argument('--e-public',required=True)
    args=p.parse_args()
    print(json.dumps(verify_bundle(json.loads(Path(args.package).read_text()),key_from_b64(args.c_public),
                                   key_from_b64(args.x_public),key_from_b64(args.e_public)),indent=2))
