"""Real loopback HTTP, actual MCP stdio child, disconnect and persistent restart."""
import http.client
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from competition.tests.renewal_fixtures import RenewalCase, refresh_short, P
from competition.support.wire import b64, canonical
from competition.w_cases import save_recovery_fixture, public_snapshot

class OperationTransportTests(RenewalCase):
    def start(self,crash='none'):
        if not hasattr(self,'meta'):
            self.meta=save_recovery_fixture(self.run)
            self.token='test-transport-token-with-at-least-32-bytes'
            self.token_file=Path(self.tmp.name)/'transport-token'
            self.token_file.write_text(self.token);self.token_file.chmod(0o600)
            self.starts=0
        self.starts+=1
        ready=Path(self.tmp.name)/('ready-'+str(self.starts)+'.json')
        proc=subprocess.Popen([sys.executable,'-m','competition.tests.transport_fixture',self.meta,
            str(self.token_file),str(ready),crash],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        def cleanup():
            if proc.poll() is None:proc.terminate()
            proc.communicate(timeout=10)
        self.addCleanup(cleanup)
        limit=time.monotonic()+15
        while not ready.exists() and time.monotonic()<limit:
            if proc.poll() is not None:
                out,err=proc.communicate();self.fail('server failed: '+err)
            time.sleep(.02)
        self.assertTrue(ready.exists(),'server did not become ready')
        self.port=json.loads(ready.read_text())['port']
        return proc

    def post(self,method,params,*,token=None,extra_headers=None,raw=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=8)
        headers={'Authorization':'Bearer '+(self.token if token is None else token),
                 'Content-Type':'application/json'}
        headers.update(extra_headers or {})
        body=raw if raw is not None else json.dumps({'method':method,'params':params})
        try:
            conn.request('POST','/v1/operation',body,headers)
            response=conn.getresponse();return response.status,json.loads(response.read())
        finally:conn.close()

    def call(self,method,params):
        status,body=self.post(method,params)
        self.assertEqual(status,200,body);self.assertTrue(body['ok'],body)
        return body['result']

    def recover_http(self):
        cl=self.call('recover_challenge',{'key':self.row['key']})
        proof={'claim':cl,'signature':b64(self.run.actors[P]['H'].key.sign(canonical(['ZJJ-APP-RECOVER-v1',cl])))}
        return self.call('recover',{'key':self.row['key'],'proof':proof})

    def submit_http(self,op=None,version='0',ref=''):
        op=op or self.op
        return self.call('submit',{'key':self.row['key'],'op':op,
            'identity':self.run.identity_proof(P,op),'expected_version':version,'expected_ref':ref})

    def ticket_http(self,op):
        return self.call('prepare',{'key':self.row['key'],'identity':self.run.identity_proof(P,op)})

    def accept_http(self,ticket):
        cl=self.call('accept_challenge',{'ticket_id':ticket['ticket_id']})
        proof={'claim':cl,'signature':b64(self.run.actors[P]['H'].key.sign(canonical(['COMP-APP-ACCEPT-v1',cl])))}
        return self.call('accept',{'ticket_id':ticket['ticket_id'],'proof':proof})

    def test_http_auth_origin_and_duplicate_json_fail_before_operation_access(self):
        self.start()
        status,body=self.post('recover',{},token='wrong')
        self.assertEqual(status,403);self.assertNotIn('result',body)
        status,body=self.post('recover',{},token='é')
        self.assertEqual(status,403);self.assertNotIn('result',body)
        status,_=self.post('recover',{},extra_headers={'Origin':'https://evil.example'})
        self.assertEqual(status,403)
        status,_=self.post('',{},raw='{"method":"propose","method":"recover","params":{}}')
        self.assertEqual(status,400)
        status,body=self.post('complete_receipt',{})
        self.assertEqual(status,400);self.assertEqual(body['error']['code'],'METHOD_NOT_ALLOWED')
        self.assertEqual(self.run.w.counts()['accepts'],0)

    def test_http_short_renewal_acceptance_and_one_effect(self):
        self.start();first=self.submit_http();old=self.ticket_http(self.op)
        fresh=refresh_short(self.run,self.op)
        second=self.submit_http(fresh,str(first['version']),first['request_ref'])
        cl=self.call('accept_challenge',{'ticket_id':old['ticket_id']})
        proof={'claim':cl,'signature':b64(self.run.actors[P]['H'].key.sign(canonical(['COMP-APP-ACCEPT-v1',cl])))}
        status,body=self.post('accept',{'ticket_id':old['ticket_id'],'proof':proof})
        self.assertEqual(status,409);self.assertEqual(body['error']['code'],'SUBMISSION_SUPERSEDED')
        accepted=self.accept_http(self.ticket_http(fresh))
        self.assertEqual(accepted['acceptance_state'],'COMMITTED')
        self.assertEqual(self.recover_http()['submission'],second)
        oid=self.op['action']['operation_id']
        self.run.w.claim(P,oid,self.run.worker_proof(P,oid,'CLAIM'))
        response=self.run.w.execute_once(P,oid,self.run.worker_proof(P,oid,'EXECUTE'))
        self.run.w.settle(P,oid,response,self.run.worker_proof(P,oid,'SETTLE'))
        snap=public_snapshot(self.run,P,oid)
        self.assertEqual((snap['counts']['accepts'],snap['counts']['attempts'],snap['counts']['exec_invocations'],snap['effect_count'],snap['counts']['settlements']),(1,1,1,1,1))

    def test_http_disconnect_after_commit_and_server_restart_recovers_original_core(self):
        proc=self.start('accept');self.submit_http();ticket=self.ticket_http(self.op)
        with self.assertRaises((http.client.RemoteDisconnected,ConnectionError)):
            self.accept_http(ticket)
        proc.wait(timeout=10);self.assertEqual(proc.returncode,97)
        oid=self.op['action']['operation_id'];before=public_snapshot(self.run,P,oid)
        self.assertIsNone(before['operation']['receipt'])
        self.start();view=self.recover_http()
        self.assertEqual(view['state'],'COMMITTED')
        self.assertEqual(view['operation']['receipt_state'],'PENDING')
        result=self.accept_http(self.ticket_http(self.op))
        self.assertEqual({k:result['acceptance'][k] for k in ('protected','body')},before['acceptance_core'])
        self.assertEqual(self.run.w.counts()['accepts'],1)
        self.assertEqual(self.run.w.counts()['attempts'],0)

    def test_mcp_stdio_lists_only_allowlist_and_requires_holder_proof(self):
        self.start()
        proc=subprocess.Popen([sys.executable,'-m','competition.application.mcp_stdio',
            '--url','http://127.0.0.1:'+str(self.port), '--token-file',str(self.token_file)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        def stop():
            if proc.poll() is None:proc.terminate()
            proc.communicate(timeout=10)
        self.addCleanup(stop)
        def rpc(message,respond=True):
            proc.stdin.write(json.dumps(message)+'\n');proc.stdin.flush()
            if respond:return json.loads(proc.stdout.readline())
        initialized=rpc({'jsonrpc':'2.0','id':1,'method':'initialize','params':{
            'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'test','version':'1'}}})
        self.assertEqual(initialized['result']['protocolVersion'],'2025-06-18')
        rpc({'jsonrpc':'2.0','method':'notifications/initialized'},False)
        listed=rpc({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
        names={x['name'] for x in listed['result']['tools']}
        self.assertIn('propose',names);self.assertIn('recover',names)
        self.assertFalse({'sign','execute_once','complete_receipt','load'}&names)
        denied=rpc({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{
            'name':'recover','arguments':{'key':self.row['key'],'proof':None}}})
        self.assertTrue(denied['result']['isError'])
        proposed=rpc({'jsonrpc':'2.0','id':4,'method':'tools/call','params':{
            'name':'propose','arguments':{'proposal':self.proposal,'auth':self.auth(self.proposal)}}})
        self.assertFalse(proposed['result']['isError'])
        self.assertEqual(proposed['result']['structuredContent']['key'],self.row['key'])
        def call(i,name,args):
            response=rpc({'jsonrpc':'2.0','id':i,'method':'tools/call',
                'params':{'name':name,'arguments':args}})
            self.assertFalse(response['result']['isError'],response)
            return response['result']['structuredContent']
        saved=call(5,'submit',{'key':self.row['key'],'op':self.op,
            'identity':self.run.identity_proof(P,self.op),'expected_version':'0','expected_ref':''})
        ticket=call(6,'prepare',{'key':self.row['key'],'identity':self.run.identity_proof(P,self.op)})
        cl=call(7,'accept_challenge',{'ticket_id':ticket['ticket_id']})
        proof={'claim':cl,'signature':b64(self.run.actors[P]['H'].key.sign(canonical(['COMP-APP-ACCEPT-v1',cl])))}
        accepted=call(8,'accept',{'ticket_id':ticket['ticket_id'],'proof':proof})
        self.assertEqual(accepted['acceptance_state'],'COMMITTED')
        self.assertEqual(self.run.w.counts()['attempts'],0)
