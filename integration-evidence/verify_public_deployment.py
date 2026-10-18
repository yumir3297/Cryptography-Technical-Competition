"""Verify a public deployment export without keys, tokens or runtime databases.

Signatures and exported consistency are checked under the bundled synthetic
root; this does not prove physical effects or completeness of a trusted W DB.
"""
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from competition.support.wire import raw, strict_verify, canonical, action_hash, rec_ref, msgref
from competition.support.tool_final import verify_certificate, final_sign_bytes, final_fact_id

def verify(path):
    path=Path(path);e=json.loads(path.read_text());cfg=e['config_public'];p='IND-DEMO-1'
    certificate=json.loads((path.parent/'public-tool-certificate.json').read_text())
    roster={v['kid']:v for v in cfg['actors'][p].values()}
    signatures=0
    for op in (e['original_op'],e['renewed_op']):
        assert action_hash(p,op['action'])==op['ctx']['action_hash']
        for m in op['reviews']+[op[k] for k in ('authorization','issue','permit','challenge_request','challenge','proof')]:
            who=roster[m['protected']['kid']]
            assert m['protected']['issuer']==who['name']
            strict_verify(raw(who['public_key'],32),raw(m['sig'],64),
                          canonical(['ZJJ-SIG-v1',m['protected'],m['body']]))
            signatures+=1
    receipt=e['final']['operation']['receipt']
    who=roster[receipt['protected']['kid']]
    strict_verify(raw(who['public_key'],32),raw(receipt['sig'],64),
                  canonical(['ZJJ-SIG-v1',receipt['protected'],receipt['body']]))
    signatures+=1
    assert rec_ref(e['final']['commit'])==receipt['body']['payload']['commit_record_ref']
    assert e['final']['acceptance_core']=={k:receipt[k] for k in ('protected','body')}
    assert e['before_restart']['commit']==e['after_restart']['commit']==e['final']['commit']
    assert e['original_op']['permit']==e['renewed_op']['permit']
    assert e['original_op']['action']==e['renewed_op']['action']
    trust=verify_certificate(certificate,raw(cfg['root_public'],32),p)
    pub=raw(trust['value']['public_key'],32);record=e['query']['record'];cp=e['query']['checkpoint']
    strict_verify(pub,raw(record['value']['attestation']['sig'],64),final_sign_bytes(record))
    strict_verify(pub,raw(cp['signature'],64),canonical(['COMP-TOOL-CHECKPOINT-v1',cp['claim']]))
    settlement=json.loads((path.parent/'public-settlement.json').read_text())
    assert (settlement['profile'],settlement['oid'])==(p,e['operation_id'])
    assert json.loads(settlement['evidence'])['record']==record
    assert final_fact_id(record)==cp['claim']['final_fact_id']==settlement['fact_id']
    assert record['value']['dispatch_attempt']==e['recovered']['operation']['attempt_id']
    assert e['actual_counts']==dict.fromkeys(('accepts','attempts','exec_consumptions','effects','settlements'),1)
    return {'passed':True,'participant_and_receipt_signatures':signatures,
            'root_signed_tool_certificate':True,'signed_final_and_checkpoint':True,
            'same_commit_core_permit_and_attempt':True,'exported_W_settlement_matches_tool_fact':True,
            'evidence_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'scope':'Bundled synthetic root/roster, signed evidence and exported W projection; no private-state access, current authorization, independent identity or physical effect claim'}

if __name__=='__main__':print(json.dumps(verify(sys.argv[1])))
