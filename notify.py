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
from datetime import date, datetime, timedelta
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


def format_person_notification(
    person_name: str,
    asset: dict,
    person_messages: List[str],
    test_mode: bool = False,
) -> dict:
    """Format notification for a random person photo."""
    asset_id = asset.get("id")

    # Select random message and format with person name
    if person_messages:
        message_template = random.choice(person_messages)
        message = message_template.format(person_name=person_name)
    else:
        message = f"A lovely moment with {person_name}..."

    title = f"A memory with {person_name}"
    if test_mode:
        title = "[TEST] " + title

    return {
        "title": title,
        "message": message,
        "has_content": True,
        "asset_id": asset_id,
        "person_name": person_name,
        "is_person_photo": True,
    }


def fetch_thumbnail(immich_url: str, api_key: str, asset_id: str, timeout: int = 30) -> bytes:
    """Fetch thumbnail image from Immich."""
    headers = {"x-api-key": api_key}
    url = f"{immich_url}/api/assets/{asset_id}/thumbnail"
    response = requests.get(url, headers=headers, params={"size": "thumbnail"}, timeout=timeout)
    response.raise_for_status()
    return response.content


# =============================================================================
# People/Face Recognition API
# =============================================================================

def fetch_people(immich_url: str, api_key: str, timeout: int = 10) -> list:
    """Fetch all recognized people from Immich API."""
    headers = {"Accept": "application/json", "x-api-key": api_key}
    response = requests.get(f"{immich_url}/api/people", headers=headers, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    # API returns {"people": [...], "total": N} or just a list
    if isinstance(data, dict) and "people" in data:
        return data["people"]
    return data if isinstance(data, list) else []


def fetch_person_assets(immich_url: str, api_key: str, person_id: str, timeout: int = 30, size: int = 1000) -> list:
    """Fetch assets for a specific person using search API."""
    headers = {"Accept": "application/json", "x-api-key": api_key}
    payload = {
        "personIds": [person_id],
        "size": size,
    }
    response = requests.post(
        f"{immich_url}/api/search/metadata",
        headers=headers,
        json=payload,
        timeout=timeout
    )
    response.raise_for_status()
    data = response.json()

    # Response format: {"albums": [...], "assets": {"items": [...], ...}} or {"assets": [...]}
    assets = data.get("assets", [])
    if isinstance(assets, dict):
        return assets.get("items", [])
    return assets


def get_top_persons(immich_url: str, api_key: str, limit: int = 5, logger=None) -> list:
    """
    Get top N persons by photo count, filtered to only those with names.
    Queries asset count for each named person using search API.
    Returns list of dicts with 'id', 'name', and 'asset_count'.
    """
    people = fetch_people(immich_url, api_key)

    # Filter to only people with names
    named_people = [p for p in people if p.get("name")]

    if logger:
        logger.debug(f"Found {len(named_people)} named people, counting assets...")

    # Query asset count for each named person
    headers = {"Accept": "application/json", "x-api-key": api_key}
    person_counts = []

    for person in named_people:
        person_id = person["id"]
        person_name = person["name"]

        try:
            # Use search API with size=1 to get total count efficiently
            payload = {"personIds": [person_id], "size": 1}
            response = requests.post(
                f"{immich_url}/api/search/metadata",
                headers=headers,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            assets_data = data.get("assets", {})
            if isinstance(assets_data, dict):
                # 'total' field contains the full count
                count = assets_data.get("total", len(assets_data.get("items", [])))
            else:
                count = len(assets_data)

            person_counts.append({
                "id": person_id,
                "name": person_name,
                "asset_count": count
            })
        except Exception as e:
            if logger:
                logger.warning(f"Could not count assets for {person_name}: {e}")
            # Still include them with 0 count
            person_counts.append({
                "id": person_id,
                "name": person_name,
                "asset_count": 0
            })

    # Sort by asset count descending
    person_counts.sort(key=lambda x: x["asset_count"], reverse=True)

    top = person_counts[:limit]

    if logger:
        logger.debug(f"Top {limit} named persons: {[(p['name'], p['asset_count']) for p in top]}")

    return top


def get_random_person_photo(
    immich_url: str,
    api_key: str,
    top_persons: list,
    exclude_days: int = 30,
    exclude_asset_ids: set = None,
    logger=None,
) -> Optional[dict]:
    """
    Get a random photo from one of the top persons, excluding recent photos.
    Returns dict with 'asset', 'person_name', 'person_id' or None if no valid photos.
    """
    if not top_persons:
        return None

    if exclude_asset_ids is None:
        exclude_asset_ids = set()

    cutoff_date = datetime.now() - timedelta(days=exclude_days)

    # Shuffle persons to add randomness in which person we try first
    shuffled_persons = random.sample(top_persons, len(top_persons))

    for person in shuffled_persons:
        person_id = person["id"]
        person_name = person["name"]

        try:
            assets = fetch_person_assets(immich_url, api_key, person_id)

            # Filter out recent photos and already-used assets
            valid_assets = []
            for asset in assets:
                asset_id = asset.get("id")
                if asset_id in exclude_asset_ids:
                    continue

                # Check date
                created_at = asset.get("fileCreatedAt") or asset.get("createdAt")
                if created_at:
                    try:
                        asset_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        if asset_date.replace(tzinfo=None) > cutoff_date:
                            continue  # Too recent
                    except (ValueError, TypeError):
                        pass

                valid_assets.append(asset)

            if valid_assets:
                chosen = random.choice(valid_assets)
                if logger:
                    logger.debug(f"Selected random photo of {person_name}")
                return {
                    "asset": chosen,
                    "person_name": person_name,
                    "person_id": person_id,
                }
        except Exception as e:
            if logger:
                logger.warning(f"Could not fetch assets for {person_name}: {e}")
            continue

    return None


def get_asset_people(immich_url: str, api_key: str, asset_id: str, timeout: int = 10) -> list:
    """Get people recognized in a specific asset."""
    headers = {"Accept": "application/json", "x-api-key": api_key}
    response = requests.get(f"{immich_url}/api/assets/{asset_id}", headers=headers, timeout=timeout)
    response.raise_for_status()
    asset_data = response.json()
    return asset_data.get("people", [])


def select_asset_with_face_preference(
    assets: list,
    top_person_ids: set,
    immich_url: str,
    api_key: str,
    exclude_asset_ids: set = None,
    logger=None,
) -> Optional[dict]:
    """
    Select an asset preferring those with recognized faces from top persons.
    Priority: 1) Has top person face, 2) Has any named face, 3) Random

    Returns the selected asset or None.
    """
    if not assets:
        return None

    if exclude_asset_ids is None:
        exclude_asset_ids = set()

    # Filter out already-used assets
    available = [a for a in assets if a.get("id") not in exclude_asset_ids]
    if not available:
        return None

    # Categorize assets
    with_top_person = []
    with_any_face = []
    without_face = []

    for asset in available:
        asset_id = asset.get("id")
        if not asset_id:
            continue

        try:
            people = get_asset_people(immich_url, api_key, asset_id)
            named_people = [p for p in people if p.get("name")]

            if any(p.get("id") in top_person_ids for p in named_people):
                with_top_person.append(asset)
            elif named_people:
                with_any_face.append(asset)
            else:
                without_face.append(asset)
        except Exception as e:
            if logger:
                logger.debug(f"Could not check faces for asset {asset_id}: {e}")
            without_face.append(asset)

    # Select by priority
    if with_top_person:
        chosen = random.choice(with_top_person)
        if logger:
            logger.debug(f"Selected asset with top person face")
        return chosen
    elif with_any_face:
        chosen = random.choice(with_any_face)
        if logger:
            logger.debug(f"Selected asset with named face")
        return chosen
    else:
        chosen = random.choice(without_face) if without_face else random.choice(available)
        if logger:
            logger.debug(f"Selected random asset (no face preference available)")
        return chosen


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
    from urllib.parse import quote

    url = f"{ntfy_url}/{topic}"

    # URL-encode non-ASCII characters in title for HTTP header safety
    encoded_title = quote(title, safe=' ')

    headers = {
        "Title": encoded_title,
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
# User Processing (Slot-based)
# =============================================================================

def process_user_slot(
    user: dict,
    config: dict,
    state: dict,
    target_date: date,
    slot: int,
    test_mode: bool = False,
    dry_run: bool = False,
    force: bool = False,
    logger: logging.Logger = None,
) -> dict:
    """
    Process a single notification slot for a user.

    Logic:
    - If memories exist: slots 1-N send memories (with face preference), last slot sends person photo
    - If no memories: all slots send person photos

    Returns dict with 'success' bool and 'asset_id' if sent.
    """
    name = user["name"]
    api_key = user["immich_api_key"]
    topic = user["ntfy_topic"]
    ntfy_user = user.get("ntfy_username")
    ntfy_pass = user.get("ntfy_password")
    ntfy_auth = (ntfy_user, ntfy_pass) if ntfy_user and ntfy_pass else None
    enabled = user.get("enabled", True)

    result = {"success": True, "name": name, "asset_id": None}

    if not enabled:
        logger.info(f"  [{name}] Skipped (disabled)")
        return result

    if not api_key:
        logger.error(f"  [{name}] No API key configured")
        result["success"] = False
        return result

    # Check if slot already sent today
    slots_sent = get_slots_sent_today(state, name, target_date)
    if not force and not test_mode and slot in slots_sent:
        logger.info(f"  [{name}] Slot {slot} already sent today, skipping")
        return result

    immich_url = config["immich"]["url"]
    retry_config = config["settings"]["retry"]
    messages = config.get("messages", [])
    person_messages = config.get("person_messages", [])
    settings = config["settings"]

    memory_notifications = settings.get("memory_notifications", 3)
    person_notifications = settings.get("person_notifications", 1)
    fallback_notifications = settings.get("fallback_notifications", 3)
    top_persons_limit = settings.get("top_persons_limit", 5)
    exclude_recent_days = settings.get("exclude_recent_days", 30)

    logger.info(f"  [{name}] Processing slot {slot}...")

    # Get assets already sent today to avoid duplicates
    assets_sent = get_assets_sent_today(state, name, target_date)

    # Fetch memories with retry
    try:
        memories = with_retry(
            lambda: fetch_memories(immich_url, api_key),
            max_attempts=retry_config["max_attempts"],
            delay=retry_config["delay_seconds"],
            logger=logger,
        )
    except Exception as e:
        logger.error(f"  [{name}] Failed to fetch memories: {e}")
        result["success"] = False
        return result

    # Filter for today
    todays = filter_todays_memories(memories, target_date)

    # In test mode, find any date with memories
    if test_mode and not todays:
        for memory in memories[:10]:
            show_at = memory.get("showAt", "")
            if show_at:
                test_date = datetime.strptime(show_at[:10], "%Y-%m-%d").date()
                todays = filter_todays_memories(memories, test_date)
                if todays:
                    logger.info(f"  [{name}] Test mode: using date {test_date}")
                    break

    # Parse memories by year
    parsed = parse_memories(todays) if todays else {"years": [], "by_year": {}}
    has_memories = bool(parsed["years"])

    # Get top persons for this user
    try:
        top_persons = with_retry(
            lambda: get_top_persons(immich_url, api_key, limit=top_persons_limit, logger=logger),
            max_attempts=retry_config["max_attempts"],
            delay=retry_config["delay_seconds"],
            logger=logger,
        )
        top_person_ids = {p["id"] for p in top_persons}
    except Exception as e:
        logger.warning(f"  [{name}] Could not fetch top persons: {e}")
        top_persons = []
        top_person_ids = set()

    # Determine what to send for this slot
    notification = None

    if has_memories:
        # Has memories: slots 1-memory_notifications send memories, rest send person photos
        total_slots = memory_notifications + person_notifications

        if slot <= memory_notifications:
            # Send a memory notification
            notification = prepare_memory_notification(
                parsed=parsed,
                slot=slot,
                assets_sent=assets_sent,
                top_person_ids=top_person_ids,
                immich_url=immich_url,
                api_key=api_key,
                messages=messages,
                test_mode=test_mode,
                logger=logger,
            )
        elif slot <= total_slots:
            # Send a person photo notification
            notification = prepare_person_notification(
                top_persons=top_persons,
                assets_sent=assets_sent,
                immich_url=immich_url,
                api_key=api_key,
                exclude_days=exclude_recent_days,
                person_messages=person_messages,
                test_mode=test_mode,
                logger=logger,
            )
        else:
            logger.info(f"  [{name}] Slot {slot} exceeds configured slots ({total_slots}), skipping")
            return result
    else:
        # No memories: all slots send person photos
        if slot <= fallback_notifications:
            notification = prepare_person_notification(
                top_persons=top_persons,
                assets_sent=assets_sent,
                immich_url=immich_url,
                api_key=api_key,
                exclude_days=exclude_recent_days,
                person_messages=person_messages,
                test_mode=test_mode,
                logger=logger,
            )
        else:
            logger.info(f"  [{name}] Slot {slot} exceeds fallback slots ({fallback_notifications}), skipping")
            return result

    if not notification or not notification.get("has_content"):
        logger.info(f"  [{name}] No content available for slot {slot}")
        return result

    if dry_run:
        logger.info(f"  [{name}] [DRY RUN] Would send: {notification['title']} - {notification['message']}")
        return result

    # Send the notification
    success = send_single_notification(
        user=user,
        notification=notification,
        config=config,
        ntfy_auth=ntfy_auth,
        logger=logger,
    )

    if success:
        logger.info(f"  [{name}] Notification sent for slot {slot}!")
        result["asset_id"] = notification.get("asset_id")

        # Mark slot as sent
        if not test_mode:
            mark_slot_sent(state, name, target_date, slot, notification.get("asset_id"))
    else:
        result["success"] = False

    return result


def prepare_memory_notification(
    parsed: dict,
    slot: int,
    assets_sent: set,
    top_person_ids: set,
    immich_url: str,
    api_key: str,
    messages: list,
    test_mode: bool,
    logger: logging.Logger,
) -> Optional[dict]:
    """Prepare a memory notification for a specific slot, preferring faces."""
    years = parsed["years"]
    if not years:
        return None

    # Select year for this slot (cycle through available years)
    year_index = (slot - 1) % len(years)
    year = years[year_index]
    year_data = parsed["by_year"].get(year, {})
    assets = year_data.get("assets", [])

    if not assets:
        return None

    # Select asset with face preference
    selected_asset = select_asset_with_face_preference(
        assets=assets,
        top_person_ids=top_person_ids,
        immich_url=immich_url,
        api_key=api_key,
        exclude_asset_ids=assets_sent,
        logger=logger,
    )

    if not selected_asset:
        # Fallback to first available
        available = [a for a in assets if a.get("id") not in assets_sent]
        selected_asset = available[0] if available else assets[0]

    # Format notification
    years_ago = date.today().year - year
    if messages:
        message_template = random.choice(messages)
        message = message_template.format(year=year, years_ago=years_ago)
    else:
        message = f"You have memories from {year}!"

    title = f"Memories from {year}"
    if test_mode:
        title = "[TEST] " + title

    return {
        "title": title,
        "message": message,
        "has_content": True,
        "asset_id": selected_asset.get("id"),
        "year": year,
        "is_person_photo": False,
    }


def prepare_person_notification(
    top_persons: list,
    assets_sent: set,
    immich_url: str,
    api_key: str,
    exclude_days: int,
    person_messages: list,
    test_mode: bool,
    logger: logging.Logger,
) -> Optional[dict]:
    """Prepare a random person photo notification."""
    if not top_persons:
        if logger:
            logger.info("No named persons available for person notification")
        return None

    result = get_random_person_photo(
        immich_url=immich_url,
        api_key=api_key,
        top_persons=top_persons,
        exclude_days=exclude_days,
        exclude_asset_ids=assets_sent,
        logger=logger,
    )

    if not result:
        if logger:
            logger.info("Could not find valid person photo")
        return None

    return format_person_notification(
        person_name=result["person_name"],
        asset=result["asset"],
        person_messages=person_messages,
        test_mode=test_mode,
    )


def send_single_notification(
    user: dict,
    notification: dict,
    config: dict,
    ntfy_auth: tuple,
    logger: logging.Logger,
) -> bool:
    """Send a single notification."""
    name = user["name"]
    asset_id = notification.get("asset_id")

    immich_url = config["immich"]["url"]
    ntfy_url = config["ntfy"]["url"]
    topic = user["ntfy_topic"]
    retry_config = config["settings"]["retry"]
    api_key = user["immich_api_key"]

    # Fetch thumbnail with retry
    thumbnail_data = None
    if asset_id:
        click_url = "https://my.immich.app/memory?id=" + asset_id
        try:
            thumbnail_data = with_retry(
                lambda: fetch_thumbnail(immich_url, api_key, asset_id),
                max_attempts=retry_config["max_attempts"],
                delay=retry_config["delay_seconds"],
                logger=logger,
            )
            logger.debug(f"  [{name}] Thumbnail: {len(thumbnail_data):,} bytes")
        except Exception as e:
            logger.warning(f"  [{name}] Could not fetch thumbnail: {e}")
    else:
        click_url = "https://my.immich.app/"
    # Send notification with retry
    try:
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
        logger.error(f"  [{name}] Error sending notification: {e}")
        return False


def calculate_random_delay(window_start: str, window_end: str, test_mode: bool = False) -> int:
    """
    Calculate random delay in seconds within a time window.
    window_start/window_end format: "HH:MM"
    Returns seconds to sleep.
    """
    if test_mode:
        # In test mode, use 1-5 second delay
        return random.randint(1, 5)

    now = datetime.now()

    # Parse window times
    start_hour, start_min = map(int, window_start.split(":"))
    end_hour, end_min = map(int, window_end.split(":"))

    window_start_time = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
    window_end_time = now.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)

    # If we're already past window start, random time from now to window end
    if now >= window_start_time:
        if now >= window_end_time:
            # Past window, no delay
            return 0
        # Random time between now and window end
        remaining_seconds = int((window_end_time - now).total_seconds())
        return random.randint(0, max(0, remaining_seconds))
    else:
        # Before window start, delay to random time in window
        window_duration = int((window_end_time - window_start_time).total_seconds())
        delay_to_start = int((window_start_time - now).total_seconds())
        random_offset = random.randint(0, window_duration)
        return delay_to_start + random_offset


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Send Immich memory notifications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python notify.py --slot 1          # Send slot 1 notification (with random delay)
  python notify.py --slot 2 --test   # Test slot 2 (minimal delay)
  python notify.py --slot 1 --dry-run # Preview slot 1 without sending
  python notify.py --slot 1 --force   # Force send even if already sent
  python notify.py --slot 1 --no-delay # Send immediately without random delay
        """,
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--slot", type=int, required=True, help="Notification slot number (1, 2, 3, ...)")
    parser.add_argument("--test", action="store_true", help="Test mode (minimal delays, use any date)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent")
    parser.add_argument("--force", action="store_true", help="Force send even if already sent today")
    parser.add_argument("--no-delay", action="store_true", help="Skip random delay, send immediately")
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
    logger.info(f"Slot:    {args.slot}")
    logger.info(f"Config:  {args.config}")

    if args.test:
        logger.info("Mode:    TEST")
    if args.dry_run:
        logger.info("Mode:    DRY RUN")
    if args.force:
        logger.info("Mode:    FORCE")

    # Get notification windows
    notification_windows = settings.get("notification_windows", [
        {"start": "08:00", "end": "10:00"},
        {"start": "12:00", "end": "14:00"},
        {"start": "16:00", "end": "18:00"},
        {"start": "19:00", "end": "20:00"},
    ])

    # Calculate and apply random delay for this slot's window
    if not args.no_delay and not args.dry_run:
        if args.slot <= len(notification_windows):
            window = notification_windows[args.slot - 1]
            delay_seconds = calculate_random_delay(
                window["start"],
                window["end"],
                test_mode=args.test,
            )

            if delay_seconds > 0:
                delay_minutes = delay_seconds // 60
                logger.info(f"Window:  {window['start']} - {window['end']}")
                if args.test:
                    logger.info(f"Delay:   {delay_seconds} seconds (test mode)")
                else:
                    logger.info(f"Delay:   ~{delay_minutes} minutes")
                time.sleep(delay_seconds)
        else:
            logger.warning(f"No window configured for slot {args.slot}, sending immediately")

    # Load state
    state_file = settings.get("state_file", "state.json")
    state = load_state(state_file)

    # Get enabled users
    users = [u for u in config.get("users", []) if u.get("enabled", True)]
    logger.info(f"Users:   {len(users)}")

    if not users:
        logger.warning("No enabled users found in config")
        return 0

    # Process each user for this slot
    success_count = 0

    for user in users:
        result = process_user_slot(
            user=user,
            config=config,
            state=state,
            target_date=target_date,
            slot=args.slot,
            test_mode=args.test,
            dry_run=args.dry_run,
            force=args.force,
            logger=logger,
        )
        if result["success"]:
            success_count += 1

    # Save state
    if not args.dry_run:
        save_state(state_file, state)

    logger.info("=" * 60)
    logger.info(f"Complete: {success_count}/{len(users)} users successful")
    logger.info("=" * 60)

    return 0 if success_count == len(users) else 1


if __name__ == "__main__":
    sys.exit(main())
