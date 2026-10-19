"""Entry point: ``python -m competition.caller --directory D --name caller-h ...``.

``--keygen``
    make this caller's own credential and print the allowlist line the deployment
    collects, so ``--keygen >> callers.jsonl`` needs no merge step.
``--entry`` plus ``--submit`` / ``--step`` / ``--package``
    drive this caller's side of the flow against one trusted entry: propose an
    operation, carry each step's challenge to the endpoint that owns it and the
    signature back.

The credential is never named on the command line: it comes from the conventional
file ``<directory>/<name>.key``, and the caller refuses to use it unless it is its
own 0600 credential.  Which side of the flow it may drive is not decided here
either -- the entry's caller list decides, and a step the caller was not listed
for comes back refused.
"""
import argparse
import json
import sys
from pathlib import Path

from competition.caller import generate, key_file_name
from competition.caller.flow import Caller
from competition.support.wire import ProtocolError, require
from competition.web.session import SIDES


def build_parser():
    parser = argparse.ArgumentParser(
        prog='python -m competition.caller',
        description='业务调用者：持自己的钥亮证，把每一步的挑战转给对应角色端签名，再交回受信端。')
    parser.add_argument('--directory', default='.', help='持有（--keygen 时为写入）本调用者钥文件的目录')
    parser.add_argument('--name', default=None, help='调用者名字（allowlist 里的 name）')
    parser.add_argument('--sides', default=None,
                        help='--keygen 时提议的 sides，逗号分隔（%s）' % ' / '.join(SIDES))
    parser.add_argument('--keygen', action='store_true',
                        help='只生成本调用者密钥并打印 allowlist 一行，不连接任何服务')
    parser.add_argument('--entry', default=None, help='受信端入口基址，如 http://trusted:8000')
    parser.add_argument('--endpoints', default=None, help='各角色端地址基址，如 http://endpoints')
    parser.add_argument('--profile', default=None, help='--submit 时的 Profile')
    parser.add_argument('--intent', default=None, help='业务意图 JSON 文件（可选）')
    parser.add_argument('--operation-id', default=None, help='--step 时的操作 id')
    parser.add_argument('--submit', action='store_true', help='提交一个操作（提出方那一侧）')
    parser.add_argument('--step', action='append', default=[],
                        help='驱动一个步骤，可重复（如 --step claim --step exec --step settle）')
    parser.add_argument('--package', action='store_true', help='打印受信端发布的公开包')
    return parser


def _dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _sides(text):
    return [side for side in text.split(',') if side]


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.keygen:
            require(bool(args.name and args.sides), 'CALLER_USAGE')
            line = generate(args.directory, args.name, _sides(args.sides))
            sys.stderr.write('key: %s\n' % (Path(args.directory) / key_file_name(args.name)))
            print(json.dumps(line, ensure_ascii=False, sort_keys=True))
            return
        require(bool(args.entry and args.name), 'CALLER_USAGE')
        caller = Caller(args.entry, Path(args.directory) / key_file_name(args.name),
                        args.endpoints)
        opened = caller.start()
        # The token is not printed: it is a credential, and the caller is the only
        # thing that has to carry it.
        print('已亮证:', opened['caller'], ' sides=%s' % ','.join(opened['sides']),
              '到期=%s' % opened['expires'])
        if args.package:
            print('公开包:', _dump(caller.package))
        if args.submit:
            require(args.profile is not None, 'CALLER_USAGE')
            intent = (json.loads(Path(args.intent).read_text(encoding='utf-8'))
                      if args.intent else None)
            print('提交:', _dump(caller.submit(args.profile, intent)))
        for step in args.step:
            require(args.operation_id is not None, 'CALLER_USAGE')
            print('步骤 %s:' % step, _dump(caller.step(args.operation_id, step)))
    except (ProtocolError, OSError, ValueError) as exc:
        sys.stderr.write('DENY:' + getattr(exc, 'code', type(exc).__name__) + '\n')
        raise SystemExit(41)


if __name__ == '__main__':
    main()
