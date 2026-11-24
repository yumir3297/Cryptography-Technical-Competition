"""Build the read-only observation page: a flow model plus one static page.

The committed protocol diagram is the single source of the flow.  This module
parses it at build time into ``flow.json`` — nodes, the four relation classes,
sub-block membership and the block-level aggregate — and renders the page from
that same model.  No pre-rendered picture is produced or shipped: the browser
draws the boxes and the connector paths itself, so every stage can carry the
live highlight of ``/api/diag/*``.

Nothing here touches W, C or the entry.  The page is static markup; the numbers
on it are fetched at read time with the reader's own auditor token.

Usage::

    python -m competition.web.observe_page
"""
from __future__ import annotations

import json
import re
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / 'ppt材料' / '协议架构图-开发级-20261124.mmd'
STATIC = HERE / 'static' / 'observe'
FLOW = STATIC / 'flow.json'
INDEX = STATIC / 'index.html'

KINDS = ('control', 'evidence', 'feedback', 'reject')

KIND_LABEL = {
    'control': '控制',
    'evidence': '证据',
    'feedback': '反馈',
    'reject': '阻断',
}

# ── 分块 ───────────────────────────────────────────────────────────────────
# The mmd already draws TRUST / S45 / S6 / S7 / DB; CTX+GUARD, TOOL+TOOLDB and
# OBS+VIEW+NOTE are top-level there and are grouped here so every stage of the
# flow belongs to exactly one clickable block.  ``col``/``row`` place the block
# on the map: two rows, the second read right to left.
BLOCKS = (
    ('trust', 1, 1, '入口与信任域', 'TRUST',
     'Agent 只提供候选；C 负责登记与发布；E 只认证来源。两个入口并列，不串联。',
     ('AG', 'ENTRY_SRV', 'ENTRY_IND', 'C', 'E')),
    ('gate', 2, 1, '可信构造与关系核验', 'CONSTRUCT · VERIFY',
     'CTX 把意图固化成完整 Action 与 ActionHash；GUARD 在初检、接受与终局各重核一次。',
     ('CTX', 'GUARD')),
    ('s45', 3, 1, '准备、判定与原子接受', 'PREPARE · ACCEPT',
     'PREPARE 成功不等于接受；GoalFloor 默认 off，只在 ACCEPT 事务内判定。',
     ('PREPARE', 'CHAL', 'GF', 'ACCEPT')),
    ('s6', 4, 1, '回执与唯一执行资格', 'RECEIPT · CLAIM',
     '回执只签原冻结 Core；EXEC-0 先持久消费标记，再向工具派发。',
     ('RECEIPT', 'PENDING', 'CLAIM', 'EXEC0')),
    ('view', 1, 2, '只读投影与边界', 'READ-ONLY VIEW',
     '投影只读，不形成授权；UNKNOWN 保留占用，不保证生产效果恰好一次。',
     ('OBS', 'VIEW', 'NOTE')),
    ('s7', 2, 2, '终局、结算与恢复', 'FINAL · RECOVER',
     '只有可信终局才结算；STARTED 不可通用取消，未知只能认证查询原 attempt。',
     ('QUERY', 'FINAL', 'SETTLE', 'CANCEL', 'UNKNOWN', 'HALTED', 'DUP', 'REJ')),
    ('tool', 3, 2, '工具端与独立账本', 'TOOL',
     '工具验签后执行并签名返回；工具账本独立，不并入 W 事务。',
     ('TOOL', 'TOOLDB')),
    ('db', 4, 2, '共享 SQLite 与账本', 'SHARED LEDGER',
     'C 控制状态与 W 业务状态同库同事务；资源与义务账随终局更新。',
     ('SHARED', 'RES', 'OBL')),
)

# 块内阅读顺序：主链在前，分支随后。控制流边本身仍以 mmd 为准。
NODE_ORDER = {
    'trust': ('AG', 'ENTRY_SRV', 'ENTRY_IND', 'C', 'E'),
    'gate': ('CTX', 'GUARD'),
    's45': ('PREPARE', 'CHAL', 'GF', 'ACCEPT'),
    's6': ('RECEIPT', 'PENDING', 'CLAIM', 'EXEC0'),
    'view': ('OBS', 'VIEW', 'NOTE'),
    's7': ('QUERY', 'FINAL', 'SETTLE', 'CANCEL', 'UNKNOWN', 'HALTED', 'DUP', 'REJ'),
    'tool': ('TOOL', 'TOOLDB'),
    'db': ('SHARED', 'RES', 'OBL'),
}

# 每一步在数据流上的先后（只用于「当前停在哪」）。
STAGES = ('AG', 'ENTRY_SRV', 'ENTRY_IND', 'C', 'E', 'CTX', 'GUARD',
          'PREPARE', 'CHAL', 'GF', 'ACCEPT', 'RECEIPT', 'PENDING', 'CLAIM',
          'EXEC0', 'TOOL', 'FINAL', 'SETTLE', 'CANCEL', 'QUERY')

# 每个阶段旁要贴的实时值：(标签, 接口, data 内路径)。
LIVE = {
    'AG': (('候选', 'entry', 'data.operations'), ('入口', 'entry', 'data.entry_kinds')),
    'ENTRY_SRV': (('入口种类', 'entry', 'data.entry_kinds'),),
    'ENTRY_IND': (('入口种类', 'entry', 'data.entry_kinds'),),
    'C': (('登记记录', 'registry', 'data.records'),),
    'E': (('来源 kid', 'source', 'data.actor.kid'),),
    'CTX': (('ActionHash', 'construct', 'data.action_hash'),),
    'GUARD': (('判定', 'guard', 'data.decision'), ('已观测', 'guard', 'data.observed_stages')),
    'PREPARE': (('意图', 'plan', 'data.intent'), ('资源', 'plan', 'data.resource_key')),
    'CHAL': (('nonce', 'challenge', 'data.nonces'), ('身份', 'identity', 'data.stage')),
    'GF': (('模式', 'goal', 'data.mode'), ('判定', 'goal', 'data.decision')),
    'ACCEPT': (('state', 'accept', 'data.state'), ('receipt', 'accept', 'data.receipt_state')),
    'RECEIPT': (('state', 'receipt', 'data.state'),),
    'PENDING': (('receipt', 'accept', 'data.receipt_state'), ('禁止领取', 'accept', 'data.claim_blocked')),
    'CLAIM': (('attempt', 'claim', 'data.attempt_id'), ('state', 'claim', 'data.state')),
    'EXEC0': (('已消费', 'exec', 'data.exec_consumed'), ('effect', 'exec', 'data.effect_state')),
    'QUERY': (('查询', 'query', 'data.queries'), ('上次', 'query', 'data.last_state')),
    'FINAL': (('终局', 'final', 'data.final_outcome'), ('effect', 'final', 'data.effect_state')),
    'SETTLE': (('结果', 'settlement', 'data.outcome'), ('ledger', 'settlement', 'data.ledger')),
    'CANCEL': (('state', 'cancel', 'data.state'), ('已释放', 'cancel', 'data.released')),
    'UNKNOWN': (('effect', 'exec', 'data.effect_state'),),
    'HALTED': (('已停用', 'exec', 'data.halted'),),
    'DUP': (('重复阻断', 'exec', 'data.replay_blocked'),),
    'REJ': (('DENY', 'deny', 'data.complete'), ('refs', 'deny', 'data.refs')),
    'TOOL': (('requests', 'tool', 'data.requests'), ('effects', 'tool', 'data.effects')),
    'TOOLDB': (('库', 'store', 'data.tool.databases'), ('独立', 'store', 'data.tool.separate')),
    'SHARED': (('库', 'store', 'data.shared.database'), ('事务', 'store', 'data.transaction')),
    'RES': (('资源', 'obligations', 'data.resources'), ('预留', 'obligations', 'data.reservations')),
    'OBL': (('义务', 'obligations', 'data.goals'), ('模式', 'obligations', 'data.mode')),
    'OBS': (('事件', 'observe', 'data.events'), ('游标', 'observe', 'data.last')),
    'VIEW': (('派发', 'result', 'data.status.dispatch_state'), ('链', 'result', 'data.chain_valid')),
    'NOTE': (),
}

# 折叠明细：每个阶段背后的只读投影。字段名逐一取自 diag_*.py。
CARDS = {
    'AG': (
        ('entry', 'static', (('入口种类', 'data.entry_kinds'),
                             ('候选操作', 'data.operations'),
                             ('profiles', 'data.profiles'),
                             ('GoalFloor', 'data.goal_mode'))),
    ),
    'ENTRY_SRV': (
        ('entry', 'static', (('入口种类', 'data.entry_kinds'),
                             ('端点', 'data.endpoints'),
                             ('操作数', 'data.operations'))),
    ),
    'ENTRY_IND': (
        ('entry', 'static', (('入口种类', 'data.entry_kinds'),
                             ('操作数', 'data.operations'))),
    ),
    'C': (
        ('registry', 'static', (('记录', 'data.records'),)),
        ('endpoints', 'static', (('README', 'data.profiles'),)),
    ),
    'E': (
        ('endpoints', 'static', (('公开名册', 'data.profiles'),)),
        ('source', 'operation', (('subject', 'data.actor.subject'),
                                 ('kid', 'data.actor.kid'),
                                 ('来源依赖', 'data.source_deps'),
                                 ('来源记录', 'data.sources'),
                                 ('证据引用', 'data.evidence_refs'))),
    ),
    'CTX': (
        ('construct', 'operation', (('ActionHash', 'data.action_hash'),
                                    ('Selector', 'data.selector'),
                                    ('request_ref', 'data.request_ref'),
                                    ('Ctx', 'data.ctx'),
                                    ('Basis', 'data.basis.ref'),
                                    ('Assessment', 'data.assessment.ref'),
                                    ('RequiredDeps', 'data.required'),
                                    ('Deps', 'data.deps'),
                                    ('提交版本', 'data.submission_version'))),
        ('source', 'operation', (('来源依赖', 'data.source_deps'),
                                 ('来源记录', 'data.sources'))),
    ),
    'GUARD': (
        ('guard', 'operation', (('范围', 'data.scope'),
                                ('已观测阶段', 'data.observed_stages'),
                                ('判定', 'data.decision'),
                                ('状态', 'data.status'),
                                ('检查', 'data.checks'),
                                ('链引用', 'data.chain_refs'),
                                ('时间见证', 'data.time_witness'))),
        ('clock', 'static', (('W 序列', 'data.w_sequence'),
                             ('时间下界', 'data.time_floor'),
                             ('实例', 'data.instance_id'))),
    ),
    'PREPARE': (
        ('plan', 'operation', (('意图', 'data.intent'),
                               ('数量', 'data.amount'),
                               ('资源', 'data.resource_key'),
                               ('单位', 'data.unit'),
                               ('taskflight', 'data.taskflight'),
                               ('行为前', 'data.behavior_before'),
                               ('行为后', 'data.behavior_after'),
                               ('场景前', 'data.scene_before'),
                               ('场景后', 'data.scene_after'))),
    ),
    'CHAL': (
        ('challenge', 'operation', (('nonce', 'data.nonces'),)),
        ('identity', 'operation', (('阶段', 'data.stage'),
                                   ('过期', 'data.expires'),
                                   ('已用', 'data.used'),
                                   ('ticket', 'data.ticket'),
                                   ('nonces', 'data.nonces'))),
    ),
    'GF': (
        ('goal', 'operation', (('适用', 'data.applicable'),
                               ('模式', 'data.mode'),
                               ('判定', 'data.decision'),
                               ('原因', 'data.reason'),
                               ('容量', 'data.capacity'),
                               ('已耗', 'data.spent'),
                               ('已预留', 'data.reserved'),
                               ('本次代价', 'data.candidate_cost'),
                               ('剩余下界', 'data.remaining_floor'),
                               ('总下界', 'data.total'),
                               ('headroom', 'data.headroom'))),
    ),
    'ACCEPT': (
        ('accept', 'operation', (('派发状态', 'data.state'),
                                 ('effect', 'data.effect_state'),
                                 ('receipt', 'data.receipt_state'),
                                 ('禁止新领取', 'data.claim_blocked'),
                                 ('接受时刻', 'data.accepted_at'),
                                 ('request_ref', 'data.request_ref'),
                                 ('可信时间', 'data.trusted_time'))),
        ('commit', 'operation', (('commit_ref', 'data.commit_ref'),
                                 ('accept_seq', 'data.accept_seq'),
                                 ('dispatch_before', 'data.dispatch_before'),
                                 ('预留', 'data.reservation_ids'),
                                 ('评审引用', 'data.review_refs'))),
        ('obligations', 'profile', (('模式', 'data.mode'),
                                    ('义务', 'data.goals'),
                                    ('资源', 'data.resources'),
                                    ('预留', 'data.reservations'))),
    ),
    'RECEIPT': (
        ('receipt', 'operation', (('state', 'data.state'),
                                  ('kid', 'data.kid'),
                                  ('iat', 'data.iat'),
                                  ('exp', 'data.exp'),
                                  ('绑定 COMMIT', 'data.commit_record_ref'))),
    ),
    'PENDING': (
        ('receipt', 'operation', (('state', 'data.state'),)),
        ('accept', 'operation', (('派发状态', 'data.state'),
                                 ('receipt', 'data.receipt_state'),
                                 ('禁止新领取', 'data.claim_blocked'),
                                 ('接受时刻', 'data.accepted_at'))),
    ),
    'CLAIM': (
        ('claim', 'operation', (('attempt', 'data.attempt_id'),
                                ('state', 'data.state'),
                                ('执行标记', 'data.exec_marker'),
                                ('派发已见', 'data.send_observed'),
                                ('查询数', 'data.queries'))),
    ),
    'EXEC0': (
        ('exec', 'operation', (('attempt', 'data.attempt_id'),
                               ('已消费', 'data.exec_consumed'),
                               ('重复阻断', 'data.replay_blocked'),
                               ('已停止', 'data.halted'),
                               ('effect', 'data.effect_state'))),
    ),
    'QUERY': (
        ('query', 'operation', (('查询数', 'data.queries'),
                                ('上次状态', 'data.last_state'),
                                ('上次原因', 'data.last_reason'))),
    ),
    'FINAL': (
        ('final', 'operation', (('终局事实', 'data.final_fact_id'),
                                ('结果', 'data.final_outcome'),
                                ('effect', 'data.effect_state'),
                                ('派发状态', 'data.dispatch_state'),
                                ('工具行', 'data.tools'))),
    ),
    'SETTLE': (
        ('settlement', 'operation', (('事实', 'data.fact_id'),
                                     ('账本', 'data.ledger'),
                                     ('final_seq', 'data.final_seq'),
                                     ('effect_id', 'data.effect_id'),
                                     ('结果', 'data.outcome'))),
    ),
    'CANCEL': (
        ('cancel', 'operation', (('state', 'data.state'),
                                 ('已释放', 'data.released'),
                                 ('原因', 'data.reason'),
                                 ('义务状态', 'data.obligation_state'))),
    ),
    'UNKNOWN': (
        ('exec', 'operation', (('effect', 'data.effect_state'),
                               ('已消费', 'data.exec_consumed'),
                               ('attempt', 'data.attempt_id'))),
    ),
    'HALTED': (
        ('exec', 'operation', (('已停止', 'data.halted'),
                               ('effect', 'data.effect_state'))),
    ),
    'DUP': (
        ('exec', 'operation', (('重复阻断', 'data.replay_blocked'),
                               ('执行标记', 'data.exec_marker'))),
    ),
    'REJ': (
        ('deny', 'operation', (('覆盖完整', 'data.complete'),
                               ('revision', 'data.revision'),
                               ('拒绝引用', 'data.refs'),
                               ('发布记录', 'data.publications'))),
    ),
    'TOOL': (
        ('tool', 'operation', (('profile', 'data.profile'),
                               ('requests', 'data.requests'),
                               ('finalfacts', 'data.finalfacts'),
                               ('effects', 'data.effects'),
                               ('未适配列', 'data.columns'))),
    ),
    'TOOLDB': (
        ('tool', 'operation', (('requests', 'data.requests'),
                               ('effects', 'data.effects'))),
        ('store', 'static', (('库', 'data.tool.databases'),
                             ('独立事务', 'data.tool.separate'))),
    ),
    'SHARED': (
        ('store', 'static', (('库', 'data.shared.database'),
                             ('控制表', 'data.shared.tables.control'),
                             ('业务表', 'data.shared.tables.business'),
                             ('时钟表', 'data.shared.tables.clock'),
                             ('事务', 'data.transaction'))),
        ('db', 'table', (('表', 'data.table'),
                         ('列', 'data.columns'),
                         ('行', 'data.rows'),
                         ('上限', 'data.limit'),
                         ('偏移', 'data.offset'))),
    ),
    'RES': (
        ('obligations', 'profile', (('profile', 'data.profile'),
                                    ('资源', 'data.resources'),
                                    ('预留', 'data.reservations'))),
    ),
    'OBL': (
        ('obligations', 'profile', (('模式', 'data.mode'),
                                    ('义务', 'data.goals'),
                                    ('资源', 'data.resources'))),
    ),
    'OBS': (
        ('observe', 'static', (('事件', 'data.events'),
                               ('游标', 'data.last'))),
    ),
    'VIEW': (
        ('result', 'operation', (('类型', 'data.kind'),
                                 ('链校验', 'data.chain_valid'),
                                 ('派发', 'data.status.dispatch_state'),
                                 ('effect', 'data.status.effect_state'),
                                 ('receipt', 'data.status.receipt_state'),
                                 ('终局', 'data.status.final_outcome'),
                                 ('commit_ref', 'data.audit.commit.commit_ref'),
                                 ('证据', 'data.audit.evidence'),
                                 ('导出错误', 'data.export_error'))),
    ),
    'NOTE': (),
}

# 接口 → 路径参数类型。前端据此拼 URL；27 个端点全在这张表里。
ENDPOINT_SCOPE = {
    'entry': 'static', 'registry': 'static', 'observe': 'static', 'db': 'table',
    'guard': 'operation', 'plan': 'operation', 'goal': 'operation',
    'accept': 'operation', 'commit': 'operation', 'receipt': 'operation',
    'deny': 'operation',
    'identity': 'operation', 'challenge': 'operation', 'claim': 'operation',
    'exec': 'operation', 'final': 'operation', 'settlement': 'operation',
    'cancel': 'operation', 'query': 'operation',
    'clock': 'static', 'endpoints': 'static', 'tool': 'operation',
    'result': 'operation',
    'construct': 'operation', 'source': 'operation', 'store': 'static',
    'obligations': 'profile',
}


SUBNODE_RE = re.compile(r'^subgraph\s+([A-Za-z_]\w*)\s*(?:\["([^"]*)"\])?\s*$')
NODE_RE = re.compile(r'^([A-Za-z_]\w*)\s*[\[\(]+"([^"]*)"[\]\)]*\s*$')
EDGE_RE = re.compile(r'^([A-Za-z_]\w*)\s*(-->|==>|-\.->)\s*'
                     r'(?:\|"([^"]*)"\|\s*)?([A-Za-z_]\w*)\s*$')
CLASS_RE = re.compile(r'^class\s+([\w,\s]+?)\s+([a-z]+)\s*$')


class Diagram:
    """The committed mmd, reduced to what the page needs."""

    def __init__(self, text):
        self.nodes = {}
        self.edges = []
        self.classes = {}
        self.subgraphs = {}
        self._parse(text)

    def _parse(self, text):
        stack = []
        kind = 'control'
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith('%%'):
                mark = line.lstrip('% ').strip()[:2]
                if mark in ('1)', '2)', '3)', '4)'):
                    kind = {'1': 'control', '2': 'evidence',
                            '3': 'feedback', '4': 'reject'}[mark[0]]
                continue
            found = SUBNODE_RE.match(line)
            if found:
                sid, label = found.group(1), (found.group(2) or found.group(1))
                self.subgraphs[sid] = {'label': label,
                                       'parent': stack[-1] if stack else None}
                stack.append(sid)
                continue
            if line == 'end':
                if stack:
                    stack.pop()
                continue
            if line.startswith(('flowchart', 'linkStyle', 'classDef')):
                continue
            found = CLASS_RE.match(line)
            if found:
                for name in found.group(1).split(','):
                    if name.strip():
                        self.classes[name.strip()] = found.group(2)
                continue
            found = EDGE_RE.match(line)
            if found:
                self.edges.append({'src': found.group(1),
                                   'dst': found.group(4),
                                   'kind': kind,
                                   'label': (found.group(3) or '').strip()})
                continue
            found = NODE_RE.match(line)
            if found:
                lines = [part.strip() for part in
                         found.group(2).split('<br/>') if part.strip()]
                self.nodes[found.group(1)] = {
                    'lines': lines,
                    'subgraph': stack[-1] if stack else None,
                }


def _short(text, limit=26):
    text = text.replace('（', '(').replace('）', ')')
    return text if len(text) <= limit else text[:limit - 1] + '…'


def build_flow(diagram):
    """The page model: blocks, their nodes, and the aggregate block graph."""
    block_of = {}
    for bid, _col, _row, _label, _en, _note, members in BLOCKS:
        for name in members:
            if name not in diagram.nodes:
                raise SystemExit('block %s names unknown node %s' % (bid, name))
            if name in block_of:
                raise SystemExit('node %s is in two blocks' % name)
            block_of[name] = bid
    missing = set(diagram.nodes) - set(block_of)
    if missing:
        raise SystemExit('nodes without a block: ' + ', '.join(sorted(missing)))

    aggregate = {}
    for edge in diagram.edges:
        src, dst = block_of[edge['src']], block_of[edge['dst']]
        if src == dst:
            continue
        key = (src, dst, edge['kind'])
        item = aggregate.setdefault(key, {'src': src, 'dst': dst,
                                          'kind': edge['kind'], 'labels': []})
        if edge['label'] and edge['label'] not in item['labels']:
            item['labels'].append(edge['label'])

    blocks = []
    for bid, col, row, label, en, note, members in BLOCKS:
        order = NODE_ORDER[bid]
        nodes = []
        for name in order:
            node = diagram.nodes[name]
            lines = node['lines'] or [name]
            nodes.append({
                'id': name,
                'title': lines[0],
                'lines': lines[1:],
                'style': diagram.classes.get(name, 'entry'),
                'subgraph': node['subgraph'],
                'live': [{'label': item[0], 'diag': item[1], 'field': item[2]}
                         for item in LIVE.get(name, ())],
                'cards': [{'diag': diag, 'scope': scope,
                           'rows': [{'label': r[0], 'field': r[1]} for r in rows]}
                          for diag, scope, rows in CARDS.get(name, ())],
            })
        inside = set(members)
        edges = [dict(edge) for edge in diagram.edges
                 if edge['src'] in inside and edge['dst'] in inside]
        cross = []
        for edge in diagram.edges:
            if edge['src'] in inside and edge['dst'] not in inside:
                cross.append({'direction': 'out', 'kind': edge['kind'],
                              'label': edge['label'], 'peer': block_of[edge['dst']],
                              'node': edge['src'], 'other': edge['dst']})
            elif edge['dst'] in inside and edge['src'] not in inside:
                cross.append({'direction': 'in', 'kind': edge['kind'],
                              'label': edge['label'], 'peer': block_of[edge['src']],
                              'node': edge['dst'], 'other': edge['src']})
        blocks.append({
            'id': bid, 'col': col, 'row': row,
            'label': label, 'en': en, 'note': note,
            'nodes': nodes, 'edges': edges, 'cross': cross,
        })

    block_edges = sorted(aggregate.values(),
                         key=lambda e: (e['src'], e['dst'], e['kind']))
    return {
        'source': SOURCE.name,
        'stages': list(STAGES),
        'kinds': list(KINDS),
        'endpoints': ENDPOINT_SCOPE,
        'blocks': blocks,
        'block_edges': block_edges,
    }


# ── 渲染 ──────────────────────────────────────────────────────────────────
def _live_html(node):
    if not node['live']:
        return ''
    chips = ''.join(
        '<div class="ob-k"><dt>%s</dt>'
        '<dd><span class="ob-v" data-live data-live-diag="%s" '
        'data-live-field="%s">—</span></dd></div>'
        % (escape(item['label']), escape(item['diag']), escape(item['field']))
        for item in node['live'])
    return '<dl class="ob-keys">%s</dl>' % chips


def _cards_html(node):
    if not node['cards']:
        return ''
    parts = []
    for card in node['cards']:
        rows = ''.join(
            '<div class="ob-row"><dt>%s</dt>'
            '<dd data-field="%s">—</dd></div>'
            % (escape(row['label']), escape(row['field']))
            for row in card['rows'])
        source = '/api/diag/%s' % card['diag']
        if card['scope'] == 'operation':
            source += '/{oid}'
        elif card['scope'] == 'profile':
            source += '/{profile}'
        elif card['scope'] == 'table':
            source += '/w_operation'
        parts.append(
            '<article class="ob-card" data-diag="%s" data-scope="%s"%s>'
            '<header class="ob-card__head">'
            '<span class="ob-card__code">%s</span>'
            '<span class="ob-card__src">%s</span>'
            '</header><dl class="ob-card__rows">%s</dl></article>'
            % (escape(card['diag']), escape(card['scope']),
               ' data-table="w_operation"' if card['scope'] == 'table' else '',
               escape(card['diag']), escape(source), rows))
    return ('<details class="ob-more"><summary>投影字段</summary>'
            '<div class="ob-cards">%s</div></details>' % ''.join(parts))


def _relations_html(node, edges, cross):
    items = []
    for edge in edges:
        if edge['src'] == node['id']:
            arrow, peer = '→', edge['dst']
        elif edge['dst'] == node['id']:
            arrow, peer = '←', edge['src']
        else:
            continue
        items.append(
            '<li class="ob-rel" data-kind="%s"><span class="ob-rel__k">%s</span>'
            '<span class="ob-rel__d">%s</span>'
            '<span class="ob-rel__t">%s%s</span></li>'
            % (edge['kind'], KIND_LABEL[edge['kind']], arrow,
               escape(peer), (' · ' + escape(edge['label'])) if edge['label'] else ''))
    for item in cross:
        if item['node'] != node['id']:
            continue
        peer = next((b[3] for b in BLOCKS if b[0] == item['peer']), item['peer'])
        arrow = '⇥' if item['direction'] == 'out' else '⇤'
        items.append(
            '<li class="ob-rel ob-rel--cross" data-kind="%s">'
            '<span class="ob-rel__k">%s</span>'
            '<span class="ob-rel__d">%s</span>'
            '<span class="ob-rel__t">块外 · %s · %s</span></li>'
            % (item['kind'], KIND_LABEL[item['kind']], arrow,
               escape(_short(peer, 12)),
               escape(item['label'] or item['other'])))
    if not items:
        return ''
    return '<ul class="ob-rels">%s</ul>' % ''.join(items)


def _node_html(node, edges, cross):
    title = escape(node['title'])
    desc = ' '.join(escape(line) for line in node['lines'])
    body = ''
    if desc:
        body = '<p class="ob-node__desc">%s</p>' % desc
    return (
        '<li class="ob-node" data-node="%s" data-state="idle">'
        '<span class="ob-node__rail" aria-hidden="true"></span>'
        '<article class="ob-node__body">'
        '<header class="ob-node__head">'
        '<span class="ob-node__code">%s</span>'
        '<h3 class="ob-node__title">%s</h3>'
        '<span class="ob-node__state" data-node-state>未到达</span>'
        '</header>%s%s%s%s'
        '</article></li>'
        % (escape(node['id']), escape(node['id']), title, body,
           _live_html(node), _relations_html(node, edges, cross),
           _cards_html(node)))


def _dots_html(nodes):
    return ''.join('<i class="ob-dot" data-node="%s" data-state="idle"></i>'
                   % escape(node['id']) for node in nodes)


def render_map(blocks):
    items = []
    for index, block in enumerate(blocks, start=1):
        items.append(
            '<li class="ob-map__cell" data-col="%d" data-row="%d">'
            '<button type="button" class="ob-block" data-block="%s" data-state="idle">'
            '<span class="ob-block__head">'
            '<span class="ob-block__code">%02d</span>'
            '<span class="ob-block__label">%s</span>'
            '<span class="ob-block__state" data-block-state>未到达</span>'
            '</span>'
            '<span class="ob-block__en">%s</span>'
            '<span class="ob-block__note">%s</span>'
            '<span class="ob-block__dots" aria-hidden="true">%s</span>'
            '<span class="ob-block__cta" aria-hidden="true">打开</span>'
            '</button></li>'
            % (block['col'], block['row'], escape(block['id']),
               index, escape(block['label']), escape(block['en']),
               escape(block['note']), _dots_html(block['nodes'])))
    return '\n'.join(items)


def render_details(blocks):
    blocks_by_id = {block['id']: block for block in blocks}
    out = []
    for index, block in enumerate(blocks, start=1):
        nodes = ''.join(_node_html(node, block['edges'], block['cross'])
                        for node in block['nodes'])
        out.append(
            '<section class="ob-detail" id="block-%s" data-block="%s" hidden>'
            '<header class="ob-detail__head"><div class="ob-detail__inner">'
            '<button type="button" class="ob-back" data-back>'
            '<span aria-hidden="true">←</span> 返回总图</button>'
            '<div class="ob-detail__title">'
            '<span class="ob-detail__code">%02d</span>'
            '<h2>%s</h2>'
            '<span class="ob-detail__en">%s</span>'
            '</div>'
            '<p class="ob-detail__note">%s</p>'
            '<ul class="ob-legend ob-legend--inline" aria-label="四类关系">'
            '<li data-kind="control">控制流</li>'
            '<li data-kind="evidence">证据绑定</li>'
            '<li data-kind="feedback">状态反馈</li>'
            '<li data-kind="reject">阻断 / 未知</li>'
            '</ul>'
            '</div></header>'
            '<ol class="ob-chain">%s</ol>'
            '</section>'
            % (escape(block['id']), escape(block['id']), index,
               escape(block['label']), escape(block['en']),
               escape(block['note']), nodes))
    return '\n'.join(out)


def build(source=SOURCE):
    diagram = Diagram(source.read_text(encoding='utf-8'))
    flow = build_flow(diagram)
    layout = (STATIC / 'layout.html').read_text(encoding='utf-8')
    page = (layout
            .replace('<!-- {{MAP}} -->', render_map(flow['blocks']))
            .replace('<!-- {{DETAIL}} -->', render_details(flow['blocks'])))
    if '{{' in page:
        raise SystemExit('unreplaced placeholder in layout.html')
    FLOW.write_text(json.dumps(flow, ensure_ascii=False, indent=1) + '\n',
                    encoding='utf-8')
    INDEX.write_text(page, encoding='utf-8')
    return flow, INDEX


def main(argv=None):
    if not SOURCE.is_file():
        raise SystemExit('diagram source not found: %s' % SOURCE)
    flow, page = build()
    print('wrote', FLOW.relative_to(ROOT))
    print('wrote', page.relative_to(ROOT))
    print('blocks', len(flow['blocks']),
          'nodes', sum(len(b['nodes']) for b in flow['blocks']),
          'block edges', len(flow['block_edges']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
