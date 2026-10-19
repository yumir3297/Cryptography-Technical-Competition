"""Pure final-fact helpers and controller certificates for the competition core.

Extracted from ``tool_final`` so the official CommonW chain owns the final-fact
definitions without importing the retired durable-ledger settlement classes.
Names, field order and signing domains are preserved from the original source.
"""
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from competition.support.wire import (b64, canonical, digest, good_point, is_id,
    keyid, number, raw, require, strict_verify)

FACT_FIELDS=('ledger_id','operation_id','action_hash','dispatch_attempt','tool','tool_version',
             'destination','outcome','effect_id','no_late_effect','final_seq','finalized_at')
BASE_FIELDS=set(FACT_FIELDS)|{'method','iat','exp'}
TRUST_FIELDS={'issuer','tool','tool_version','destination','ledger_id','evidence_method',
              'public_key','kid','epoch','iat','exp'}


def final_fact(record):
    return {k:record['value'][k] for k in FACT_FIELDS}

def final_fact_id(record):
    return digest(['ZJJ-TOOL-FACT-v1','2.6','tool-final-v2',record['profile'],record['scope'],final_fact(record)])

def final_sign_bytes(record):
    v=record['value']; t=v['attestation'];vv={k:v[k] for k in v if k!='attestation'}
    return canonical(['ZJJ-TOOL-FINAL-v2','2.6',record['profile'],record['scope'],vv,
                      {'issuer':t['issuer'],'kid':t['kid']}])


def _pub(priv):
    return priv.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)

@dataclass(frozen=True)
class Controller:
    key: Ed25519PrivateKey
    name: str = 'c-root'
    @classmethod
    def fixture(cls):
        return cls(Ed25519PrivateKey.from_private_bytes(b'\x77'*32))
    @property
    def public_key(self):return _pub(self.key)
    def certify(self,scope,value,revision,ledger_head,ledger_origin,profile="PAY-1"):
        require(set(value)==TRUST_FIELDS,'TRUST_FIELDS')
        rec={'version':'2.6','profile':profile,'kind':'TOOL_TRUST','scope':scope,'value':value}
        claim={'record':rec,'revision':str(revision),'ledger_head':ledger_head,'ledger_origin':ledger_origin}
        return {'claim':claim,'root_kid':keyid(self.public_key),
                'signature':b64(self.key.sign(canonical(['ZJJ-CONTROL-TOOL-v1',claim])))}


def verify_certificate(cert,root_pub,expected_profile="PAY-1"):
    require(set(cert)=={'claim','root_kid','signature'},'CONTROL_FIELDS')
    require(cert['root_kid']==keyid(root_pub),'CONTROL_ROOT')
    claim=cert['claim'];require(set(claim)=={'record','revision','ledger_head','ledger_origin'},'CONTROL_FIELDS')
    strict_verify(root_pub,raw(cert['signature'],64),canonical(['ZJJ-CONTROL-TOOL-v1',claim]))
    rec=claim['record'];require(set(rec)=={'version','profile','kind','scope','value'},'RECORD_FIELDS')
    require((rec['version'],rec['profile'],rec['kind'])==('2.6',expected_profile,'TOOL_TRUST'),'TRUST_KIND')
    v=rec['value'];require(set(v)==TRUST_FIELDS and v['evidence_method']=='tool-final-v2','TRUST_FIELDS')
    require(keyid(raw(v['public_key'],32))==v['kid'] and good_point(raw(v['public_key'],32)),'TRUST_KEY')
    require(number(v['epoch'],True) and number(v['iat']) and number(v['exp']) and
            0<int(v['exp'])-int(v['iat'])<=31536000,'TRUST_TIME')
    require(number(claim['revision'],True) and claim['ledger_head'] and len(raw(claim['ledger_origin'],32))==32,'TRUST_REVISION')
    for k in ('issuer','tool','tool_version','destination','ledger_id'):require(is_id(v[k]),'TRUST_ID')
    return rec
