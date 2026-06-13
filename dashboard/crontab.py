"""Crontab generation and scheduler reload for embedded crond."""

import logging
import os
import subprocess
from pathlib import Path

import yaml

ENV_FILE = "/app/.cron.env"

DEFAULT_CONFIG = {
    "immich": {
        "url": "${IMMICH_URL}",
        "external_url": "${IMMICH_EXTERNAL_URL}",
    },
    "ntfy": {
        "url": "${NTFY_URL}",
        "external_url": "${NTFY_EXTERNAL_URL}",
    },
    "users": [],
    "settings": {
        "retry": {"max_attempts": 3, "delay_seconds": 5},
        "state_file": "state/state.json",
        "log_level": "INFO",
        "memory_notifications": 3,
        "person_notifications": 2,
        "fallback_notifications": 4,
        "top_persons_limit": 5,
        "exclude_recent_days": 30,
        "include_location": True,
        "include_album": True,
        "video_emoji": True,
        "prefer_group_photos": True,
        "min_group_size": 2,
        "weekly_collage_enabled": True,
        "weekly_collage_day": 6,
        "weekly_collage_slots": 2,
        "collage_person_limit": 5,
        "year_range": 20,
        "collage_template": "random",
        "collage_album_name": "Weekly Highlights",
        "then_and_now_enabled": True,
        "then_and_now_min_gap": 3,
        "then_and_now_slot": 0,
        "then_and_now_cooldown_days": 7,
        "trip_highlights_enabled": True,
        "trip_highlights_cooldown_days": 7,
        "trip_highlights_min_photos": 5,
        "birthday_enabled": True,
        "notification_windows": [
            {"start": "08:00", "end": "09:00"},
            {"start": "10:00", "end": "12:00"},
            {"start": "13:00", "end": "15:00"},
            {"start": "17:00", "end": "19:00"},
            {"start": "20:00", "end": "22:00"},
        ],
    },
    "messages": [
        "A little trip back to {year}...",
        "Remember this day {years_ago} years ago?",
        "Some memories from {year} want to say hello",
        "Throwback to {year}! Take a moment to smile",
        "Once upon a time in {year}...",
        "A cozy memory from {years_ago} years ago",
        "{year} called, it has something beautiful to show you",
        "Let's revisit {year} together",
        "A gentle reminder of {year}",
        "Look what we found from {year}!",
    ],
    "person_messages": [
        "A lovely moment with {person_name}...",
        "Remember this time with {person_name}?",
        "A random treasure featuring {person_name}",
        "Look who we found! {person_name} says hello",
        "A cozy memory with {person_name}",
        "Here's a favorite moment with {person_name}",
        "{person_name} wanted to brighten your day",
        "Throwback featuring {person_name}!",
    ],
    "video_messages": [
        "Watch this moment from {year}...",
        "A video memory from {years_ago} years ago",
        "Relive this video from {year}",
        "Press play on {year}",
        "A moving memory from {years_ago} years ago",
    ],
    "video_person_messages": [
        "Watch this moment with {person_name}...",
        "A video featuring {person_name}",
        "Press play on this memory with {person_name}",
        "Relive this moment with {person_name}",
    ],
    "then_and_now_messages": [
        "Look how much {person_name} has changed! {then_year} vs {now_year}",
        "{gap} years between these moments with {person_name}",
        "Then and now — {person_name}, {gap} years apart",
        "Time flies... {person_name} in {then_year} and {now_year}",
        "From {then_year} to {now_year} with {person_name}",
    ],
    "trip_highlights_messages": [
        "{gap} years ago in {city}, {country}! \U0001f30d",
        "Remember this trip to {city}? Back in {year}!",
        "{city}, {country} — {gap} years have passed",
        "Flashback to {city}, {year} ✈️",
        "What a trip! {city}, {country} — {year}",
    ],
    "album_messages": [
        "A random moment from {album_name}",
        "Something from {album_name} to brighten your day",
        "From your {album_name} collection...",
        "A surprise from {album_name}!",
    ],
    "video_album_messages": [
        "Watch this clip from {album_name}...",
        "A video from your {album_name} album",
    ],
    "memory_titles": [
        "{years_ago} years ago today",
    ],
    "person_titles": [
        "A memory with {person_name}",
    ],
    "collage_titles": [
        "Weekly Highlights",
    ],
    "then_and_now_titles": [
        "Then & Now — {person_name}",
    ],
    "trip_highlights_titles": [
        "Trip Highlights",
    ],
    "album_titles": [
        "{album_name}",
    ],
    "birthday_messages": [
        "Happy Birthday, {person_name}! \U0001f382",
        "It's {person_name}'s special day! \U0001f389",
        "Wishing {person_name} a wonderful birthday! \U0001f381",
        "Cheers to {person_name} on their birthday! \U0001f973",
    ],
    "birthday_titles": [
        "Happy Birthday, {person_name}! \U0001f389",
    ],
}


def ensure_config(config_path: str = "/app/config.yaml"):
    """Create default config.yaml if it doesn't exist, so the dashboard can start."""
    path = Path(config_path)
    if path.is_file():
        return

    log = logging.getLogger("dashboard")

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
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    env[key] = value
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
