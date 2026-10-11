"""Actual restricted X child signs only original committed Acceptance bytes.

The child reads W through a read-only SQLite connection. The trusted host and
bootstrap remain the isolation boundary; this is not an HSM or OS DAC claim.
"""
import copy
import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from research.reference_executor.wire import (ProtocolError,require,b64,raw,canonical,
    keyid,action_hash,envelope,good_point)
from competition.core.trusted_state import TrustedState,PublicActor,PROFILE_SCOPES
from competition.core.event_clock import require_window
from research.strict_v26.upstream_schema import UpstreamSchema


class _ReadonlyCredentials(TrustedState):
    """Reuse verified credential logic while deliberately omitting all DB setup."""
    def __init__(self,root_public,profile,actor):
        self.root_public=root_public
        self.actors={profile:{'X':actor}}


class CommonReceiptSigner:
    def __init__(self,key_path,db_path,root_public,profile):
        require(profile in PROFILE_SCOPES and good_point(root_public),'SIGNER_CONFIGURATION')
        self.profile=profile
        self.answers=queue.Queue();self.lock=threading.Lock()
        self.proc=subprocess.Popen([sys.executable,'-m','competition.core.common_receipt',str(Path(key_path).resolve()),
            str(Path(db_path).resolve()),b64(root_public),profile],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1,cwd=str(Path(__file__).resolve().parents[2]))
        def read():
            for line in self.proc.stdout:self.answers.put(line)
            self.answers.put(None)
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        try:self.info=self._answer(5)
        except Exception:
            self.close();raise

    def _answer(self,timeout):
        try:
            line=self.answers.get(timeout=timeout)
            require(line is not None,'SIGNER_UNAVAILABLE')
            result=json.loads(line)
            if 'error' in result:raise ProtocolError(result['error'])
            return result
        except queue.Empty as exc:
            self.close();raise ProtocolError('SIGNER_UNAVAILABLE') from exc
        except (OSError,json.JSONDecodeError) as exc:
            raise ProtocolError('SIGNER_UNAVAILABLE') from exc

    def sign(self,profile,oid,core):
        require(profile==self.profile,'SIGNER_BINDING')
        with self.lock:
            require(self.proc.poll() is None,'SIGNER_UNAVAILABLE')
            try:
                self.proc.stdin.write(json.dumps({'profile':profile,'operation_id':oid,'core':core},ensure_ascii=False)+'\n')
                self.proc.stdin.flush()
            except (OSError,ValueError) as exc:raise ProtocolError('SIGNER_UNAVAILABLE') from exc
            result=self._answer(1.5)
            self.last_generated_wall_ns=result['generated_wall_ns']
            return result['message']

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate();self.proc.wait(timeout=5)
        if hasattr(self,'reader'):self.reader.join(timeout=5)
        for pipe in (self.proc.stdin,self.proc.stdout):
            if pipe:pipe.close()


def _sign_committed(c,request,key,pub,root_public,profile,origin_wall,origin_mono,floor):
    require(type(request) is dict and set(request)=={'profile','operation_id','core'},'SIGNER_REQUEST')
    require(request['profile']==profile,'SIGNER_BINDING');raw(request['operation_id'],16)
    core=request['core'];require(type(core) is dict and set(core)=={'protected','body'},'SIGNER_REQUEST')
    row=c.execute('SELECT frozen FROM w_operation WHERE profile=? AND oid=?',(profile,request['operation_id'])).fetchone()
    require(row is not None,'NOT_COMMITTED')
    frozen=json.loads(row[0]);require(frozen['acceptance_core']==core,'SIGNER_BINDING')
    h,b=core['protected'],core['body'];scope=PROFILE_SCOPES[profile]
    require((h['proto'],h['version'],h['alg'],h['profile'],h['type'],h['kid'],b['scope'])==
            ('ZJJ-AAP','2.6','Ed25519',profile,'Acceptance',keyid(pub),scope),'SIGNER_BINDING')
    require(frozen['x_kid']==h['kid'] and frozen['x_public']==b64(pub),'SIGNER_BINDING')
    action=frozen['op']['action'];payload=b['payload'];ctx=payload['ctx']
    schema=UpstreamSchema(Path(__file__).resolve().parents[2],profile)
    schema.validate(action,'Action')
    require(action['operation_id']==request['operation_id'] and action['scope']==scope
        and action['executor']==h['issuer'] and ctx['action_hash']==action_hash(profile,action)
        and all(ctx[k]==action[k] for k in ('scope','operation_id','principal','holder','holder_kid','executor')),'SIGNER_BINDING')
    require(payload['commit_record_ref']==frozen['commit_ref'] and payload['accepted_at']==str(frozen['accepted_at']),'SIGNER_BINDING')
    wall,mono=time.time_ns(),time.monotonic_ns()
    require(abs((wall-origin_wall)-(mono-origin_mono))<=12_500_000 and wall>=floor,'CLOCK_UNKNOWN')
    now=wall//1_000_000_000
    event={'lo':now,'hi':now}
    actor=PublicActor(h['issuer'],keyid(pub),pub,frozenset({'EXECUTOR'}),frozenset({'Challenge','Acceptance','Result'}))
    view=_ReadonlyCredentials(root_public,profile,actor)
    k,r=view.credential(c,profile,'X','EXECUTOR','Acceptance',action,event)
    for credential,definition in ((k,'Record_KEY_GRANT'),(r,'Record_ROLE_GRANT')):
        schema.validate(credential['record'],definition)
    require_window(b,event)
    message=copy.deepcopy(core);message['sig']=b64(key.sign(canonical(['ZJJ-SIG-v1',h,b])))
    schema.validate(message,'Acceptance')
    envelope(message,{actor.kid:actor},now=now)
    return {'message':message,'generated_wall_ns':str(wall)},wall


def worker(key_path,db_path,root_b64,profile):
    key=Ed25519PrivateKey.from_private_bytes(Path(key_path).read_bytes())
    pub=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw);root_public=raw(root_b64,32)
    require(profile in PROFILE_SCOPES and good_point(root_public),'SIGNER_CONFIGURATION')
    print(json.dumps({'kid':keyid(pub),'public_key':b64(pub),'pid':os.getpid()}),flush=True)
    origin_wall,origin_mono=time.time_ns(),time.monotonic_ns();floor=origin_wall
    for line in sys.stdin:
        try:
            request=json.loads(line)
            uri=Path(db_path).resolve().as_uri()+'?mode=ro'
            with closing(sqlite3.connect(uri,uri=True,isolation_level=None,timeout=0.1)) as c:
                c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
                result,new_floor=_sign_committed(c,request,key,pub,root_public,profile,origin_wall,origin_mono,floor)
                c.execute('COMMIT');floor=new_floor
            print(json.dumps(result,ensure_ascii=False),flush=True)
        except Exception as exc:
            print(json.dumps({'error':exc.code if isinstance(exc,ProtocolError) else 'SIGNER_UNAVAILABLE'}),flush=True)


if __name__=='__main__':worker(*sys.argv[1:])
