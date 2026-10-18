"""Controlled local SIMULATOR acceptance operator, never an Agent service.

Loads synthetic role keys and supplies explicit lab approvals outside the HTTP
host. Run only against a freshly provisioned owned simulator installation.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
import urllib.error
import urllib.request

from competition.application.local_runtime import inspect_config
from competition.application.trusted_action_resolver import AUTH_DOMAIN
from competition.tests.resolver_fixtures import approve_in_lab, P
from competition.tests.renewal_fixtures import refresh_short, SHORT
from competition.support.wire import b64, canonical, require
from competition.w_cases import recover_fixture, public_snapshot

def accept(config_path, evidence_path):
    config=Path(config_path).resolve()
    cfg=inspect_config(config)
    output=Path(evidence_path).resolve();output.mkdir(parents=True,exist_ok=False)
    env={k:v for k,v in os.environ.items() if k!='PYTHONHOME'}
    source=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(Path('competition').rglob('*.py'))}
    before_source=source()
    (output/'source-before.json').write_text(json.dumps(before_source,indent=2))
    token=(config.parent/'transport-token').read_text().strip()
    run=recover_fixture(config.parent/'lab-metadata.json')
    hosts=[];logs=[];transcript=[];checks=[]
    def passed(name,details=None):
        checks.append({'check':name,'passed':True,'details':details})
    def start():
        log=(output/('host-'+str(len(hosts)+1)+'.log')).open('x')
        proc=subprocess.Popen([sys.executable,'-m','competition.application.local_runtime',
            '--config',str(config)],stdout=log,stderr=subprocess.STDOUT,env=env)
        hosts.append(proc);logs.append(log)
        ready=config.parent/'service-ready.json';deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            if ready.exists():
                value=json.loads(ready.read_text())
                if value['pid']==proc.pid:return value
            require(proc.poll() is None,'DEPLOYMENT_START_FAILED')
            time.sleep(.05)
        raise RuntimeError('Deployment readiness timeout')
    def stop(proc):
        if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
        require(proc.returncode==0,'DEPLOYMENT_STOP_FAILED')
    info=None
    def call(method,params,*,expected=None,transport_token=token):
        request=urllib.request.Request(info['url']+'/v1/operation',
            json.dumps({'method':method,'params':params}).encode(),
            {'Content-Type':'application/json','Authorization':'Bearer '+transport_token})
        try:
            with urllib.request.urlopen(request,timeout=10) as response:
                status=response.status;result=json.load(response)
        except urllib.error.HTTPError as exc:status=exc.code;result=json.load(exc)
        transcript.append({'method':method,'http':status,
                           'error':result.get('error',{}).get('code')})
        if expected:
            require(result.get('ok') is False and result['error']['code']==expected,'ACCEPTANCE_EXPECTATION')
            return result
        require(status==200 and result.get('ok') is True,'ACCEPTANCE_CALL_FAILED')
        return result['result']
    def sign(domain,claim):
        return {'claim':claim,'signature':b64(run.actors[P]['H'].key.sign(canonical([domain,claim])))}
    def identity(op):return sign('COMP-APP-AUTHZ-IDENTITY-v1',call('identity_challenge',{'op':op}))
    def recover(key):
        claim=call('recover_challenge',{'key':key})
        return call('recover',{'key':key,'proof':sign('ZJJ-APP-RECOVER-v1',claim)})
    def proposal_auth(proposal):
        now=int(time.time())
        return sign(AUTH_DOMAIN,{'profile':P,'task_id':cfg['task_id'],'proposal':proposal,
                                 'iat':str(now),'exp':str(now+60)})
    try:
        info=start();first_ready=dict(info);first_pid=hosts[-1].pid
        passed('actual_loopback_service_started',first_ready)
        duplicate=subprocess.run([sys.executable,'-m','competition.application.local_runtime',
            '--config',str(config)],capture_output=True,text=True,timeout=12,env=env)
        require(duplicate.returncode==1 and json.loads(duplicate.stdout)['error']=='SERVICE_ALREADY_RUNNING',
                'ACCEPTANCE_EXPECTATION')
        passed('second_host_refused')
        call('status_challenge',{'operation_id':b64(bytes(16))},
             transport_token='invalid-transport-token',expected='TRANSPORT_AUTH_REQUIRED')
        call('complete_receipt',{},expected='METHOD_NOT_ALLOWED')
        passed('transport_authentication_and_private_method_refused')
        proposal={'request_id':'industrial-deployment-acceptance','unit_id':'unit-a','route':'INSPECT'}
        row=call('propose',{'proposal':proposal,'auth':proposal_auth(proposal)})
        again=call('propose',{'proposal':proposal,'auth':proposal_auth(proposal)})
        require(row==again,'ACCEPTANCE_EXPECTATION')
        changed={**proposal,'route':'QUARANTINE'}
        call('propose',{'proposal':changed,'auth':proposal_auth(changed)},expected='REQUEST_CONFLICT')
        passed('same_request_persistent_mapping_and_changed_content_refused')
        original=approve_in_lab(run,row)
        call('submit',{'key':row['key'],'op':original,'identity':{},
             'expected_version':'0','expected_ref':''},expected='IDENTITY_REQUIRED')
        with run.store.db() as c:
            saved=c.execute('SELECT full_op FROM app_request WHERE request_key=?',(row['key'],)).fetchone()
            require(saved['full_op'] is None,'ACCEPTANCE_EXPECTATION')
        passed('transport_access_does_not_replace_H_proof')
        first=call('submit',{'key':row['key'],'op':original,'identity':identity(original),
                   'expected_version':'0','expected_ref':''})
        old=call('prepare',{'key':row['key'],'identity':identity(original)})
        renewed=refresh_short(run,original)
        second=call('submit',{'key':row['key'],'op':renewed,'identity':identity(renewed),
                    'expected_version':'1','expected_ref':first['request_ref']})
        require(first['version']==1 and second['version']==2 and
                all(original[k]==renewed[k] for k in original if k not in SHORT),'ACCEPTANCE_EXPECTATION')
        challenge=call('accept_challenge',{'ticket_id':old['ticket_id']})
        call('accept',{'ticket_id':old['ticket_id'],'proof':sign('COMP-APP-ACCEPT-v1',challenge)},
             expected='SUBMISSION_SUPERSEDED')
        passed('same_authority_short_proof_update_and_old_ticket_refusal')
        stop(hosts[-1])
        info=start()
        saved=recover(row['key'])
        require(saved['state']=='NOT_ACCEPTED' and saved['submission']['version']==2 and
                saved['submission']['op']==renewed,'ACCEPTANCE_EXPECTATION')
        passed('pending_submission_survives_actual_host_restart',{'previous_pid':first_pid,'pid':info['pid']})
        ticket=call('prepare',{'key':row['key'],'identity':identity(renewed)})
        claim=call('accept_challenge',{'ticket_id':ticket['ticket_id']})
        # Send the full authenticated request but deliberately discard its response.
        payload=json.dumps({'method':'accept','params':{'ticket_id':ticket['ticket_id'],
                              'proof':sign('COMP-APP-ACCEPT-v1',claim)}}).encode()
        conn=http.client.HTTPConnection('127.0.0.1',int(info['url'].rsplit(':',1)[1]),timeout=5)
        conn.request('POST','/v1/operation',payload,
                     {'Content-Type':'application/json','Authorization':'Bearer '+token})
        conn.close()
        oid=row['action']['operation_id'];deadline=time.monotonic()+8
        while True:
            with run.store.db() as c:
                accepted=c.execute('SELECT receipt FROM w_operation WHERE profile=? AND oid=?',(P,oid)).fetchone()
            if accepted and accepted['receipt']:break
            require(time.monotonic()<deadline,'ACCEPTANCE_COMMIT_TIMEOUT')
            time.sleep(.02)
        prior=public_snapshot(run,P,oid)
        stop(hosts[-1]);info=start()
        restored=recover(row['key'])
        require(restored['state']=='COMMITTED' and restored['submission']['op']==renewed,
                'ACCEPTANCE_EXPECTATION')
        after=public_snapshot(run,P,oid)
        require(prior['commit']==after['commit'] and prior['acceptance_core']==after['acceptance_core'],
                'ACCEPTANCE_EXPECTATION')
        passed('lost_accept_response_and_restart_recover_original_commit')
        dispatch=run.w.claim(P,oid,run.worker_proof(P,oid,'CLAIM'))
        response=run.w.execute_once(P,oid,run.worker_proof(P,oid,'EXECUTE'))
        run.w.execute_once(P,oid,run.worker_proof(P,oid,'EXECUTE'))
        query=run.w.query_attempt(P,oid,run.worker_proof(P,oid,'QUERY'))
        run.w.settle(P,oid,query,run.worker_proof(P,oid,'SETTLE'))
        run.w.settle(P,oid,query,run.worker_proof(P,oid,'SETTLE'))
        final=public_snapshot(run,P,oid);counts=final['counts']
        require((counts['accepts'],counts['attempts'],counts['exec_invocations'],
                 final['effect_count'],counts['settlements'])==(1,1,1,1,1),'ACCEPTANCE_EXPECTATION')
        require(final['tool']['effects']['industrial_routes'][0]['payload']==row['action']['payload'],
                'ACCEPTANCE_EXPECTATION')
        passed('internal_authenticated_worker_one_attempt_effect_and_settlement')
        stop(hosts[-1]);info=start();last=recover(row['key'])
        require(last['operation']['attempt_id']==dispatch['attempt_id'] and
                last['operation']['exec_consumed'] is True,'ACCEPTANCE_EXPECTATION')
        passed('settled_operation_survives_actual_host_restart')
        # Standard MCP stdio adapter against the very same deployed HTTP host.
        bridge=subprocess.Popen([sys.executable,'-m','competition.application.mcp_stdio',
            '--url',info['url'],'--token-file',str(config.parent/'transport-token')],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
        try:
            seq=0
            def rpc(method,params=None,notification=False):
                nonlocal seq
                seq+=1;msg={'jsonrpc':'2.0','method':method}
                if not notification:msg['id']=seq
                if params is not None:msg['params']=params
                bridge.stdin.write(json.dumps(msg)+'\n');bridge.stdin.flush()
                if notification:return
                require(bool(select.select([bridge.stdout],[],[],8)[0]),'MCP_TIMEOUT')
                result=json.loads(bridge.stdout.readline());require('error' not in result,'MCP_ERROR')
                return result['result']
            rpc('initialize',{'protocolVersion':'2025-06-18','capabilities':{},
                             'clientInfo':{'name':'local-deployment-acceptance','version':'1'}})
            rpc('notifications/initialized',notification=True)
            names=[x['name'] for x in rpc('tools/list')['tools']]
            require(len(names)==10 and 'complete_receipt' not in names,'ACCEPTANCE_EXPECTATION')
            challenge=rpc('tools/call',{'name':'recover_challenge','arguments':{'key':row['key']}})
            result=rpc('tools/call',{'name':'recover','arguments':{'key':row['key'],
                'proof':sign('ZJJ-APP-RECOVER-v1',challenge['structuredContent'])}})
            require(result['isError'] is False and result['structuredContent']['state']=='COMMITTED',
                    'ACCEPTANCE_EXPECTATION')
            passed('real_MCP_stdio_bridge_authenticated_recovery',names)
        finally:
            bridge.terminate();bridge.communicate(timeout=8)
        private_files=list(Path(cfg['runtime_dir']).glob('*.key'))+[config.parent/'transport-token']
        require(all(p.stat().st_mode&0o777==0o600 for p in private_files),'ACCEPTANCE_EXPECTATION')
        passed('retained_private_material_permissions_0600')
        evidence={'scope':'Owned local industrial simulator, real HTTP and MCP processes; no physical device',
            'config_public':cfg,'checks':checks,'http_transcript':transcript,
            'processes':[p.pid for p in hosts],'operation_id':oid,
            'versions':[first['version'],second['version']],'original_op':original,'renewed_op':renewed,
            'before_restart':prior,'after_restart':after,'final':final,'recovered':last,
            'execute_response':response,'query':query,
            'actual_counts':dict(zip(('accepts','attempts','exec_consumptions','effects','settlements'),
                (counts['accepts'],counts['attempts'],counts['exec_invocations'],
                 final['effect_count'],counts['settlements'])))}
        (output/'public-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
        require(source()==before_source,'ACCEPTANCE_SOURCE_CHANGED')
        (output/'source-after.json').write_text(json.dumps(source(),indent=2))
        summary={'successful':True,'checks':len(checks),'actual_counts':evidence['actual_counts'],
                 'sources_unchanged':True,'service_stopped_after_acceptance':True}
        (output/'results.json').write_text(json.dumps(summary,indent=2))
        return summary
    except BaseException as exc:
        # Protocol errors or clock failures remain failed; never retry as success.
        (output/'failure.json').write_text(json.dumps({'error':getattr(exc,'code',type(exc).__name__),
            'message':str(exc),'checks_completed':checks,'http_transcript':transcript},ensure_ascii=False,indent=2))
        raise
    finally:
        for proc in reversed(hosts):
            if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
        for log in logs:log.close()
        run.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--evidence',required=True)
    args=parser.parse_args()
    print(json.dumps(accept(args.config,args.evidence)),flush=True)

if __name__=='__main__':main()
