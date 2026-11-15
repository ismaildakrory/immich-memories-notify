#!/bin/sh
# Runs as root only long enough to make bind-mounted files writable by the
# unprivileged `app` user, then drops privileges and hands over to start.sh.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    # Remap the app user to the requested uid/gid (lets host files stay owned by you)
    if [ "$(id -g app)" != "$PGID" ]; then
        delgroup app 2>/dev/null || true
        addgroup -g "$PGID" app 2>/dev/null || addgroup app
    fi
    if [ "$(id -u app)" != "$PUID" ]; then
        deluser app 2>/dev/null || true
        adduser -D -u "$PUID" -G app -h /app app 2>/dev/null || adduser -D -G app -h /app app
    fi

    # Writable runtime paths: state, config, secrets, scheduler files
    mkdir -p /app/state
    chown app:app /app /app/state 2>/dev/null || true
    for f in /app/config.yaml /app/.env /app/state/state.json /app/state/state.json.lock /app/config.yaml.lock /app/.env.lock; do
        [ -e "$f" ] && chown app:app "$f" 2>/dev/null || true
    done
    chown -R app:app /app/state 2>/dev/null || true

    # Legacy setups that still mount the Docker socket: grant the socket's group
    if [ -S /var/run/docker.sock ]; then
        sock_gid="$(stat -c '%g' /var/run/docker.sock)"
        if [ "$sock_gid" != "0" ]; then
            addgroup -g "$sock_gid" dockersock 2>/dev/null || true
            sock_group="$(getent group "$sock_gid" | cut -d: -f1)"
            [ -n "$sock_group" ] && addgroup app "$sock_group" 2>/dev/null || true
        else
            echo "[entrypoint] docker.sock is root-owned; prefer the docker-socket-proxy service (see docker-compose.yml)"
        fi
    fi

    exec su-exec app /app/start.sh
fi

exec /app/start.sh
