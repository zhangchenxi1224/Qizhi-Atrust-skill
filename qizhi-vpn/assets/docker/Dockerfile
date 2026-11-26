ARG ATRUST_BASE
FROM ${ATRUST_BASE}

RUN rm -f /etc/apt/apt.conf.d/docker-clean \
    && printf '%s\n' \
       'deb https://deb.debian.org/debian bookworm main' \
       'deb https://deb.debian.org/debian-security bookworm-security main' \
       > /etc/apt/sources.list
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends chromium curl

COPY chromium-launcher /usr/local/bin/chromium-launcher
COPY xdg-open /usr/bin/xdg-open
COPY start-local.sh /usr/local/bin/start-local.sh
COPY vpn-guard.sh /usr/local/bin/vpn-guard.sh
RUN chmod 755 /usr/local/bin/chromium-launcher /usr/bin/xdg-open /usr/local/bin/start-local.sh /usr/local/bin/vpn-guard.sh
CMD ["/usr/local/bin/start-local.sh"]
