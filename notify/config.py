"""Configuration, logging, and state management."""

import fcntl
import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .defaults import ALL_EVENTS, DEPRECATED_SETTINGS, apply_setting_defaults, apply_template_defaults

# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging(level: str = "INFO", log_file: Optional[str] = None):
    """Configure logging with proper formatting."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    handlers = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    handlers.append(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        handlers.append(file_handler)

    logging.basicConfig(level=log_level, handlers=handlers)
    return logging.getLogger("immich-memories-notify")


# =============================================================================
# Configuration
# =============================================================================

def expand_env_vars(value):
    """Recursively expand environment variables in config values."""
    if isinstance(value, str):
        # Match ${VAR} or ${VAR:-default}
        pattern = r'\$\{([^}:]+)(?::-([^}]*))?\}'

        def replacer(match):
            var_name = match.group(1)
            default = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default)

        return re.sub(pattern, replacer, value)
    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file with environment variable expansion."""
    import yaml

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    # Shared lock (same lock file the dashboard uses) so we never read a
    # half-written config while the dashboard is saving. Falls back to an
    # unlocked read if the lock file can't be created (e.g. read-only dir).
    try:
        with open(str(path) + ".lock", "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_SH)
            try:
                with open(path) as f:
                    config = yaml.safe_load(f)
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)
    except OSError:
        with open(path) as f:
            config = yaml.safe_load(f)

    # Expand environment variables
    config = expand_env_vars(config)

    # Set defaults for settings
    if "settings" not in config or config["settings"] is None:
        config["settings"] = {}

    settings = config["settings"]
    # Migrate old collage_year_range → year_range
    if "collage_year_range" in settings and "year_range" not in settings:
        settings["year_range"] = settings.pop("collage_year_range")
    apply_setting_defaults(settings)
    apply_template_defaults(config)

    # Migrate windows: ensure each window has an 'events' list
    _migrate_window_events(config)

    # Default notification_service for users
    for user in config.get("users", []):
        user.setdefault("notification_service", "ntfy")

    return config


def _migrate_window_events(config: dict):
    """Add events field to windows that don't have it. Remove deprecated slot-count fields."""
    settings = config.get("settings", {})
    windows = settings.get("notification_windows", [])
    for i, window in enumerate(windows):
        if "events" not in window:
            # Window 1 used to send only memories whatever it listed: keep that for old configs
            window["events"] = ["memory"] if i == 0 else list(ALL_EVENTS)

    # Remove deprecated fields (they're no longer used by the engine)
    for old_field in DEPRECATED_SETTINGS:
        settings.pop(old_field, None)


def get_window_events(config: dict, slot: int) -> list:
    """Get enabled events list for a window (slot is 1-indexed)."""
    windows = config.get("settings", {}).get("notification_windows", [])
    if 0 < slot <= len(windows):
        return windows[slot - 1].get("events", list(ALL_EVENTS))
    return list(ALL_EVENTS)


# =============================================================================
# State Management (Skip if sent today)
# =============================================================================

def load_state(state_file: str) -> dict:
    """Load state from JSON file with shared lock."""
    path = Path(state_file)
    if path.is_dir():
        raise RuntimeError(
            f"'{path}' is a directory, not a file — this is a Docker bind-mount artifact.\n"
            f"Fix: on the host run:  rm -rf {path} && mkdir -p {path.parent}"
        )
    if path.exists():
        lock_path = Path(str(path) + ".lock")
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with open(lock_path, "w") as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_SH)
                try:
                    with open(path) as f:
                        return json.load(f)
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
        except json.JSONDecodeError:
            logging.getLogger("immich-memories-notify").warning(
                f"State file {path} is corrupted — starting with empty state"
            )
            return {}
        except IOError:
            return {}
    return {}


def save_state(state_file: str, state: dict):
    """Save state to JSON file (atomic write with file lock)."""
    path = Path(state_file)
    if path.is_dir():
        raise RuntimeError(
            f"'{path}' is a directory, not a file — this is a Docker bind-mount artifact.\n"
            f"Fix: on the host run:  rm -rf {path} && mkdir -p {path.parent}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(path) + ".lock")
    tmp_path = path.with_suffix(".tmp")
    with open(lock_path, "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            with open(tmp_path, "w") as f:
                json.dump(state, f, indent=2)
            tmp_path.replace(path)
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def get_slots_sent_today(state: dict, user_name: str, target_date: date) -> list:
    """Get list of slot numbers already sent today for user."""
    date_str = target_date.isoformat()
    user_state = state.get("users", {}).get(user_name, {})
    if user_state.get("slots_date") != date_str:
        return []
    return user_state.get("slots_sent", [])


def mark_slot_sent(state: dict, user_name: str, target_date: date, slot: int, asset_id: str = None):
    """Mark a specific slot as sent for user."""
    date_str = target_date.isoformat()
    if "users" not in state:
        state["users"] = {}
    if user_name not in state["users"]:
        state["users"][user_name] = {}

    user_state = state["users"][user_name]

    # Reset if new day
    if user_state.get("slots_date") != date_str:
        user_state["slots_date"] = date_str
        user_state["slots_sent"] = []
        user_state["assets_sent_today"] = []

    if slot not in user_state["slots_sent"]:
        user_state["slots_sent"].append(slot)

    if asset_id and asset_id not in user_state.get("assets_sent_today", []):
        if "assets_sent_today" not in user_state:
            user_state["assets_sent_today"] = []
        user_state["assets_sent_today"].append(asset_id)

    user_state["last_slot_time"] = datetime.now().isoformat()


def get_assets_sent_today(state: dict, user_name: str, target_date: date) -> set:
    """Get set of asset IDs already sent today for user."""
    date_str = target_date.isoformat()
    user_state = state.get("users", {}).get(user_name, {})
    if user_state.get("slots_date") != date_str:
        return set()
    return set(user_state.get("assets_sent_today", []))


def is_feature_ready(state: dict, user_name: str, feature_key: str, cooldown_days: int, target_date: date) -> bool:
    """Check if enough days have passed since last fire of a feature."""
    user_state = state.get("users", {}).get(user_name, {})
    last_date_str = user_state.get(feature_key)
    if not last_date_str:
        return True
    try:
        last_date = date.fromisoformat(last_date_str)
        return (target_date - last_date).days >= cooldown_days
    except ValueError:
        return True


def mark_feature_fired(state: dict, user_name: str, feature_key: str, target_date: date):
    """Record that a feature fired today."""
    if "users" not in state:
        state["users"] = {}
    if user_name not in state["users"]:
        state["users"][user_name] = {}
    state["users"][user_name][feature_key] = target_date.isoformat()


def was_special_sent_today(state: dict, user_name: str, target_date: date) -> bool:
    """Check if a special event (T&N/Trip/Collage) already fired today for this user."""
    user_state = state.get("users", {}).get(user_name, {})
    return user_state.get("special_sent_date") == target_date.isoformat()


def mark_special_sent_today(state: dict, user_name: str, target_date: date):
    """Record that a special event fired today for this user."""
    if "users" not in state:
        state["users"] = {}
    if user_name not in state["users"]:
        state["users"][user_name] = {}
    state["users"][user_name]["special_sent_date"] = target_date.isoformat()


# =============================================================================
# Longer-horizon repeat prevention
# =============================================================================

def get_recent_assets(state: dict, user_name: str, target_date: date, repeat_days: int) -> set:
    """Asset IDs sent to this user within the last `repeat_days` days (0 disables)."""
    if not repeat_days:
        return set()
    recent = state.get("users", {}).get(user_name, {}).get("assets_sent_recent", {})
    out = set()
    for asset_id, sent_str in recent.items():
        try:
            if (target_date - date.fromisoformat(sent_str)).days < repeat_days:
                out.add(asset_id)
        except (ValueError, TypeError):
            continue
    return out


MAX_SENT_HISTORY = 5000   # per user; ~3 years at 4 notifications/day
MAX_HISTORY_RECORDS = 500  # per user; shown in the dashboard History tab


def mark_asset_sent_recent(state: dict, user_name: str, target_date: date, asset_id: str, repeat_days: int = None):
    """Record an asset as sent. Entries are kept (oldest pruned past MAX_SENT_HISTORY) so
    `get_ever_sent_assets` can steer picks toward photos never shown before."""
    if not asset_id:
        return
    user_state = state.setdefault("users", {}).setdefault(user_name, {})
    recent = user_state.setdefault("assets_sent_recent", {})
    recent[asset_id] = target_date.isoformat()
    if len(recent) > MAX_SENT_HISTORY:
        for key in sorted(recent, key=lambda k: recent[k])[: len(recent) - MAX_SENT_HISTORY]:
            del recent[key]


def get_ever_sent_assets(state: dict, user_name: str) -> set:
    """Every asset ID this user has ever been sent (bounded by MAX_SENT_HISTORY)."""
    return set(state.get("users", {}).get(user_name, {}).get("assets_sent_recent", {}))


def append_history(state: dict, user_name: str, record: dict):
    """Append a sent-notification record for the dashboard History tab (newest last, bounded)."""
    user_state = state.setdefault("users", {}).setdefault(user_name, {})
    history = user_state.setdefault("history", [])
    history.append(record)
    if len(history) > MAX_HISTORY_RECORDS:
        del history[: len(history) - MAX_HISTORY_RECORDS]


# =============================================================================
# Context themes and memory lanes
# =============================================================================

MAX_TRACKED_LANES = 50  # per user; lanes are deleted after lane_keep_days, this only bounds a stuck backlog


def get_context_last_used(state: dict, user_name: str) -> dict:
    """{theme: ISO date} of the last time each context theme was sent to this user."""
    return dict(state.get("users", {}).get(user_name, {}).get("context_last_used", {}))


def mark_context_used(state: dict, user_name: str, theme: str, target_date: date):
    """Record that a context theme was sent today."""
    user_state = state.setdefault("users", {}).setdefault(user_name, {})
    user_state.setdefault("context_last_used", {})[theme] = target_date.isoformat()


def get_lane_ids(state: dict, user_name: str) -> set:
    """Ids of the memory lanes this app created for the user (still tracked)."""
    return {lane.get("id") for lane in state.get("users", {}).get(user_name, {}).get("lanes", [])}


def record_lane(state: dict, user_name: str, memory_id: str, target_date: date):
    """Remember a memory lane created by this app so it can be cleaned up later."""
    user_state = state.setdefault("users", {}).setdefault(user_name, {})
    lanes = user_state.setdefault("lanes", [])
    lanes.append({"id": memory_id, "created": target_date.isoformat()})
    del lanes[:-MAX_TRACKED_LANES]


# =============================================================================
# Run markers (missed-run recovery)
# =============================================================================
#
# state["runs"] = {"YYYY-MM-DD": {"<slot>": {"started": iso, "done": bool}}}
# A slot run marks itself "started" before its random delay and "done" after
# processing. `--catch-up` uses these to find windows that never ran (container
# was down at the cron time) or died mid-delay.

RUN_MARKER_KEEP_DAYS = 3


def get_run_marker(state: dict, target_date: date, slot: int) -> Optional[dict]:
    return state.get("runs", {}).get(target_date.isoformat(), {}).get(str(slot))


def mark_run_started(state: dict, target_date: date, slot: int, now: datetime = None):
    runs = state.setdefault("runs", {})
    runs.setdefault(target_date.isoformat(), {})[str(slot)] = {
        "started": (now or datetime.now()).isoformat(timespec="seconds"),
        "done": False,
    }
    for day in list(runs):
        try:
            if (target_date - date.fromisoformat(day)).days >= RUN_MARKER_KEEP_DAYS:
                del runs[day]
        except (ValueError, TypeError):
            del runs[day]


def mark_run_done(state: dict, target_date: date, slot: int):
    marker = state.setdefault("runs", {}).setdefault(target_date.isoformat(), {}).setdefault(str(slot), {})
    marker["done"] = True


def slots_due_for_catch_up(windows: list, state: dict, now: datetime, max_late_hours: float = 3.0) -> list:
    """Return 1-indexed slots that should run now because their scheduled run never completed.

    A slot is due when its window has started today, it is not marked done, and
    either no run was started (cron never fired) or the started run is past
    the window end (the process died while waiting). Windows whose end is more
    than `max_late_hours` ago are left alone — nobody wants four stale
    notifications at once after a day-long outage.
    """
    due = []
    today = now.date()
    for idx, window in enumerate(windows, 1):
        try:
            sh, sm = map(int, window["start"].split(":"))
            eh, em = map(int, window["end"].split(":"))
        except (KeyError, ValueError, AttributeError):
            continue
        start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
        if end <= start:
            end = end + timedelta(days=1)
        if now < start:
            continue
        if (now - end).total_seconds() > max_late_hours * 3600:
            continue
        marker = get_run_marker(state, today, idx)
        if marker and marker.get("done"):
            continue
        if marker and now <= end:
            continue  # a run is still sleeping out its random delay
        due.append(idx)
    return due
