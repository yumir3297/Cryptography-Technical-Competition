"""Independent restricted-canonical-JSON / strict-Ed25519 v2.6 wire checker.

Scope: exact Envelope shell and a subset of payload/role semantics; not the
full upstream Profile Schema, and not a production cryptography implementation.
"""
from __future__ import annotations
import base64, hashlib, json, re
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

L=2**252+27742317777372353535851937790883648493
P=2**255-19
D=(-121665*pow(121666,P-2,P))%P
I=pow(2,(P-1)//4,P)
O=(0,1)
TYPES=('Review','Authorization','IssueRequest','Permit','ChallengeRequest','Challenge','CommitProof','Acceptance','Result','StatusQuery')
PROFILE_SCENARIO={'PAY-1':'payment','IND-DEMO-1':'industrial','MED-DEMO-1':'medical'}
LIFETIME={'Review':900,'Authorization':900,'IssueRequest':120,'Permit':120,'ChallengeRequest':30,'Challenge':30,'CommitProof':30,'Acceptance':900,'Result':30,'StatusQuery':30}
PAYLOAD_FIELDS={
 'Review':{'ctx','purpose','verdict','reason'},
 'Authorization':{'ctx','review_refs','purpose','verdict'},
 'IssueRequest':{'ctx','review_refs','authorization_ref'},
 'Permit':{'ctx','review_refs','authorization_ref','max_uses','dispatch_before'},
 'ChallengeRequest':{'purpose','operation_id','permit_ref','action_hash','attempt_id'},
 'Challenge':{'purpose','operation_id','permit_ref','action_hash','holder','holder_kid','session_id','nonce','request_ref'},
 'CommitProof':{'ctx','permit_ref','challenge_ref','session_id','nonce','attempt_id'},
 'Acceptance':{'ctx','permit_ref','proof_ref','authorization_ref','review_refs','accept_seq','accepted_at','commit_record_ref','dispatch_before'},
 'Result':{'request_ref','attempt_id','result','reasons','operation_id','permit_ref','acceptance_ref','status','status_seq','retry_after'},
 'StatusQuery':{'operation_id','challenge_ref','session_id','nonce','attempt_id'}
}
REF_FIELDS={
 'Review':(), 'Authorization':('review_refs',), 'IssueRequest':('review_refs','authorization_ref'),
 'Permit':('review_refs','authorization_ref'), 'ChallengeRequest':('permit_ref',),
 'Challenge':('request_ref','permit_ref'), 'CommitProof':('permit_ref','challenge_ref'),
 'Acceptance':('permit_ref','proof_ref','authorization_ref','review_refs'),
 'Result':('request_ref','permit_ref','acceptance_ref'), 'StatusQuery':('challenge_ref',)
}

class ProtocolError(ValueError):
 def __init__(self, code):self.code=code;super().__init__(code)

def require(cond,code):
 if not cond:raise ProtocolError(code)

def canonical(v):
 def walk(a,depth=0):
  require(depth<=32,'LIMIT')
  if isinstance(a,dict):
   require(all(type(k) is str and k.isascii() for k in a),'KEY_ENCODING')
   for x in a.values():walk(x,depth+1)
  elif isinstance(a,list):
   require(len(a)<=256,'LIMIT')
   for x in a:walk(x,depth+1)
  elif isinstance(a,str):
   try:a.encode('utf-8','strict')
   except UnicodeError:raise ProtocolError('UNICODE')
  else:require(type(a) is bool,'WIRE_TYPE')
 walk(v)
 return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')

def load_canonical(blob):
 require(isinstance(blob,bytes),'WIRE_TYPE')
 require(len(blob)<=1048576,'LIMIT')
 def pairs(seq):
  d={}
  for k,v in seq:
   require(k not in d,'DUPLICATE_KEY');d[k]=v
  return d
 try:v=json.loads(blob.decode('utf-8','strict'),object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ProtocolError('NUMBER')))
 except (UnicodeError,json.JSONDecodeError):raise ProtocolError('MALFORMED')
 require(canonical(v)==blob,'NONCANONICAL')
 return v

def b64(v):return base64.urlsafe_b64encode(v).decode().rstrip('=')
def raw(s,n):
 require(type(s) is str and re.fullmatch(r'[A-Za-z0-9_-]+',s) is not None,'BASE64')
 try:v=base64.urlsafe_b64decode(s+'='*(-len(s)%4))
 except Exception:raise ProtocolError('BASE64')
 require(len(v)==n and b64(v)==s,'BASE64');return v

def digest(value):return b64(hashlib.sha256(canonical(value)).digest())
def keyid(pub):return digest(['ZJJ-KEY-v1','Ed25519',b64(pub)])
def msgref(env):return digest(['ZJJ-OBJ-v1',env['protected'],env['body']])
def rec_ref(r):return digest(['ZJJ-RECORD-v1',r['version'],r['profile'],r['kind'],r['scope'],r['value']])
def action_hash(profile,action):return digest(['ZJJ-ACTION-v1','2.6',profile,action])
def sid(n):return b64(n.to_bytes(16,'big'))
def is_id(s):return type(s) is str and bool(re.fullmatch(r'[a-z0-9][a-z0-9._:-]{0,63}',s))
def number(s,positive=False):return type(s) is str and bool(re.fullmatch(r'0|[1-9][0-9]*',s)) and int(s)<=9223372036854775807 and (not positive or int(s)>0)
def sortset(a):return sorted(a,key=canonical)
def validset(a,n=None):return type(a) is list and len(a)<=256 and (n is None or len(a)==n) and a==sortset(a) and len({canonical(x) for x in a})==len(a)

def point_decode(s):
 """RFC8032 point decompression + canonical y/x sign checks; test-only Python code."""
 if len(s)!=32:return None
 b=int.from_bytes(s,'little');sign=b>>255;y=b&((1<<255)-1)
 if y>=P:return None
 y2=y*y%P;x2=(y2-1)*pow(D*y2+1,P-2,P)%P
 x=pow(x2,(P+3)//8,P)
 if (x*x-x2)%P:x=x*I%P
 if (x*x-x2)%P:return None
 if x==0 and sign:return None
 if x%2!=sign:x=(-x)%P
 return (x,y)

def _add_extended(a,b):
 # RFC8032 extended Edwards coordinates: no modular inversions in scalar mult.
 x1,y1,z1,t1=a;x2,y2,z2,t2=b
 A=((y1-x1)*(y2-x2))%P
 B=((y1+x1)*(y2+x2))%P
 C=(2*D*t1*t2)%P
 E=(B-A)%P
 F=(2*z1*z2-C)%P
 G=(2*z1*z2+C)%P
 H=(B+A)%P
 return (E*F%P,G*H%P,F*G%P,E*H%P)

def good_point(raw32):
 p=point_decode(raw32)
 if p is None or p==O:return False
 x,y=p;q=(0,1,1,0);r=(x,y,1,x*y%P)
 k=L
 while k:
  if k&1:q=_add_extended(q,r)
  r=_add_extended(r,r);k>>=1
 return q[0]==0 and (q[1]-q[2])%P==0

def strict_verify(pub,signature,message):
 require(good_point(pub),'PUBLIC_KEY_POINT')
 require(len(signature)==64 and good_point(signature[:32]) and int.from_bytes(signature[32:],'little')<L,'SIGNATURE_ENCODING')
 try:Ed25519PublicKey.from_public_bytes(pub).verify(signature,message)
 except InvalidSignature:raise ProtocolError('BAD_SIGNATURE')

class Identity:
 def __init__(self,name,seed,roles=(),purposes=()):
  require(is_id(name),'ID');self.name=name
  self.key=Ed25519PrivateKey.from_private_bytes(bytes([seed])*32)
  from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
  self.pub=self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
  self.kid=keyid(self.pub);self.roles=frozenset(roles);self.purposes=frozenset(purposes)
 def sign(self,profile,kind,scope,payload,refs=(),deps=(),aud=(),iid=None,at=100,ttl=None):
  require(kind in TYPES,'TYPE')
  h={'proto':'ZJJ-AAP','version':'2.6','profile':profile,'alg':'Ed25519','type':kind,'issuer':self.name,'kid':self.kid}
  b={'id':iid or sid(at*100+len(kind)),'scope':scope,'iat':str(at),'exp':str(at+(ttl or LIFETIME[kind])),'aud':sortset(list(aud)),'refs':sortset(list(refs)),'deps':sortset(list(deps)),'payload':payload}
  sig=b64(self.key.sign(canonical(['ZJJ-SIG-v1',h,b])))
  return {'protected':h,'body':b,'sig':sig}

def envelope(env,registered_keys,now=100):
 """Returns valid issuer identity after mandatory structural, temporal, signature checks."""
 require(type(env) is dict and set(env)=={'protected','body','sig'},'FIELDS')
 require(len(canonical(env))<=65536,'LIMIT')
 h,b=env['protected'],env['body']
 require(type(h) is dict and set(h)=={'proto','version','profile','alg','type','issuer','kid'},'FIELDS')
 require(type(b) is dict and set(b)=={'id','scope','iat','exp','aud','refs','deps','payload'},'FIELDS')
 require((h['proto'],h['version'],h['alg'])==('ZJJ-AAP','2.6','Ed25519'),'HEADER')
 profile,kind=h['profile'],h['type']
 require(profile in PROFILE_SCENARIO and kind in TYPES,'TYPE')
 require(is_id(h['issuer']),'ID');raw(h['kid'],32);raw(b['id'],16)
 require(type(b['scope']) is dict and set(b['scope'])=={'domain','tenant','scenario'} and all(is_id(x) for x in b['scope'].values()),'SCOPE')
 require(b['scope']['scenario']==PROFILE_SCENARIO[profile],'WRONG_SCOPE')
 require(number(b['iat']) and number(b['exp']) and 0<int(b['exp'])-int(b['iat'])<=LIFETIME[kind],'LIFETIME')
 require(int(b['iat'])<=now<int(b['exp']),'EXPIRED')
 require(validset(b['aud']) and b['aud'] and all(is_id(x) for x in b['aud']),'AUDIENCE')
 require(validset(b['refs']) and all(type(x) is str and len(raw(x,32))==32 for x in b['refs']),'REFS')
 require(validset(b['deps']) and all(type(d) is dict and set(d)=={'namespace','key','revision','ref'} and is_id(d['namespace'].lower()) and type(d['key']) is list and all(type(x) is str for x in d['key']) and number(d['revision'],True) and len(raw(d['ref'],32))==32 for d in b['deps']),'DEPS')
 p=b['payload'];require(type(p) is dict and set(p)==PAYLOAD_FIELDS[kind],'PAYLOAD_FIELDS')
 expect=[]
 for k in REF_FIELDS[kind]:
  v=p[k];expect.extend(v if type(v) is list else [v] if v else [])
 require(sortset(expect)==b['refs'] and len(set(expect))==len(expect),'REFS')
 who=registered_keys.get(h['kid']);require(who is not None and who.name==h['issuer'] and keyid(who.pub)==h['kid'],'KEY_TRUST')
 require(kind in who.purposes,'KEY_PURPOSE')
 strict_verify(who.pub,raw(env['sig'],64),canonical(['ZJJ-SIG-v1',h,b]))
 return who
