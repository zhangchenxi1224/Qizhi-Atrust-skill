"""Generate a fresh Docker project or a Mihomo overlay; never edit a live client config."""
import argparse
import ipaddress
import json
import re
from pathlib import Path
import secrets
import shutil

from credentials import private_dir

ASSETS = Path(__file__).resolve().parents[1] / 'assets'


def public_ip(value):
    address = ipaddress.ip_address(value)
    if not address.is_global:
        raise argparse.ArgumentTypeError('SII public gateway must not be a private, loopback or fake-IP address.')
    return str(address)


def prepare_docker(args):
    destination = Path(args.directory).expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError('Destination is not empty; adopt the existing deployment instead of overwriting it.')
    if not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', args.base_image):
        raise RuntimeError('Use an architecture-verified image reference pinned by SHA-256 digest.')
    private_dir(destination)
    for source in (ASSETS / 'docker').iterdir():
        if source.is_file():
            shutil.copyfile(source, destination / source.name)
    (destination / '.env').write_text('VNC_PASSWORD=' + secrets.token_urlsafe(6) + '\n', encoding='utf-8')
    try:
        (destination / '.env').chmod(0o600)
    except OSError:
        pass
    service = {
        'image': 'qizhi-atrust-local:v1', 'build': {'context': '.', 'args': {'ATRUST_BASE': args.base_image}},
        'platform': args.platform, 'container_name': 'sii-atrust', 'hostname': 'sii-atrust',
        'restart': 'unless-stopped', 'init': True,
        'devices': ['/dev/net/tun:/dev/net/tun'], 'cap_add': ['NET_ADMIN'],
        'sysctls': {'net.ipv4.conf.default.route_localnet': '1'},
        'environment': {'PASSWORD': '${VNC_PASSWORD:?VNC_PASSWORD is required}', 'USE_NOVNC': '1',
                        'VNC_SIZE': '1440x900', 'HTTP_PROXY': '', 'HTTPS_PROXY': '', 'ALL_PROXY': '',
                        'http_proxy': '', 'https_proxy': '', 'all_proxy': '',
                        'NO_PROXY': 'localhost,127.0.0.1,.sii.edu.cn', 'no_proxy': 'localhost,127.0.0.1,.sii.edu.cn'},
        'ports': ['127.0.0.1:' + str(args.http_port) + ':8888', '127.0.0.1:' + str(args.console_port) + ':8080'],
        'volumes': ['atrust-data:/root'], 'shm_size': '512m',
        'extra_hosts': {'vpn.sii.edu.cn': args.vpn_ip, 'cas.sii.edu.cn': args.cas_ip},
        'logging': {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '3'}}}
    compose = {'name': 'sii-atrust', 'services': {'atrust': service}, 'volumes': {'atrust-data': {}}}
    (destination / 'compose.yaml').write_text(json.dumps(compose, indent=2) + '\n', encoding='utf-8')
    (destination / '.gitignore').write_text('.env\nbackup*/\n*-private.*\n', encoding='utf-8')
    return {'prepared': str(destination), 'next': 'Inspect Debian base compatibility, then docker compose config --quiet and docker compose build.'}


def prepare_overlay(args):
    for value in (args.node_name, args.group_name, args.external_fallback or ''):
        if any(char in value for char in '\n\r,'):
            raise ValueError('Rule target names cannot contain commas or newlines.')
    settings = {'node': args.node_name, 'group': args.group_name, 'port': args.http_port,
                'gateways': {'vpn.sii.edu.cn': args.vpn_ip, 'cas.sii.edu.cn': args.cas_ip},
                'externalFallback': args.external_fallback}
    source = (ASSETS / 'mihomo-overlay.js').read_text(encoding='utf-8')
    source = source.replace('__QIZHI_OPTIONS__', json.dumps(settings, ensure_ascii=False))
    target = Path(args.output).expanduser().resolve()
    if target.exists():
        raise RuntimeError('Output already exists; choose a new candidate path.')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding='utf-8')
    return {'candidate': str(target), 'preserves_original_rules': args.external_fallback is None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    docker = commands.add_parser('docker')
    docker.add_argument('--directory', required=True)
    docker.add_argument('--base-image', required=True)
    docker.add_argument('--platform', required=True, choices=['linux/amd64', 'linux/arm64'])
    overlay = commands.add_parser('overlay')
    overlay.add_argument('--output', required=True)
    overlay.add_argument('--node-name', default='Qizhi-aTrust-HTTP')
    overlay.add_argument('--group-name', default='Qizhi-VPN')
    overlay.add_argument('--external-fallback', help='Only for preserving a previously GLOBAL effective egress; otherwise omit.')
    for child in (docker, overlay):
        child.add_argument('--vpn-ip', required=True, type=public_ip)
        child.add_argument('--cas-ip', required=True, type=public_ip)
        child.add_argument('--http-port', type=int, default=18080)
    docker.add_argument('--console-port', type=int, default=16080)
    args = parser.parse_args()
    if not 1 <= args.http_port <= 65535 or (args.command == 'docker' and
            (not 1 <= args.console_port <= 65535 or args.http_port == args.console_port)):
        parser.error('Ports must be distinct valid TCP ports.')
    print(json.dumps(prepare_docker(args) if args.command == 'docker' else prepare_overlay(args), ensure_ascii=False))


if __name__ == '__main__':
    main()
