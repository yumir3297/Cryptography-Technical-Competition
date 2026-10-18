"""Offline public signature/reference check; does not grant authorization."""
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from competition.support.wire import raw, rec_ref, action_hash, strict_verify, canonical
from competition.support.tool_final import verify_certificate, final_sign_bytes, final_fact_id

def verify(path):
    path=Path(path);e=json.loads(path.read_text())
    actors={v['kid']:v for v in e['public_actors'].values()};count=0
    for op in (e['original_op'],e['renewed_op']):
        assert action_hash('IND-DEMO-1',op['action'])==e['action_hash']
        for m in op['reviews']+[op[k] for k in ('authorization','issue','permit','challenge_request','challenge','proof')]:
            h,b=m['protected'],m['body'];who=actors[h['kid']];assert h['issuer']==who['name']
            strict_verify(raw(who['public_key'],32),raw(m['sig'],64),canonical(['ZJJ-SIG-v1',h,b]));count+=1
    receipt=e['accepted']['acceptance'];who=actors[receipt['protected']['kid']]
    strict_verify(raw(who['public_key'],32),raw(receipt['sig'],64),canonical(['ZJJ-SIG-v1',receipt['protected'],receipt['body']]));count+=1
    assert rec_ref(e['before']['commit'])==receipt['body']['payload']['commit_record_ref']
    assert e['before']['acceptance_core']=={k:receipt[k] for k in ('protected','body')}
    trust=verify_certificate(e['tool_certificate'],raw(e['root_public'],32),'IND-DEMO-1')
    record=e['query']['record'];pub=raw(trust['value']['public_key'],32)
    strict_verify(pub,raw(record['value']['attestation']['sig'],64),final_sign_bytes(record))
    cp=e['query']['checkpoint'];strict_verify(pub,raw(cp['signature'],64),canonical(['COMP-TOOL-CHECKPOINT-v1',cp['claim']]))
    assert final_fact_id(record)==e['settlement']['final_fact_id']==cp['claim']['final_fact_id']
    assert e['dispatch']['attempt_id']==record['value']['dispatch_attempt']==e['recovered']['operation']['attempt_id']
    assert e['before']['commit']==e['after']['commit']
    short={'challenge_request','challenge','proof'}
    assert all(e['original_op'][k]==e['renewed_op'][k] for k in e['original_op'] if k not in short)
    result={'passed':True,'verified_participant_signatures':count,'tool_certificate':True,
        'tool_final_and_checkpoint':True,'original_core_and_commit':True,
        'same_original_permit':e['same_original_permit'],'actual_counts':e['actual_counts'],
        'evidence_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'scope':'Offline signatures against exported lab public roster, references and local-ledger facts; not a replay of current authority graph or a source of new authorization'}
    return result

if __name__=='__main__':print(json.dumps(verify(sys.argv[1])))
