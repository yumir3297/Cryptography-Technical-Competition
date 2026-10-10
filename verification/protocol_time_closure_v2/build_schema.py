"""Generate only the isolated candidate structural schema; no R2 regeneration."""
from pathlib import Path
import json


def object_schema(fields):
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}


def make_schema():
    def ref(name):
        return {'$ref': '#/$defs/' + name}
    def const(value):
        return {'const': value}
    defs = {
        'N': {'type': 'string', 'pattern': '^(0|[1-9][0-9]*)$', 'maxLength': 19},
        'Positive': {'type': 'string', 'pattern': '^[1-9][0-9]*$', 'maxLength': 19},
        'Id': {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9._:-]{0,63}$'},
        'Profile': {'enum': ['PAY-1', 'IND-DEMO-1', 'MED-DEMO-1']},
    }
    for size, length in ((16,22),(32,43),(64,86)):
        defs['B' + str(size)] = {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{'+str(length)+'}$'}
    defs['Scope'] = object_schema({'domain': ref('Id'), 'tenant': ref('Id'),
                                 'scenario': {'enum': ['payment','industrial','medical']}})
    defs['Interval'] = object_schema({'lo':ref('N'),'hi':ref('N')})
    aud = {'type':'array','items':ref('Id'),'minItems':1,'maxItems':256,'uniqueItems':True,
           'x-zjj-order':'strict lexicographic Enc bytes'}
    def header(kind):
        return object_schema({'proto':const('ZJJ-TIME-RESEARCH'),'version':const('0.2'),
                              'profile':ref('Profile'),'alg':const('Ed25519'),'type':const(kind),
                              'issuer':ref('Id'),'kid':ref('B32')})
    base = {'id':ref('B16'),'scope':ref('Scope'),'iat':ref('N'),'exp':ref('N'),'aud':aud}
    defs['Query'] = object_schema({'protected':header('AcceptanceObservationQuery'),
        'body':object_schema({**base,'operation_id':ref('B16'),'session_id':ref('B16'),
                             'nonce':ref('B32'),'attempt_id':ref('B16')}),'sig':ref('B64')})
    defs['Fact'] = object_schema({'profile':ref('Profile'),'scope':ref('Scope'),'operation_id':ref('B16'),
        'action_hash':ref('B32'),'ledger_origin':ref('Id'),'accept_seq':ref('Positive'),
        'accepted_at':ref('N'),'commit_record_ref':ref('B32'),'original_acceptance_ref':ref('B32'),
        'original_core_digest':ref('B32')})
    defs['Snapshot'] = object_schema({'status':{'enum':['ACCEPTED','EFFECT_UNKNOWN','SUCCEEDED','FAILED_CONFIRMED','HALTED']},
        'status_seq':ref('Positive'),'observed_time':ref('Interval')})
    defs['Observation'] = object_schema({'protected':header('AcceptanceObservation'),
        'body':object_schema({**base,'query_ref':ref('B32'),'query_nonce':ref('B32'),
        'fact':ref('Fact'),'fact_id':ref('B32'),'snapshot':ref('Snapshot'),'control_revision':ref('Positive'),
        'ledger_epoch':ref('Positive'),'history_anchor_ref':ref('B32')}),'sig':ref('B64')})
    defs['Archive'] = object_schema({'format':const('ZJJ-CORE-ARCHIVE-PROPOSED-2'),
        'original_core':object_schema({'protected':{'type':'object'},'body':{'type':'object'}}),
        'commit':{'type':'object'}})
    defs['Package'] = object_schema({'format':const('ZJJ-TIME-PACKAGE-PROPOSED-2'),
                                    'observation':ref('Observation'),'archive':ref('Archive')})
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',
        '$id':'urn:zjj:time-research:0.2','title':'Research candidate query/package; not R2',
        '$comment':'Original Core and COMMIT additionally require the selected original R2 schema and semantics; authority/continuity/publication require trusted inputs.',
        'oneOf':[ref('Query'),ref('Package')],'$defs':defs}


if __name__ == '__main__':
    (Path(__file__).parent / 'schema.json').write_text(json.dumps(make_schema(), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
