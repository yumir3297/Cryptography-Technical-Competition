"""TEST-ONLY public evidence demo: real MCP/HTTP, real lab signatures, lost tool ACK.

All participant keys exist only in a temporary synthetic bootstrap. This is not
an approval service and must never be registered as an Agent tool.
"""
import copy
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from competition.profiles.w_seed import initialize
from competition.application.trusted_action_resolver import TrustedActionResolver, AUTH_DOMAIN
from competition.application.request_bound_w import RequestBoundW
from competition.application.operation_orchestrator import OperationOrchestrator
from competition.application.operation_service import OperationService
from competition.application.http_service import create_server
from competition.tests.resolver_fixtures import P, approve_in_lab
from competition.tests.renewal_fixtures import refresh_short, SHORT
from competition.support.wire import canonical, b64, msgref, action_hash
from competition.w_cases import public_snapshot, _configure_tool

def main(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    import time
    with tempfile.TemporaryDirectory(prefix='zjj-unified-public-demo-') as runtime:
        run=initialize(Path(runtime))
        server=thread=client=None
        try:
            resolver=TrustedActionResolver(run.store,run.operations[P]['task_id'])
            run.w=RequestBoundW(run.w,resolver.requests)
            flow=OperationOrchestrator(run.w,resolver.requests)
            token=secrets.token_urlsafe(32)
            token_file=Path(runtime)/'transport-token';token_file.write_text(token);token_file.chmod(0o600)
            server=create_server(OperationService(resolver,flow),token)
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True);thread.start()
            client=subprocess.Popen([sys.executable,'-m','competition.application.mcp_stdio',
                '--url','http://127.0.0.1:'+str(server.server_address[1]),'--token-file',str(token_file)],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            exchange=[];sequence=0
            def rpc(method,params=None,notify=False):
                nonlocal sequence
                sequence+=1
                message={'jsonrpc':'2.0','method':method}
                if not notify:message['id']=sequence
                if params is not None:message['params']=params
                client.stdin.write(json.dumps(message)+'\n');client.stdin.flush()
                if notify:return
                line=client.stdout.readline()
                if not line:raise RuntimeError('MCP bridge exited')
                response=json.loads(line);assert 'error' not in response,response
                return response['result']
            initialized=rpc('initialize',{'protocolVersion':'2025-06-18','capabilities':{},
                'clientInfo':{'name':'zjj-evidence-demo','version':'1'}})
            rpc('notifications/initialized',notify=True)
            tool_list=rpc('tools/list')['tools']
            def call(name,arguments,expected_error=None):
                result=rpc('tools/call',{'name':name,'arguments':arguments})
                value=result['structuredContent']
                exchange.append({'method':name,'isError':result['isError'],
                                 'error_code':value.get('code') if result['isError'] else None})
                if expected_error:assert result['isError'] and value['code']==expected_error
                else:assert not result['isError'],value
                return value
            def sign(domain,claim):
                return {'claim':claim,'signature':b64(run.actors[P]['H'].key.sign(canonical([domain,claim])))}
            def identity(op):return sign('COMP-APP-AUTHZ-IDENTITY-v1',call('identity_challenge',{'op':op}))
            proposal={'request_id':'public-demo','unit_id':'unit-a','route':'INSPECT'}
            now=int(time.time());claim={'profile':P,'task_id':resolver.task_id,'proposal':proposal,
                'iat':str(now),'exp':str(now+60)}
            row=call('propose',{'proposal':proposal,'auth':sign(AUTH_DOMAIN,claim)})
            original=approve_in_lab(run,row)
            first=call('submit',{'key':row['key'],'op':original,'identity':identity(original),
                'expected_version':'0','expected_ref':''})
            old_ticket=call('prepare',{'key':row['key'],'identity':identity(original)})
            renewed=refresh_short(run,original)
            second=call('submit',{'key':row['key'],'op':renewed,'identity':identity(renewed),
                'expected_version':'1','expected_ref':first['request_ref']})
            old_claim=call('accept_challenge',{'ticket_id':old_ticket['ticket_id']})
            call('accept',{'ticket_id':old_ticket['ticket_id'],
                'proof':sign('COMP-APP-ACCEPT-v1',old_claim)},'SUBMISSION_SUPERSEDED')
            ticket=call('prepare',{'key':row['key'],'identity':identity(renewed)})
            claim=call('accept_challenge',{'ticket_id':ticket['ticket_id']})
            accepted=call('accept',{'ticket_id':ticket['ticket_id'],
                'proof':sign('COMP-APP-ACCEPT-v1',claim)})
            oid=row['action']['operation_id']
            before=public_snapshot(run,P,oid)
            dispatch=run.w.claim(P,oid,run.worker_proof(P,oid,'CLAIM'))
            _configure_tool(run,P,crash_after_commit=True)
            lost=run.w.execute_once(P,oid,run.worker_proof(P,oid,'EXECUTE'))
            query=run.w.query_attempt(P,oid,run.worker_proof(P,oid,'QUERY'))
            settled=run.w.settle(P,oid,query,run.worker_proof(P,oid,'SETTLE'))
            recovered=call('recover',{'key':row['key'],'proof':sign('ZJJ-APP-RECOVER-v1',
                call('recover_challenge',{'key':row['key']}))})
            after=public_snapshot(run,P,oid);counts=after['counts']
            assert (counts['accepts'],counts['attempts'],counts['exec_invocations'],
                after['effect_count'],counts['settlements'])==(1,1,1,1,1)
            assert lost['trace']['exit_code']==98 and recovered['operation']['attempt_id']==dispatch['attempt_id']
            assert before['commit']==after['commit'] and before['acceptance_core']==after['acceptance_core']
            assert all(original[k]==renewed[k] for k in original if k not in SHORT)
            evidence={'scope':'Synthetic IND lab; actual MCP stdio + loopback HTTP and local tool process, not a physical device',
                'initialized':initialized,'public_tools':[t['name'] for t in tool_list],
                'public_actors':{alias:{'name':a.name,'kid':a.kid,'public_key':b64(a.pub)} for alias,a in run.store.actors[P].items()},
                'root_public':b64(run.store.root_public),'operation_id':oid,
                'tool_certificate':run.tools[P]['certificate'],'delivery_public':b64(run.delivery_public),
                'action_hash':action_hash(P,original['action']),'original_op':original,'renewed_op':renewed,
                'same_original_permit':original['permit']==renewed['permit'],
                'permit_ref':msgref(original['permit']),'versions':[first['version'],second['version']],
                'request_refs':[first['request_ref'],second['request_ref']],'exchange':exchange,
                'accepted':accepted,'dispatch':dispatch,'lost_tool_response':lost,'query':query,
                'settlement':settled,'recovered':recovered,'before':before,'after':after,
                'actual_counts':{'accepts':counts['accepts'],'attempts':counts['attempts'],
                    'exec_consumptions':counts['exec_invocations'],'effects':after['effect_count'],
                    'settlements':counts['settlements']}}
            (output/'public-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
            print(json.dumps(evidence['actual_counts']),flush=True)
        finally:
            if client:
                if client.poll() is None:client.terminate()
                client.communicate(timeout=10)
            if server:server.shutdown();server.server_close()
            if thread:thread.join(timeout=5)
            run.close()

if __name__=='__main__':main(sys.argv[1])
