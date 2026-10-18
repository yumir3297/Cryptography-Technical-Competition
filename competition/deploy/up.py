"""One command to start the deployment and watch it work.

``python -m competition.deploy.up``
    build the image, bring up the five services, wait for the two sides of the flow
    to finish, and print what they did.  The services stay up afterwards; the door
    is on the host at 8080.
``--local``
    run the same entry points as plain processes on this machine, in one
    directory, for a host whose docker daemon is not reachable.  Nothing is
    simulated: ``deploy.endpoints``, ``deploy.trusted`` and ``deploy.demo`` are the
    very processes the containers run, and only who connects them differs.

What the script deliberately does not do is quietly clean up after a refusal.  The
trusted side initializes once per run directory -- the run *is* the record -- so if
it refuses to start, that is what you are told, and ``--fresh`` is how a demo is
asked to start over.  Nothing here decides on its own that a ledger is disposable.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from competition.deploy import expected_manifest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = Path(__file__).resolve().parent / 'docker-compose.yml'
# The two services that walk the flow; the rest stay up and serve.
DEMO = ('caller-h', 'caller-worker')


def compose(args, sudo, *, capture=False, check=True):
    """One ``docker compose`` call against this deployment's file."""
    argv = (['sudo'] if sudo else []) + ['docker', 'compose', '-f', str(COMPOSE)] + list(args)
    return subprocess.run(argv, cwd=str(ROOT), check=check, text=True,
                          capture_output=capture)


def docker_says(container, template, sudo):
    """One field off a container, asked of the daemon rather than guessed."""
    argv = (['sudo'] if sudo else []) + ['docker', 'inspect', '-f', template, container]
    return subprocess.run(argv, capture_output=True, text=True, check=False).stdout.strip()


def service_container(service, sudo):
    """The id of one compose service, running or not."""
    done = compose(['ps', '--all', '-q', service], sudo, capture=True, check=False)
    found = done.stdout.split()
    return found[0] if found else None


def wait_for_service(service, sudo, timeout):
    """The exit code of one service, once it has exited; ``None`` if it never did."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container = service_container(service, sudo)
        if container and docker_says(container, '{{.State.Status}}', sudo) == 'exited':
            return int(docker_says(container, '{{.State.ExitCode}}', sudo) or 0)
        time.sleep(1.0)
    return None


def show(service, sudo):
    """What one service said, indented under its name."""
    text = compose(['logs', '--no-log-prefix', service], sudo, capture=True,
                   check=False).stdout.rstrip()
    print('--- %s ---' % service, flush=True)
    print(text or '(没有输出)', flush=True)


def up_docker(args):
    probe = (['sudo'] if args.sudo else []) + ['docker', 'info']
    if subprocess.run(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        print('docker daemon 不可达。加 --sudo（daemon 权限不足），或者用 --local 在本机'
              '以普通进程跑同一套入口脚本。', file=sys.stderr, flush=True)
        return 1
    if args.fresh:
        print('[1/5] 丢掉上次的卷', flush=True)
        compose(['down', '-v'], args.sudo)
    if not args.no_build:
        print('[2/5] 构建镜像', flush=True)
        compose(['build'], args.sudo)
    print('[3/5] 起服务', flush=True)
    compose(['up', '-d'], args.sudo)
    print('[4/5] 等两侧把演示跑完（最多 %ds）' % args.timeout, flush=True)
    codes = {service: wait_for_service(service, args.sudo, args.timeout) for service in DEMO}
    print('[5/5] 结果', flush=True)
    for service in DEMO:
        show(service, args.sudo)
    if any(codes[service] != 0 for service in DEMO):
        for service in ('trusted', 'endpoints'):
            show(service, args.sudo)
        print('演示没有跑完：%s' % codes, file=sys.stderr, flush=True)
        print('若受信端是说 run 目录里已有 W，那是初始化只能发生一次：'
              '要重新跑一遍演示就加 --fresh。', file=sys.stderr, flush=True)
        return 1
    print('演示跑完了。对外入口在 http://127.0.0.1:8080/healthz；'
          '再跑一遍加 --fresh。', flush=True)
    if args.down:
        print('收摊。', flush=True)
        compose(['down', '-v'], args.sudo)
    return 0


def spawn(argv, env, *, capture=False, **extra):
    """One entry point as a plain process, with the environment it was given."""
    print('起:', argv[0], flush=True)
    return subprocess.Popen([sys.executable, '-m', *argv], cwd=str(ROOT),
                            env={**env, **extra}, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.STDOUT if capture else None)


def up_local(args):
    root = Path(args.dir).resolve() if args.dir else ROOT / '.runtime' / 'deploy'
    if args.fresh and root.exists():
        print('[1/4] 丢掉上次的运行目录', root, flush=True)
        shutil.rmtree(root)
    endpoints = root / 'endpoints'
    callers = root / 'callers'
    callers.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONUNBUFFERED': '1'}
    entry = 'http://127.0.0.1:%d' % args.port
    children = []
    try:
        print('[2/4] 起各角色端与受信端（它们自己的日志就在下面）', flush=True)
        children.append(spawn(['competition.deploy.endpoints'], env,
                              ZJJ_ENDPOINTS=str(endpoints), ZJJ_ENDPOINT_HOST='127.0.0.1'))
        children.append(spawn(['competition.deploy.trusted'], env,
                              ZJJ_RUN=str(root / 'run'), ZJJ_ENDPOINTS=str(endpoints),
                              ZJJ_CALLERS=str(callers / 'callers.jsonl'),
                              ZJJ_ENDPOINT_BASE='http://127.0.0.1',
                              ZJJ_ENTRY_HOST='127.0.0.1', ZJJ_ENTRY_PORT=str(args.port)))
        print('[3/4] 起两侧调用者，等它们把一遍流程走完', flush=True)
        demo = [(side, spawn(['competition.deploy.demo'], env, capture=True,
                             ZJJ_SIDE=side, ZJJ_NAME='caller-' + side.lower(),
                             ZJJ_CALLERS=str(callers), ZJJ_ENTRY=entry,
                             ZJJ_ENDPOINTS='http://127.0.0.1',
                             ZJJ_HANDOFF=str(callers / 'demo-operation')))
                for side in ('H', 'worker')]
        deadline = time.monotonic() + args.timeout
        while any(child.poll() is None for _, child in demo) and time.monotonic() < deadline:
            for child in children:
                if child.poll() not in (None, 0):
                    print('基础设施进程提前退出了，演示跑不下去', file=sys.stderr, flush=True)
                    return 1
            time.sleep(0.2)
        print('[4/4] 结果', flush=True)
        failed = False
        for side, child in demo:
            output = child.communicate(timeout=30)[0] or ''
            print('--- caller-%s（退出码 %s）---' % (side.lower(), child.returncode), flush=True)
            print(output.rstrip() or '(没有输出)', flush=True)
            failed = failed or child.returncode != 0
        if failed:
            print('演示没有跑完。', file=sys.stderr, flush=True)
            return 1
        print('演示跑完了。运行目录：%s' % root, flush=True)
        print('受信端的入口在 %s（容器里那个门是 caddy 的 8080）。' % entry, flush=True)
        print('再跑一遍加 --fresh。', flush=True)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='python -m competition.deploy.up',
        description='一键起整套，并看着两侧把一遍流程跑完。')
    parser.add_argument('--local', action='store_true',
                        help='不用 docker，在本机以普通进程跑同一套入口脚本')
    parser.add_argument('--sudo', action='store_true', help='docker 命令走 sudo')
    parser.add_argument('--fresh', action='store_true', help='先丢掉上次的运行/卷重新开始')
    parser.add_argument('--no-build', action='store_true', help='跳过镜像构建')
    parser.add_argument('--down', action='store_true', help='跑完就收摊（连卷一起删）')
    parser.add_argument('--dir', default=None, help='--local 时的运行目录（默认 .runtime/deploy）')
    parser.add_argument('--port', type=int, default=8000, help='--local 时受信端入口端口')
    parser.add_argument('--timeout', type=float, default=600.0, help='等演示跑完的上限秒数')
    args = parser.parse_args(argv)
    print('这一套要 22 个端点凭据，其中 %d 个会起服务。' % (expected_manifest() - 3), flush=True)
    try:
        return up_local(args) if args.local else up_docker(args)
    except subprocess.CalledProcessError as exc:
        print('命令失败了：%s' % ' '.join(exc.cmd), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
