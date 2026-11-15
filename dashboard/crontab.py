"""Crontab generation and scheduler reload for embedded crond."""

import logging
import os
import subprocess
from pathlib import Path

import yaml

from notify.defaults import build_default_config

from .utils.envfile import parse_env_line

ENV_FILE = "/app/.cron.env"

# Written on first start when config.yaml is missing/empty. Defaults live in notify/defaults.py.
DEFAULT_CONFIG = build_default_config()


def ensure_config(config_path: str = "/app/config.yaml"):
    """Create default config.yaml if it doesn't exist or is empty, so the dashboard can start."""
    path = Path(config_path)
    log = logging.getLogger("dashboard")

    if path.is_file():
        # An empty file (e.g. created with `touch config.yaml` for the Docker
        # bind mount) still needs the default config, otherwise there are no
        # notification windows and the scheduler never fires.
        try:
            with open(path) as f:
                if yaml.safe_load(f) is not None:
                    return
        except yaml.YAMLError:
            log.warning(f"{config_path} contains invalid YAML — leaving it untouched")
            return
        log.info("config.yaml is empty — writing default configuration")
    else:
        # Docker bind-mount creates an empty directory when the source file is missing on the host.
        # That directory is a mount point and can't be removed from inside the container.
        if path.is_dir():
            log.error(
                f"{config_path} is a directory (Docker bind-mount without source file). "
                "Create the file on the host first: touch config.yaml"
            )
            return
        log.info("config.yaml not found — creating default configuration for first-run wizard")

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def dump_env():
    """Save current environment to a file that cron jobs can source.

    Merges os.environ with the .env file so that secrets added through the
    dashboard after container startup are available to cron jobs.
    """
    env = dict(os.environ)

    env_path = os.environ.get("ENV_PATH", "/app/.env")
    try:
        with open(env_path) as f:
            for line in f:
                parsed = parse_env_line(line)
                if parsed and parsed[0]:
                    env[parsed[0]] = parsed[1]
    except FileNotFoundError:
        pass

    with open(ENV_FILE, "w") as f:
        for key, value in env.items():
            if key in ("PWD", "SHLVL", "_", "HOSTNAME"):
                continue
            value = value.replace("'", "'\\''")
            f.write(f"export {key}='{value}'\n")


def generate_crontab(config_path: str = "/app/config.yaml"):
    """Generate /etc/crontabs/root from config.yaml notification windows."""
    ensure_config(config_path)
    dump_env()
    path = Path(config_path)
    if path.is_file():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}
    windows = config.get("settings", {}).get("notification_windows", [])
    prefix = f". {ENV_FILE} && cd /app"
    with open("/etc/crontabs/root", "w") as f:
        for i, w in enumerate(windows, 1):
            h, m = w.get("start", "08:00").split(":")
            f.write(f"{int(m)} {int(h)} * * * {prefix} && python -m notify --slot {i} >> /proc/1/fd/1 2>&1\n")
        f.write(f"0 6 * * * {prefix} && python -m notify --check-updates >> /proc/1/fd/1 2>&1\n")


def reload_scheduler(config_path: str = "/app/config.yaml"):
    """Regenerate crontab and restart crond."""
    generate_crontab(config_path)
    subprocess.run(["killall", "crond"], check=False)
    subprocess.run(["crond", "-l", "2"], check=False)
