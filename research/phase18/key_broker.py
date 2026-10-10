"""Phase18 role-key broker used by individually owned Linux signer identities.

This module is a restricted one-shot signing *service*, not a general-purpose
signing oracle. It reads exactly the private key owned by its running UID,
validates the canonical protocol domain and role-scoped message type, and emits
only Ed25519 signature bytes. It never prints or exports private keys.

CI sudo/root has powers beyond any DAC sandbox; this proves *unprivileged*
W and sibling roles cannot open other role files, NOT separate trust domains
against a compromised sudo-capable deployment administrator.
"""
from __future__ import annotations
import argparse,base64,hashlib,json,os,sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat

class ProtocolError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

def require(condition,code):
    if not condition:raise ProtocolError(code)

def canonical(value):
    # Exact JSON byte format of the original protocol wire canonicalizer.
    def walk(item,depth=0):
        require(depth<=32,'LIMIT')
        if isinstance(item,dict):
            require(all(type(k) is str and k.isascii() for k in item),'KEY_ENCODING')
            for val in item.values():walk(val,depth+1)
        elif isinstance(item,list):
            require(len(item)<=256,'LIMIT')
            for val in item:walk(val,depth+1)
        elif isinstance(item,str):
            item.encode('utf-8','strict')
        else:require(type(item) is bool,'WIRE_TYPE')
    walk(value)
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')

def b64(raw_bytes):
    return base64.urlsafe_b64encode(raw_bytes).decode().rstrip('=')

def keyid(pub):
    return b64(hashlib.sha256(canonical(['ZJJ-KEY-v1','Ed25519',b64(pub)])).digest())

PROFILES={'H':('IssueRequest','ChallengeRequest','CommitProof'),
 'G':('Permit',),'U':('Authorization',),'X':('Challenge','Acceptance','Result'),
 'V':('Review',)}
# Competition profile bindings. No signer may pick an arbitrary tenant/scope.
PROFILE_SCOPES={
 'IND-DEMO-1':{'domain':'lab','tenant':'tenant-1','scenario':'industrial'},
 'PAY-1':{'domain':'lab','tenant':'tenant-1','scenario':'payment'},
 'MED-DEMO-1':{'domain':'lab','tenant':'tenant-1','scenario':'medical'},
}
SOURCE_TYPES={'IND-DEMO-1':'IND_EVIDENCE','MED-DEMO-1':'MED_EVIDENCE'}
# PAY-1 currently has a separate verified X signer; remaining PAY actor
# names must be frozen by authenticated enrollment before broker enablement.
ISSUER_BY_PROFILE={
 'IND-DEMO-1':{r:'pilot-'+r.lower() for r in PROFILES},
 'MED-DEMO-1':{r:'pilot-'+r.lower() for r in PROFILES},
 'PAY-1':{'X':'executor'},
}
ALLOW_DOMAINS={
 'C':{'ZJJ-CONTROL-TOOL-v1','ZJJ-C-TRUSTED-CLOCK-RESEARCH-v1','ZJJ-C-CONTROL-LAB-v1','ZJJ-P15-C-SOURCE-v1'},
 'E':{'ZJJ-SOURCE-v1'},'TOOL':{'ZJJ-TOOL-FINAL-v2'},
 **{r:{'ZJJ-SIG-v1'} for r in PROFILES},
}
def decode_packet(raw_line,role,pub):
    require(role in ALLOW_DOMAINS,'BROKER_ROLE')
    require(len(raw_line)<=130000,'BROKER_SIZE')
    item=json.loads(raw_line)
    require(type(item) is dict and set(item)=={'message'},'BROKER_FIELDS')
    encoded=item['message']
    require(type(encoded) is str,'BROKER_FIELDS')
    msg=base64.b64decode(encoded,validate=True)
    require(0<len(msg)<=65536,'BROKER_SIZE')
    value=json.loads(msg)
    require(type(value) is list and value and type(value[0]) is str,'BROKER_DOMAIN')
    require(value[0] in ALLOW_DOMAINS[role],'BROKER_DOMAIN')
    require(canonical(value)==msg,'BROKER_NONCANONICAL')
    if role in PROFILES:
        require(len(value)==3 and type(value[1]) is dict and type(value[2]) is dict,
                'BROKER_FORMAT')
        h,b=value[1],value[2]
        profile=h.get('profile')
        require(profile in PROFILE_SCOPES and
            h.get('proto')=='ZJJ-AAP' and h.get('version')=='2.6' and
            h.get('alg')=='Ed25519' and h.get('type') in PROFILES[role] and
            h.get('issuer')==ISSUER_BY_PROFILE[profile].get(role) and
            h.get('kid')==keyid(pub),'BROKER_FOREIGN_ROLE')
        require(b.get('scope')==PROFILE_SCOPES[profile],'BROKER_SCOPE')
        if h['type']=='Result':
            require(profile=='PAY-1' and role=='X','BROKER_RESULT_PROFILE')
        require(type(b.get('payload')) is dict and
                type(b.get('refs')) is list and type(b.get('deps')) is list,
                'BROKER_FIELDS')
    elif role=='E':
        require(len(value)==7 and value[1]=='2.6' and value[2] in SOURCE_TYPES and
            value[3]==SOURCE_TYPES[value[2]] and value[4]==PROFILE_SCOPES[value[2]],
            'BROKER_SOURCE')
        # The source may sign only an evidence record bound to its own E kid.
        att=value[-1]
        require(type(att) is dict and att.get('issuer')=='pilot-e' and
                att.get('kid')==keyid(pub),'BROKER_SOURCE')
    elif role=='C':
        require(len(value)==2 and type(value[1]) is dict,'BROKER_CONTROL_FORMAT')
        claim=value[1];domain=value[0]
        if domain=='ZJJ-C-TRUSTED-CLOCK-RESEARCH-v1':
            profile=claim.get('profile')
            require(profile in PROFILE_SCOPES and
                claim.get('scope')==PROFILE_SCOPES[profile],
                'BROKER_CLOCK_PROFILE')
        elif domain=='ZJJ-CONTROL-TOOL-v1':
            record=claim.get('record')
            require(type(record) is dict and record.get('profile') in PROFILE_SCOPES and
                record.get('scope')==PROFILE_SCOPES[record['profile']],
                'BROKER_TOOL_SCOPE')
        elif domain=='ZJJ-C-CONTROL-LAB-v1':
            record=claim.get('record')
            require(type(record) is dict and record.get('profile') in
                ('IND-DEMO-1','MED-DEMO-1') and
                record.get('scope')==PROFILE_SCOPES[record['profile']] and
                claim.get('scope')==record['scope'],'BROKER_CONTROL_SCOPE')
        elif domain=='ZJJ-P15-C-SOURCE-v1':
            require(claim.get('scope')==PROFILE_SCOPES['PAY-1'] and
                type(claim.get('rows')) is list and
                12<=len(claim['rows'])<=64,'BROKER_SOURCE_SCOPE')
        else:raise ProtocolError('BROKER_CONTROL_DOMAIN')
    elif role=='TOOL':
        require(len(value)>=4 and value[2] in PROFILE_SCOPES,
                'BROKER_TOOL_FINAL_SCOPE')
    return msg

def serve(args):
    require(os.name=='posix','LINUX_ONLY')
    role=args.role
    require(role in ALLOW_DOMAINS,'BROKER_ROLE')
    base=Path(args.directory).resolve()
    # The role file is readable only by its own UID (0600).
    f=base/'signers'/f'{role}.key'
    st=f.stat()
    require(st.st_uid==os.geteuid() and (st.st_mode&0o777)==0o600,
            'BROKER_KEY_OWNER')
    private=Ed25519PrivateKey.from_private_bytes(f.read_bytes())
    pub=private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    msg=decode_packet(sys.stdin.buffer.readline(),role,pub)
    signature=private.sign(msg)
    sys.stdout.write(json.dumps({'signature':b64(signature),'role':role,
         'kid':keyid(pub),'pid':os.getpid(),'euid':os.geteuid()},sort_keys=True)+'\n')

def main():
    p=argparse.ArgumentParser();p.add_argument('--role',required=True)
    p.add_argument('--directory',required=True)
    args=p.parse_args()
    try:serve(args)
    except (ProtocolError,ValueError,KeyError,TypeError,PermissionError) as ex:
        sys.stderr.write('DENY:'+getattr(ex,'code',type(ex).__name__)+'\n')
        raise SystemExit(41)

if __name__=='__main__':main()
