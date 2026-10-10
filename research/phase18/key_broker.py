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
import argparse,base64,json,os,sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from research.reference_executor.wire import canonical,b64,keyid,require,ProtocolError

PROFILES={'H':('IssueRequest','ChallengeRequest','CommitProof'),
 'G':('Permit',),'U':('Authorization',),'X':('Challenge','Acceptance'),
 'V':('Review',)}
ALLOW_DOMAINS={
 'C':{'ZJJ-CONTROL-TOOL-v1','ZJJ-C-TRUSTED-CLOCK-RESEARCH-v1','ZJJ-C-CONTROL-LAB-v1'},
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
        require(h.get('proto')=='ZJJ-AAP' and h.get('version')=='2.6' and
            h.get('profile')=='IND-DEMO-1' and h.get('alg')=='Ed25519' and
            h.get('type') in PROFILES[role] and h.get('issuer')=='pilot-'+role.lower() and
            h.get('kid')==keyid(pub),'BROKER_FOREIGN_ROLE')
        require(b.get('scope')=={'domain':'lab','tenant':'tenant-1','scenario':'industrial'},
                'BROKER_SCOPE')
        require(type(b.get('payload')) is dict and
                type(b.get('refs')) is list and type(b.get('deps')) is list,
                'BROKER_FIELDS')
    elif role=='E':
        require(len(value)==8 and value[:5]==['ZJJ-SOURCE-v1','2.6','IND-DEMO-1',
            'IND_EVIDENCE',{'domain':'lab','tenant':'tenant-1','scenario':'industrial'}],
            'BROKER_SOURCE')
        # The source may sign only an evidence record bound to its own E kid.
        att=value[-1]
        require(type(att) is dict and att.get('issuer')=='pilot-e' and
                att.get('kid')==keyid(pub),'BROKER_SOURCE')
    elif role=='C':
        if value[0]=='ZJJ-C-TRUSTED-CLOCK-RESEARCH-v1':
            require(len(value)==2 and value[1].get('profile')=='IND-DEMO-1',
                    'BROKER_CLOCK_PROFILE')
        if value[0]=='ZJJ-CONTROL-TOOL-v1':
            require(len(value)==2 and value[1]['record']['profile']=='IND-DEMO-1',
                    'BROKER_TOOL_SCOPE')
    elif role=='TOOL':
        require(len(value)>=4 and value[2]=='IND-DEMO-1','BROKER_TOOL_FINAL_SCOPE')
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
