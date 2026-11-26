#!/bin/sh
unset CHROMIUM
/usr/local/bin/vpn-guard.sh || exit 1
/usr/local/bin/start.sh &
vpn_pid=$!
trap 'kill -TERM "$vpn_pid" 2>/dev/null; wait "$vpn_pid"' TERM INT
(
  export DISPLAY=:1
  attempt=0
  until xdpyinfo >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    [ "$attempt" -ge 90 ] && exit 1
    sleep 1
  done
  rm -f /root/.config/chromium/SingletonLock /root/.config/chromium/SingletonSocket /root/.config/chromium/SingletonCookie
  exec /usr/local/bin/chromium-launcher https://vpn.sii.edu.cn/
) >/tmp/chromium.log 2>&1 &
wait "$vpn_pid"
