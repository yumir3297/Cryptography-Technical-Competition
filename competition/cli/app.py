"""Trusted-side interactive CLI over the challenge/signature interface.

Every command maps to one :class:`~competition.server.service.TrustedService`
call.  Operations that need a signature first request the core's challenge, then
answer it and pass the proof back -- the same explicit two-step the interface
exposes.  This round the answer comes from the local fallback signer; when
external role clients are connected, only the signer changes.
"""
import json
from pathlib import Path

from competition.core.trusted_state import PROFILE_SCOPES
from competition.server.service import (ACCEPT_DOMAIN, GUARD_DOMAIN, READ_DOMAIN,
                                        TrustedService, WORKER_DOMAIN)
from competition.server.signer import LocalSigner
from competition.support.wire import ProtocolError

ROOT = Path(__file__).resolve().parents[2]

HELP = """\
命令：
  init [dir]        建立受信运行并启动可信端（默认 .runtime/server）
  profiles          列出三个固定 Profile
  use <profile>     选择当前 Profile
  show              显示会话状态
  action            打印当前 Profile 的演示动作
  build [file]      构造完整请求（Resolver）；默认用演示动作，或从 JSON 文件读取
  prepare           发起挑战并提交 H 签名，取得 ticket
  accept            提交接受签名
  claim             领取唯一派发尝试
  exec              消费执行资格并发送工具请求
  query             重新认证查询同一 attempt
  settle            用最近一次工具响应结算
  cancel            取消尚未领取且当前无效的操作
  status            认证读取单操作投影
  audit             认证读取投影加 commit/证据
  auto              build->prepare->accept->claim->exec->settle->status 一键跑完
  counts            全 W 汇总计数（无调用者认证）
  help              显示本帮助
  quit              退出
"""


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)


class Session:
    def __init__(self):
        self.run = None
        self.service = None
        self.signer = None
        self.profile = None
        self.op = None
        self.ticket = None
        self.operation_id = None
        self.response = None
        self.quit = False

    # -- guards -------------------------------------------------------------
    def _need_run(self):
        if self.run is None:
            raise RuntimeError('还没有会话，先运行 init')

    def _need_profile(self):
        self._need_run()
        if self.profile is None:
            raise RuntimeError('还没有选择 Profile，先运行 use <profile>')

    def _need_op(self):
        self._need_profile()
        if self.op is None:
            raise RuntimeError('还没有构造请求，先运行 build')

    def _need_ticket(self):
        self._need_op()
        if self.ticket is None:
            raise RuntimeError('还没有 ticket，先运行 prepare')

    # -- session ------------------------------------------------------------
    def cmd_init(self, args):
        from competition.profiles.w_seed import initialize
        folder = Path(args[0]).resolve() if args else ROOT / '.runtime' / 'server'
        self.run = initialize(folder)
        self.signer = LocalSigner(self.run)
        self.service = TrustedService(self.run, self.signer)
        print('可信端会话已建立:', folder)

    def cmd_profiles(self, args):
        for profile, scope in PROFILE_SCOPES.items():
            print(profile, '=', _dump(scope))

    def cmd_use(self, args):
        self._need_run()
        if not args:
            raise RuntimeError('用法: use <profile>')
        if args[0] not in PROFILE_SCOPES:
            raise RuntimeError('未知 Profile: %s' % args[0])
        self.profile = args[0]
        self.op = self.ticket = self.operation_id = self.response = None
        print('当前 Profile:', self.profile)

    def cmd_show(self, args):
        print(_dump({
            'run': str(self.run.folder) if self.run else None,
            'profile': self.profile,
            'operation_id': self.operation_id,
            'ticket': self.ticket,
            'has_op': self.op is not None,
            'has_response': self.response is not None,
        }))

    def cmd_action(self, args):
        self._need_profile()
        print(_dump(self.run.operations[self.profile]['action']))

    # -- Resolver -----------------------------------------------------------
    def cmd_build(self, args):
        self._need_profile()
        base = self.run.operations[self.profile]
        if args:
            action = json.loads(Path(args[0]).read_text(encoding='utf-8'))
        else:
            action = base['action']
        self.op = self.service.build_op(self.profile, action, base['task_id'], base['scene_key'])
        self.operation_id = self.op['action']['operation_id']
        self.ticket = None
        self.response = None
        print('operation_id:', self.operation_id)

    # -- interface: challenge -> answer -> operate --------------------------
    def cmd_prepare(self, args):
        self._need_op()
        claim = self.service.challenge(self.profile, self.op)
        print('GUARD 挑战:', _dump(claim))
        proof = self.service.answer(self.profile, 'H', GUARD_DOMAIN, claim)
        self.ticket = self.service.prepare(self.profile, self.op, proof)['ticket_id']
        print('ticket:', self.ticket)

    def cmd_accept(self, args):
        self._need_ticket()
        claim = self.service.challenge_accept(self.profile, self.ticket)
        proof = self.service.answer(self.profile, 'H', ACCEPT_DOMAIN, claim)
        print('接受:', _dump(self.service.accept(self.profile, self.ticket, proof)))

    def cmd_claim(self, args):
        self._need_op()
        claim = self.service.challenge_worker(self.profile, self.operation_id, 'CLAIM')
        proof = self.service.answer(self.profile, 'worker', WORKER_DOMAIN, claim)
        print('领取:', _dump(self.service.claim(self.profile, self.operation_id, proof)))

    def cmd_exec(self, args):
        self._need_op()
        claim = self.service.challenge_worker(self.profile, self.operation_id, 'EXECUTE')
        proof = self.service.answer(self.profile, 'worker', WORKER_DOMAIN, claim)
        self.response = self.service.execute_once(self.profile, self.operation_id, proof)
        print('执行响应:', _dump(self.response))

    def cmd_query(self, args):
        self._need_op()
        claim = self.service.challenge_worker(self.profile, self.operation_id, 'QUERY')
        proof = self.service.answer(self.profile, 'worker', WORKER_DOMAIN, claim)
        self.response = self.service.query_attempt(self.profile, self.operation_id, proof)
        print('查询响应:', _dump(self.response))

    def cmd_settle(self, args):
        self._need_op()
        if self.response is None:
            raise RuntimeError('还没有工具响应，先运行 exec 或 query')
        claim = self.service.challenge_worker(self.profile, self.operation_id, 'SETTLE')
        proof = self.service.answer(self.profile, 'worker', WORKER_DOMAIN, claim)
        print('结算:', _dump(self.service.settle(self.profile, self.operation_id, self.response, proof)))

    def cmd_cancel(self, args):
        self._need_op()
        claim = self.service.challenge_worker(self.profile, self.operation_id, 'CANCEL')
        proof = self.service.answer(self.profile, 'worker', WORKER_DOMAIN, claim)
        print('取消:', _dump(self.service.cancel(self.profile, self.operation_id, proof)))

    def cmd_status(self, args):
        self._need_op()
        claim = self.service.challenge_read(self.profile, self.operation_id, 'STATUS')
        proof = self.service.answer(self.profile, 'H', READ_DOMAIN, claim)
        print('状态:', _dump(self.service.status(self.profile, self.operation_id, proof)))

    def cmd_audit(self, args):
        self._need_op()
        claim = self.service.challenge_read(self.profile, self.operation_id, 'AUDIT')
        proof = self.service.answer(self.profile, 'H', READ_DOMAIN, claim)
        print('审计:', _dump(self.service.audit(self.profile, self.operation_id, proof)))

    def cmd_counts(self, args):
        self._need_run()
        print(_dump(self.service.counts()))

    # -- convenience --------------------------------------------------------
    def cmd_auto(self, args):
        self._need_profile()
        result = self.service.run_normal(self.profile)
        self.op = result['op']
        self.operation_id = result['operation_id']
        self.ticket = result['ticket']['ticket_id']
        self.response = result['response']
        print('operation_id:', self.operation_id)
        print('结算:', _dump(result['settled']))
        print('状态:', _dump(result['status']))

    def cmd_help(self, args):
        print(HELP, end='')

    def cmd_quit(self, args):
        self.quit = True


COMMANDS = {
    'help': 'cmd_help',
    'quit': 'cmd_quit', 'exit': 'cmd_quit',
    'init': 'cmd_init',
    'profiles': 'cmd_profiles',
    'use': 'cmd_use',
    'show': 'cmd_show',
    'action': 'cmd_action',
    'build': 'cmd_build',
    'prepare': 'cmd_prepare',
    'accept': 'cmd_accept',
    'claim': 'cmd_claim',
    'exec': 'cmd_exec',
    'query': 'cmd_query',
    'settle': 'cmd_settle',
    'cancel': 'cmd_cancel',
    'status': 'cmd_status',
    'audit': 'cmd_audit',
    'auto': 'cmd_auto',
    'counts': 'cmd_counts',
}


def main():
    session = Session()
    print('ZJJ-CORE 可信端 CLI。输入 help 查看命令。')
    while not session.quit:
        try:
            line = input('zjj> ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        handler = COMMANDS.get(parts[0])
        if handler is None:
            print('未知命令:', parts[0], '（输入 help 查看）')
            continue
        try:
            getattr(session, handler)(parts[1:])
        except ProtocolError as exc:
            print('已拒绝:', exc.code)
        except Exception as exc:  # noqa: BLE001 - top-level CLI guard
            print('错误:', type(exc).__name__, exc)
    if session.run is not None:
        session.run.close()
