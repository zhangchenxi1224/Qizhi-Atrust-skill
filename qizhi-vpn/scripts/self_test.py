"""Offline regression checks. No live VPN or client configuration is changed."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import credentials
import prepare
import qizhi_vpn


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    root = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix='qizhi-vpn-tests-', dir=root) as folder:
        workspace = Path(folder).resolve()
        check(workspace.parent == root and workspace.name.startswith('qizhi-vpn-tests-'), 'Unexpected temporary path')
        args = SimpleNamespace(directory=str(workspace / 'docker'),
            base_image='hagb/docker-atrust@sha256:' + 'a' * 64,
            platform='linux/amd64', vpn_ip='59.78.86.21', cas_ip='59.78.86.22',
            http_port=18080, console_port=16080)
        prepare.prepare_docker(args)
        compose = json.loads((workspace / 'docker/compose.yaml').read_text())
        service = compose['services']['atrust']
        check(all(p.startswith('127.0.0.1:') for p in service['ports']), 'Port exposed outside loopback')
        check(not service.get('privileged') and service.get('network_mode') != 'host', 'Network isolation changed')
        check(service['environment']['HTTP_PROXY'] == '', 'Runtime proxy recursion risk')
        try:
            prepare.prepare_docker(args)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Existing deployment must not be overwritten')
        for address in ('127.0.0.1', '10.0.0.1', '198.18.0.1'):
            try:
                prepare.public_ip(address)
            except Exception:
                pass
            else:
                raise AssertionError('Private/fake gateway accepted')
        docker = qizhi_vpn.command_path('docker')
        if docker:
            result = subprocess.run([docker, 'compose', 'config', '--quiet'], cwd=workspace / 'docker', capture_output=True)
            check(result.returncode == 0, 'Generated Compose failed validation')
        node = shutil.which('node')
        if not node:
            raise RuntimeError('Node is required for routing invariant tests')
        source = (prepare.ASSETS / 'mihomo-overlay.js').read_text(encoding='utf-8')
        options = {'node': 'Qizhi-HTTP', 'group': 'Qizhi', 'port': 18080,
                   'gateways': {'vpn.sii.edu.cn': '59.78.86.21', 'cas.sii.edu.cn': '59.78.86.22'},
                   'externalFallback': None}
        javascript = r'''
const vm = require('vm'); const assert = require('assert');
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const baseline = {mode:'rule', proxies:[{name:'Outside',type:'ss',server:'example.test',password:'synthetic'}],
  'proxy-groups':[{name:'Choice',type:'select',proxies:['Outside','DIRECT']}],
  rules:['DOMAIN-SUFFIX,example.cn,DIRECT','GEOIP,CN,DIRECT','MATCH,Choice'],
  dns:{'fake-ip-filter':['localhost']}, hosts:{'example.test':'1.2.3.4'}};
function apply(settings, value) {
  const context = {value:structuredClone(value)};
  vm.createContext(context);
  vm.runInContext(input.source.replace('__QIZHI_OPTIONS__', JSON.stringify(settings)) + '\nvalue=main(value);', context);
  return JSON.parse(JSON.stringify(context.value));
}
const next = apply(input.options, baseline);
assert.deepStrictEqual(next.proxies[0],baseline.proxies[0]);
assert.deepStrictEqual(next['proxy-groups'][0],baseline['proxy-groups'][0]);
assert.equal(next['proxy-groups'].at(-1).url,'https://qz.sii.edu.cn/');
assert.equal(next['proxy-groups'].at(-1)['expected-status'],'200/302');
assert.deepStrictEqual(next.rules.slice(-baseline.rules.length),baseline.rules);
assert.equal(next.rules.filter(x=>x.startsWith('MATCH,')).length,1);
assert.deepStrictEqual(apply(input.options,next),next);
assert.equal(next.hosts['example.test'],'1.2.3.4');
const global = apply({...input.options,externalFallback:'Choice'}, {...baseline,mode:'global'});
assert.equal(global.mode,'rule');
assert(global.rules.indexOf('MATCH,Choice') > global.rules.indexOf('DOMAIN-SUFFIX,sii.edu.cn,Qizhi'));
assert.throws(()=>apply({...input.options,externalFallback:'Missing'},baseline));
assert.throws(()=>apply({...input.options,node:'Outside'},baseline));
assert.throws(()=>apply({...input.options,group:'Choice'},baseline));
const bound = structuredClone(next); bound.proxies.at(-1)['interface-name']='WLAN';
assert(!('interface-name' in apply(input.options,bound).proxies.at(-1)));
const stale = structuredClone(next); stale['proxy-groups'].at(-1).url='https://cp.cloudflare.com/generate_204';
assert.deepStrictEqual(apply(input.options,stale),next);
console.log('routing preservation, idempotency, Global handling, collision checks: passed');
'''
        script = workspace / 'routing-test.js'
        script.write_text(javascript, encoding='utf-8')
        result = subprocess.run([node, str(script)], input=json.dumps({'source':source, 'options':options}), capture_output=True, text=True)
        check(result.returncode == 0, result.stderr)
        print(result.stdout.strip())
        # A live controller failure must never be reported as verified routing.
        state = {'external_proxy':'http://127.0.0.1:7897', 'mihomo_config':'synthetic',
                 'node_name':'Qizhi-HTTP', 'group_name':'Qizhi'}
        probes = [{'exit_code':0, 'http_status':code} for code in ('302','204','200','200')]
        with patch.object(qizhi_vpn,'status',return_value={'status':'vpn_ready'}), \
             patch.object(qizhi_vpn,'mihomo_reader',side_effect=RuntimeError('unavailable')), \
             patch.object(qizhi_vpn,'curl_probe',side_effect=probes), \
             patch.object(qizhi_vpn,'state_dir',return_value=workspace / 'state'):
            result = qizhi_vpn.verify(state)
            check(result['status'] == 'connectivity_verified_needs_route_check', 'False-positive verification')
        if sys.platform == 'win32':
            value = b'synthetic credential test only'
            encrypted = credentials.dpapi(value)
            check(value not in encrypted and credentials.dpapi(encrypted,True) == value, 'DPAPI roundtrip failed')
        print('Compose, private gateways, controller failure, credential encryption: passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
