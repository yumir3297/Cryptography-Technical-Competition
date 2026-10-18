"""Read-only deployment evidence audit against the exported synthetic trust root."""
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from competition.support.wire import raw, strict_verify, canonical, action_hash, rec_ref, msgref
from competition.support.tool_final import verify_certificate, final_sign_bytes, final_fact_id

def verify(path):
    path=Path(path);e=json.loads(path.read_text());cfg=e['config_public'];p='IND-DEMO-1'
    state=Path(cfg['runtime_dir'])
    tool=json.loads((state/'IND-DEMO-1-tool.json').read_text())
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
    trust=verify_certificate(tool['certificate'],raw(cfg['root_public'],32),p)
    pub=raw(trust['value']['public_key'],32);record=e['query']['record'];cp=e['query']['checkpoint']
    strict_verify(pub,raw(record['value']['attestation']['sig'],64),final_sign_bytes(record))
    strict_verify(pub,raw(cp['signature'],64),canonical(['COMP-TOOL-CHECKPOINT-v1',cp['claim']]))
    with closing(sqlite3.connect((state/'auth-w.sqlite').as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        settlement=dict(c.execute('SELECT * FROM w_settlement WHERE profile=? AND oid=?',
                                   (p,e['operation_id'])).fetchone())
    assert final_fact_id(record)==cp['claim']['final_fact_id']==settlement['fact_id']
    assert record['value']['dispatch_attempt']==e['recovered']['operation']['attempt_id']
    assert e['actual_counts']==dict.fromkeys(('accepts','attempts','exec_consumptions','effects','settlements'),1)
    for name,value in [('public-tool-certificate.json',tool['certificate']),
                       ('public-settlement.json',settlement)]:
        target=path.parent/name
        with target.open('x') as stream:json.dump(value,stream,indent=2)
    return {'passed':True,'participant_and_receipt_signatures':signatures,
            'root_signed_tool_certificate':True,'signed_final_and_checkpoint':True,
            'same_commit_core_permit_and_attempt':True,'W_settlement_matches_tool_fact':True,
            'evidence_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'scope':'Exported local synthetic root/roster and current owned W row; no independent real-world identity or physical effect claim'}

if __name__=='__main__':print(json.dumps(verify(sys.argv[1])))
