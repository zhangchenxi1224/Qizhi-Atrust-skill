"""Inspect, register, start and verify a local Docker-isolated SII aTrust deployment."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

from credentials import private_dir, state_dir, status as credential_status

SKILL = Path(__file__).resolve().parents[1]
PLATFORM_URL = 'https://qz.sii.edu.cn/'


def run(args, timeout=20, cwd=None):
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(args, 127, '', 'command_unavailable_or_timed_out')


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def read_state():
    path = state_dir() / 'state.json'
    if not path.exists():
        raise RuntimeError('not_configured: run doctor and follow references/setup.md')
    return json.loads(path.read_text(encoding='utf-8'))


def write_state(value):
    private_dir(state_dir())
    path = state_dir() / 'state.json'
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    if sys.platform != 'win32':
        path.chmod(0o600)


def command_path(name):
    found = shutil.which(name)
    if found:
        return found
    if name == 'docker' and sys.platform == 'win32':
        path = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Docker/Docker/resources/bin/docker.exe'
        if path.exists():
            return str(path)
    if name == 'docker' and sys.platform == 'darwin':
        path = Path('/Applications/Docker.app/Contents/Resources/bin/docker')
        if path.exists():
            return str(path)
    return None


def available_port(port):
    with socket.socket() as listener:
        try:
            listener.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def doctor():
    clients = []
    if sys.platform == 'win32':
        script = r"""
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$roots = @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')
Get-ItemProperty $roots -ErrorAction SilentlyContinue |
Where-Object { $_.DisplayName -match 'Clash|Mihomo|aTrust|Sangfor|Surge|v2ray|sing.box|Docker|VPN' } |
Select-Object DisplayName,DisplayVersion,InstallLocation | ConvertTo-Json -Compress
"""
        response = run(['powershell.exe', '-NoProfile', '-Command', script])
        try:
            clients = json.loads(response.stdout) if response.stdout.strip() else []
            if isinstance(clients, dict):
                clients = [clients]
        except ValueError:
            clients = []
        config_roots = [Path(os.environ['APPDATA']) / 'io.github.clash-verge-rev.clash-verge-rev']
    else:
        if sys.platform == 'darwin':
            for folder in (Path('/Applications'), Path.home() / 'Applications'):
                for app in folder.glob('*.app'):
                    if any(word in app.name.lower() for word in ('clash', 'surge', 'stash', 'mihomo', 'vpn', 'atrust', 'docker', 'orbstack')):
                        clients.append({'name': app.name, 'path': str(app)})
            config_roots = [Path.home() / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev']
        else:
            config_roots = [Path.home() / '.local/share/io.github.clash-verge-rev.clash-verge-rev']
        config_roots += [Path.home() / '.config/clash', Path.home() / '.config/mihomo']
    docker = command_path('docker')
    info = run([docker, 'info', '--format', '{{json .ServerVersion}}']) if docker else None
    context = run([docker, 'context', 'show']).stdout.strip() if docker else None
    candidates = []
    for root in config_roots:
        if root.exists():
            candidates.append(str(root))
    recorded = None
    try:
        recorded = read_state()
    except RuntimeError:
        pass
    return {'os': platform.system(), 'architecture': platform.machine(),
            'software': clients, 'config_candidates': candidates,
            'commands': {name: command_path(name) for name in ('docker', 'curl', 'node', 'winget', 'brew', 'mihomo', 'clash', 'sing-box')},
            'docker_engine_ready': bool(info and info.returncode == 0), 'docker_context': context,
            'home_free_gb': round(shutil.disk_usage(Path.home()).free / 2**30, 2),
            'ports_free': {str(p): available_port(p) for p in (18080, 16080)},
            'recorded_deployment': recorded, 'credentials': credential_status()}


def curl_probe(url, proxy):
    curl = command_path('curl')
    if not curl:
        return {'host': urllib.parse.urlsplit(url).hostname, 'status': 'curl_missing'}
    response = run([curl, '--silent', '--show-error', '--noproxy', '', '--proxy', proxy,
                    '--connect-timeout', '5', '--max-time', '12', '-o', os.devnull,
                    '-w', '%{http_code}', url], timeout=16)
    return {'host': urllib.parse.urlsplit(url).hostname, 'http_status': response.stdout.strip(),
            'exit_code': response.returncode}


def mihomo_reader(state):
    path = state.get('mihomo_config')
    if not path:
        return None
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError('PyYAML is needed to inspect this Mihomo configuration; install it in a task venv.') from exc
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    controller = config.get('external-controller', '')
    if not controller:
        raise RuntimeError('Mihomo external-controller is not configured.')
    if controller.startswith('0.0.0.0:'):
        controller = '127.0.0.1:' + controller.rsplit(':', 1)[1]
    url = 'http://' + controller
    if urllib.parse.urlsplit(url).hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise RuntimeError('Only a local Mihomo controller is supported by this helper.')
    headers = {'Authorization': 'Bearer ' + config.get('secret', '')}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def api(path):
        with opener.open(urllib.request.Request(url + path, headers=headers), timeout=3) as response:
            return json.load(response)
    return api


def status(state, probes=True):
    docker = command_path('docker')
    if not docker:
        return {'status': 'docker_missing', 'next': 'references/setup.md'}
    engine = run([docker, 'info', '--format', '{{.ServerVersion}}'])
    if engine.returncode:
        return {'status': 'docker_stopped'}
    context = run([docker, 'context', 'show']).stdout.strip()
    if state.get('docker_context') and context != state['docker_context']:
        return {'status': 'docker_context_changed', 'current_context': context,
                'expected_context': state['docker_context']}
    inspected = run([docker, 'inspect', '--format', '{{.State.Status}}', state['container']])
    result = {'status': 'container_missing' if inspected.returncode else inspected.stdout.strip(),
              'console': state['console'], 'proxy': state['atrust_proxy']}
    if result['status'] == 'running' and probes:
        result['protected_probe'] = curl_probe(PLATFORM_URL, state['atrust_proxy'])
        probe = result['protected_probe']
        result['status'] = 'vpn_ready' if probe.get('exit_code') == 0 and probe.get('http_status') in ('200', '302', '303', '307', '308') else 'needs_login_or_diagnosis'
    return result


def start(state):
    docker = command_path('docker')
    if not docker:
        return {'status': 'docker_missing', 'next': 'Agent should install Docker following references/setup.md.'}
    if run([docker, 'info', '--format', '{{.ServerVersion}}'], timeout=6).returncode:
        if sys.platform in ('win32', 'darwin'):
            launched = run([docker, 'desktop', 'start', '--detach'], timeout=20)
            if launched.returncode:
                if sys.platform == 'darwin':
                    run(['open', '-g', '-a', 'Docker'])
                else:
                    desktop = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Docker/Docker/Docker Desktop.exe'
                    if desktop.exists():
                        startup = subprocess.STARTUPINFO()
                        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startup.wShowWindow = 0
                        subprocess.Popen([str(desktop)], startupinfo=startup, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return {'status': 'docker_stopped', 'next': 'Start the existing Docker service using available permissions.'}
        for _ in range(12):
            if run([docker, 'info', '--format', '{{.ServerVersion}}'], timeout=2).returncode == 0:
                break
            time.sleep(1)
        else:
            return {'status': 'docker_starting_or_needs_attention', 'next': 'Inspect Docker Desktop; rerun status after initialization.'}
    context = run([docker, 'context', 'show']).stdout.strip()
    if state.get('docker_context') and context != state['docker_context']:
        return {'status': 'docker_context_changed', 'current_context': context,
                'expected_context': state['docker_context']}
    exists = run([docker, 'inspect', '--format', '{{.State.Status}}', state['container']])
    if exists.returncode == 0:
        if exists.stdout.strip() != 'running':
            response = run([docker, 'compose', 'start', 'atrust'], cwd=state['deployment_dir'], timeout=30)
        else:
            response = subprocess.CompletedProcess([], 0)
    else:
        response = run([docker, 'compose', 'up', '-d'], cwd=state['deployment_dir'], timeout=45)
    if response.returncode:
        return {'status': 'container_start_failed', 'next': 'Inspect compose ps and bounded, redacted logs.'}
    return status(state)


def verify(state):
    result = {'vpn': status(state), 'external_proxy': state.get('external_proxy')}
    if not state.get('external_proxy'):
        result['status'] = 'external_proxy_not_configured'
        return result
    targets = [PLATFORM_URL, 'https://www.google.com/generate_204', 'https://github.com/', 'https://chatgpt.com/']
    seen, stopped = set(), threading.Event()
    api = None
    try:
        api = mihomo_reader(state)
        if api:
            result['mode'] = api('/configs')['mode']
    except Exception as exc:
        result['controller_check'] = type(exc).__name__
    def watch():
        hosts = {urllib.parse.urlsplit(url).hostname for url in targets}
        while not stopped.is_set():
            try:
                for conn in api('/connections').get('connections', []):
                    host = conn.get('metadata', {}).get('host')
                    if host in hosts:
                        seen.add((host, tuple(conn.get('chains', [])), conn.get('rule', '')))
            except Exception:
                pass
            stopped.wait(0.15)
    thread = threading.Thread(target=watch, daemon=True) if api else None
    if thread:
        thread.start()
    try:
        result['probes'] = [curl_probe(url, state['external_proxy']) for url in targets]
    finally:
        stopped.set()
        if thread:
            thread.join(timeout=4)
    result['connections'] = [{'host': h, 'chains': list(c), 'rule': r} for h,c,r in sorted(seen)]
    expected = [('200','302','303','307','308'), ('204',), ('200',), ('200',)]
    successful = all(p.get('exit_code') == 0 and p.get('http_status') in allowed for p,allowed in zip(result['probes'], expected))
    sii_chain_ok = any(c['host'] == 'qz.sii.edu.cn' and state['node_name'] in c['chains'] for c in result['connections'])
    result['connectivity_ok'] = successful
    result['sii_route_observed'] = sii_chain_ok if api else 'inspect_client_manually'
    outside = [c for c in result['connections'] if c['host'] != 'qz.sii.edu.cn']
    external_route_ok = len({c['host'] for c in outside}) >= 2 and all(
        state['node_name'] not in c['chains'] and state['group_name'] not in c['chains']
        for c in outside)
    result['external_routes_observed'] = external_route_ok
    if successful and result['vpn']['status'] == 'vpn_ready':
        result['status'] = 'verified' if api and sii_chain_ok and external_route_ok and result.get('mode') == 'rule' else 'connectivity_verified_needs_route_check'
    else:
        result['status'] = 'needs_attention'
    private_dir(state_dir())
    (state_dir() / 'last-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    sub.add_parser('start')
    sub.add_parser('verify')
    status_cmd = sub.add_parser('status')
    status_cmd.add_argument('--no-probes', action='store_true')
    reg = sub.add_parser('register')
    reg.add_argument('--deployment-dir', required=True)
    reg.add_argument('--container', default='sii-atrust')
    reg.add_argument('--http-port', type=int, default=18080)
    reg.add_argument('--console-port', type=int, default=16080)
    reg.add_argument('--external-proxy', required=True)
    reg.add_argument('--client', required=True)
    reg.add_argument('--mihomo-config')
    reg.add_argument('--node-name', default='SII-aTrust')
    reg.add_argument('--group-name', default='Qizhi-Compute')
    args = parser.parse_args()
    try:
        if args.command == 'doctor':
            result = doctor()
        elif args.command == 'register':
            directory = Path(args.deployment_dir).expanduser().resolve()
            if not any((directory / filename).is_file() for filename in ('compose.yaml', 'compose.yml', 'compose.json')):
                raise RuntimeError('No compose file found in deployment directory.')
            parsed = urllib.parse.urlsplit(args.external_proxy)
            if parsed.scheme not in ('http', 'https', 'socks5', 'socks5h') or parsed.username or parsed.password:
                raise RuntimeError('Use a proxy URL without embedded credentials.')
            docker = command_path('docker')
            value = {'version': 1, 'deployment_dir': str(directory), 'container': args.container,
                     'docker_context': run([docker, 'context', 'show']).stdout.strip() if docker else None,
                     'atrust_proxy': 'http://127.0.0.1:' + str(args.http_port),
                     'console': 'http://127.0.0.1:' + str(args.console_port) + '/',
                     'external_proxy': args.external_proxy, 'client': args.client,
                     'mihomo_config': str(Path(args.mihomo_config).resolve()) if args.mihomo_config else None,
                     'node_name': args.node_name, 'group_name': args.group_name,
                     'credential_service': 'qizhi-vpn.sii.edu.cn'}
            write_state(value)
            result = {'status': 'registered', 'state_file': str(state_dir() / 'state.json')}
        else:
            state = read_state()
            result = status(state, not args.no_probes) if args.command == 'status' else start(state) if args.command == 'start' else verify(state)
        output(result)
        return 0
    except Exception as exc:
        output({'status': 'error', 'error': type(exc).__name__, 'message': str(exc)})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
