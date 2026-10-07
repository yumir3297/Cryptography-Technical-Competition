"""Check protocol artifacts and produce public structural/cryptographic vectors.

No product endpoints, database writes, authorization decision or tools are run.
"""
from pathlib import Path
from datetime import datetime, timezone
import base64
import copy
import hashlib
import json
import re
import subprocess
import sys
import platform
import importlib.metadata

from jsonschema import Draft202012Validator
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

BASE=Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]
sys.path.insert(0,str(ROOT))
from verification.protocol_v25_reference.wire import verify_raw, L
from build_contracts import PROFILES, TYPES, build

def enc(v):
    def check(x):
        if isinstance(x,dict):
            assert all(isinstance(k,str) and k.isascii() for k in x)
            for z in x.values():check(z)
        elif isinstance(x,list):
            for z in x:check(z)
        elif isinstance(x,str):x.encode('utf-8','strict')
        else:assert type(x) is bool
    check(v)
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def b64(v):return base64.urlsafe_b64encode(v).decode().rstrip('=')
def digest(v):return b64(hashlib.sha256(enc(v)).digest())
def ordered(v):return sorted(v,key=enc)
SEED=bytes.fromhex('42'*32)
SK=Ed25519PrivateKey.from_private_bytes(SEED)
PK=SK.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
KID=digest(['ZJJ-KEY-v1','Ed25519',b64(PK)])

def sample(s,d,index=0):
    if '$ref' in s:return sample(d[s['$ref'].split('/')[-1]],d,index)
    if 'const' in s:return s['const']
    if 'enum' in s:return s['enum'][index%len(s['enum'])]
    if 'oneOf' in s:return sample(s['oneOf'][0],d,index)
    typ=s.get('type')
    if typ=='object':return {k:sample(v,d,index) for k,v in s['properties'].items()}
    if typ=='array':
        if 'prefixItems' in s:return [sample(v,d,index) for v in s['prefixItems']]
        values=[sample(s['items'],d,i) for i in range(s.get('minItems',0))]
        return ordered(values) if s.get('uniqueItems') else values
    if typ=='boolean':return True
    if typ=='string':
        if s.get('minLength') in (22,43,86):return b64(bytes([index+1])*{22:16,43:32,86:64}[s['minLength']])
        if 'pattern' in s:
            for value in ('0','1','actor-'+str(index),'审批🙂\n证据'):
                if re.search(s['pattern'],value):return value
        return 'sample'
    raise ValueError(s)

def sign(o):
    o['protected']['kid']=KID
    o['sig']=b64(SK.sign(enc(['ZJJ-SIG-v1',o['protected'],o['body']])))
    return o
def message(profile,typ,schema):
    o=sample(schema['$defs'][typ],schema['$defs'])
    b=o['body'];p=b['payload'];b['iat']='100'
    b['exp']=str(100+min(120,schema['$defs'][typ]['x-zjj-max-lifetime-seconds']))
    b['aud']=['actor-0'];b['refs']=[];b['deps']=[]
    if typ=='Review':p['reason']='审批🙂\n证据'
    if typ=='Permit':p['dispatch_before']=b['exp']
    if typ in ('Challenge','ChallengeRequest'):
        p['purpose']='COMMIT';p['permit_ref']=b64(bytes([4])*32);p['action_hash']=b64(bytes([5])*32)
    if typ=='Result':
        p.update(result='ISSUED',attempt_id='',operation_id=b64(bytes([2])*16),permit_ref=b64(bytes([4])*32),acceptance_ref='',status='NONE',status_seq='0',retry_after='',reasons=[{'check':'result','code':'OK'}])
    keys={'Review':[],'Authorization':['review_refs'],'IssueRequest':['review_refs','authorization_ref'],'Permit':['review_refs','authorization_ref'],'ChallengeRequest':['permit_ref'],'Challenge':['request_ref','permit_ref'],'CommitProof':['permit_ref','challenge_ref'],'Acceptance':['permit_ref','proof_ref','authorization_ref','review_refs'],'Result':['request_ref','permit_ref','acceptance_ref'],'StatusQuery':['challenge_ref']}[typ]
    values=[]
    for k in keys:
        v=p[k];values.extend(v if isinstance(v,list) else [v] if v else [])
    b['refs']=ordered(list(set(values)))
    return sign(o)

def main():
    checks=[]; envelopes=[];records=[];actions=[];tool_evidence=[]
    def require(ok,name):
        checks.append({'id':name,'pass':bool(ok)})
        if not ok:raise AssertionError(name)
    schemas={}
    for profile,(_,stem) in PROFILES.items():
        schema=json.loads((BASE/'contracts'/f'{stem}.schema.json').read_text(encoding='utf-8'))
        require(schema==build(profile),profile+':deterministic-schema')
        Draft202012Validator.check_schema(schema);schemas[profile]=schema
        if profile=='IND-DEMO-1':
            # Independent normative anchor, not sampled from the generator.
            norm=(BASE/'03_industrial_medical_profiles.md').read_text(encoding='utf-8')
            package_id=re.search(r'package_id:"([^"]+)"',norm).group(1)
            require(schema['$defs']['Record_IND_PACKAGE']['properties']['value']['properties']['package_id']['const']==package_id,'IND-DEMO-1:normative-package-id')
        validator=Draft202012Validator(schema)
        require(len([k for k in schema['$defs'] if k in TYPES])==10,profile+':ten-types')
        for typ in TYPES:
            o=message(profile,typ,schema);require(validator.is_valid(o),profile+':'+typ+':structure')
            ts=enc(['ZJJ-SIG-v1',o['protected'],o['body']]); sig=base64.urlsafe_b64decode(o['sig']+'==')
            verify_raw(PK,sig,ts);require(True,profile+':'+typ+':strict-valid-signature')
            v={'id':profile+':'+typ,'envelope':o,'wire_base64':base64.b64encode(enc(o)).decode(),'to_sign_base64':base64.b64encode(ts).decode(),'ref':digest(['ZJJ-OBJ-v1',o['protected'],o['body']])}
            envelopes.append(v)
            for kind in ('unknown','missing','number','profile','scope'):
                bad=copy.deepcopy(o)
                if kind=='unknown':bad['body']['payload']['unexpected']=False
                elif kind=='missing':del bad['body']['payload'][next(iter(bad['body']['payload']))]
                elif kind=='number':bad['body']['iat']=100
                elif kind=='profile':bad['protected']['profile']='PAY-1' if profile!='PAY-1' else 'MED-DEMO-1'
                else:bad['body']['scope']['scenario']='medical' if profile=='PAY-1' else 'payment'
                require(not validator.is_valid(bad),v['id']+':reject-'+kind)
        for name,sub in schema['$defs'].items():
            if not name.startswith('Record_'):continue
            o=sample(sub,schema['$defs'])
            if name=='Record_ROLE_GRANT' and profile!='PAY-1':
                o['value']['role']='HOLDER'
            if name=='Record_PAY_EVIDENCE':
                sign(o['value']['source_envelope'])
                x=o['value']['source_envelope'];o['value']['source_ref']=digest(['ZJJ-OBJ-v1',x['protected'],x['body']])
            nested={'$schema':schema['$schema'],'$defs':schema['$defs'],**sub}
            validator_record=Draft202012Validator(nested)
            require(validator_record.is_valid(o),profile+':'+name+':structure')
            for mode in ('missing','unknown'):
                bad=copy.deepcopy(o)
                if mode=='missing':del bad['value'][next(iter(bad['value']))]
                else:bad['value']['unexpected']=False
                require(not validator_record.is_valid(bad),profile+':'+name+':reject-'+mode)
            records.append({'id':profile+':'+name,'record':o,'wire_base64':base64.b64encode(enc(o)).decode(),'ref':digest(['ZJJ-RECORD-v1',o['version'],o['profile'],o['kind'],o['scope'],o['value']])})
        a=sample(schema['$defs']['Action'],schema['$defs'])
        actions.append({'id':profile+':Action','profile':profile,'action':a,'hash':digest(['ZJJ-ACTION-v1','2.6',profile,a])})
        final=copy.deepcopy(next(v['record'] for v in records if v['id']==profile+':Record_TOOL_FINAL'))
        v=final['value'];v.update(ledger_id='test-ledger',operation_id=b64(bytes([11])*16),action_hash=b64(bytes([12])*32),dispatch_attempt=b64(bytes([13])*16),outcome='SUCCEEDED',effect_id='test-effect',no_late_effect=False,final_seq='1',finalized_at='100',iat='200',exp='1100')
        v['attestation']={'issuer':'test-tool','kid':KID,'sig':b64(bytes(64))}
        unsigned={k:z for k,z in v.items() if k!='attestation'}
        sign_bytes=enc(['ZJJ-TOOL-FINAL-v2','2.6',profile,final['scope'],unsigned,{'issuer':'test-tool','kid':KID}])
        v['attestation']['sig']=b64(SK.sign(sign_bytes))
        vr=Draft202012Validator({'$defs':schema['$defs'],**schema['$defs']['Record_TOOL_FINAL']})
        require(vr.is_valid(final),profile+':tool-v2-signed-structure')
        verify_raw(PK,base64.urlsafe_b64decode(v['attestation']['sig']+'=='),sign_bytes)
        require(True,profile+':tool-v2-strict-signature')
        fields=('ledger_id','operation_id','action_hash','dispatch_attempt','tool','tool_version','destination','outcome','effect_id','no_late_effect','final_seq','finalized_at')
        fact={k:v[k] for k in fields}
        tool_evidence.append({'id':profile+':tool-final-v2','record':final,'public_key':b64(PK),'to_sign_base64':base64.b64encode(sign_bytes).decode(),'fact_id':digest(['ZJJ-TOOL-FACT-v1','2.6','tool-final-v2',profile,final['scope'],fact])})
        for value,expected in [('9223372036854775807',True),('9223372036854775808',False),('01',False),('-1',False),('1\n',False)]:
            atom=Draft202012Validator(schema['$defs']['N']);require(atom.is_valid(value)==expected,profile+':N-'+repr(value))
        if profile!='PAY-1':
            for role in schema['$defs']['Role']['enum']:
                grant=copy.deepcopy(next(v['record'] for v in records if v['id']==profile+':Record_ROLE_GRANT'))
                grant['value']['role']=role
                if role=='AUDITOR':grant['value']['constraints']={'scope_set':[grant['scope']]}
                elif profile=='IND-DEMO-1' and role in ('CONTROLLER','SOURCE','ISSUER','EXECUTOR'):grant['value']['constraints'].pop('unit_set',None)
                vr=Draft202012Validator({'$defs':schema['$defs'],**schema['$defs']['Record_ROLE_GRANT']})
                require(vr.is_valid(grant),profile+':role-'+role)
    # Strict raw encoding checks; no business predicates implied.
    def parse(raw):
        def pairs(items):
            out={}
            for k,v in items:
                if k in out:raise ValueError('duplicate')
                out[k]=v
            return out
        val=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=pairs)
        if enc(val)!=raw:raise ValueError('noncanonical')
        return val
    raw=enc(envelopes[0]['envelope'])
    for name,bad in [('whitespace',b' '+raw),('duplicate',b'{"sig":"duplicate",'+raw[1:]),('bom',b'\xef\xbb\xbf'+raw),('utf8',b'\xff'),('surrogate',b'{"x":"\\ud800"}')]:
        try:parse(bad);ok=False
        except (ValueError,UnicodeError,AssertionError):ok=True
        require(ok,'raw-reject-'+name)
    valid_sig=SK.sign(b'protocol-vector')
    strict_cases=[('identity-key',b'\x01'+bytes(31),valid_sig,b'protocol-vector'),('identity-R',PK,b'\x01'+bytes(31)+valid_sig[32:],b'protocol-vector'),('noncanonical-S',PK,valid_sig[:32]+L.to_bytes(32,'little'),b'protocol-vector'),('invalid-R',PK,bytes([255])*32+valid_sig[32:],b'protocol-vector'),('tampered-message',PK,valid_sig,b'other'),('short-signature',PK,valid_sig[:-1],b'protocol-vector')]
    for name,pk,sig,msg in strict_cases:
        try:verify_raw(pk,sig,msg);ok=False
        except ValueError:ok=True
        require(ok,'strict-reject-'+name)
    out=BASE/'vectors';out.mkdir(exist_ok=True)
    dataset={'contract':'ZJJ-CORE-2.6-R2','test_seed':SEED.hex(),'public_key':b64(PK),'envelopes':envelopes,'records':records,'actions':actions,'tool_evidence':tool_evidence,'scope':'Public structural samples and cryptographic vectors only. Placeholder references do not form valid authorization graphs or real authority snapshots; no protocol action may be accepted from these samples.'}
    path=out/'wire_vectors.json';path.write_text(json.dumps(dataset,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    proc=subprocess.run(['node',str(BASE/'tools/check_vectors.mjs'),str(path)],capture_output=True,text=True,encoding='utf-8',check=False)
    require(proc.returncode==0,'node-cross-language-bytes-and-crypto')
    node=json.loads(proc.stdout)
    require(node['checked']==len(envelopes)+len(records)+len(actions)+len(tool_evidence),'node-vector-count')
    sources=list((BASE/'contracts').glob('*.json'))+list((BASE/'tools').glob('*.py'))+[BASE/'tools/check_vectors.mjs']+list(BASE.glob('0*.md'))+[path,BASE/'README.md',BASE/'semantic_cases.json',ROOT/'system_dev/contracts/pay1.schema.json',ROOT/'verification/protocol_v25_reference/wire.py']
    report={'date':'2026-10-07','generated_at_utc':datetime.now(timezone.utc).isoformat(),'contract':'ZJJ-CORE-2.6-R2','checks_passed':len(checks),'checks':checks,'envelope_vectors':len(envelopes),'record_vectors':len(records),'action_vectors':len(actions),'tool_evidence_vectors':len(tool_evidence),'node':node,'environment':{'python':sys.version,'platform':platform.platform(),'jsonschema':importlib.metadata.version('jsonschema')},'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},'strict_point_check_source':'verification/protocol_v25_reference/wire.py.verify_raw (same mathematical acceptance, no v2.5 message validator used)','limits':['Node comparison checks bytes/hashes/deterministic signing, not JS schema or strict-subgroup rejection.','No handler, registered authority, whole business trajectory, transaction or tool is tested.','No full protocol implementation, independent security audit or formal proof claimed.']}
    (BASE/'verification_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'checks_passed':len(checks),'envelopes':len(envelopes),'records':len(records),'actions':len(actions),'tool_evidence':len(tool_evidence),'node_checked':node['checked']},ensure_ascii=False))

if __name__=='__main__':main()
