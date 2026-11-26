// Generate with scripts/prepare.py; compose with the user's existing extension.
const QIZHI = __QIZHI_OPTIONS__;
function main(config) {
  const desired = {name: QIZHI.node, type: 'http', server: '127.0.0.1', port: QIZHI.port};
  const old = (config.proxies || []).find(p => p.name === QIZHI.node);
  if (old && !(old.type === 'http' && old.server === '127.0.0.1' && old.port === QIZHI.port)) {
    throw new Error('Proxy name conflict: choose a unique Qizhi node name.');
  }
  config.proxies = (config.proxies || []).filter(p => p.name !== QIZHI.node).concat([desired]);
  config['proxy-groups'] = config['proxy-groups'] || [];
  let group = config['proxy-groups'].find(g => g.name === QIZHI.group);
  if (group && !(group.type === 'select' && JSON.stringify(group.proxies) === JSON.stringify([QIZHI.node]))) {
    throw new Error('Group name conflict: choose a unique Qizhi group name.');
  }
  if (!group) {
    group = {name: QIZHI.group, type: 'select', proxies: [QIZHI.node]};
    config['proxy-groups'].push(group);
  }
  group.url = 'https://qz.sii.edu.cn/';
  group['expected-status'] = '200/302';
  if (QIZHI.externalFallback) {
    const names = config.proxies.concat(config['proxy-groups']).map(p => p.name).concat(['DIRECT','REJECT']);
    if (!names.includes(QIZHI.externalFallback)) throw new Error('External fallback does not exist.');
  }
  const prefix = ['IP-CIDR,127.0.0.0/8,DIRECT,no-resolve','IP-CIDR6,::1/128,DIRECT,no-resolve'];
  for (const [host, ip] of Object.entries(QIZHI.gateways)) {
    prefix.push('DOMAIN,' + host + ',DIRECT');
    prefix.push((ip.includes(':') ? 'IP-CIDR6,' + ip + '/128' : 'IP-CIDR,' + ip + '/32') + ',DIRECT,no-resolve');
  }
  prefix.push('AND,((NETWORK,UDP),(DOMAIN-SUFFIX,sii.edu.cn)),REJECT');
  prefix.push('DOMAIN-SUFFIX,sii.edu.cn,' + QIZHI.group);
  if (QIZHI.externalFallback) prefix.push('MATCH,' + QIZHI.externalFallback);
  config.rules = prefix.concat((config.rules || []).filter(rule => !prefix.includes(rule)));
  config.mode = 'rule';
  config.dns = config.dns || {};
  config.dns['fake-ip-filter'] = Array.from(new Set((config.dns['fake-ip-filter'] || []).concat(Object.keys(QIZHI.gateways))));
  // Gateways are verified public addresses; avoid fake-IP collisions when establishing the tunnel.
  config.hosts = Object.assign({}, config.hosts || {}, QIZHI.gateways);
  return config;
}
