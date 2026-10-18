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
from competition.support.wire import ProtocolError, b64

ROOT = Path(__file__).resolve().parents[2]

HELP = """\
命令：
  init [dir] [manifest [endpoints_dir]]
                    建立受信运行并启动可信端（默认 .runtime/server）；
                    给了 manifest 则用各端上交的公钥（外部密钥模式）
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
  identities        列出 roster 的 subject/alias/kid/purposes
  roster [file]     载入并列出 roster manifest（各端上交的公钥，JSON Lines）
  enroll <subject> [<public_key> <purpose,purpose>]  发 pending
                    （已载入 manifest 时可只给 subject）
  enroll-register <subject>  本地签 POP 并登记，打印 grant
  result <oid>      取回单操作结果包（公钥/签名/投影，不含私钥）
  export <oid> <dir> 把结果包写到新目录（bundle/chain/manifest）
  verify <dir>      独立核验结果包（manifest 哈希 + 签名链 + 禁导检查）
  package [file]    组装并打印（或写到新文件）公开包：各端被登记成什么
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
        self.roster_path = None
        self.roster_entries = None
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
        """init [dir] [manifest [endpoints_dir]] —— 给了 manifest 就走外部密钥模式。"""
        from competition.profiles.w_seed import initialize
        folder = Path(args[0]).resolve() if args else ROOT / '.runtime' / 'server'
        fleet = None
        if len(args) > 1:
            from competition.server.roster import Fleet
            manifest = Path(args[1]).resolve()
            endpoints = Path(args[2]).resolve() if len(args) > 2 else manifest.parent
            fleet = Fleet.read(endpoints, manifest)
        self.run = initialize(folder, fleet=fleet)
        self.signer = LocalSigner(self.run)
        self.service = TrustedService(self.run, self.signer)
        print('可信端会话已建立:', folder, '(外部密钥)' if fleet else '(本地兜底密钥)')

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

    # -- 身份面: 登记 / 持钥证明（POP） -------------------------------------
    # Appended last on purpose: another face edits this file concurrently.
    def _pendings(self):
        """The per-session pending enrollments, created on first use."""
        if not hasattr(self, '_pending'):
            self._pending = {}
        return self._pending

    def cmd_identities(self, args):
        self._need_run()
        for profile in ([self.profile] if self.profile else sorted(PROFILE_SCOPES)):
            for alias, actor in sorted(self.run.actors[profile].items()):
                print(profile, alias, actor.name, actor.kid,
                      json.dumps(sorted(actor.purposes), ensure_ascii=False), sep='\t')

    def cmd_roster(self, args):
        """载入（或重新列出）roster manifest：各端自生成并上交的公钥。"""
        if args:
            from competition.server.roster import read_manifest
            self.roster_entries = read_manifest(args[0])
            self.roster_path = str(Path(args[0]).resolve())
            print('manifest:', self.roster_path)
        if self.roster_entries is None:
            raise RuntimeError('用法: roster <manifest.jsonl>')
        from competition.server.roster import describe
        print(_dump(describe(self.roster_entries)))

    def _roster_entry(self, subject):
        """当前 Profile 下该 subject 的 manifest 条目（若已载入）。"""
        for entry in self.roster_entries or ():
            if entry.profile == self.profile and entry.subject == subject:
                return entry
        return None

    def cmd_enroll(self, args):
        self._need_profile()
        if not args:
            raise RuntimeError('用法: enroll <subject> [<public_key> <purpose,purpose>]')
        subject, public_key, purposes = args[0], None, None
        if len(args) == 3:
            public_key, purposes = args[1], [p for p in args[2].split(',') if p]
        elif len(args) != 1:
            raise RuntimeError('用法: enroll <subject> [<public_key> <purpose,purpose>]')
        if public_key is None:
            entry = self._roster_entry(subject)
            if entry is not None:
                public_key, purposes = b64(entry.pub), list(entry.purposes)
        pending = self.service.enroll(self.profile, subject, public_key, purposes)
        self._pendings()[(self.profile, subject)] = pending
        print('enrollment_id:', pending['enrollment_id'])
        print('nonce:', pending['nonce'])
        print('tuple:', _dump(pending['tuple']))

    def cmd_enroll_register(self, args):
        self._need_profile()
        if not args:
            raise RuntimeError('用法: enroll-register <subject>')
        import time
        subject = args[0]
        pending = self._pendings().get((self.profile, subject))
        if pending is None:
            raise RuntimeError('还没有登记请求，先运行 enroll %s' % subject)
        now = int(time.time())
        proof = self.service.enroll_proof(self.profile, subject, pending, now, now + 60)
        grant = self.service.enroll_register(self.profile, proof)
        self._pendings().pop((self.profile, subject), None)
        print('grant:', _dump(grant))

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

    # -- 公开包: 各端拿回去自己核对 -----------------------------------------
    def cmd_package(self, args):
        self._need_run()
        package = self.service.package()
        if args:
            from competition.server.package import write_package
            print('已写出:', _dump(write_package(package, args[0])))
            return
        print(_dump(package))


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
    'identities': 'cmd_identities',
    'roster': 'cmd_roster',
    'enroll': 'cmd_enroll',
    'enroll-register': 'cmd_enroll_register',
    'result': 'cmd_result',
    'export': 'cmd_export',
    'verify': 'cmd_verify',
    'package': 'cmd_package',
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
