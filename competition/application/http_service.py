"""Loopback, short-connection JSON API. This is REST, not MCP Streamable HTTP."""
import hmac
import json
import socket
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from competition.application.operation_service import OperationService
from competition.support.wire import ProtocolError, require

MAX_BODY=1048576

def parse_json(data):
    def pairs(values):
        result={}
        for key,value in values:
            require(key not in result,'DUPLICATE_KEY');result[key]=value
        return result
    def constant(value):raise ProtocolError('MALFORMED')
    try:return json.loads(data.decode('utf-8','strict'),object_pairs_hook=pairs,parse_constant=constant)
    except ProtocolError:raise
    except (UnicodeError,ValueError,RecursionError) as exc:
        raise ProtocolError('MALFORMED') from exc

def error_result(code):
    recovery='READ_W_STATE'
    if code in ('SUBMISSION_SUPERSEDED','SUBMISSION_VERSION_CONFLICT','SUBMISSION_REPLAY'):
        recovery='RECOVER_CURRENT_PACKET'
    elif code in ('EXPIRED','STALE','DEP_CONFLICT','REVOKED','NO_ROLE','REVIEW_DENY','DENY_COVERAGE_UNKNOWN'):
        recovery='STOP_AND_REASSESS_AUTHORITY'
    elif code in ('REPLAY','IDENTITY_REQUIRED','BAD_SIGNATURE','AUTH_BINDING','BINDING'):
        recovery='OBTAIN_FRESH_AUTHENTICATION'
    elif code=='CLOCK_UNKNOWN':recovery='WAIT_FOR_TRUSTED_CLOCK_THEN_READ_STATE'
    return {'ok':False,'error':{'code':code,'recovery':recovery}}

def create_server(service,token,*,host='127.0.0.1',port=0):
    require(isinstance(service,OperationService),'SERVICE_REQUIRED')
    require(host=='127.0.0.1' and type(port) is int and 0<=port<=65535,'LOCAL_BINDING_REQUIRED')
    require(type(token) is str and 32<=len(token)<=256 and token.isascii() and
            not any(ch.isspace() for ch in token),'TRANSPORT_TOKEN_REQUIRED')

    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def setup(self):
            super().setup();self.connection.settimeout(5)
        def log_message(self,*args):pass
        def reply(self,status,body):
            data=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode('utf-8')
            self.close_connection=True
            try:
                self.send_response(status)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(data)))
                self.send_header('Connection','close');self.end_headers();self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError,socket.timeout):
                pass  # Durable decisions remain committed when the client disconnects.
        def do_GET(self):self.reply(405,error_result('METHOD_NOT_ALLOWED'))
        do_PUT=do_GET
        do_DELETE=do_GET
        def do_POST(self):
            authorization=self.headers.get('Authorization','')
            if not authorization.isascii() or not hmac.compare_digest(authorization,'Bearer '+token):
                return self.reply(403,error_result('TRANSPORT_AUTH_REQUIRED'))
            allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            if self.headers.get('Origin') is not None or self.headers.get('Host') not in allowed:
                return self.reply(403,error_result('LOCAL_ORIGIN_REQUIRED'))
            if self.path!='/v1/operation':return self.reply(404,error_result('ROUTE_UNKNOWN'))
            try:
                require(self.headers.get('Content-Type','').split(';')[0].strip()=='application/json','CONTENT_TYPE')
                require(self.headers.get('Transfer-Encoding') is None and
                        len(self.headers.get_all('Content-Length',[]))==1,'CONTENT_LENGTH')
                size=self.headers['Content-Length'];require(len(size)<=7 and size.isascii() and size.isdigit(),'CONTENT_LENGTH')
                size=int(size);require(0<size<=MAX_BODY,'LIMIT')
                data=self.rfile.read(size);require(len(data)==size,'MALFORMED')
                request=parse_json(data)
                require(type(request) is dict and set(request)=={'method','params'},'SERVICE_FIELDS')
                result=service.invoke(request['method'],request['params'])
                return self.reply(200,{'ok':True,'result':result})
            except ProtocolError as exc:
                if exc.code in ('SUBMISSION_SUPERSEDED','SUBMISSION_VERSION_CONFLICT','SUBMISSION_REPLAY','ALREADY_ACCEPTED','REQUEST_CONFLICT'):
                    status=409
                elif exc.code in ('CLOCK_UNKNOWN','SIGNER_UNAVAILABLE'):status=503
                elif exc.code in ('MALFORMED','DUPLICATE_KEY','LIMIT','SERVICE_FIELDS','METHOD_NOT_ALLOWED','CONTENT_TYPE','CONTENT_LENGTH'):
                    status=400
                else:status=422
                return self.reply(status,error_result(exc.code))
            except (socket.timeout,TimeoutError):return self.reply(503,error_result('SERVICE_TIMEOUT'))
            except sqlite3.OperationalError:return self.reply(503,error_result('STATE_UNAVAILABLE'))

    server=ThreadingHTTPServer((host,port),Handler)
    server.daemon_threads=True
    return server
