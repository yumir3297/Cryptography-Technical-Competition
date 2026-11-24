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


# ── 分块 ───────────────────────────────────────────────────────────────────
# A block is a mmd subgraph or a lone node: what decides the level is whether
# it has children, not whether it is drawn as a box.  Five have children and
# can be opened; the other seven are leaves and can only be selected.  There is
# deliberately no W block — its three children sit on the map at their own
# rank, and no grouping frame is drawn.
BLOCKS = (
    ('trust', '入口与信任域', 'TRUST',
     'Agent 只提供候选；C 负责登记与发布；E 只认证来源。两个入口并列，不串联。',
     ('AG', 'ENTRY_SRV', 'ENTRY_IND', 'C', 'E'), True),
    ('ctx', '可信构造', 'CONSTRUCT',
     '把意图固化成完整 Action 与 ActionHash；Basis / Assessment / RequiredDeps / Ctx 一并冻结。',
     ('CTX',), False),
    ('guard', '关系核验', 'COMMON GUARD',
     '签名 / Ctx / Refs / RequiredDeps / DENY / 窗口；PREPARE 初检、ACCEPT 事务内重核、终局再核。',
     ('GUARD',), False),
    ('s45', '准备、判定与原子接受', 'PREPARE · ACCEPT',
     'PREPARE 成功不等于接受；GoalFloor 默认 off，只在 ACCEPT 事务内判定。',
     ('PREPARE', 'CHAL', 'GF', 'ACCEPT'), True),
    ('s6', '回执与唯一执行资格', 'RECEIPT · CLAIM',
     '回执只签原冻结 Core；EXEC-0 先持久消费标记，再向工具派发。',
     ('RECEIPT', 'PENDING', 'CLAIM', 'EXEC0'), True),
    ('s7', '终局、结算与恢复', 'FINAL · RECOVER',
     '只有可信终局才结算；STARTED 不可通用取消，未知只能认证查询原 attempt。',
     ('QUERY', 'FINAL', 'SETTLE', 'CANCEL', 'UNKNOWN', 'HALTED', 'DUP', 'REJ'), True),
    ('tool', '工具端效果', 'TOOL',
     '验签后执行或查询，并签名返回；工具账本在 W 事务之外。',
     ('TOOL',), False),
    ('tooldb', '工具账本', 'TOOL SQLITE',
     'requests / effects / finalfacts 独立存放，不并入 W 事务。',
     ('TOOLDB',), False),
    ('db', '共享 SQLite 与账本', 'SHARED LEDGER',
     'C 控制状态与 W 业务状态同库同事务；资源与义务账随终局更新。',
     ('SHARED', 'RES', 'OBL'), True),
    ('obs', '观察 / 审计投影', 'OBSERVE',
     '只读投影，不形成授权。',
     ('OBS',), False),
    ('view', 'Agent 认证视图', 'AGENT VIEW',
     '只读投影，不含执行权限。',
     ('VIEW',), False),
    ('note', '边界', 'BOUNDARIES',
     '原子性仅限各自事务；UNKNOWN 保留占用；哈希不认证来源。',
     ('NOTE',), False),
)

# 块内阅读顺序：主链在前，分支随后。控制流边本身仍以 mmd 为准。
NODE_ORDER = {
    'trust': ('AG', 'ENTRY_SRV', 'ENTRY_IND', 'C', 'E'),
    'ctx': ('CTX',),
    'guard': ('GUARD',),
    's45': ('PREPARE', 'CHAL', 'GF', 'ACCEPT'),
    's6': ('RECEIPT', 'PENDING', 'CLAIM', 'EXEC0'),
    's7': ('QUERY', 'FINAL', 'SETTLE', 'CANCEL', 'UNKNOWN', 'HALTED', 'DUP', 'REJ'),
    'tool': ('TOOL',),
    'tooldb': ('TOOLDB',),
    'db': ('SHARED', 'RES', 'OBL'),
    'obs': ('OBS',),
    'view': ('VIEW',),
    'note': ('NOTE',),
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


# ── 分层布局 ───────────────────────────────────────────────────────────────
# The page draws the diagram the way the mmd declares it: a left-to-right
# layered graph.  Ranking happens here so the browser only has to measure
# boxes and place them; cycles in the committed diagram (QUERY → TOOL and
# TOOL → FINAL, ACCEPT → SFARED and SHARED → GF) are cut at the back edges
# before the longest-path pass, exactly like a layered drawer would.

def _pos(hint, name):
    try:
        return hint.index(name)
    except ValueError:
        return len(hint)


def _back_edges(ids, edges, hint):
    """DFS over the declared order; edges back into the stack are feedback."""
    adj = {name: [] for name in ids}
    for edge in edges:
        if edge['src'] in adj and edge['dst'] in adj:
            adj[edge['src']].append(edge['dst'])
    color = {name: 0 for name in ids}
    back = set()
    for root in sorted(ids, key=lambda name: _pos(hint, name)):
        if color[root]:
            continue
        color[root] = 1
        stack = [[root, 0]]
        while stack:
            name, index = stack[-1]
            if index < len(adj[name]):
                stack[-1][1] += 1
                target = adj[name][index]
                if color[target] == 1:
                    back.add((name, target))
                elif color[target] == 0:
                    color[target] = 1
                    stack.append([target, 0])
            else:
                color[name] = 2
                stack.pop()
    return back


def _ranks(ids, edges, back, hint):
    """Longest-path ranks over the acyclic part, in the declared order."""
    rank = {name: 0 for name in ids}
    indegree = {name: 0 for name in ids}
    dag = []
    for edge in edges:
        if (edge['src'], edge['dst']) in back:
            continue
        if edge['src'] not in rank or edge['dst'] not in rank:
            continue
        dag.append(edge)
        indegree[edge['dst']] += 1
    ready = sorted((name for name in ids if indegree[name] == 0),
                   key=lambda name: _pos(hint, name))
    while ready:
        name = ready.pop(0)
        for edge in dag:
            if edge['src'] != name:
                continue
            target = edge['dst']
            rank[target] = max(rank[target], rank[name] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
        ready.sort(key=lambda item: _pos(hint, item))
    return rank


def _orders(ids, edges, rank, hint):
    """Barycenter pass over ranked rows: fewer crossings, stable order."""
    levels = {}
    for name in ids:
        levels.setdefault(rank[name], []).append(name)
    for row in levels.values():
        row.sort(key=lambda name: _pos(hint, name))
    neighbours = {name: set() for name in ids}
    for edge in edges:
        if edge['src'] in neighbours and edge['dst'] in neighbours:
            neighbours[edge['src']].add(edge['dst'])
            neighbours[edge['dst']].add(edge['src'])

    order = {}
    for name in ids:
        order[name] = levels[rank[name]].index(name)
    for _ in range(6):
        for level in sorted(levels)[1:]:
            previous = levels[level - 1]
            position = {name: index for index, name in enumerate(previous)}
            def key(name):
                hits = [position[item] for item in neighbours[name] if item in position]
                return ((sum(hits) / len(hits) if hits else order[name]), order[name])
            levels[level].sort(key=key)
            for index, name in enumerate(levels[level]):
                order[name] = index
    for level in levels:
        for index, name in enumerate(levels[level]):
            order[name] = index
    return order


def arrange(ids, edges, hint):
    """Evidence edges bind, they do not order: rank on the behavioural spine.

    Ranking on every edge lets a binding pointer back to a prerequisite win the
    cycle cut and drags the prerequisite into the same column (ACCEPT below
    RECEIPT, for example).  The spine is control + feedback + reject; evidence
    only fine-tunes the order inside a column.
    """
    spine = [edge for edge in edges if edge['kind'] != 'evidence']
    back = _back_edges(ids, spine, hint)
    rank = _ranks(ids, spine, back, hint)
    spine_nodes = {edge['src'] for edge in spine} | {edge['dst'] for edge in spine}
    for _ in range(3):
        for edge in edges:
            if edge['kind'] != 'evidence' or edge['dst'] in spine_nodes:
                continue
            if rank[edge['dst']] == 0 and rank[edge['src']] > 0:
                rank[edge['dst']] = rank[edge['src']]
    order = _orders(ids, edges, rank, hint)
    return rank, order, back


# ── 模型 ──────────────────────────────────────────────────────────────────
def _node_meta(name, diagram):
    lines = diagram.nodes[name]['lines'] or [name]
    return {
        'id': name,
        'title': lines[0],
        'lines': lines[1:],
        'style': diagram.classes.get(name, 'entry'),
        'live': [{'label': item[0], 'diag': item[1], 'field': item[2]}
                 for item in LIVE.get(name, ())],
        'cards': [{'diag': diag, 'scope': scope,
                   'rows': [{'label': row[0], 'field': row[1]} for row in rows]}
                  for diag, scope, rows in CARDS.get(name, ())],
    }


def _block_graph(members, diagram, block_of, block_label):
    """One block drawn like the mmd subgraph: its nodes plus one-hop stubs."""
    inside = set(members)
    ids = list(members)
    edges = []
    seen = set()
    for edge in diagram.edges:
        src, dst = edge['src'], edge['dst']
        if src not in inside and dst not in inside:
            continue
        key = (src, dst, edge['kind'], edge['label'])
        if key in seen:
            continue
        seen.add(key)
        edges.append({'src': src, 'dst': dst, 'kind': edge['kind'],
                      'label': edge['label']})
        for endpoint in (src, dst):
            if endpoint not in inside and endpoint not in ids:
                ids.append(endpoint)

    hint = list(NODE_ORDER[block_of[members[0]]]) + \
        sorted(name for name in ids if name not in inside)
    rank, order, back = arrange(ids, edges, hint)

    nodes = []
    for name in ids:
        if name in inside:
            node = _node_meta(name, diagram)
            node['stub'] = False
            node['block'] = block_of[name]
        else:
            lines = diagram.nodes[name]['lines'] or [name]
            node = {'id': name, 'title': lines[0], 'lines': lines[1:],
                    'style': diagram.classes.get(name, 'entry'),
                    'live': [], 'cards': [], 'stub': True,
                    'block': block_label[block_of[name]]}
        node['rank'] = rank[name]
        node['order'] = order[name]
        nodes.append(node)

    for edge in edges:
        edge['back'] = (edge['src'], edge['dst']) in back

    # A node with no remaining edge (a boundary note) sits at the far right.
    if nodes:
        top = max(node['rank'] for node in nodes)
        for node in nodes:
            if not any(edge['src'] == node['id'] or edge['dst'] == node['id']
                       for edge in edges):
                node['rank'] = top
                node['order'] = max(item['order'] for item in nodes
                                    if item['rank'] == top) + 1
    return nodes, edges


def build_flow(diagram):
    block_of = {}
    for bid, _label, _en, _note, members, _expand in BLOCKS:
        for name in members:
            if name not in diagram.nodes:
                raise SystemExit('block %s names unknown node %s' % (bid, name))
            if name in block_of:
                raise SystemExit('node %s is in two blocks' % name)
            block_of[name] = bid
    missing = set(diagram.nodes) - set(block_of)
    if missing:
        raise SystemExit('nodes without a block: ' + ', '.join(sorted(missing)))

    block_label = {bid: label for bid, label, _en, _note, _m, _x in BLOCKS}
    blocks = []
    for bid, label, en, note, members, expand in BLOCKS:
        nodes, edges = _block_graph(members, diagram, block_of, block_label)
        blocks.append({
            'id': bid, 'label': label, 'en': en, 'note': note,
            'expand': expand,
            'nodes': nodes, 'edges': edges,
        })

    # The map is the same diagram with every block collapsed: one node per
    # block, every original edge folded into a block-to-block relation.  Edges
    # keep their two endpoint names so the open layer can draw each one on its
    # own lane.
    aggregate = {}
    for edge in diagram.edges:
        src, dst = block_of[edge['src']], block_of[edge['dst']]
        if src == dst:
            continue
        key = (src, dst, edge['kind'])
        item = aggregate.setdefault(key, {'src': src, 'dst': dst,
                                          'kind': edge['kind'], 'labels': [],
                                          'count': 0, 'members': []})
        item['count'] += 1
        item['members'].append({'src': edge['src'], 'dst': edge['dst'],
                                'label': edge['label']})
        if edge['label'] and edge['label'] not in item['labels']:
            item['labels'].append(edge['label'])

    ids = [block[0] for block in BLOCKS]
    priority = {'control': 0, 'evidence': 1, 'feedback': 2, 'reject': 3}
    map_edges = sorted(aggregate.values(),
                       key=lambda item: (priority[item['kind']],
                                         ids.index(item['src']),
                                         ids.index(item['dst'])))
    map_nodes = [{'id': name,
                  'label': next(block[1] for block in BLOCKS if block[0] == name),
                  'en': next(block[2] for block in BLOCKS if block[0] == name),
                  'expand': next(block[5] for block in BLOCKS if block[0] == name)}
                 for name in ids]

    return {
        'source': SOURCE.name,
        'stages': list(STAGES),
        'kinds': list(KINDS),
        'endpoints': ENDPOINT_SCOPE,
        'blocks': blocks,
        'map': {'nodes': map_nodes, 'edges': map_edges},
    }


# ── 渲染 ──────────────────────────────────────────────────────────────────
def _live_html(node):
    if not node['live']:
        return ''
    chips = ''.join(
        '<span class="ob-gkey"><i>%s</i>'
        '<b data-live data-live-diag="%s" data-live-field="%s">—</b></span>'
        % (escape(item['label']), escape(item['diag']), escape(item['field']))
        for item in node['live'])
    return '<span class="ob-gnode__keys">%s</span>' % chips


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
    return ''.join(parts)


def _text_html(node):
    if not node['lines']:
        return ''
    return '<span class="ob-gnode__text">%s</span>' % '<br>'.join(
        escape(line) for line in node['lines'])


def _step_html(node):
    if node['stub']:
        return ('<div class="ob-gnode ob-gnode--stub" data-gid="%s" data-node="%s" '
                'data-graph-node data-rank="%d" data-order="%d" data-state="idle">'
                '<span class="ob-gnode__top"><span class="ob-gnode__code">块外</span>'
                '<span class="ob-gnode__tag" data-node-state></span></span>'
                '<span class="ob-gnode__label">%s</span>'
                '<span class="ob-gnode__en">%s</span></div>'
                % (escape(node['id']), escape(node['id']), node['rank'],
                   node['order'], escape(node['title']), escape(node['block'])))
    return ('<div class="ob-gnode ob-gnode--step" data-gid="%s" data-node="%s" '
            'data-graph-node data-rank="%d" data-order="%d" data-state="idle">'
            '<span class="ob-gnode__top"><span class="ob-gnode__code">%s</span>'
            '<span class="ob-gnode__tag" data-node-state>未到达</span></span>'
            '<span class="ob-gnode__label">%s</span>%s%s</div>'
            % (escape(node['id']), escape(node['id']), node['rank'],
               node['order'], escape(node['id']), escape(node['title']),
               _text_html(node), _live_html(node)))


def _dots_html(block):
    return ''.join('<i class="ob-dot" data-node="%s" data-state="idle"></i>'
                   % escape(node['id']) for node in block['nodes']
                   if not node['stub'])


def render_map(flow):
    items = []
    for index, block in enumerate(flow['blocks'], start=1):
        items.append(
            '<button type="button" class="ob-gnode ob-gnode--block" '
            'data-gid="%s" data-graph-node data-block="%s" data-state="idle" '
            'data-expandable="%d" data-code="%02d" data-label="%s" data-en="%s">'
            '<span class="ob-gnode__top">'
            '<span class="ob-gnode__code">%02d</span>'
            '<span class="ob-gnode__tag" data-block-state>未到达</span>'
            '</span>'
            '<span class="ob-gnode__label">%s</span>'
            '<span class="ob-gnode__en">%s</span>'
            '<span class="ob-gnode__dots" aria-hidden="true">%s</span>'
            '</button>'
            % (escape(block['id']), escape(block['id']),
               1 if block['expand'] else 0, index,
               escape(block['label']), escape(block['en']),
               index, escape(block['label']), escape(block['en']),
               _dots_html(block)))
    return '\n'.join(items)


def render_expand(flow):
    """One layer per block with children: the sub-graph laid out in the map."""
    parts = []
    for index, block in enumerate(flow['blocks'], start=1):
        if not block['expand']:
            continue
        nodes = ''.join(_step_html(node) for node in block['nodes'])
        parts.append(
            '<div class="ob-expand" data-expand="%s" data-graph="expand-%s" '
            'data-code="%02d" data-label="%s" data-en="%s" data-gap="54" hidden>'
            '<div class="ob-canvas">'
            '<svg class="ob-edges" aria-hidden="true" focusable="false"></svg>'
            '<div class="ob-nodes">%s</div>'
            '</div></div>'
            % (escape(block['id']), escape(block['id']), index,
               escape(block['label']), escape(block['en']), nodes))
    return '\n'.join(parts)


def render_hud(flow):
    """Raw projections stay available, folded into the corner inspector."""
    parts = []
    for block in flow['blocks']:
        with_cards = [node for node in block['nodes']
                      if node['cards'] and not node['stub']]
        if with_cards:
            body = ''.join(
                '<section class="ob-hud__node"><h4>%s</h4>'
                '<div class="ob-cards">%s</div></section>'
                % (escape(node['id']), _cards_html(node))
                for node in with_cards)
        else:
            body = '<p class="ob-hint">本模块没有投影字段。</p>'
        parts.append(
            '<div class="ob-hud__part" data-panel="%s" hidden>%s</div>'
            % (escape(block['id']), body))
    return '\n'.join(parts)


def build(source=SOURCE):
    diagram = Diagram(source.read_text(encoding='utf-8'))
    flow = build_flow(diagram)
    layout = (STATIC / 'layout.html').read_text(encoding='utf-8')
    page = (layout
            .replace('<!-- {{MAP}} -->', render_map(flow))
            .replace('<!-- {{EXPAND}} -->', render_expand(flow))
            .replace('<!-- {{HUD}} -->', render_hud(flow)))
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
    print('blocks', len(flow['blocks']))
    print('map', [(node['id'], 'open' if node['expand'] else 'leaf')
                  for node in flow['map']['nodes']])
    for block in flow['blocks']:
        print(block['id'], 'ranks',
              sorted({node['rank'] for node in block['nodes']}),
              'nodes', len(block['nodes']), 'edges', len(block['edges']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
