"""MCP 2025-06-18 stdio bridge to the local proof-authenticated REST service.

The host supplies URL/token path on startup. Tool arguments cannot choose them.
This process holds a transport token, never an H/U/V/G/X signing credential.
"""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError
from competition.application.operation_service import METHOD_FIELDS
from competition.application.http_service import MAX_BODY, parse_json, error_result
from competition.support.wire import ProtocolError, require

def tools():
    descriptions={
        'propose':'Resolve authenticated IND candidate to unsigned approval material.',
        'identity_challenge':'Request a full-packet H authentication challenge; grants no authority.',
        'submit':'Save fully signed packet; renew only three short proofs using expected version/ref.',
        'prepare':'Prepare the current saved packet with fresh H authentication.',
        'accept_challenge':'Request a ticket-bound H acceptance challenge.',
        'accept':'Accept current packet with the actual H signature; never dispatch the tool.',
        'recover_challenge':'Request a one-use H recovery challenge without returning saved data.',
        'recover':'Read saved request and W state with current H authority; never repeat EXEC.',
        'status_challenge':'Request the original W status authentication challenge.',
        'status':'Read original W projection with H status proof.',
    }
    objects={'op','proposal','auth','identity','proof'}
    return [{'name':name,'description':descriptions[name],'inputSchema':{
        'type':'object','properties':{field:{'type':'object' if field in objects else 'string'} for field in fields},
        'required':list(fields),'additionalProperties':False}} for name,fields in METHOD_FIELDS.items()]

class LocalClient:
    def __init__(self,url,token):
        parts=urlsplit(url)
        require(parts.scheme=='http' and parts.hostname in ('127.0.0.1','localhost') and
            parts.port is not None and not parts.username and not parts.password and
            parts.path in ('','/') and not parts.query and not parts.fragment,'LOCAL_BINDING_REQUIRED')
        self.url=url.rstrip('/')+'/v1/operation';self.token=token
        self.opener=build_opener(ProxyHandler({}))
    def invoke(self,method,params):
        data=json.dumps({'method':method,'params':params},ensure_ascii=False).encode('utf-8')
        require(len(data)<=MAX_BODY,'LIMIT')
        request=Request(self.url,data,headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        try:
            with self.opener.open(request,timeout=8) as response:return parse_json(response.read(MAX_BODY+1))
        except HTTPError as exc:
            with exc:return parse_json(exc.read(MAX_BODY+1))
        except (URLError,TimeoutError,OSError):return error_result('TRANSPORT_UNKNOWN')

class MCPStdio:
    def __init__(self,client):self.client=client;self.initialized=False;self.ready=False
    @staticmethod
    def error(i,code,message):return {'jsonrpc':'2.0','id':i,'error':{'code':code,'message':message}}
    def handle(self,request):
        if type(request) is not dict or request.get('jsonrpc')!='2.0' or type(request.get('method')) is not str:
            return self.error(None,-32600,'Invalid Request')
        notification='id' not in request;i=request.get('id');method=request['method'];params=request.get('params',{})
        if not notification and type(i) not in (str,int):return self.error(None,-32600,'Invalid Request')
        if notification:
            if method=='notifications/initialized' and self.initialized:self.ready=True
            return None
        if type(params) is not dict:return self.error(i,-32602,'Invalid params')
        if method=='initialize':
            if self.initialized:return self.error(i,-32600,'Already initialized')
            if not {'protocolVersion','capabilities','clientInfo'}<=set(params):
                return self.error(i,-32602,'Invalid params')
            self.initialized=True
            result={'protocolVersion':'2025-06-18','capabilities':{'tools':{'listChanged':False}},
                    'serverInfo':{'name':'zjj-core-ind','version':'1.1'}}
        elif method=='ping':result={}
        elif not self.ready:return self.error(i,-32002,'Not initialized')
        elif method=='tools/list':result={'tools':tools()}
        elif method=='tools/call':
            if type(params.get('name')) is not str or params['name'] not in METHOD_FIELDS or type(params.get('arguments')) is not dict:
                return self.error(i,-32602,'Invalid tool or arguments')
            try:body=self.client.invoke(params['name'],params['arguments'])
            except ProtocolError as exc:body=error_result(exc.code)
            value=body['result'] if body.get('ok') else body['error']
            result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],
                    'structuredContent':value,'isError':not body.get('ok',False)}
        else:return self.error(i,-32601,'Method not found')
        return {'jsonrpc':'2.0','id':i,'result':result}

    def run(self,source,sink):
        while True:
            line=source.readline(MAX_BODY+1)
            if not line:return
            if len(line)>MAX_BODY:
                sink.write(json.dumps(self.error(None,-32700,'Message too large'))+'\n');sink.flush();return
            try:result=self.handle(parse_json(line))
            except ProtocolError:result=self.error(None,-32700,'Parse error')
            if result is not None:sink.write(json.dumps(result,ensure_ascii=False)+'\n');sink.flush()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--token-file',required=True)
    args=parser.parse_args()
    token_path=Path(args.token_file)
    require(token_path.stat().st_mode & 0o077 == 0,'TRANSPORT_TOKEN_PERMISSIONS')
    token=token_path.read_text(encoding='ascii').strip()
    MCPStdio(LocalClient(args.url,token)).run(sys.stdin.buffer,sys.stdout)

if __name__=='__main__':main()
