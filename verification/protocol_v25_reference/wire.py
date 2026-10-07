"""PAY-1 2.5 crypto and structural validation; not business authorization."""
import base64, hashlib, json, os, re, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'protocol_v24_crypto'/'vendor'))
from nacl.bindings import (crypto_core_ed25519_is_valid_point, crypto_scalarmult_ed25519_noclamp,
                          crypto_core_ed25519_add)
from nacl.signing import VerifyKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from .schema import SCHEMA

L=2**252+27742317777372353535851937790883648493
SCOPE={'domain':'lab','tenant':'tenant-1','scenario':'payment'}
HEADER={'proto':'ZJJ-AAP','version':'2.5','profile':'PAY-1','alg':'Ed25519'}
WHITESPACE=set(range(9,14))|{32,133,160,5760,8232,8233,8239,8287,12288}|set(range(8192,8203))

class ProtocolError(ValueError): pass

def require(ok, code):
    if not ok: raise ProtocolError(code)

def enc(x):
    def check(y,depth=0):
        require(depth<=32,'LIMIT')
        if isinstance(y,dict):
            require(all(isinstance(k,str) and k.isascii() for k in y),'KEY_ENCODING')
            for v in y.values():check(v,depth+1)
        elif isinstance(y,list):
            for v in y:check(v,depth+1)
        elif isinstance(y,str):y.encode('utf-8','strict')
        else:require(type(y) is bool,'WIRE_TYPE')
    check(x)
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')

def b64(x):return base64.urlsafe_b64encode(x).decode().rstrip('=')
def unb64(s,n):
    require(isinstance(s,str) and bool(re.fullmatch('[A-Za-z0-9_-]+',s)),'BASE64')
    x=base64.urlsafe_b64decode(s+'='*(-len(s)%4))
    require(len(x)==n and b64(x)==s,'BASE64');return x
def digest(x):return b64(hashlib.sha256(enc(x)).digest())
def ref(o):return digest(['ZJJ-OBJ-v1',o['protected'],o['body']])
def kid(pk):return digest(['ZJJ-KEY-v1','Ed25519',b64(pk)])
def ah(a):return digest(['ZJJ-ACTION-v1','2.5','PAY-1',a])
def ident():return b64(os.urandom(16))
def public(sk):return sk.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
def sortedset(items):return sorted(items,key=enc)

def point_ok(p):
    # libsodium documented workaround also covers versions <=1.0.20 mixed-order issue.
    try:
        return (len(p)==32 and crypto_core_ed25519_is_valid_point(p) and
                crypto_core_ed25519_add(crypto_scalarmult_ed25519_noclamp((L-1).to_bytes(32,'little'),p),p)==b'\x01'+bytes(31))
    except Exception:return False

def verify_raw(pk,sig,message):
    require(point_ok(pk),'PUBLIC_KEY_POINT')
    require(len(sig)==64 and point_ok(sig[:32]) and int.from_bytes(sig[32:],'little')<L,'SIGNATURE_ENCODING')
    try:VerifyKey(pk).verify(message,sig)
    except Exception as e:raise ProtocolError('BAD_SIGNATURE') from e

def typed(v,t):
    if isinstance(t,dict):
        require(isinstance(v,dict) and set(v)==set(t),'FIELDS')
        for k,s in t.items():typed(v[k],s)
    elif t in SCHEMA['types']:typed(v,SCHEMA['types'][t])
    elif t.startswith(('set:','list:')):
        require(isinstance(v,list) and len(v)<=256,'ARRAY')
        for x in v:typed(x,t.split(':',1)[1])
        if t.startswith('set:'):require(v==sortedset(v) and len({enc(x) for x in v})==len(v),'SET_ORDER')
    elif t.startswith('maybe:'):
        if v!='':typed(v,t[6:])
    elif t.startswith('enum:'):require(isinstance(v,str) and v in t[5:].split(','),'ENUM')
    elif t.startswith('='):require(v==t[1:],'CONST')
    elif t=='empty':require(v==[],'EMPTY')
    elif t in ('N','Positive','Ratio'):
        require(isinstance(v,str) and bool(re.fullmatch('0|[1-9][0-9]*',v)) and len(v)<=19,'N')
        require(int(v)<=9223372036854775807 and (t!='Positive' or int(v)>0) and (t!='Ratio' or int(v)<=10000),'RANGE')
    elif t in ('B16','B32','B64'):unb64(v,int(t[1:]))
    elif t=='Bool':require(type(v) is bool,'BOOL')
    elif t in ('Text','Nonblank'):
        require(isinstance(v,str) and len(v)<=1024,'TEXT');v.encode('utf-8','strict')
        if t=='Nonblank':require(any(ord(c) not in WHITESPACE for c in v),'BLANK')
    elif t=='Id':require(isinstance(v,str) and bool(re.fullmatch('[a-z0-9][a-z0-9._:-]{0,63}',v)),'ID')
    elif t=='Code':require(isinstance(v,str) and bool(re.fullmatch('[A-Z][A-Z0-9_]{0,63}',v)),'CODE')
    else:raise ProtocolError('SCHEMA')

def payload_refs(p):
    out=[]
    for k,v in p.items():
        if k.endswith('_ref') and v:out.append(v)
        elif k.endswith('_refs'):out.extend(v)
        elif isinstance(v,dict):out.extend(payload_refs(v))
    return sortedset(list(set(out)))

def validate(o):
    require(isinstance(o,dict) and set(o)=={'protected','body','sig'},'ENVELOPE')
    h=o['protected'];b=o['body']
    require(isinstance(h,dict) and set(h)==set(HEADER)|{'issuer','kid','type'},'HEADER')
    require(all(h[k]==v for k,v in HEADER.items()),'PROFILE')
    typed(h['issuer'],'Id');typed(h['kid'],'B32');typ=h['type']
    require(typ in SCHEMA['payloads'],'TYPE')
    typed(b,{'id':'B16','scope':'Scope','iat':'N','exp':'N','aud':'set:Id','refs':'set:B32','deps':'set:Dep','payload':SCHEMA['payloads'][typ]})
    require(b['aud'] and 0<int(b['exp'])-int(b['iat'])<=SCHEMA['lifetimes'][typ],'LIFETIME')
    require(len(o['body']['deps'])<=256,'LIMIT');typed(o['sig'],'B64')
    p=b['payload'];expected=payload_refs(p)
    if typ=='Result' and p['result']=='ISSUED':
        require(set(expected)<set(b['refs']) and len(b['refs'])==len(expected)+1,'REFS')
    else:require(b['refs']==expected,'REFS')
    if typ in ('EnrollmentChallenge','KeyGrant'):
        require(p['kid']==kid(unb64(p['public_key'],32)) and p['purposes'],'KEY_BINDING')
        require(point_ok(unb64(p['public_key'],32)),'PUBLIC_KEY_POINT')
    if typ=='EnrollmentChallenge':
        require(0<int(p['key_not_after'])-int(p['key_not_before'])<=31536000,'KEY_LIFETIME')
    if typ in ('Challenge','ChallengeRequest'):
        require((p['purpose']=='STATUS')==(p['permit_ref']==p['action_hash']==''),'PURPOSE_BINDING')
        if p['purpose']=='COMMIT':require(bool(p['permit_ref'] and p['action_hash']),'PURPOSE_BINDING')
    if typ=='Permit':require(p['dispatch_before']==b['exp'],'DISPATCH_TIME')
    if typ=='StateUpdate':require(int(p['new_revision'])==int(p['expected_revision'])+1,'REVISION')
    if typ=='ExperienceSnapshot':require(len(p['cases'])<=128,'LIMIT')
    require(len(enc(o))<=65536,'LIMIT')
    return o

def parse(data):
    require(isinstance(data,bytes) and len(data)<=65536,'LIMIT')
    def pairs(items):
        out={}
        for k,v in items:require(k not in out,'DUPLICATE');out[k]=v
        return out
    try:o=json.loads(data.decode('utf-8','strict'),object_pairs_hook=pairs)
    except (UnicodeError,json.JSONDecodeError,RecursionError) as e:raise ProtocolError('MALFORMED') from e
    require(enc(o)==data,'NONCANONICAL')
    return validate(o)

def sign(sk,issuer,typ,payload,*,now=100,exp=None,aud=None,deps=None,scope=None,object_id=None):
    h={**HEADER,'issuer':issuer,'kid':kid(public(sk)),'type':typ}
    b={'id':object_id or ident(),'scope':scope or SCOPE,'iat':str(now),'exp':str(exp or now+SCHEMA['lifetimes'][typ]),
       'aud':sortedset(aud or ['executor']),'refs':payload_refs(payload),'deps':sortedset(deps or []),'payload':payload}
    o={'protected':h,'body':b,'sig':b64(sk.sign(enc(['ZJJ-SIG-v1',h,b])))}
    return validate(o)

def verify(o,pk):
    validate(o);require(o['protected']['kid']==kid(pk),'KID')
    verify_raw(pk,unb64(o['sig'],64),enc(['ZJJ-SIG-v1',o['protected'],o['body']]))
    return True

