"""Malformed client input must return bounded errors rather than crash the bridge."""
import unittest
import io
import json
from competition.application.mcp_stdio import MCPStdio, LocalClient
from competition.application.http_service import parse_json
from competition.support.wire import ProtocolError

class ServiceFramingTests(unittest.TestCase):
    def test_mcp_nonstr_tool_name_is_invalid_params_and_session_survives(self):
        bridge=MCPStdio(None);bridge.initialized=True;bridge.ready=True
        for name in ([],{},None,True):
            with self.subTest(name=name):
                result=bridge.handle({'jsonrpc':'2.0','id':1,'method':'tools/call',
                    'params':{'name':name,'arguments':{}}})
                self.assertEqual(result['error']['code'],-32602)
        result=bridge.handle({'jsonrpc':'2.0','id':2,'method':'tools/list'})
        self.assertIn('tools',result['result'])

    def test_bridge_refuses_remote_urls_and_json_duplicate_keys(self):
        for url in ('https://127.0.0.1:1','http://example.com:80','http://user@127.0.0.1:1',
                    'http://127.0.0.1:1/?url=http://evil.example'):
            with self.subTest(url=url),self.assertRaises(ProtocolError):LocalClient(url,'T'*32)
        with self.assertRaises(ProtocolError) as caught:parse_json(b'{"op":{"id":"a","id":"b"}}')
        self.assertEqual(caught.exception.code,'DUPLICATE_KEY')

    def test_oversized_integer_returns_parse_error_then_next_mcp_request_survives(self):
        invalid=b'{"jsonrpc":"2.0","id":'+b'9'*5000+b',"method":"ping"}\n'
        valid=b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
        sink=io.StringIO();MCPStdio(None).run(io.BytesIO(invalid+valid),sink)
        replies=[json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual(replies[0]['error']['code'],-32700)
        self.assertEqual(replies[1],{'jsonrpc':'2.0','id':2,'result':{}})
