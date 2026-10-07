"""Signed, bounded R2 settlement model; not a product/tool implementation.

Control registration, original acceptance/claim and tool-ledger continuity are
trusted fixture inputs. Real Ed25519 and schemas check evidence; counters model
resource settlement and at-most-one execution rather than real-world effects.
"""
from pathlib import Path
from threading import RLock
import copy
import json
from jsonschema import Draft202012Validator
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from verification.protocol_v25_reference.wire import enc, digest, b64, unb64, kid, verify_raw

ROOT=Path(__file__).resolve().parents[2]
FACT_FIELDS=('ledger_id','operation_id','action_hash','dispatch_attempt','tool','tool_version','destination','outcome','effect_id','no_late_effect','final_seq','finalized_at')
BINDING_FIELDS=('ledger_id','operation_id','action_hash','dispatch_attempt','tool','tool_version','destination')
PROFILE=('PAY-1','payment','pay1','pay-sim')

def public(sk):return sk.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
def sk(seed):return Ed25519PrivateKey.from_private_bytes(bytes([seed])*32)
def record_ref(r):return digest(['ZJJ-RECORD-v1',r['version'],r['profile'],r['kind'],r['scope'],r['value']])
def fact_of(r):return {k:copy.deepcopy(r['value'][k]) for k in FACT_FIELDS}
def fact_id(r):return digest(['ZJJ-TOOL-FACT-v1','2.6','tool-final-v2',r['profile'],r['scope'],fact_of(r)])
def to_sign(r):
    v=copy.deepcopy(r['value']);a=v.pop('attestation')
    return enc(['ZJJ-TOOL-FINAL-v2','2.6',r['profile'],r['scope'],v,{'issuer':a['issuer'],'kid':a['kid']}])
def sign(r,key):
    r=copy.deepcopy(r);r['value']['attestation']['kid']=kid(public(key))
    r['value']['attestation']['sig']=b64(key.sign(to_sign(r)))
    return r
def schema_valid(r,stem,kind):
    s=json.loads((ROOT/'system_dev/v26/contracts'/f'{stem}.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator({'$defs':s['$defs'],'$ref':'#/$defs/Record_'+kind}).validate(r)
def interval(iat,exp,lo,hi):
    if hi<lo or hi-lo>2:raise ValueError('CLOCK_UNKNOWN')
    if lo>=exp:raise ValueError('EXPIRED')
    if not(iat<=lo and hi<exp):raise ValueError('CLOCK_UNKNOWN')

class Ledger:
    """A pre-existing immutable effect ledger fixture, not an execute API."""
    def __init__(self,fact,scope,profile,ledger_id='ledger-1'):
        self.profile=profile;self.scope=copy.deepcopy(scope);self.ledger_id=ledger_id
        self._fact=copy.deepcopy(fact)
        self.call_count=1;self.effect_count=1 if fact and fact['outcome']=='SUCCEEDED' else 0

    def reattest(self,trust,key,now):
        # No execute/retry method is called; cannot turn a missing row into failure.
        if self._fact is None:raise ValueError('UNKNOWN')
        if trust['scope']!=self.scope or trust['profile']!=self.profile or trust['value']['ledger_id']!=self.ledger_id:
            raise ValueError('LEDGER_MISMATCH')
        if trust['value']['kid']!=kid(public(key)):raise ValueError('KID')
        v=trust['value'];interval(int(v['iat']),int(v['exp']),now,now)
        evidence={'version':'2.6','profile':self.profile,'kind':'TOOL_FINAL','scope':copy.deepcopy(self.scope),
          'value':{**copy.deepcopy(self._fact),'method':'tool-final-v2','iat':str(now),'exp':str(min(now+900,int(v['exp']))),
                   'attestation':{'issuer':v['issuer'],'kid':v['kid'],'sig':b64(bytes(64))}}}
        return sign(evidence,key)

class Settlement:
    def __init__(self,expected,scope,profile,stem,trust):
        self.expected=copy.deepcopy(expected);self.scope=copy.deepcopy(scope);self.profile=profile;self.stem=stem
        self.trust=copy.deepcopy(trust);self.lock=RLock()
        # Original claimed attempt and corresponding reservation are assumed valid.
        self.state='EFFECT_UNKNOWN';self.reserved=1;self.spent=0;self.flight=True
        self.settlements=0;self.saved_fact=None;self.saved_fact_id=None;self.receipts={}

    def rotate(self,trust,*,continuity_verified):
        # C-authorized control fixture; a wire record cannot assert this boolean.
        with self.lock:
            schema_valid(trust,self.stem,'TOOL_TRUST')
            if not continuity_verified:raise ValueError('CONTINUITY_UNKNOWN')
            if trust['scope']!=self.scope or trust['profile']!=self.profile:raise ValueError('SCOPE')
            if trust['value']['ledger_id']!=self.expected['ledger_id']:raise ValueError('LEDGER_MISMATCH')
            if int(trust['value']['epoch'])<=int(self.trust['value']['epoch']):raise ValueError('REVISION')
            self.trust=copy.deepcopy(trust)

    def receive(self,r,lo,hi=None):
        if hi is None:hi=lo
        with self.lock:
            schema_valid(r,self.stem,'TOOL_FINAL')
            if r['scope']!=self.scope or r['profile']!=self.profile:raise ValueError('SCOPE')
            rid=record_ref(r)
            # Only the exact locally confirmed canonical bytes get a historical shortcut.
            if rid in self.receipts:
                saved=self.receipts[rid]
                if enc(r)!=saved['bytes']:raise ValueError('OBJECT_INTEGRITY')
                verify_raw(saved['pk'],unb64(r['value']['attestation']['sig'],64),to_sign(r))
                return {'code':'EXISTING','state':self.state,'fact_id':self.saved_fact_id}
            t=self.trust;tv=t['value'];v=r['value'];a=v['attestation']
            schema_valid(t,self.stem,'TOOL_TRUST')
            if t['scope']!=self.scope or t['profile']!=self.profile:raise ValueError('SCOPE')
            if a['issuer']!=tv['issuer'] or a['kid']!=tv['kid']:raise ValueError('CURRENT_KEY')
            pk=unb64(tv['public_key'],32)
            if kid(pk)!=tv['kid']:raise ValueError('KID')
            verify_raw(pk,unb64(a['sig'],64),to_sign(r))
            interval(int(tv['iat']),int(tv['exp']),lo,hi)
            interval(int(v['iat']),int(v['exp']),lo,hi)
            if not(0<int(v['exp'])-int(v['iat'])<=900 and int(v['finalized_at'])<=int(v['iat']) and int(v['exp'])<=int(tv['exp'])):
                raise ValueError('TIME_BINDING')
            if tv['ledger_id']!=self.expected['ledger_id'] or tv['evidence_method']!='tool-final-v2':raise ValueError('LEDGER_MISMATCH')
            for field in BINDING_FIELDS:
                if v[field]!=self.expected[field]:raise ValueError('BINDING')
            for field in ('tool','tool_version','destination'):
                if tv[field]!=v[field]:raise ValueError('BINDING')
            if v['outcome']=='SUCCEEDED':
                if not v['effect_id'] or v['no_late_effect'] is not False:raise ValueError('OUTCOME')
            elif v['effect_id'] or v['no_late_effect'] is not True:raise ValueError('OUTCOME')
            f=fact_of(r);fid=fact_id(r)
            if self.saved_fact is not None and (fid!=self.saved_fact_id or f!=self.saved_fact):
                self.state='HALTED'
                return {'code':'HALTED','state':self.state,'fact_id':self.saved_fact_id}
            if self.state=='HALTED':return {'code':'HALTED','state':self.state,'fact_id':self.saved_fact_id}
            if self.saved_fact is None:
                self.saved_fact=f;self.saved_fact_id=fid;self.settlements+=1
                self.reserved-=1;self.spent+=int(v['outcome']=='SUCCEEDED');self.flight=False;self.state=v['outcome']
                code='SETTLED'
            else:code='EXISTING'
            self.receipts[rid]={'bytes':enc(r),'pk':pk}
            return {'code':code,'state':self.state,'fact_id':fid}

def fixture(profile='PAY-1',outcome='SUCCEEDED'):
    scene,stem,tool={'PAY-1':('payment','pay1','pay-sim'),'IND-DEMO-1':('industrial','industrial','line-sort-sim'),'MED-DEMO-1':('medical','medical','med-order-sim')}[profile]
    scope={'domain':'lab','tenant':'tenant-1','scenario':scene}
    key1,key2=sk(41),sk(42)
    destination='med-demo-ledger' if scene=='medical' else 'ind-release-bin' if scene=='industrial' else 'pay-ledger'
    fact={'ledger_id':'ledger-1','operation_id':b64(bytes([1])*16),'action_hash':b64(bytes([2])*32),'dispatch_attempt':b64(bytes([3])*16),'tool':tool,'tool_version':'1','destination':destination,'outcome':outcome,'effect_id':'effect-1' if outcome=='SUCCEEDED' else '','no_late_effect':outcome=='FAILED_CONFIRMED','final_seq':'1','finalized_at':'101'}
    def trust(key,epoch,iat):
        return {'version':'2.6','profile':profile,'kind':'TOOL_TRUST','scope':copy.deepcopy(scope),'value':{'issuer':'tool-1','tool':tool,'tool_version':'1','destination':destination,'ledger_id':'ledger-1','evidence_method':'tool-final-v2','public_key':b64(public(key)),'kid':kid(public(key)),'epoch':str(epoch),'iat':str(iat),'exp':'10000'}}
    t1,t2=trust(key1,1,100),trust(key2,2,200)
    expected={k:fact[k] for k in BINDING_FIELDS}
    ledger=Ledger(fact,scope,profile)
    return ledger,Settlement(expected,scope,profile,stem,t1),t1,t2,key1,key2
