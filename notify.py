#!/usr/bin/env python3
"""
Immich Memories Notify
======================
Sends daily memory notifications to all configured users.

Usage:
    python notify.py                 # Send notifications for today
    python notify.py --test          # Test mode (uses any available date)
    python notify.py --dry-run       # Show what would be sent without sending
    python notify.py --force         # Force send even if already sent today
    python notify.py --config FILE   # Use custom config file
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict
from typing import Optional, List

import requests
import yaml


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
    settings.setdefault("state_file", "state.json")
    settings.setdefault("log_level", "INFO")

    return config


# =============================================================================
# State Management (Skip if sent today)
# =============================================================================

def load_state(state_file: str) -> dict:
    """Load state from JSON file."""
    path = Path(state_file)
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_state(state_file: str, state: dict):
    """Save state to JSON file."""
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


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


# =============================================================================
# Retry Logic
# =============================================================================

def with_retry(func, max_attempts: int = 3, delay: int = 5, logger=None):
    """Execute function with retry logic."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as e:
            last_error = e
            if logger:
                logger.warning(f"Attempt {attempt}/{max_attempts} failed: {e}")
            if attempt < max_attempts:
                time.sleep(delay)
    raise last_error


# =============================================================================
# Immich API
# =============================================================================

def fetch_memories(immich_url: str, api_key: str, timeout: int = 10) -> list:
    """Fetch all memories from Immich API."""
    headers = {"Accept": "application/json", "x-api-key": api_key}
    response = requests.get(f"{immich_url}/api/memories", headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def filter_todays_memories(memories: list, target_date: date = None) -> list:
    """Filter memories for a specific date."""
    if target_date is None:
        target_date = date.today()
    target_str = target_date.isoformat()
    return [m for m in memories if m.get("showAt", "").startswith(target_str)]


def parse_memories(memories: list) -> dict:
    """Parse memories into a structured format."""
    result = {
        "total_assets": 0,
        "image_count": 0,
        "video_count": 0,
        "years": [],
        "by_year": defaultdict(lambda: {"images": 0, "videos": 0, "assets": []}),
        "first_asset_id": None,
    }

    for memory in memories:
        year = memory.get("data", {}).get("year")
        if not year:
            continue

        for asset in memory.get("assets", []):
            asset_id = asset.get("id")
            asset_type = asset.get("type", "IMAGE")

            if asset_id:
                result["by_year"][year]["assets"].append(asset)
                if result["first_asset_id"] is None:
                    result["first_asset_id"] = asset_id

                result["total_assets"] += 1
                if asset_type == "VIDEO":
                    result["video_count"] += 1
                    result["by_year"][year]["videos"] += 1
                else:
                    result["image_count"] += 1
                    result["by_year"][year]["images"] += 1

    result["years"] = sorted(result["by_year"].keys(), reverse=True)
    result["by_year"] = dict(result["by_year"])
    return result


def format_notification_for_year(
    year: int,
    year_data: dict,
    messages: List[str],
    test_mode: bool = False,
) -> dict:
    """Format notification for a single year using random message from config."""
    if not year_data.get("assets"):
        return {"title": None, "message": None, "has_content": False, "asset_id": None}

    years_ago = date.today().year - year

    # Select random message and format it
    if messages:
        message_template = random.choice(messages)
        message = message_template.format(year=year, years_ago=years_ago)
    else:
        message = f"You have memories from {year}!"

    title = f"Memories from {year}"
    if test_mode:
        title = "[TEST] " + title

    # Get first asset for thumbnail
    first_asset_id = year_data["assets"][0].get("id") if year_data["assets"] else None

    return {
        "title": title,
        "message": message,
        "has_content": True,
        "asset_id": first_asset_id,
    }


def fetch_thumbnail(immich_url: str, api_key: str, asset_id: str, timeout: int = 30) -> bytes:
    """Fetch thumbnail image from Immich."""
    headers = {"x-api-key": api_key}
    url = f"{immich_url}/api/assets/{asset_id}/thumbnail"
    response = requests.get(url, headers=headers, params={"size": "thumbnail"}, timeout=timeout)
    response.raise_for_status()
    return response.content


# =============================================================================
# ntfy API
# =============================================================================

def upload_image_to_ntfy(ntfy_url: str, image_data: bytes, auth: tuple = None, timeout: int = 30) -> Optional[str]:
    """Upload an image to ntfy and return the URL."""
    temp_topic = f"upload-{int(time.time())}"
    url = f"{ntfy_url}/{temp_topic}"

    headers = {"Filename": "memory.jpg"}
    response = requests.put(url, headers=headers, data=image_data, auth=auth, timeout=timeout)

    if response.status_code == 200:
        data = response.json()
        attachment = data.get("attachment", {})
        return attachment.get("url")
    return None


def send_notification(
    ntfy_url: str,
    topic: str,
    title: str,
    message: str,
    thumbnail_data: bytes = None,
    click_url: str = None,
    auth: tuple = None,
    timeout: int = 10,
) -> bool:
    """Send a notification to ntfy."""
    url = f"{ntfy_url}/{topic}"

    headers = {
        "Title": title,
        "Tags": "camera,calendar",
        "Priority": "default",
    }

    if click_url:
        headers["Click"] = click_url

    # Upload thumbnail and attach it
    if thumbnail_data:
        image_url = upload_image_to_ntfy(ntfy_url, thumbnail_data, auth=auth)
        if image_url:
            headers["Attach"] = image_url

    response = requests.post(url, headers=headers, data=message.encode("utf-8"), auth=auth, timeout=timeout)
    return response.status_code == 200


# =============================================================================
# User Processing
# =============================================================================

def process_user(
    user: dict,
    config: dict,
    state: dict,
    target_date: date,
    test_mode: bool = False,
    dry_run: bool = False,
    force: bool = False,
    logger: logging.Logger = None,
) -> dict:
    """
    Process notifications for a single user.
    Returns dict with 'success' bool and 'pending_notifications' list for delayed sending.
    """
    name = user["name"]
    api_key = user["immich_api_key"]
    topic = user["ntfy_topic"]
    ntfy_user = user.get("ntfy_username")
    ntfy_pass = user.get("ntfy_password")
    ntfy_auth = (ntfy_user, ntfy_pass) if ntfy_user and ntfy_pass else None
    enabled = user.get("enabled", True)

    result = {"success": True, "pending_notifications": [], "name": name}

    if not enabled:
        logger.info(f"  [{name}] Skipped (disabled)")
        return result

    if not api_key:
        logger.error(f"  [{name}] No API key configured")
        result["success"] = False
        return result

    # Check if already sent today
    if not force and not test_mode and was_sent_today(state, name, target_date):
        logger.info(f"  [{name}] Already sent today, skipping")
        return result

    immich_url = config["immich"]["url"]
    ntfy_url = config["ntfy"]["url"]
    retry_config = config["settings"]["retry"]
    messages = config.get("messages", [])
    max_notifications = config["settings"].get("max_notifications_per_day", 3)

    logger.info(f"  [{name}] Processing...")

    # Fetch memories with retry
    try:
        memories = with_retry(
            lambda: fetch_memories(immich_url, api_key),
            max_attempts=retry_config["max_attempts"],
            delay=retry_config["delay_seconds"],
            logger=logger,
        )
        logger.debug(f"  [{name}] Found {len(memories)} total memories")
    except Exception as e:
        logger.error(f"  [{name}] Failed to fetch memories: {e}")
        result["success"] = False
        return result

    # Filter for today
    todays = filter_todays_memories(memories, target_date)

    # In test mode, find any date with memories
    actual_date = target_date
    if test_mode and not todays:
        for memory in memories[:10]:
            show_at = memory.get("showAt", "")
            if show_at:
                actual_date = datetime.strptime(show_at[:10], "%Y-%m-%d").date()
                todays = filter_todays_memories(memories, actual_date)
                if todays:
                    logger.info(f"  [{name}] Test mode: using date {actual_date}")
                    break

    if not todays:
        logger.info(f"  [{name}] No memories for {target_date}")
        return result

    # Parse memories by year
    parsed = parse_memories(todays)

    if not parsed["years"]:
        logger.info(f"  [{name}] No content to notify")
        return result

    logger.info(f"  [{name}] {parsed['total_assets']} assets from years: {parsed['years']}")

    # Select years (random if more than max)
    years_to_notify = parsed["years"]
    if len(years_to_notify) > max_notifications:
        years_to_notify = random.sample(years_to_notify, max_notifications)
        years_to_notify.sort(reverse=True)
        logger.info(f"  [{name}] Randomly selected {max_notifications} years: {years_to_notify}")

    # Prepare notifications for each year
    notifications = []
    for year in years_to_notify:
        year_data = parsed["by_year"].get(year, {})
        notification = format_notification_for_year(year, year_data, messages, test_mode)

        if notification["has_content"]:
            notifications.append({
                "year": year,
                "notification": notification,
                "year_data": year_data,
                "user": user,
            })

    if dry_run:
        for notif in notifications:
            logger.info(f"  [{name}] [DRY RUN] Would send: {notif['notification']['title']} - {notif['notification']['message']}")
        return result

    # Send first notification immediately
    if notifications:
        first = notifications[0]
        success = send_year_notification(
            first, config, ntfy_auth, logger
        )
        if success:
            logger.info(f"  [{name}] Notification sent for {first['year']}!")
        else:
            result["success"] = False

        # Queue remaining notifications for delayed sending
        result["pending_notifications"] = notifications[1:]

    # Mark as sent
    if not test_mode and result["success"]:
        mark_as_sent(state, name, target_date)

    return result


def send_year_notification(
    notif: dict,
    config: dict,
    ntfy_auth: tuple,
    logger: logging.Logger,
) -> bool:
    """Send a single year's notification."""
    user = notif["user"]
    name = user["name"]
    notification = notif["notification"]
    year = notif["year"]
    asset_id = notification.get("asset_id")

    immich_url = config["immich"]["url"]
    ntfy_url = config["ntfy"]["url"]
    topic = user["ntfy_topic"]
    retry_config = config["settings"]["retry"]
    api_key = user["immich_api_key"]

    # Fetch thumbnail with retry
    thumbnail_data = None
    if asset_id:
        try:
            thumbnail_data = with_retry(
                lambda: fetch_thumbnail(immich_url, api_key, asset_id),
                max_attempts=retry_config["max_attempts"],
                delay=retry_config["delay_seconds"],
                logger=logger,
            )
            logger.debug(f"  [{name}] Thumbnail for {year}: {len(thumbnail_data):,} bytes")
        except Exception as e:
            logger.warning(f"  [{name}] Could not fetch thumbnail for {year}: {e}")

    # Send notification with retry
    try:
        click_url = "https://my.immich.app/"
        success = with_retry(
            lambda: send_notification(
                ntfy_url=ntfy_url,
                topic=topic,
                title=notification["title"],
                message=notification["message"],
                thumbnail_data=thumbnail_data,
                click_url=click_url,
                auth=ntfy_auth,
            ),
            max_attempts=retry_config["max_attempts"],
            delay=retry_config["delay_seconds"],
            logger=logger,
        )
        return success
    except Exception as e:
        logger.error(f"  [{name}] Error sending notification for {year}: {e}")
        return False


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Send Immich memory notifications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python notify.py                  # Send notifications for today
  python notify.py --test           # Test with any available date
  python notify.py --dry-run        # Preview without sending
  python notify.py --force          # Send even if already sent today
        """,
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--test", action="store_true", help="Test mode (use any date with memories)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent")
    parser.add_argument("--force", action="store_true", help="Force send even if already sent today")
    parser.add_argument("--date", help="Specific date to check (YYYY-MM-DD)")
    args = parser.parse_args()

    # Load config first to get log settings
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Error loading config: {e}")
        return 1

    # Setup logging
    settings = config.get("settings", {})
    logger = setup_logging(
        level=settings.get("log_level", "INFO"),
        log_file=settings.get("log_file"),
    )

    # Determine target date
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"Invalid date format: {args.date} (use YYYY-MM-DD)")
            return 1
    else:
        target_date = date.today()

    logger.info("=" * 60)
    logger.info("Immich Memories Notify")
    logger.info("=" * 60)
    logger.info(f"Date:    {target_date}")
    logger.info(f"Config:  {args.config}")

    if args.test:
        logger.info("Mode:    TEST")
    if args.dry_run:
        logger.info("Mode:    DRY RUN")
    if args.force:
        logger.info("Mode:    FORCE")

    # Load state
    state_file = settings.get("state_file", "state.json")
    state = load_state(state_file)

    # Get enabled users
    users = [u for u in config.get("users", []) if u.get("enabled", True)]
    logger.info(f"Users:   {len(users)}")

    if not users:
        logger.warning("No enabled users found in config")
        return 0

    # Get interval settings
    interval_minutes = settings.get("interval_minutes", 60)

    # Process each user - send first notification immediately
    success_count = 0
    all_pending = []

    for user in users:
        result = process_user(
            user=user,
            config=config,
            state=state,
            target_date=target_date,
            test_mode=args.test,
            dry_run=args.dry_run,
            force=args.force,
            logger=logger,
        )
        if result["success"]:
            success_count += 1
        # Collect pending notifications with user auth info
        for pending in result["pending_notifications"]:
            ntfy_user = user.get("ntfy_username")
            ntfy_pass = user.get("ntfy_password")
            ntfy_auth = (ntfy_user, ntfy_pass) if ntfy_user and ntfy_pass else None
            all_pending.append((pending, ntfy_auth))

    # Save state after first round
    if not args.dry_run:
        save_state(state_file, state)

    # Process pending notifications with intervals (round by round)
    # Group pending by round number (position in each user's queue)
    if all_pending and not args.dry_run:
        # Reorganize: group by which round they should be sent in
        # all_pending is flat, but we need to send one per user per round
        rounds = {}
        user_round_counters = {}
        for pending, ntfy_auth in all_pending:
            name = pending["user"]["name"]
            if name not in user_round_counters:
                user_round_counters[name] = 2  # Start at round 2
            round_num = user_round_counters[name]
            if round_num not in rounds:
                rounds[round_num] = []
            rounds[round_num].append((pending, ntfy_auth))
            user_round_counters[name] += 1

        total_pending = len(all_pending)
        logger.info(f"Pending: {total_pending} more notifications across {len(rounds)} rounds")

        # In test mode, use 5 second intervals for quick testing
        actual_interval = 5 if args.test else interval_minutes * 60

        for round_num in sorted(rounds.keys()):
            if args.test:
                logger.info(f"Waiting 5 seconds before round {round_num} (test mode)...")
            else:
                logger.info(f"Waiting {interval_minutes} minutes before round {round_num}...")
            time.sleep(actual_interval)

            logger.info(f"Round {round_num}:")
            for pending, ntfy_auth in rounds[round_num]:
                name = pending["user"]["name"]
                year = pending["year"]
                if send_year_notification(pending, config, ntfy_auth, logger):
                    logger.info(f"  [{name}] Notification sent for {year}!")
                else:
                    logger.error(f"  [{name}] Failed to send for {year}")

    logger.info("=" * 60)
    logger.info(f"Complete: {success_count}/{len(users)} users successful")
    logger.info("=" * 60)

    return 0 if success_count == len(users) else 1


if __name__ == "__main__":
    sys.exit(main())
