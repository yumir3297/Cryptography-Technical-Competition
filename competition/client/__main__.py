"""Entry point: ``python -m competition.client --directory D --profile P --alias A``.

Four modes:

``--keygen``
    generate this endpoint's own key, print the public metadata a roster manifest
    carries, and exit.  The private half stays in ``--directory``.
``--check-package FILE``
    read the trusted side's public package and check this endpoint's own
    registration against the credential it holds, then exit.
default
    serve: answer exactly one request line and exit -- the broker-style one-shot.
``--serve``
    stay up until the input closes; ``--socket PATH`` moves that input to a unix
    socket instead of stdin.
``--serve-http``
    answer the same requests over HTTP instead of a byte stream.  ``--port``
    defaults to the deterministic port this endpoint's place in the roster
    implies, so nothing has to be published or discovered.

The key is never named on the command line: it comes from the conventional file
``<directory>/<profile>-<alias>.key`` (``W-worker.key`` for ``worker``,
``<profile>-tool.key`` for ``tool``), and the client refuses to use it unless it
is its own 0600 credential.

``--keygen`` writes the manifest entry to stdout and the path it used to stderr,
so ``python -m competition.client --keygen ... >> roster.jsonl`` collects a
manifest without a merge step.
"""
import argparse
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from competition.client.host import serve_connection, serve_unix
from competition.client.keys import ENDPOINTS, generate, key_file_name, propose_purposes, propose_subject
from competition.client.signer import RoleSigner, load_role_key
from competition.support.wire import ProtocolError, keyid, require


def build_parser():
    parser = argparse.ArgumentParser(
        prog='python -m competition.client',
        description='外部角色签署端：本地生成密钥，按域白名单回答受信端的挑战。')
    parser.add_argument('--directory', required=True,
                        help='持有（--keygen 时为写入）本端钥文件的目录')
    parser.add_argument('--profile', default=None,
                        help='本客户端绑定的 Profile（worker 是跨 Profile 能力，不需要）')
    parser.add_argument('--alias', required=True, choices=sorted(ENDPOINTS),
                        help='本端角色（worker 用 W-worker.key；tool 只生成密钥）')
    parser.add_argument('--keygen', action='store_true',
                        help='只生成本端密钥并打印公钥元数据（manifest 一行），不启动服务')
    parser.add_argument('--check-package', default=None,
                        help='读受信端公开包，核对本端被登记成什么，然后退出')
    parser.add_argument('--name', default=None, help='--keygen / --check-package 时的 subject')
    parser.add_argument('--serve', action='store_true',
                        help='持续应答直到输入关闭（默认只应答一行）')
    parser.add_argument('--socket', default=None,
                        help='改为监听该 unix socket（需与 --serve 同用）')
    parser.add_argument('--serve-http', action='store_true',
                        help='改为 HTTP 服务（与 --socket 互斥）')
    parser.add_argument('--host', default='127.0.0.1', help='--serve-http 时监听地址')
    parser.add_argument('--port', type=int, default=None,
                        help='--serve-http 时监听端口（默认按 roster 位置推出的那个）')
    return parser


def _own_public(path):
    """This endpoint's own public key, from the credential it holds as an 0600 file."""
    key = load_role_key(path)
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return public, keyid(public)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        path = Path(args.directory) / key_file_name(args.profile, args.alias)
        if args.keygen:
            metadata = generate(args.directory, args.profile, args.alias, name=args.name)
            sys.stderr.write('key: %s\n' % path)
            print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
            return
        if args.check_package is not None:
            from competition.client.package import check, read_package
            require(args.profile is not None or args.alias == 'worker', 'CLIENT_USAGE')
            public, kid = _own_public(path)
            facts = check(read_package(args.check_package), args.profile, args.alias,
                          public=public, kid=kid,
                          name=args.name or propose_subject(args.profile, args.alias),
                          purposes=propose_purposes(args.alias))
            print(json.dumps({'check': 'OK', **facts}, ensure_ascii=False, sort_keys=True))
            return
        # A roster alias or the worker serves challenges; the tool keeps its own
        # ledger process and reads its own key file.
        require(args.alias != 'tool', 'CLIENT_USAGE')
        require(args.profile is not None or args.alias == 'worker', 'CLIENT_USAGE')
        require(not (args.serve_http and args.socket), 'CLIENT_USAGE')
        require(args.port is None or 0 < args.port < 65536, 'CLIENT_USAGE')
        signer = RoleSigner.from_directory(args.directory, args.profile, args.alias)
        if args.serve_http:
            from competition.client.web import serve_http
            from competition.server.roster import endpoint_port
            port = args.port or endpoint_port(args.profile, args.alias)
            serve_http(args.host, port, signer, name=args.name)
        elif args.socket is not None:
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
