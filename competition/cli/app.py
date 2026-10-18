"""Trusted-side interactive CLI over the minimal interface.

Every command maps to one :class:`~competition.server.service.TrustedService`
call.  ``submit`` takes only a profile and (optionally) business intent; every
later step is the explicit two-move the interface exposes -- request the core's
challenge, then hand the proof back.  This round the proof comes from the local
fallback signer; when external role clients are connected, only that changes.

Run it with ``python -m competition.server`` (or ``python -m competition.cli``).
"""
import json
from pathlib import Path

from competition.core.trusted_state import PROFILE_SCOPES
from competition.server.service import STEPS, INTENT_FIELDS, TrustedService
from competition.server.signer import LocalSigner
from competition.support.wire import ProtocolError

ROOT = Path(__file__).resolve().parents[2]

HELP = """\
命令：
  init [dir]        建立受信运行并启动可信端（默认 .runtime/server）
  profiles          列出三个固定 Profile
  intent            列出各 Profile 允许的业务意图字段
  use <profile>     选择当前 Profile
  show              显示会话状态
  action            打印当前 Profile 的绑定模板动作
  submit [file]     提交候选（Resolver）；不带文件用绑定语料，或从 JSON 读业务意图
  prepare           回答 prepare 挑战并取得 ticket
  accept            回答接受挑战
  claim             领取唯一派发尝试
  exec              消费执行资格并发送工具请求
  query             重新认证查询同一 attempt
  settle            用最近一次工具响应结算
  cancel            取消尚未领取且当前无效的操作
  status            认证读取单操作投影
  audit             认证读取投影加 commit/证据
  auto              submit->prepare->accept->claim->exec->settle->status 一键跑完
  counts            全 W 汇总计数（无调用者认证）
  result <oid>      取回单操作结果包（公钥/签名/投影，不含私钥）
  export <oid> <dir> 把结果包写到新目录（bundle/chain/manifest）
  verify <dir>      独立核验结果包（manifest 哈希 + 签名链 + 禁导检查）
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
        self.operation_id = None
        self.prepare_challenge = None
        self.quit = False

    # -- guards -------------------------------------------------------------
    def _need_run(self):
        if self.run is None:
            raise RuntimeError('还没有会话，先运行 init')

    def _need_profile(self):
        self._need_run()
        if self.profile is None:
            raise RuntimeError('还没有选择 Profile，先运行 use <profile>')

    def _need_operation(self):
        self._need_profile()
        if self.operation_id is None:
            raise RuntimeError('还没有提交候选，先运行 submit')

    # -- session ------------------------------------------------------------
    def cmd_init(self, args):
        from competition.profiles.w_seed import initialize
        folder = Path(args[0]).resolve() if args else ROOT / '.runtime' / 'server'
        self.run = initialize(folder)
        self.signer = LocalSigner(self.run)
        self.service = TrustedService(self.run, self.signer)
        print('可信端会话已建立:', folder)

    def cmd_profiles(self, args):
        for profile in PROFILE_SCOPES:
            print(profile)

    def cmd_intent(self, args):
        for profile, fields in INTENT_FIELDS.items():
            print(profile, '=', _dump(list(fields)))

    def cmd_use(self, args):
        self._need_run()
        if not args:
            raise RuntimeError('用法: use <profile>')
        if args[0] not in PROFILE_SCOPES:
            raise RuntimeError('未知 Profile: %s' % args[0])
        self.profile = args[0]
        self.operation_id = None
        self.prepare_challenge = None
        print('当前 Profile:', self.profile)

    def cmd_show(self, args):
        print(_dump({
            'run': str(self.run.folder) if self.run else None,
            'profile': self.profile,
            'operation_id': self.operation_id,
            'has_pending_challenge': self.prepare_challenge is not None,
        }))

    def cmd_action(self, args):
        self._need_profile()
        print(_dump(self.run.operations[self.profile]['action']))

    # -- 候选提交 -----------------------------------------------------------
    def cmd_submit(self, args):
        self._need_profile()
        intent = json.loads(Path(args[0]).read_text(encoding='utf-8')) if args else None
        submitted = self.service.submit(self.profile, intent)
        self.operation_id = submitted['operation_id']
        self.prepare_challenge = submitted['challenge']
        print('operation_id:', self.operation_id)
        print('prepare 挑战:', _dump(self.prepare_challenge))

    # -- interface: challenge -> answer -> prove ----------------------------
    def _drive(self, step):
        _, _, role, domain = STEPS[step]
        claim = self.service.challenge(self.operation_id, step)
        proof = self.service.answer(self.profile, role, domain, claim)
        return self.service.prove(self.operation_id, step, proof)

    def cmd_prepare(self, args):
        self._need_operation()
        if self.prepare_challenge is None:
            self.prepare_challenge = self.service.challenge(self.operation_id, 'prepare')
        print('GUARD 挑战:', _dump(self.prepare_challenge))
        _, _, role, domain = STEPS['prepare']
        proof = self.service.answer(self.profile, role, domain, self.prepare_challenge)
        ticket = self.service.prove(self.operation_id, 'prepare', proof)['ticket_id']
        self.prepare_challenge = None
        print('ticket:', ticket)

    def cmd_accept(self, args):
        self._need_operation()
        print('接受:', _dump(self._drive('accept')))

    def cmd_claim(self, args):
        self._need_operation()
        print('领取:', _dump(self._drive('claim')))

    def cmd_exec(self, args):
        self._need_operation()
        print('执行响应:', _dump(self._drive('exec')))

    def cmd_query(self, args):
        self._need_operation()
        print('查询响应:', _dump(self._drive('query')))

    def cmd_settle(self, args):
        self._need_operation()
        print('结算:', _dump(self._drive('settle')))

    def cmd_cancel(self, args):
        self._need_operation()
        print('取消:', _dump(self._drive('cancel')))

    def cmd_status(self, args):
        self._need_operation()
        print('状态:', _dump(self._drive('status')))

    def cmd_audit(self, args):
        self._need_operation()
        print('审计:', _dump(self._drive('audit')))

    def cmd_counts(self, args):
        self._need_run()
        print(_dump(self.service.counts()))

    # -- convenience --------------------------------------------------------
    def cmd_auto(self, args):
        self._need_profile()
        result = self.service.run_normal(self.profile)
        self.operation_id = result['operation_id']
        self.prepare_challenge = None
        print('operation_id:', self.operation_id)
        print('结算:', _dump(result['settled']))
        print('状态:', _dump(result['status']))

    def cmd_help(self, args):
        print(HELP, end='')

    def cmd_quit(self, args):
        self.quit = True

    # -- result face --------------------------------------------------------
    def cmd_result(self, args):
        self._need_operation()
        operation_id = args[0] if args else self.operation_id
        print('结果包:', _dump(self.service.result(operation_id)))

    def cmd_export(self, args):
        self._need_run()
        if len(args) != 2:
            raise RuntimeError('用法: export <oid> <dir>')
        report = self.service.export(args[0], args[1])
        print('已导出:', _dump(report))

    def cmd_verify(self, args):
        if len(args) != 1:
            raise RuntimeError('用法: verify <dir>')
        from competition.server.export import verify_bundle
        print('核验:', _dump(verify_bundle(args[0])))


COMMANDS = {
    'help': 'cmd_help',
    'quit': 'cmd_quit', 'exit': 'cmd_quit',
    'init': 'cmd_init',
    'profiles': 'cmd_profiles',
    'intent': 'cmd_intent',
    'use': 'cmd_use',
    'show': 'cmd_show',
    'action': 'cmd_action',
    'submit': 'cmd_submit',
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
    'result': 'cmd_result',
    'export': 'cmd_export',
    'verify': 'cmd_verify',
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
