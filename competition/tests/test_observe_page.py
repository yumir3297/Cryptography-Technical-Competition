"""The observation page is static markup; the numbers behind it stay gated.

Four things are checked here and nothing else: the page and its assets are
served, the flow model still matches the committed diagram, the page ships no
pre-rendered picture, and every data route it reads still refuses a caller
without an ``auditor`` session.  The page must not become a side door around
the session.
"""
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from competition.support.wire import ProtocolError
from competition.web.app import make_app

WEB = Path(__file__).resolve().parents[1] / 'web'
STATIC = WEB / 'static' / 'observe'
FLOW = STATIC / 'flow.json'
SOURCE = WEB.parents[1] / 'ppt材料' / '协议架构图-开发级-20261124.mmd'
KINDS = {'control', 'evidence', 'feedback', 'reject'}
SCOPES = {'static', 'operation', 'profile', 'table'}


class _Store:
    def __init__(self, path):
        self.path = path


class _Run:
    def __init__(self, path):
        self.store = _Store(path)
        self.operations = {}
        self.actors = {}


class _Service:
    """Just enough service for the app to be built; no route is exercised."""

    def __init__(self, path):
        self.run = _Run(path)
        self._entries = {}


class _Sessions:
    def authorize(self, token, side=None):
        raise ProtocolError('SESSION_REQUIRED')


class ObservePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db = Path(cls.temp.name) / 'w.sqlite'
        cls.db.write_bytes(b'')
        cls.client = TestClient(make_app(_Service(cls.db), _Sessions()))
        cls.flow = json.loads(FLOW.read_text(encoding='utf-8'))
        cls.page = cls.client.get('/observe').text

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_the_page_is_served_without_a_session(self):
        response = self.client.get('/observe')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response.headers['content-type'])
        for block in ('trust', 'gate', 's45', 's6', 'tool', 's7', 'db', 'view'):
            self.assertIn('data-block="%s"' % block, self.page)

    def test_the_page_holds_no_credential_of_its_own(self):
        self.assertNotIn('Bearer ', self.page)
        self.assertNotIn('authorization:', self.page.lower())

    def test_assets_are_served(self):
        for path, kind in (
            ('/observe/assets/observe.css', 'text/css'),
            ('/observe/assets/observe.js', 'javascript'),
            ('/observe/assets/flow.json', 'json'),
            ('/observe/assets/prts/prts-design.css', 'text/css'),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(kind, response.headers['content-type'], path)

    def test_the_page_ships_no_pre_rendered_picture(self):
        self.assertNotIn('<img', self.page)
        self.assertNotIn('diagrams/', self.page)
        self.assertNotIn('.svg', self.page)
        for asset in STATIC.rglob('*'):
            if asset.is_file():
                self.assertNotIn(asset.suffix, ('.svg', '.png'), str(asset))

    def test_the_flow_model_matches_the_committed_diagram(self):
        self.assertEqual(self.flow['source'], SOURCE.name)
        self.assertEqual(set(self.flow['kinds']), KINDS)
        blocks = self.flow['blocks']
        self.assertEqual(len(blocks), 8)

        seen = []
        for block in blocks:
            self.assertTrue(set(block) >= {'id', 'label', 'nodes', 'edges'})
            names = [node['id'] for node in block['nodes']]
            seen.extend(node['id'] for node in block['nodes'] if not node['stub'])
            for node in block['nodes']:
                self.assertIn(node['rank'], range(0, 32), block['id'])
                self.assertIn(node['order'], range(0, 32), block['id'])
            for edge in block['edges']:
                self.assertIn(edge['kind'], KINDS)
                self.assertIn(edge['src'], names)
                self.assertIn(edge['dst'], names)
        self.assertEqual(len(seen), len(set(seen)), 'a node is in two blocks')

        map_nodes = [node['id'] for node in self.flow['map']['nodes']]
        self.assertEqual(map_nodes, [block['id'] for block in blocks])
        for edge in self.flow['map']['edges']:
            self.assertIn(edge['kind'], KINDS)
            self.assertIn(edge['src'], map_nodes)
            self.assertIn(edge['dst'], map_nodes)
            self.assertGreaterEqual(edge['count'], 1)

    def test_every_live_value_names_a_known_endpoint(self):
        endpoints = self.flow['endpoints']
        self.assertEqual(len(endpoints), 27)
        for name, scope in endpoints.items():
            self.assertIn(scope, SCOPES, name)
        for block in self.flow['blocks']:
            for node in block['nodes']:
                if node['stub']:
                    self.assertEqual(node['live'], [])
                    self.assertEqual(node['cards'], [])
                for item in node['live']:
                    self.assertIn(item['diag'], endpoints, node['id'])
                for card in node['cards']:
                    self.assertIn(card['diag'], endpoints, node['id'])
                    self.assertEqual(card['scope'], endpoints[card['diag']], node['id'])

    def test_the_data_routes_still_need_an_auditor(self):
        for path in ('/api/diag/entry', '/api/diag/store', '/api/diag/endpoints',
                     '/api/diag/construct/x', '/api/diag/obligations/PAY-1'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)
            self.assertEqual(response.json()['deny'], 'SESSION_REQUIRED', path)


if __name__ == '__main__':
    unittest.main()
