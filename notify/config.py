"""Configuration, logging, and state management."""

import fcntl
import json
import logging
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional


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

    with open(path) as f:
        config = yaml.safe_load(f)

    # Expand environment variables
    config = expand_env_vars(config)

    # Set defaults for settings
    if "settings" not in config:
        config["settings"] = {}

    settings = config["settings"]
    settings.setdefault("retry", {"max_attempts": 3, "delay_seconds": 5})
    settings.setdefault("state_file", "state/state.json")
    settings.setdefault("log_level", "INFO")
    settings.setdefault("then_and_now_enabled", True)
    settings.setdefault("then_and_now_min_gap", 3)
    settings.setdefault("then_and_now_slot", 0)  # 0 = auto (last memory slot)
    settings.setdefault("trip_highlights_enabled", True)
    settings.setdefault("then_and_now_cooldown_days", 7)
    settings.setdefault("trip_highlights_cooldown_days", 7)
    # Migrate old collage_year_range → year_range
    if "collage_year_range" in settings and "year_range" not in settings:
        settings["year_range"] = settings.pop("collage_year_range")
    settings.setdefault("year_range", 5)

    return config


# =============================================================================
# State Management (Skip if sent today)
# =============================================================================

def load_state(state_file: str) -> dict:
    """Load state from JSON file."""
    path = Path(state_file)
    if path.is_dir():
        raise RuntimeError(
            f"'{path}' is a directory, not a file — this is a Docker bind-mount artifact.\n"
            f"Fix: on the host run:  rm -rf {path} && mkdir -p {path.parent}"
        )
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
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


def was_sent_today(state: dict, user_name: str, target_date: date) -> bool:
    """Check if notification was already sent to user today."""
    date_str = target_date.isoformat()
    user_state = state.get("users", {}).get(user_name, {})
    return user_state.get("last_sent_date") == date_str


def mark_as_sent(state: dict, user_name: str, target_date: date):
    """Mark notification as sent for user."""
    date_str = target_date.isoformat()
    if "users" not in state:
        state["users"] = {}
    if user_name not in state["users"]:
        state["users"][user_name] = {}
    state["users"][user_name]["last_sent_date"] = date_str
    state["users"][user_name]["last_sent_time"] = datetime.now().isoformat()


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
