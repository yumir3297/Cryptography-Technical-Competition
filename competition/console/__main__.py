"""Entry point: ``python -m competition.console``.

Reads where the entry and the endpoints are, enrolls its two callers, serves the
page, and opens the two sessions behind it.  The two credentials are its own and
are never printed; the session tokens stay in the process.

The page goes up *before* the sessions are opened, and that order is the point.
Four of the six roles sign inside the chain that the entry assembles, and their
endpoints park those signatures until a person answers -- so the entry can be
blocked waiting on somebody who needs this page open to answer.  Serving first
and opening the sessions behind it is what keeps the two from deadlocking.  What
the page shows while it waits is read straight from those endpoints, not through
the entry, so it works while the entry is blocked.
"""
import argparse
import os
import sys
import threading

from competition.console.app import serve
from competition.console.control import DEFAULT_PROFILE, START_TIMEOUT, Console


def build_parser():
    parser = argparse.ArgumentParser(
        prog='python -m competition.console',
        description='客户端控制台：以两个调用者身份接入受信端入口，把一遍流程呈现为页面。')
    parser.add_argument('--directory', default=os.environ.get('ZJJ_CALLERS', '/callers'),
                        help='持有本控制台两个调用者钥文件与 allowlist 的目录')
    parser.add_argument('--entry', default=os.environ.get('ZJJ_ENTRY', 'http://trusted:8000'),
                        help='受信端入口基址，如 http://trusted:8000')
    parser.add_argument('--endpoints', default=os.environ.get('ZJJ_ENDPOINTS', 'http://endpoints'),
                        help='各角色端地址基址，如 http://endpoints')
    parser.add_argument('--profile', default=os.environ.get('ZJJ_PROFILE', DEFAULT_PROFILE),
                        help='页面默认 Profile')
    parser.add_argument('--host', default=os.environ.get('ZJJ_CONSOLE_HOST', '0.0.0.0'),
                        help='页面监听地址')
    parser.add_argument('--port', type=int,
                        default=int(os.environ.get('ZJJ_CONSOLE_PORT', '8100')),
                        help='页面监听端口')
    parser.add_argument('--dist', default=os.environ.get('ZJJ_CONSOLE_DIST'),
                        help='已构建页面的目录（默认包内 frontend/dist）')
    parser.add_argument('--wait', type=float,
                        default=float(os.environ.get('ZJJ_CONSOLE_WAIT', str(START_TIMEOUT))),
                        help='等入口应答的上限秒数')
    return parser


def open_sessions(console):
    """Open both sessions and say so.  A failure is reported, not raised.

    This runs behind the page, so an entry that is not up yet -- or one that is
    blocked on an approval -- must not take the page down with it.
    """
    try:
        opened = console.start()
    except Exception as exc:  # noqa: BLE001 - report whatever it was, keep serving
        print('两个会话没能开：%s' % exc, file=sys.stderr, flush=True)
        return
    print('两个会话已开：%s' % ', '.join(
        '%s=%s' % (entry['side'], entry.get('caller')) for entry in opened['sessions']),
        flush=True)


def main(argv=None):
    args = build_parser().parse_args(argv)
    console = Console(args.directory, args.entry, args.endpoints,
                      profile=args.profile, timeout=args.wait)
    print('两个调用者登记在 %s' % console.enroll(), flush=True)
    threading.Thread(target=open_sessions, args=(console,), daemon=True).start()
    print('控制台在 http://%s:%d%s/' % (args.host, args.port, '/console'), flush=True)
    serve(args.host, args.port, console, dist=args.dist)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
