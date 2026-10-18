"""One command to start the deployment and watch it work.

``python -m competition.deploy.up``
    bring up the five services, bring up DeepSeek Harness alongside them, wait for
    the two sides of the flow to finish, and print what they did.  Everything stays
    up afterwards; the deployment's door is on the host at 8080, the harness at
    3080.
``--local``
    run the same entry points as plain processes on this machine, in one
    directory, for a host whose docker daemon is not reachable.  Nothing is
    simulated: ``deploy.endpoints``, ``deploy.trusted`` and ``deploy.demo`` are the
    very processes the containers run, and only who connects them differs.  The
    harness is a container, so this mode leaves it alone.

What the script deliberately does not do is quietly clean up after a refusal.  The
trusted side initializes once per run directory -- the run *is* the record -- so if
it refuses to start, that is what you are told, and ``--fresh`` is how a demo is
asked to start over.  Nothing here decides on its own that a ledger is disposable.
The harness is treated the same way on ``--down``: its container goes, its volume
stays, because the volume is where the API key and the session history live.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from competition.deploy import expected_manifest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = Path(__file__).resolve().parent / 'docker-compose.yml'
# The two services that walk the flow; the rest stay up and serve.
DEMO = ('caller-h', 'caller-worker')

# DeepSeek Harness is not part of the competition software and nothing of it is
# delivered here.  It is the agent workbench this machine is worked from, and it is
# pinned to one image tag so that a run today and a run in a month are the same
# thing.  The image is a community one -- dsh publishes no container of its own --
# and it is worth having for one more reason than convenience: it builds node-pty's
# Linux side from source, which a bare ``npm install -g`` cannot do without a
# toolchain, and which dsh ships no prebuilt binary for.
HARNESS_NAME = 'deepseek-harness'
HARNESS_IMAGE = 'smanx/deepseek-harness:devtools-0.2.0-rc.2'
HARNESS_HOME = 'dsh-home'
HARNESS_PORT = 3080


def compose(args, sudo, *, capture=False, check=True):
    """One ``docker compose`` call against this deployment's file."""
    argv = (['sudo'] if sudo else []) + ['docker', 'compose', '-f', str(COMPOSE)] + list(args)
    return subprocess.run(argv, cwd=str(ROOT), check=check, text=True,
                          capture_output=capture)


def docker(args, sudo, *, capture=False, check=True):
    """One plain ``docker`` call.  Stderr rides along when capturing, so the
    daemon's own wording reaches whoever is reading the output."""
    argv = (['sudo'] if sudo else []) + ['docker'] + list(args)
    if capture:
        return subprocess.run(argv, cwd=str(ROOT), check=check, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return subprocess.run(argv, cwd=str(ROOT), check=check)


def docker_says(container, template, sudo):
    """One field off a container, asked of the daemon rather than guessed."""
    return docker(['inspect', '-f', template, container], sudo,
                  capture=True, check=False).stdout.strip()


def service_container(service, sudo):
    """The id of one compose service, running or not."""
    found = compose(['ps', '--all', '-q', service], sudo, capture=True,
                    check=False).stdout.split()
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


def harness_running(sudo):
    """Whether the harness is already up, so that a second run is a no-op."""
    return bool(docker(['ps', '-q', '--filter', 'name=^%s$' % HARNESS_NAME], sudo,
                       capture=True, check=False).stdout.split())


def harness_ready(address, timeout=180.0):
    """Wait until the harness answers.  Any answer counts, even a refusal: what is
    being waited for is that something is listening, not what it decides."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(address, timeout=3)
            return True
        except urllib.error.HTTPError:
            return True
        except OSError:
            time.sleep(1.0)
    return False


def open_page(address):
    """Hand the address to this machine's desktop, if it has one."""
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return False
    opener = shutil.which('xdg-open')
    return bool(opener) and subprocess.run([opener, address], check=False).returncode == 0


def start_harness(args):
    """Bring DeepSeek Harness up beside the deployment.

    It does not go through compose and it is not part of the competition: it is a
    separate container with its own volume, so that ``--down`` can take the
    deployment apart without taking the workbench with it.

    The image carries a small reverse proxy.  That is not decoration: this dsh
    refuses to bind anything but loopback, and a browser on a plain-HTTP address
    cannot reach the frontend's ``crypto.randomUUID``.  The proxy answers on
    0.0.0.0 inside the container and forwards to dsh's loopback, which is what
    makes an ordinary ``-p`` mapping work at all.
    """
    if harness_running(args.sudo):
        print('  已经在跑了，跳过。', flush=True)
    else:
        docker(['rm', '-f', HARNESS_NAME], args.sudo, check=False)
        if not docker(['images', '-q', HARNESS_IMAGE], args.sudo,
                      capture=True, check=False).stdout.strip():
            print('  先拉镜像（社区镜像，第一次要几分钟）。', flush=True)
            docker(['pull', HARNESS_IMAGE], args.sudo)
        docker(['run', '-d', '--name', HARNESS_NAME,
                '--restart', 'unless-stopped',
                # 只对宿主机的回环开放。想让它对局域网可见，把这个改成 3080:3080，
                # 并给代理配 PROXY_USERNAME/PROXY_PASSWORD。
                '-p', '127.0.0.1:%d:%d' % (HARNESS_PORT, HARNESS_PORT),
                '-v', '%s:/root/.dsh' % HARNESS_HOME,
                '-v', '%s:/workspace' % args.harness_dir,
                '-w', '/workspace',
                HARNESS_IMAGE], args.sudo, capture=True)
    address = 'http://127.0.0.1:%d/' % HARNESS_PORT
    if not harness_ready(address):
        print('  容器起来了但迟迟不应答，用 docker logs %s 看它怎么说。'
              % HARNESS_NAME, file=sys.stderr, flush=True)
        return
    print('  %s' % address, flush=True)
    if args.no_open:
        return
    if open_page(address):
        print('  已经在浏览器里打开了。', flush=True)
    else:
        print('  （这台机器没有桌面可开，自己开上面的地址。）', flush=True)


def stop_harness(sudo):
    """Take the container, keep the volume: the API key and the session history
    are in there, and neither is this script's to throw away."""
    docker(['rm', '-f', HARNESS_NAME], sudo, check=False)


def up_docker(args):
    probe = (['sudo'] if args.sudo else []) + ['docker', 'info']
    if subprocess.run(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        print('docker daemon 不可达。加 --sudo（daemon 权限不足），或者用 --local 在本机'
              '以普通进程跑同一套入口脚本。', file=sys.stderr, flush=True)
        return 1
    if args.fresh:
        print('== 丢掉上次的卷', flush=True)
        compose(['down', '-v'], args.sudo)
    if not args.no_build:
        print('== 构建镜像', flush=True)
        compose(['build'], args.sudo)
    print('== 起服务', flush=True)
    compose(['up', '-d'], args.sudo)
    if not args.no_deepseek:
        print('== 起 DeepSeek Harness', flush=True)
        start_harness(args)
    print('== 等两侧把演示跑完（最多 %ds）' % args.timeout, flush=True)
    codes = {service: wait_for_service(service, args.sudo, args.timeout) for service in DEMO}
    print('== 结果', flush=True)
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
        print('== 收摊', flush=True)
        compose(['down', '-v'], args.sudo)
        if not args.no_deepseek:
            stop_harness(args.sudo)
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
    parser.add_argument('--no-deepseek', action='store_true',
                        help='不起 DeepSeek Harness，只起竞赛这套')
    parser.add_argument('--no-open', action='store_true',
                        help='不要把 DeepSeek Harness 的地址扔给浏览器')
    parser.add_argument('--harness-dir', default=str(Path.home() / 'Projects'),
                        help='挂给 DeepSeek Harness 当工作区的宿主机目录（默认 ~/Projects）')
    parser.add_argument('--dir', default=None, help='--local 时的运行目录（默认 .runtime/deploy）')
    parser.add_argument('--port', type=int, default=8000, help='--local 时受信端入口端口')
    parser.add_argument('--timeout', type=float, default=600.0, help='等演示跑完的上限秒数')
    args = parser.parse_args(argv)
    print('这一套要 22 个端点凭据，其中 %d 个会起服务。' % (expected_manifest() - 3), flush=True)
    try:
        return up_local(args) if args.local else up_docker(args)
    except subprocess.CalledProcessError as exc:
        print('命令失败了：%s' % ' '.join(exc.cmd), file=sys.stderr, flush=True)
        if exc.output:
            print(exc.output.rstrip(), file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
