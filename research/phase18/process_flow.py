"""Phase18 IND Linux DAC-isolated role keys plugged into Phase17 minimum loop.

Uses per-role Linux users and a single-use subprocess signing interface.
W and other unprivileged UIDs cannot read other actors' private key files.
Privileged CI sudo remains an overall administrator / can issue signing
requests, so these are OS DAC boundary tests, NOT independently sovereign KMS.
"""
from __future__ import annotations
import argparse,base64,hashlib,json,os,pwd,subprocess,sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from research.phase17 import process_flow as v17
from research.phase14.process_flow import dump,load,manifest,db,tool_path
from research.phase16.industrial_delivery import DOMAIN
from research.phase11.run_phase11 import ROOT
from research.reference_executor.wire import (
    ProtocolError,canonical,b64,raw,strict_verify,require,keyid
)
from research.phase18.key_broker import ALLOW_DOMAINS

ROLE_USERS={x:'zjj18_'+x.lower() for x in ALLOW_DOMAINS}
RECORDS=[]
ORIGINAL_LOCAL_KEY=v17.key

def broker_base(directory):
    # A root-owned directory under sticky /tmp; unlike a runner-owned working
    # directory, this cannot be replaced by an unprivileged W process.
    suffix=hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest()[:16]
    return Path('/tmp')/('zjj18_trusted_broker_'+suffix)

def broker_file(directory):
    return broker_base(directory)/'key_broker.py'

def sudo(*argv,check=True,input=None):
    cmd=['sudo','-n',*map(str,argv)]
    return subprocess.run(cmd,cwd=ROOT,input=input,text=True,capture_output=True,
                          timeout=60,check=check)

def setup_isolated_users(d):
    require(os.name=='posix','LINUX_ONLY')
    d=Path(d).resolve()
    v=v17.load(manifest(d))
    # One-time provisioner saw all keys. After migration the keys belong to
    # separate OS principals. Never describe this as HSM attestation.
    roles=sorted(ROLE_USERS)
    for r in roles:
        user=ROLE_USERS[r]
        try:pwd.getpwnam(user)
        except KeyError:
            sudo('useradd','--system','--no-create-home','--shell','/usr/sbin/nologin',user)
    keys=d/'signers'
    keys.chmod(0o711)
    for r in roles:
        file=keys/(r+'.key')
        require(file.is_file() and (file.stat().st_mode&0o777)==0o600,'KEY_MODE_BEFORE')
        sudo('chown',ROLE_USERS[r],file)
        sudo('chmod','0600',file)
    # Root owns the signer directory itself: W cannot unlink/replace a role key.
    # Role owners retain read-only access to their own private key file.
    sudo('chown','root:root',keys)
    sudo('chmod','0711',keys)
    # Install the independently importable signer into a root-owned, immutable
    # (to W) broker directory in /tmp. Parent /tmp has sticky-bit semantics.
    target=broker_base(d)
    sudo('install','-d','-o','root','-g','root','-m','0755',target)
    sudo('install','-o','root','-g','root','-m','0444',
         ROOT/'research/phase18/key_broker.py',broker_file(d))
    require(target.stat().st_uid==0 and broker_file(d).stat().st_uid==0,
            'UNTRUSTED_BROKER_BINARY')
    # WTOOL signer is correctly owned by W; C/E/X/TOOL remain delegated.
    require((keys/'WTOOL.key').stat().st_uid==os.geteuid(),'WTOOL_NOT_LOCAL')
    check=check_permissions(d)
    v['signer_key_custody']='phase18 Linux users own 0600 keys; runner sudo may administer/sign'
    v['isolated_os_key_directory']=True
    dump(manifest(d),v)
    return check

def check_permissions(d):
    d=Path(d).resolve();dir_=d/'signers'
    require((dir_.stat().st_mode&0o777)==0o711 and dir_.stat().st_uid==0,'SIGNERS_DIR_MODE')
    out={'unprivileged_W_cannot_read':True,'other_roles_cannot_read':True,
         'roles_verified':len(ROLE_USERS),'same_ci_runner_has_privileged_sudo':True}
    for role,user in ROLE_USERS.items():
        f=dir_/(role+'.key')
        require(f.stat().st_uid==pwd.getpwnam(user).pw_uid and
                (f.stat().st_mode&0o777)==0o600,'KEY_OWNERSHIP')
        try:f.read_bytes()
        except PermissionError:pass
        else:raise ProtocolError('UNPRIVILEGED_W_READ_SECRET')
        ok=sudo('-u',user,'test','-r',f,check=False)
        require(ok.returncode==0,'OWNER_CANNOT_READ')
        for sibling in ROLE_USERS:
            if sibling==role:continue
            denied=sudo('-u',ROLE_USERS[sibling],'test','-r',f,check=False)
            require(denied.returncode!=0,'CROSS_ROLE_SECRET_ACCESS')
    return out

def public_for(d,role):
    v=load(manifest(d))
    if role in v['fixture_actor_public']:return raw(v['fixture_actor_public'][role]['pub'],32)
    if role=='C':return raw(v['fixture_root_public'],32)
    if role=='TOOL':return raw(v['tool_public'],32)
    raise ProtocolError('UNKNOWN_REMOTE_ROLE')

class RemoteEd25519:
    """Only has public key and delegated sign RPC. Never opens signer private file."""
    def __init__(self,directory,role):
        require(role in ROLE_USERS,'REMOTE_ROLE')
        self.directory=Path(directory).resolve()
        self.role=role
        self.public=public_for(directory,role)
    def public_key(self):
        return Ed25519PublicKey.from_public_bytes(self.public)
    def sign(self,message):
        require(type(message) is bytes and 0<len(message)<=65536,'SIGNER_MESSAGE')
        payload=json.dumps({'message':base64.b64encode(message).decode('ascii')})
        result=sudo('-u',ROLE_USERS[self.role],sys.executable,
                  broker_file(self.directory),'--role',self.role,
                  '--directory',self.directory,check=False,input=payload+'\n')
        if result.returncode:
            # Broker reports only a denial code or Python import failure; never secret bytes.
            sys.stderr.write('ROLE_BROKER_'+self.role+':'+result.stderr[-700:]+'\\n')
            raise ProtocolError('BROKER_REJECTED_'+self.role)
        obj=json.loads(result.stdout)
        require(set(obj)=={'signature','role','kid','pid','euid'} and
                obj['role']==self.role and obj['kid']==keyid(self.public) and
                obj['euid']==pwd.getpwnam(ROLE_USERS[self.role]).pw_uid,
                'BROKER_IDENTITY')
        sig=raw(obj['signature'],64)
        strict_verify(self.public,sig,message)
        RECORDS.append({'role':self.role,'key_kid':obj['kid'],
             'broker_pid':obj['pid'],'signer_euid':obj['euid'],
             'domain':json.loads(message)[0],
             'signature_verified':True})
        return sig

def delegated_key(d,role):
    if role=='WTOOL':
        # This is the W delivery credential, NOT a C/E/X authority key.
        return ORIGINAL_LOCAL_KEY(d,role)
    return RemoteEd25519(d,role)

def worker(d,step):
    v17.key=delegated_key
    out=v17.stage(d,step)
    v=load(manifest(d))
    if RECORDS:
        v.setdefault('isolated_signer_receipts',[]).extend(RECORDS)
        dump(manifest(d),v)
    return out

def subprocess_worker(d,step):
    if step=='provision':
        return v17.subprocess_stage(d,'provision')
    p=subprocess.run([sys.executable,'-m','research.phase18.process_flow',
           '--worker',step,'--dir',str(d)],cwd=ROOT,capture_output=True,
           text=True,timeout=120)
    if step=='tool_crash':
        require(p.returncode==97,'NO_TOOL_POSTCOMMIT_CRASH')
        return {'stage':step,'exit_code':97,'response_lost':True}
    if p.returncode:raise RuntimeError(f'{step}: {p.returncode} {p.stderr[-2300:]}')
    return json.loads(p.stdout)

def run(output):
    d=Path(output).resolve();d.mkdir(parents=True,exist_ok=True)
    require(not any(d.iterdir()),'OUTPUT_NOT_EMPTY')
    results=[subprocess_worker(d,'provision')]
    checks=setup_isolated_users(d)
    for step in v17.STAGES[1:]:
        obj=subprocess_worker(d,step);results.append(obj)
        if step=='tool_crash':
            v=load(manifest(d));v['delivery_crash']=obj;dump(manifest(d),v)
    audited=v17.audit(d)
    v=load(manifest(d))
    receipts=v.get('isolated_signer_receipts',[])
    needed={'E','C','H','G','U','X','TOOL'}
    if v17.PROFILE=='MED-DEMO-1':needed.add('V')
    require(needed.issubset({x['role'] for x in receipts}),'MISSING_EXTERNAL_SIGNER_RECEIPTS')
    require(all(x['signer_euid']!=os.geteuid() for x in receipts),'SIGNER_NOT_SEPARATE_UID')
    require(audited['W_accept_count']==audited['W_call_count']==audited['W_settlement_count']==
            audited['durable_effects']==1,'FULL_LOOP_NOT_CLOSED')
    report={'phase':18,'contract':'ZJJ-CORE-2.6-R2','profile':v17.PROFILE,
      'candidate':'LINUX_DAC_ROLE_KEY_ISOLATION_'+v17.PROFILE+'_MINIMAL_LOOP',
      'official_complete_pass':False,'stage_count':len(results),'stages':results,
      'public_signer_receipts':receipts,'OS_access_audit':checks,
      'readonly_audit':audited,'W_no_C_E_X_file_access':True,
      'signature_provisioner_initially_saw_all_keys':True,
      'CI_sudo_can_impersonate_signer_by_request':True,
      'limitations':[
        'All initial keys are generated in the Phase17 bootstrap process before chown; no independent C/E/X key ceremony',
        'CI has passwordless sudo, thus its controlling account can still invoke privileged signing services',
        'Signer broker validates role/domain, not the complete independently governed business policy',
        'W and signer role calls use local sudo subprocess IPC, not mutually authenticated network services',
        'Laboratory C time signs identical PREPARE and FINALIZE instants; no real latency solution yet',
        'Tool effect is an authenticated simulator ledger fact, not proof of actual physical equipment movement',
        '39 official semantics retain 0 complete PASS; this is an isolated scoped industrial candidate',
      ]}
    dump(d/'phase18_process_report.json',report)
    return report

def main():
    a=argparse.ArgumentParser()
    a.add_argument('--output');a.add_argument('--worker');a.add_argument('--dir')
    z=a.parse_args()
    result=worker(z.dir,z.worker) if z.worker else run(z.output or '/tmp/zjj_phase18_ind')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
