"""Entry point: ``python -m competition.client --directory D --profile P --alias A``.

Three modes:

``--keygen``
    generate this endpoint's own key, print the public metadata a roster manifest
    carries, and exit.  The private half stays in ``--directory``.
default
    serve: answer exactly one request line and exit -- the broker-style one-shot.
``--serve``
    stay up until the input closes; ``--socket PATH`` moves that input to a unix
    socket instead of stdin.

The key is never named on the command line: it comes from the conventional file
``<directory>/<profile>-<alias>.key`` (``W-worker.key`` for ``worker``), and the
client refuses to start unless that file is its own 0600 credential.
"""
import argparse
import json
import sys
from pathlib import Path

from competition.client.host import serve_connection, serve_unix
from competition.client.keys import ENDPOINTS, generate, key_file_name
from competition.client.signer import RoleSigner
from competition.support.wire import ProtocolError, require


def build_parser():
    parser = argparse.ArgumentParser(
        prog='python -m competition.client',
        description='外部角色签署端：本地生成密钥，按域白名单回答受信端的挑战。')
    parser.add_argument('--directory', required=True,
                        help='持有（--keygen 时为写入）本端钥文件的目录')
    parser.add_argument('--profile', required=True, help='本客户端绑定的 Profile')
    parser.add_argument('--alias', required=True, choices=sorted(ENDPOINTS),
                        help='本端角色（worker 用 W-worker.key；tool 只生成密钥）')
    parser.add_argument('--keygen', action='store_true',
                        help='只生成本端密钥并打印公钥元数据，不启动服务')
    parser.add_argument('--name', default=None, help='--keygen 时替代默认 subject')
    parser.add_argument('--serve', action='store_true',
                        help='持续应答直到输入关闭（默认只应答一行）')
    parser.add_argument('--socket', default=None,
                        help='改为监听该 unix socket（需与 --serve 同用）')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.keygen:
            metadata = generate(args.directory, args.profile, args.alias, name=args.name)
            metadata['key_path'] = str(Path(args.directory) / key_file_name(args.profile, args.alias))
            print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
            return
        # The tool keeps its own ledger process and reads its own key file, so it
        # has no challenge host to serve.
        require(args.alias != 'tool', 'CLIENT_USAGE')
        signer = RoleSigner.from_directory(args.directory, args.profile, args.alias)
        if args.socket is not None:
            require(args.serve, 'CLIENT_USAGE')
            serve_unix(args.socket, signer)
        else:
            serve_connection(sys.stdin.buffer, sys.stdout.buffer, signer,
                             once=not args.serve)
    except (ProtocolError, OSError, ValueError) as exc:
        sys.stderr.write('DENY:' + getattr(exc, 'code', type(exc).__name__) + '\n')
        raise SystemExit(41)


if __name__ == '__main__':
    main()
