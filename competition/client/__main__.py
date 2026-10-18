"""Entry point: ``python -m competition.client --directory D --profile P --alias A``.

Without ``--serve`` the client answers exactly one request line and exits -- the
broker-style one-shot.  With ``--serve`` it stays up until its input closes;
``--socket PATH`` moves that input to a unix socket instead of stdin.

The key is never named on the command line: it comes from the conventional file
``<directory>/<profile>-<alias>.key`` (``W-worker.key`` for ``worker``), and the
client refuses to start unless that file is its own 0600 credential.
"""
import argparse
import sys

from competition.client.host import serve_connection, serve_unix
from competition.client.signer import ROLE_DOMAINS, RoleSigner
from competition.support.wire import ProtocolError, require


def build_parser():
    parser = argparse.ArgumentParser(
        prog='python -m competition.client',
        description='外部角色签署端：按域白名单回答受信端的挑战。')
    parser.add_argument('--directory', required=True, help='持有角色钥文件的目录')
    parser.add_argument('--profile', required=True, help='本客户端绑定的 Profile')
    parser.add_argument('--alias', required=True, choices=sorted(ROLE_DOMAINS),
                        help='本客户端绑定的角色（worker 使用 W-worker.key）')
    parser.add_argument('--serve', action='store_true',
                        help='持续应答直到输入关闭（默认只应答一行）')
    parser.add_argument('--socket', default=None,
                        help='改为监听该 unix socket（需与 --serve 同用）')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
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
