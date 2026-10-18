"""One command to start the deployment and watch it work.

``python -m competition.deploy.up``
    bring up the deployment, bring up DeepSeek Harness alongside it, wait for the
    two sides of the flow to finish, and print what they did.  Everything stays up
    afterwards; the deployment's door is on the host at 8080, the display page at
    8081, the harness at 3080.
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
import json
import os
import secrets
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
# The services that walk the agent flow: the gateway is served, and the two
# workbench callers the agent boundary used to hand work to are *not*, because
# the console drives those steps now.  Leaving them up would accept and execute
# every candidate before a person could look at it, which is exactly the thing
# the console is there to decide.  ``up --auto`` puts them back.
AGENT_SERVICES = ('endpoints', 'trusted', 'caddy', 'console', 'viewer', 'caller-observer',
                  'agent-gateway')
# The same deployment with the automatic workbench callers, for a run that is not
# meant to stop for a person.
AUTO_SERVICES = AGENT_SERVICES + ('agent-operator', 'agent-executor')
# The original core services, kept for --no-zjj and --local.  ``caller-h`` and
# ``caller-worker`` still walk their two sides, but they stop where a person has
# to answer, so they stop there.
CORE_SERVICES = ('endpoints', 'trusted', 'caddy', 'console', 'viewer', 'caller-observer',
                 'caller-h', 'caller-worker')
# The watcher that reads the observation face.  It drives no step, so its run is
# shown for its output and never counted against the demo.
OBSERVER = 'caller-observer'
# The display's gateway.  It serves the built page and carries the four read
# routes for the browser; it runs until the deployment is taken down, so it is
# shown and never waited on.
VIEWER = 'viewer'
VIEWER_PORT = 8081
DISPLAY = ROOT / 'competition' / 'display' / 'dist'
TOKEN_FILE = ROOT / '.runtime' / 'agent-tokens.json'
TOKEN_ENV = ROOT / '.runtime' / 'agent-tokens.env'
PLUGIN_DIR = ROOT / 'competition' / 'agent' / 'dsh-plugin'
BOOTSTRAP = ROOT / 'competition' / 'deploy' / 'harness-entrypoint.sh'

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
# The compose network the deployment's services share.  ``docker compose`` names
# it after the project, and the project is named after the file's directory
# (``competition/deploy`` -> ``deploy``).  The harness joins it so it can reach
# the gateway by service name; the gateway's published port stays on the host
# loopback, and nothing new is exposed.
HARNESS_NETWORK = 'deploy_default'


def load_tokens(await_approval=False):
    """Reuse or mint the two gateway tokens, and put them in this process's env.

    The agent token reaches dsh; the internal token reaches only the operator and
    executor on the compose network.  Neither is a role key.  Persisting them
    under ``.runtime`` keeps a re-run against an already-started dsh container
    consistent instead of rotating the token out from under it.  A small env file
    carries them to ``docker compose``: ``sudo`` resets the environment, so the
    compose interpolation reads this file instead of inheriting variables.  The
    same file carries whether the endpoints ask a person before they sign, for
    the same reason.
    """
    stored = {}
    try:
        stored = json.loads(TOKEN_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        stored = {}
    agent = os.environ.get('ZJJ_AGENT_TOKEN') or stored.get('agent') or secrets.token_urlsafe(32)
    internal = (os.environ.get('ZJJ_INTERNAL_TOKEN') or stored.get('internal')
                or secrets.token_urlsafe(32))
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({'agent': agent, 'internal': internal}), encoding='utf-8')
    os.chmod(TOKEN_FILE, 0o600)
    TOKEN_ENV.write_text(
        'ZJJ_AGENT_TOKEN=%s\nZJJ_INTERNAL_TOKEN=%s\nZJJ_AWAIT_APPROVAL=%s\n'
        % (agent, internal, '1' if await_approval else '0'), encoding='utf-8')
    os.chmod(TOKEN_ENV, 0o600)
    os.environ['ZJJ_AGENT_TOKEN'] = agent
    os.environ['ZJJ_INTERNAL_TOKEN'] = internal
    return agent, internal


def compose(args, sudo, *, capture=False, check=True):
    """One ``docker compose`` call against this deployment's file.

    The token env file is passed explicitly: with ``--sudo`` the compose process
    runs under a reset environment, so it cannot inherit the two token variables
    from this process.
    """
    argv = (['sudo'] if sudo else []) + ['docker', 'compose']
    if TOKEN_ENV.exists():
        argv += ['--env-file', str(TOKEN_ENV)]
    argv += ['-f', str(COMPOSE)] + list(args)
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


def harness_networks(sudo):
    """The networks the harness container is attached to."""
    text = docker(['inspect', '-f',
                   '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}',
                   HARNESS_NAME], sudo, capture=True, check=False).stdout
    return set(text.split())


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


def open_pages(addresses, no_open=False):
    """Hand the deployment's doors to this machine's desktop, if it has one.

    A person needs all of them at once -- the workbench where a candidate is
    proposed, the console where it is accepted and driven, and the display that
    shows the same projection -- so they open together rather than one per
    service.  A machine without a desktop, or one asked not to, is told the
    addresses instead.
    """
    if no_open:
        return False
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        print('  （这台机器没有桌面可开，自己开上面的地址。）', flush=True)
        return False
    opener = shutil.which('xdg-open')
    if not opener:
        print('  （没找到 xdg-open，自己开上面的地址。）', flush=True)
        return False
    for address in addresses:
        # A browser opener may keep running, or hand the address to something
        # that does, so waiting for it would hang the script after everything is
        # already up.  Detach it: the page opens, and the run continues -- and a
        # Ctrl-C afterwards does not reach it.
        subprocess.Popen([opener, address], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    print('  已经在浏览器里打开了。', flush=True)
    return True


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
    if harness_running(args.sudo) and (
            args.no_zjj or HARNESS_NETWORK in harness_networks(args.sudo)):
        print('  已经在跑了，跳过。', flush=True)
    else:
        if harness_running(args.sudo):
            # A container from before the harness joined the compose network
            # cannot reach the gateway by service name, and keeps reporting the
            # MCP server as disconnected even after the gateway is healthy.  Its
            # volume holds the sessions; the container is what has to be
            # recreated.
            print('  现有容器不在 %s 网络上，重建。' % HARNESS_NETWORK, flush=True)
        docker(['rm', '-f', HARNESS_NAME], args.sudo, check=False)
        if not docker(['images', '-q', HARNESS_IMAGE], args.sudo,
                      capture=True, check=False).stdout.strip():
            print('  先拉镜像（社区镜像，第一次要几分钟）。', flush=True)
            docker(['pull', HARNESS_IMAGE], args.sudo)
        argv = ['run', '-d', '--name', HARNESS_NAME,
                '--restart', 'unless-stopped',
                # 只对宿主机的回环开放。想让它对局域网可见，把这个改成 3080:3080，
                # 并给代理配 PROXY_USERNAME/PROXY_PASSWORD。
                '-p', '127.0.0.1:%d:%d' % (HARNESS_PORT, HARNESS_PORT),
                '-v', '%s:/root/.dsh' % HARNESS_HOME,
                '-v', '%s:/workspace' % args.harness_dir,
                '-w', '/workspace']
        if not args.no_zjj:
            # The harness reaches the gateway by service name on the compose
            # network.  ``host.docker.internal`` used to point at the host's
            # bridge address, but the gateway publishes on the host loopback
            # (``127.0.0.1:8090``), which that address cannot reach -- the MCP
            # client then reports the server as disconnected and the session has
            # no tools.  Joining the network keeps the published port loopback
            # only and still lets the harness reach it.
            token = os.environ.get('ZJJ_AGENT_TOKEN', '')
            if not token:
                # Starting without it would install no bundle and answer 401 on
                # every MCP call, which reads as "server disconnected" and is
                # hard to tell from a network fault.  Say it here instead.
                print('  ZJJ_AGENT_TOKEN 是空的，agent 侧不会安装（MCP 会 401）。'
                      '先用不带 --no-zjj 的 up 生成 token，再重建容器。',
                      file=sys.stderr, flush=True)
                return
            argv += [
                '--network', HARNESS_NETWORK,
                '-e', 'ZJJ_MCP_URL=http://agent-gateway:8090/mcp',
                '-e', 'ZJJ_GATEWAY_URL=http://agent-gateway:8090',
                '-e', 'ZJJ_AGENT_TOKEN=' + token,
                '-v', '%s:/opt/zjj-plugin:ro' % PLUGIN_DIR,
                '-v', '%s:/opt/zjj-entrypoint.sh:ro' % BOOTSTRAP,
                '--entrypoint', '/bin/sh',
            ]
        argv.append(HARNESS_IMAGE)
        if not args.no_zjj:
            argv.append('/opt/zjj-entrypoint.sh')
        docker(argv, args.sudo, capture=True)
    address = 'http://127.0.0.1:%d/' % HARNESS_PORT
    if not harness_ready(address):
        print('  容器起来了但迟迟不应答，用 docker logs %s 看它怎么说。'
              % HARNESS_NAME, file=sys.stderr, flush=True)
        return
    print('  %s' % address, flush=True)


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
    # Unconditional: the env file also carries whether the endpoints ask a person
    # before they sign, and that applies to the core demo too.
    load_tokens(args.await_approval)
    if args.fresh:
        print('== 丢掉上次的卷', flush=True)
        # The harness is attached to the compose network, so it has to go before
        # the network can be removed.  Its volume stays.
        stop_harness(args.sudo)
        compose(['down', '-v'], args.sudo)
    if not args.no_build:
        print('== 构建镜像', flush=True)
        compose(['build'], args.sudo)
    services = list(CORE_SERVICES if args.no_zjj
                    else (AUTO_SERVICES if args.auto else AGENT_SERVICES))
    if not args.no_zjj and not args.auto:
        # A previous run may have left the two workbench callers up, and ``up``
        # with an explicit service list does not stop what it was not asked
        # about.  Left running, they accept and execute every candidate before a
        # person can look at the console, which is the whole point of the pool.
        compose(['stop', 'agent-operator', 'agent-executor'], args.sudo, check=False)
    print('== 起服务（%s）' % ' '.join(services), flush=True)
    if 'trusted' in services:
        print('   控制台：http://127.0.0.1:8080/console/', flush=True)
    compose(['up', '-d', *services], args.sudo)
    if not args.no_deepseek:
        print('== 起 DeepSeek Harness', flush=True)
        start_harness(args)
    # The entry stops and waits: four of the six roles sign inside the chain it
    # assembles, and their endpoints park those signatures until a person
    # answers.  So running-but-not-healthy is the normal state here, and a failed
    # health check says nothing.  What matters is whether it *exited* -- and the
    # usual reason for that is a run directory that already holds a W, because
    # initialization happens once.
    code = wait_for_service('trusted', args.sudo, 5.0)
    if code is not None and code != 0:
        show('trusted', args.sudo)
        print('受信端退出了（%s）。若它说 run 目录里已有 W，那是初始化只能发生一次：'
              '要重新开始就加 --fresh。' % code, file=sys.stderr, flush=True)
        return 1
    print('== 服务都起来了', flush=True)
    show('trusted', args.sudo)
    if args.no_zjj:
        print('客户端控制台在 http://127.0.0.1:8080/console/，'
              '受信端入口在 http://127.0.0.1:8080/healthz。', flush=True)
    else:
        print('客户端控制台在 http://127.0.0.1:8080/console/；'
              'agent 网关在 http://127.0.0.1:8090/healthz（只对宿主回环）；'
              'DeepSeek Harness 在 http://127.0.0.1:%d/。' % HARNESS_PORT, flush=True)
    print('显示页在 http://127.0.0.1:%d/。' % VIEWER_PORT, flush=True)
    print('受信端初始化是脚本模拟（不代表真人同意），不会停在页面上。'
          '加 --await-approval 后，agent 每提交一条候选都要在控制台上放行'
          'G/U/V/X 的链内签名，否则候选进不来。', flush=True)
    if not args.no_zjj and not args.auto:
        print('agent 提交的候选会出现在控制台的「操作」里，接手后用提出方/执行方按钮'
              '逐个推进；没有人替你接受或执行（要自动用 --auto）。', flush=True)
    if not args.down:
        # Three doors, in the order the work goes: propose, accept and drive,
        # watch.  The harness is only there in agent mode.
        doors = []
        if not args.no_deepseek:
            doors.append('http://127.0.0.1:%d/' % HARNESS_PORT)
        doors.append('http://127.0.0.1:8080/console/')
        doors.append('http://127.0.0.1:%d/' % VIEWER_PORT)
        open_pages(doors, args.no_open)
    if args.down:
        print('== 收摊', flush=True)
        # Same reason as --fresh: detach the harness before removing the network.
        stop_harness(args.sudo)
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
    env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONUNBUFFERED': '1',
           'ZJJ_AWAIT_APPROVAL': '1' if args.await_approval else '0'}
    entry = 'http://127.0.0.1:%d' % args.port
    # 控制台在本机模式下直接托管页面：没有 caddy，端口取入口端口的下一个。
    page_port = args.port + 1
    page = ROOT / 'competition' / 'console' / 'frontend' / 'dist'
    children = []
    observer = None
    viewer = None
    try:
        print('[2/4] 起各角色端、受信端与控制台（它们自己的日志就在下面）', flush=True)
        children.append(spawn(['competition.deploy.endpoints'], env,
                              ZJJ_ENDPOINTS=str(endpoints), ZJJ_ENDPOINT_HOST='127.0.0.1'))
        children.append(spawn(['competition.deploy.trusted'], env,
                              ZJJ_RUN=str(root / 'run'), ZJJ_ENDPOINTS=str(endpoints),
                              ZJJ_CALLERS=str(callers / 'callers.jsonl'),
                              ZJJ_ENDPOINT_BASE='http://127.0.0.1',
                              ZJJ_ENTRY_HOST='127.0.0.1', ZJJ_ENTRY_PORT=str(args.port)))
        console_env = {'ZJJ_CALLERS': str(callers), 'ZJJ_ENTRY': entry,
                       'ZJJ_ENDPOINTS': 'http://127.0.0.1',
                       'ZJJ_OBSERVE': 'http://127.0.0.1:%d' % args.viewer_port,
                       'ZJJ_CONSOLE_HOST': '127.0.0.1', 'ZJJ_CONSOLE_PORT': str(page_port)}
        if page.is_dir():
            console_env['ZJJ_CONSOLE_DIST'] = str(page)
        children.append(spawn(['competition.console'], env, **console_env))
        print('[3/4] 起只读观察者。没有人替流程签字：受信端构造链时会停在', flush=True)
        print('      角色端等人，等的是页面上的放行。', flush=True)
        observer = spawn(['competition.deploy.observer'], env, capture=True,
                         ZJJ_NAME=OBSERVER, ZJJ_CALLERS=str(callers), ZJJ_ENTRY=entry)
        # The viewer runs whether or not the display page was built: its read
        # routes are what the console lists the instance's operations through,
        # and that list has nothing to do with whether a page is mounted at ``/``.
        viewer = spawn(['competition.deploy.viewer'], env,
                       ZJJ_NAME=OBSERVER, ZJJ_CALLERS=str(callers), ZJJ_ENTRY=entry,
                       ZJJ_VIEWER_PORT=str(args.viewer_port))
        if DISPLAY.is_dir():
            print('展示页在 http://127.0.0.1:%d/（只读）。' % args.viewer_port, flush=True)
        else:
            print('展示页还没构建：cd competition/display && npm install && npm run build；'
                  '构建好再跑本命令，就能在 http://127.0.0.1:%d/ 看到。'
                  '观察面本身已经在跑，控制台的「操作」走它。' % args.viewer_port, flush=True)

        if args.await_approval:
            print('[4/4] 初始化仍然自动；但 agent 每提交一条候选，都会在页面上停下，'
                  '等你放行 G/U/V/X 的链内签名：', flush=True)
            print('      http://127.0.0.1:%d/console/' % page_port, flush=True)
        else:
            print('[4/4] 受信端会自己初始化，候选进来也不问人（--await-approval 未开）。',
                  flush=True)
            print('      页面（H 与 worker 的九步）：http://127.0.0.1:%d/console/' % page_port,
                  flush=True)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            for child in children:
                if child.poll() not in (None, 0):
                    print('基础设施进程提前退出了', file=sys.stderr, flush=True)
                    return 1
            try:
                urllib.request.urlopen(entry + '/healthz', timeout=3)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print('等了 %d 秒，受信端还没起来。' % args.timeout, file=sys.stderr, flush=True)
            return 1

        print('', flush=True)
        print('受信端已经起来 —— 每个签名都是页面上的人放行的。', flush=True)
        print('流程还没走：用页面上的步骤按钮走 H 与 worker 的九步。', flush=True)
        print('页面 http://127.0.0.1:%d/console/；收摊按 Ctrl-C。运行目录：%s'
              % (page_port, root), flush=True)
        # The same two doors as the container deployment, on this mode's ports.
        open_pages(['http://127.0.0.1:%d/console/' % page_port,
                    'http://127.0.0.1:%d/' % args.viewer_port], args.no_open)
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print('收摊。', flush=True)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        if observer is not None and observer.poll() is None:
            observer.terminate()
        if viewer is not None and viewer.poll() is None:
            viewer.terminate()
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
        if observer is not None and observer.poll() is None:
            try:
                observer.wait(timeout=15)
            except subprocess.TimeoutExpired:
                observer.kill()
        if viewer is not None and viewer.poll() is None:
            try:
                viewer.wait(timeout=15)
            except subprocess.TimeoutExpired:
                viewer.kill()


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
    parser.add_argument('--no-zjj', action='store_true',
                        help='不接 agent 网关，只起原核心演示')
    parser.add_argument('--await-approval', action='store_true',
                        default=os.environ.get('ZJJ_AWAIT_APPROVAL', '0') == '1',
                        help='每次 agent 提交候选，都要在控制台上放行 G/U/V/X 的链内签名，'
                             '否则候选进不来；初始化仍然自动（也认 ZJJ_AWAIT_APPROVAL=1）')
    parser.add_argument('--auto', action='store_true',
                        help='agent 模式照旧起 operator/executor，让它们自动接受并执行，'
                             '不在控制台上等人')
    parser.add_argument('--no-open', action='store_true',
                        help='不要把 agent、控制台、显示页的地址扔给浏览器')
    parser.add_argument('--harness-dir', default=str(Path.home() / 'Projects'),
                        help='挂给 DeepSeek Harness 当工作区的宿主机目录（默认 ~/Projects）')
    parser.add_argument('--dir', default=None, help='--local 时的运行目录（默认 .runtime/deploy）')
    parser.add_argument('--port', type=int, default=8000, help='--local 时受信端入口端口')
    parser.add_argument('--viewer-port', type=int, default=8008,
                        help='--local 时观察页面网关的端口（docker 走 8081）')
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
