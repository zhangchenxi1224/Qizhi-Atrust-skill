#!/bin/bash
# Keep connections opened by the HTTP proxy inside aTrust's network namespace.
# DNS and the local client helpers use loopback; replies to host clients are established.
set -eu
eval "$(detect-iptables.sh)"
proxy_uid=$(id -u daemon)
for table_cmd in iptables ip6tables; do
  "$table_cmd" -w -N SII_PROXY_EGRESS 2>/dev/null || true
  "$table_cmd" -w -F SII_PROXY_EGRESS
  "$table_cmd" -w -A SII_PROXY_EGRESS -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
  "$table_cmd" -w -A SII_PROXY_EGRESS -o lo -j RETURN
  "$table_cmd" -w -A SII_PROXY_EGRESS -o utun7 -j RETURN
  "$table_cmd" -w -A SII_PROXY_EGRESS -j REJECT
  "$table_cmd" -w -C OUTPUT -m owner --uid-owner "$proxy_uid" -j SII_PROXY_EGRESS 2>/dev/null ||
    "$table_cmd" -w -I OUTPUT 1 -m owner --uid-owner "$proxy_uid" -j SII_PROXY_EGRESS
done
