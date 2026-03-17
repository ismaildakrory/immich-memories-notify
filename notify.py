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
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO


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
    import fcntl
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
    target_date: date = None,
) -> dict:
    """Format notification for a single year using random message from config."""
    if not year_data.get("assets"):
        return {"title": None, "message": None, "has_content": False, "asset_id": None}

    ref_date = target_date or date.today()
    years_ago = ref_date.year - year

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


def fetch_thumbnail(immich_url: str, api_key: str, asset_id: str, timeout: int = 30, size: str = "thumbnail") -> bytes:
    """Fetch thumbnail/preview image from Immich.

    Args:
        size: "thumbnail" (small), "preview" (medium), or "original" (full size)
    """
    headers = {"x-api-key": api_key}
    url = f"{immich_url}/api/assets/{asset_id}/thumbnail"
    response = requests.get(url, headers=headers, params={"size": size}, timeout=timeout)
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
    """Get people recognized in a specific asset.

    Returns list of face dicts with normalized (0-1) bounding box coordinates.
    """
    headers = {"Accept": "application/json", "x-api-key": api_key}
    response = requests.get(f"{immich_url}/api/assets/{asset_id}", headers=headers, timeout=timeout)
    response.raise_for_status()
    asset_data = response.json()
    people = asset_data.get("people", [])

    # Extract face bounding boxes and normalize to 0-1 range
    faces = []
    for person in people:
        for face in person.get("faces", []):
            img_w = face.get("imageWidth", 1)
            img_h = face.get("imageHeight", 1)
            if img_w and img_h:
                faces.append({
                    "id": person.get("id", ""),
                    "name": person.get("name", ""),
                    "boundingBoxX1": face.get("boundingBoxX1", 0) / img_w,
                    "boundingBoxY1": face.get("boundingBoxY1", 0) / img_h,
                    "boundingBoxX2": face.get("boundingBoxX2", 0) / img_w,
                    "boundingBoxY2": face.get("boundingBoxY2", 0) / img_h,
                })
    return faces


# Asset details cache (per-session, capped at 500 entries)
_CACHE_MAX = 500
_asset_details_cache = {}


def fetch_asset_details(immich_url: str, api_key: str, asset_id: str, timeout: int = 10) -> dict:
    """
    Fetch full asset details including exifInfo, albums, and people.
    Results are cached for the session to avoid repeated API calls.
    """
    cache_key = f"{immich_url}:{asset_id}"
    if cache_key in _asset_details_cache:
        return _asset_details_cache[cache_key]

    headers = {"Accept": "application/json", "x-api-key": api_key}
    response = requests.get(f"{immich_url}/api/assets/{asset_id}", headers=headers, timeout=timeout)
    response.raise_for_status()
    asset_data = response.json()

    if len(_asset_details_cache) >= _CACHE_MAX:
        _asset_details_cache.clear()
    _asset_details_cache[cache_key] = asset_data
    return asset_data


def format_location(exif_info: dict) -> dict:
    """
    Extract location from exifInfo.
    Returns dict with 'location', 'city', 'country' keys.
    Location is formatted as "City, Country" or just one if other is missing.
    """
    if not exif_info:
        return {"location": "", "city": "", "country": ""}

    city = exif_info.get("city", "")
    country = exif_info.get("country", "")

    # Build location string
    if city and country:
        location = f"{city}, {country}"
    elif city:
        location = city
    elif country:
        location = country
    else:
        location = ""

    return {
        "location": location,
        "city": city,
        "country": country,
    }


def get_primary_album(asset_details: dict) -> Optional[str]:
    """
    Get the first album name from asset's albums array.
    Returns album name or None if not in any album.
    """
    albums = asset_details.get("albums", [])
    if albums and len(albums) > 0:
        return albums[0].get("albumName")
    return None


def select_asset_with_face_preference(
    assets: list,
    top_person_ids: set,
    immich_url: str,
    api_key: str,
    exclude_asset_ids: set = None,
    logger=None,
    prefer_groups: bool = False,
    min_group_size: int = 2,
) -> Optional[dict]:
    """
    Select an asset preferring those with recognized faces from top persons.

    When prefer_groups is False (default):
    Priority: 1) Has top person face, 2) Has any named face, 3) Random

    When prefer_groups is True:
    Priority:
      1) Group photos with multiple top persons (>= min_group_size)
      2) Group photos with multiple named faces (>= min_group_size)
      3) Single top person
      4) Single named face
      5) Random

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

    # Categorize assets with face counts
    group_top_persons = []      # Multiple top persons
    group_named = []            # Multiple named faces
    single_top_person = []      # One top person
    single_named = []           # One named face
    without_face = []           # No faces

    for asset in available:
        asset_id = asset.get("id")
        if not asset_id:
            continue

        try:
            people = get_asset_people(immich_url, api_key, asset_id)
            # Deduplicate by person ID (a person may have multiple faces detected)
            seen_ids = set()
            named_people = []
            for p in people:
                pid = p.get("id")
                if p.get("name") and pid not in seen_ids:
                    seen_ids.add(pid)
                    named_people.append(p)
            top_people = [p for p in named_people if p.get("id") in top_person_ids]

            top_count = len(top_people)
            named_count = len(named_people)

            if top_count >= min_group_size:
                group_top_persons.append(asset)
            elif named_count >= min_group_size:
                group_named.append(asset)
            elif top_count > 0:
                single_top_person.append(asset)
            elif named_count > 0:
                single_named.append(asset)
            else:
                without_face.append(asset)
        except Exception as e:
            if logger:
                logger.debug(f"Could not check faces for asset {asset_id}: {e}")
            without_face.append(asset)

    # Select by priority
    if prefer_groups:
        # Group preference enabled - use new priority order
        if group_top_persons:
            chosen = random.choice(group_top_persons)
            if logger:
                logger.debug(f"Selected group photo with multiple top persons")
            return chosen
        elif group_named:
            chosen = random.choice(group_named)
            if logger:
                logger.debug(f"Selected group photo with multiple named faces")
            return chosen
        elif single_top_person:
            chosen = random.choice(single_top_person)
            if logger:
                logger.debug(f"Selected asset with single top person")
            return chosen
        elif single_named:
            chosen = random.choice(single_named)
            if logger:
                logger.debug(f"Selected asset with single named face")
            return chosen
        else:
            chosen = random.choice(without_face) if without_face else random.choice(available)
            if logger:
                logger.debug(f"Selected random asset (no face preference available)")
            return chosen
    else:
        # Original behavior - combine groups with singles
        with_top_person = group_top_persons + single_top_person
        with_any_face = group_named + single_named

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
    logger = logging.getLogger("immich-memories-notify")
    import uuid
    temp_topic = f"upload-{uuid.uuid4().hex[:12]}"
    url = f"{ntfy_url}/{temp_topic}"

    headers = {"Filename": "memory.jpg"}
    response = requests.put(url, headers=headers, data=image_data, auth=auth, timeout=timeout)

    if response.status_code == 200:
        data = response.json()
        attachment = data.get("attachment", {})
        attachment_url = attachment.get("url")
        if not attachment_url:
            logger.warning("ntfy upload returned 200 but no attachment URL — check that NTFY_BASE_URL and NTFY_ATTACHMENT_CACHE_SIZE are set on your ntfy server")
        return attachment_url

    body = response.text[:200]
    if "attachments not allowed" in body.lower():
        logger.warning(
            "ntfy rejected attachment upload: attachments not allowed. "
            "Fix: set auth-file in your ntfy server.yaml, create a user with "
            "'ntfy user add <username>', then grant access with "
            "'ntfy access <username> \"*\" read-write'. "
            "See: https://docs.ntfy.sh/config/#attachments"
        )
    elif response.status_code in (401, 403):
        logger.warning(
            f"ntfy rejected upload ({response.status_code}): check that NTFY_USER and "
            "NTFY_PASSWORD in your .env match a valid ntfy user, and that the user has "
            "read-write access: ntfy access <username> '*' read-write"
        )
    else:
        logger.warning(f"ntfy upload failed: {response.status_code} — {body}")
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
    is_video: bool = False,
) -> bool:
    """Send a notification to ntfy."""
    url = f"{ntfy_url}/{topic}"

    # Use different tags for videos
    tags = "movie,calendar" if is_video else "camera,calendar"

    # Encode title for HTTP header (RFC 2047 for non-ASCII)
    try:
        # Try latin-1 encoding first (fast path)
        title.encode('latin-1')
        encoded_title = title
    except UnicodeEncodeError:
        # Contains non-ASCII, use base64 encoding for header
        import base64
        encoded_title = f"=?UTF-8?B?{base64.b64encode(title.encode('utf-8')).decode('ascii')}?="

    headers = {
        "Title": encoded_title,
        "Tags": tags,
        "Priority": "default",
    }

    if click_url:
        headers["Click"] = click_url

    # Upload thumbnail and attach it
    if thumbnail_data:
        image_url = upload_image_to_ntfy(ntfy_url, thumbnail_data, auth=auth)
        if image_url:
            headers["Attach"] = image_url
        else:
            logging.getLogger("immich-memories-notify").warning(
                f"Thumbnail upload failed for topic '{topic}' — notification will be sent without preview ({len(thumbnail_data):,} bytes attempted)"
            )

    response = requests.post(url, headers=headers, data=message.encode("utf-8"), auth=auth, timeout=timeout)
    response.raise_for_status()
    return True


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
    video_messages = config.get("video_messages", [])
    video_person_messages = config.get("video_person_messages", [])
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

    if has_memories:
        logger.debug(f"  [{name}] Memories: {parsed['total_assets']} assets ({parsed['image_count']} images, {parsed['video_count']} videos)")

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
            # Check if this is the special slot for Then & Now / Trip Highlights
            tan_enabled = settings.get("then_and_now_enabled", True)
            trip_enabled = settings.get("trip_highlights_enabled", True)
            tan_slot_cfg = settings.get("then_and_now_slot", 0)
            tan_min_gap = settings.get("then_and_now_min_gap", 3)
            tan_messages = config.get("then_and_now_messages", [])
            trip_messages = config.get("trip_highlights_messages", [])
            home_city = user.get("home_city", "")
            trip_min_photos = settings.get("trip_highlights_min_photos", 5)
            year_range = settings.get("year_range", 5)

            is_special_slot = (tan_enabled or trip_enabled) and (
                tan_slot_cfg == slot or (tan_slot_cfg == 0 and slot == memory_notifications)
            )

            if is_special_slot:
                tan_cooldown = settings.get("then_and_now_cooldown_days", 7)
                trip_cooldown = settings.get("trip_highlights_cooldown_days", 7)
                tan_ready = tan_enabled and (test_mode or is_feature_ready(state, name, "last_tan_date", tan_cooldown, target_date))
                trip_ready = trip_enabled and (test_mode or is_feature_ready(state, name, "last_trip_date", trip_cooldown, target_date))

                if tan_ready:
                    days_info = "never" if not state.get("users", {}).get(name, {}).get("last_tan_date") else f"{state['users'][name]['last_tan_date']}"
                    logger.info(f"  [{name}] Then & Now ready (last: {days_info}, cooldown: {tan_cooldown} days)")
                else:
                    last = state.get("users", {}).get(name, {}).get("last_tan_date", "?")
                    try:
                        days_ago = (target_date - date.fromisoformat(last)).days if last != "?" else "?"
                    except ValueError:
                        days_ago = "?"
                    logger.info(f"  [{name}] Then & Now on cooldown (last: {last}, {days_ago} days ago)")

                if trip_ready:
                    days_info = "never" if not state.get("users", {}).get(name, {}).get("last_trip_date") else f"{state['users'][name]['last_trip_date']}"
                    logger.info(f"  [{name}] Trip Highlights ready (last: {days_info}, cooldown: {trip_cooldown} days)")
                else:
                    last = state.get("users", {}).get(name, {}).get("last_trip_date", "?")
                    try:
                        days_ago = (target_date - date.fromisoformat(last)).days if last != "?" else "?"
                    except ValueError:
                        days_ago = "?"
                    logger.info(f"  [{name}] Trip Highlights on cooldown (last: {last}, {days_ago} days ago)")

                # Priority: Trip first, TaN fallback (when both ready)
                if trip_ready:
                    try:
                        trip = find_trip_candidate(
                            immich_url=immich_url,
                            api_key=api_key,
                            target_date=target_date,
                            home_city=home_city,
                            min_photos=trip_min_photos,
                            year_range=year_range,
                            logger=logger,
                        )
                        if trip:
                            notification = prepare_trip_notification(
                                trip=trip,
                                immich_url=immich_url,
                                api_key=api_key,
                                messages=trip_messages,
                                test_mode=test_mode,
                                logger=logger,
                            )
                            if notification:
                                logger.info(f"  [{name}] Sending Trip Highlights "
                                            f"({trip['city']}, {trip['year']})")
                    except Exception as e:
                        logger.warning(f"  [{name}] Trip Highlights failed: {e}")

                if not notification and tan_ready:
                    try:
                        used_persons = state.get("users", {}).get(name, {}).get("tan_persons_used", [])
                        candidate = find_then_and_now_candidate(
                            immich_url=immich_url,
                            api_key=api_key,
                            top_persons=top_persons,
                            target_date=target_date,
                            min_gap=tan_min_gap,
                            year_range=year_range,
                            logger=logger,
                            used_person_ids=used_persons,
                        )
                        if candidate:
                            notification = prepare_then_and_now_notification(
                                candidate=candidate,
                                immich_url=immich_url,
                                api_key=api_key,
                                messages=tan_messages,
                                test_mode=test_mode,
                                logger=logger,
                            )
                            if notification:
                                logger.info(f"  [{name}] Sending Then & Now ({candidate['then_year']} → {candidate['now_year']})")
                    except Exception as e:
                        logger.warning(f"  [{name}] Then & Now lookup failed: {e}")

            if not notification:
                # Normal memory notification (fallback or non-special slot)
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
                    settings=settings,
                    video_messages=video_messages,
                    target_date=target_date,
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
                settings=settings,
                video_person_messages=video_person_messages,
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
                settings=settings,
                video_person_messages=video_person_messages,
            )
        else:
            logger.info(f"  [{name}] Slot {slot} exceeds fallback slots ({fallback_notifications}), skipping")
            return result

    if not notification or not notification.get("has_content"):
        logger.info(f"  [{name}] No content available for slot {slot}")
        return result

    if dry_run:
        logger.info(f"  [{name}] [DRY RUN] Would send: {notification['title']} - {notification['message']}")
        # Log additional details in debug mode
        if notification.get("location"):
            logger.debug(f"  [{name}] Location: {notification['location']}")
        if notification.get("album_name"):
            logger.debug(f"  [{name}] Album: {notification['album_name']}")
        if notification.get("is_video"):
            logger.debug(f"  [{name}] Type: VIDEO")
        return result

    # Send the notification
    # For Then & Now, pass composite image as thumbnail (no Immich asset to fetch)
    thumbnail_override = (
        notification.get("composite_image") if notification.get("is_then_and_now")
        else notification.get("collage_data") if notification.get("is_trip")
        else None
    )
    success = send_single_notification(
        user=user,
        notification=notification,
        config=config,
        ntfy_auth=ntfy_auth,
        logger=logger,
        thumbnail_override=thumbnail_override,
    )

    if success:
        logger.info(f"  [{name}] Notification sent for slot {slot}!")
        result["asset_id"] = notification.get("asset_id")

        if not test_mode:
            # Mark slot as sent
            mark_slot_sent(state, name, target_date, slot, notification.get("asset_id"))
            # Mark feature cooldowns only after successful send
            if notification.get("is_trip"):
                mark_feature_fired(state, name, "last_trip_date", target_date)
            elif notification.get("is_then_and_now"):
                mark_feature_fired(state, name, "last_tan_date", target_date)
                # Track TaN person freshness
                user_state = state.setdefault("users", {}).setdefault(name, {})
                used = user_state.setdefault("tan_persons_used", [])
                person_id = notification.get("person_id", "")
                if person_id:
                    used.append(person_id)
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
    settings: dict = None,
    video_messages: list = None,
    target_date: date = None,
) -> Optional[dict]:
    """Prepare a memory notification for a specific slot, preferring faces."""
    years = parsed["years"]
    if not years:
        return None

    if settings is None:
        settings = {}
    if video_messages is None:
        video_messages = []

    # Select year for this slot (cycle through available years)
    year_index = (slot - 1) % len(years)
    year = years[year_index]
    year_data = parsed["by_year"].get(year, {})
    assets = year_data.get("assets", [])

    if not assets:
        return None

    # Select asset with face preference (and group preference if enabled)
    prefer_groups = settings.get("prefer_group_photos", False)
    min_group_size = settings.get("min_group_size", 2)

    selected_asset = select_asset_with_face_preference(
        assets=assets,
        top_person_ids=top_person_ids,
        immich_url=immich_url,
        api_key=api_key,
        exclude_asset_ids=assets_sent,
        logger=logger,
        prefer_groups=prefer_groups,
        min_group_size=min_group_size,
    )

    if not selected_asset:
        # Fallback to first available, but skip if all already sent
        available = [a for a in assets if a.get("id") not in assets_sent]
        if not available:
            return None
        selected_asset = available[0]

    asset_id = selected_asset.get("id")

    # Detect if video
    is_video = selected_asset.get("type") == "VIDEO"

    # Fetch asset details for location and album
    location_str = ""
    album_name = None
    include_location = settings.get("include_location", False)
    include_album = settings.get("include_album", False)

    if asset_id and (include_location or include_album):
        try:
            asset_details = fetch_asset_details(immich_url, api_key, asset_id)
            if include_location:
                exif_info = asset_details.get("exifInfo", {})
                location_data = format_location(exif_info)
                location_str = location_data.get("location", "")
            if include_album:
                album_name = get_primary_album(asset_details)
        except Exception as e:
            if logger:
                logger.debug(f"Could not fetch asset details for {asset_id}: {e}")

    # Format notification
    ref_date = target_date or date.today()
    years_ago = ref_date.year - year

    # Choose message template based on video type
    if is_video and video_messages:
        message_template = random.choice(video_messages)
    elif messages:
        message_template = random.choice(messages)
    else:
        message_template = "You have memories from {year}!"

    # Build format kwargs
    format_kwargs = {
        "year": year,
        "years_ago": years_ago,
        "location": location_str,
        "album_name": album_name or "",
    }

    # Safely format message (ignore missing placeholders)
    try:
        message = message_template.format(**format_kwargs)
    except KeyError:
        # Fallback if template has unknown placeholders
        message = message_template.format(year=year, years_ago=years_ago)

    # Append location context if available (33% chance)
    if location_str and location_str not in message and random.random() < 0.33:
        message = f"{message} 📍 {location_str}"

    # Append album context if available (33% chance)
    if album_name and album_name not in message and random.random() < 0.33:
        message = f"{message}\n📁 {album_name}"

    # Build title
    video_emoji = settings.get("video_emoji", False)
    if is_video and video_emoji:
        title = f"\U0001F3AC Memories from {year}"
    else:
        title = f"Memories from {year}"

    if test_mode:
        title = "[TEST] " + title

    return {
        "title": title,
        "message": message,
        "has_content": True,
        "asset_id": asset_id,
        "year": year,
        "is_person_photo": False,
        "is_video": is_video,
        "location": location_str,
        "album_name": album_name,
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
    settings: dict = None,
    video_person_messages: list = None,
) -> Optional[dict]:
    """Prepare a random person photo notification."""
    if not top_persons:
        if logger:
            logger.info("No named persons available for person notification")
        return None

    if settings is None:
        settings = {}
    if video_person_messages is None:
        video_person_messages = []

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

    asset = result["asset"]
    person_name = result["person_name"]
    asset_id = asset.get("id")

    # Detect if video
    is_video = asset.get("type") == "VIDEO"

    # Fetch asset details for location and album
    location_str = ""
    album_name = None
    include_location = settings.get("include_location", False)
    include_album = settings.get("include_album", False)

    if asset_id and (include_location or include_album):
        try:
            asset_details = fetch_asset_details(immich_url, api_key, asset_id)
            if include_location:
                exif_info = asset_details.get("exifInfo", {})
                location_data = format_location(exif_info)
                location_str = location_data.get("location", "")
            if include_album:
                album_name = get_primary_album(asset_details)
        except Exception as e:
            if logger:
                logger.debug(f"Could not fetch asset details for {asset_id}: {e}")

    # Choose message template based on video type
    if is_video and video_person_messages:
        message_template = random.choice(video_person_messages)
    elif person_messages:
        message_template = random.choice(person_messages)
    else:
        message_template = "A lovely moment with {person_name}..."

    # Build format kwargs
    format_kwargs = {
        "person_name": person_name,
        "location": location_str,
        "album_name": album_name or "",
    }

    # Safely format message
    try:
        message = message_template.format(**format_kwargs)
    except KeyError:
        message = message_template.format(person_name=person_name)

    # Append location context if available (33% chance)
    if location_str and location_str not in message and random.random() < 0.33:
        message = f"{message} 📍 {location_str}"

    # Append album context if available (33% chance)
    if album_name and album_name not in message and random.random() < 0.33:
        message = f"{message}\n📁 {album_name}"

    # Build title
    video_emoji = settings.get("video_emoji", False)
    if is_video and video_emoji:
        title = f"\U0001F3AC A memory with {person_name}"
    else:
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
        "is_video": is_video,
        "location": location_str,
        "album_name": album_name,
    }


def is_collage_day(settings: dict, target_date: date) -> bool:
    """Check if today is the configured collage day.

    Config uses Sun=0, Sat=6 convention.
    Python weekday() uses Mon=0, Sun=6.
    Convert Python weekday to config convention: (weekday + 1) % 7
    """
    if not settings.get("weekly_collage_enabled", False):
        return False

    collage_day = settings.get("weekly_collage_day", 6)  # Saturday in Sun=0 convention
    python_as_config = (target_date.weekday() + 1) % 7
    return python_as_config == collage_day


# =============================================================================
# Collage Template System
# =============================================================================

def cover_crop_image(img: Image.Image, target_w: int, target_h: int, faces: list = None) -> Image.Image:
    """Scale image to cover target dimensions and crop intelligently.

    Uses face bounding boxes to position the crop, ensuring faces are visible.
    Falls back to center crop if no faces provided.

    Args:
        img: Source image
        target_w: Target width
        target_h: Target height
        faces: List of face dicts with boundingBoxX1, boundingBoxY1, boundingBoxX2, boundingBoxY2 (normalized 0-1)
    """
    img_w, img_h = img.size
    img_ratio = img_w / img_h
    target_ratio = target_w / target_h

    # Scale to cover (fill the space completely)
    if img_ratio > target_ratio:
        # Image is wider - fit to height and crop width
        scale = target_h / img_h
    else:
        # Image is taller - fit to width and crop height
        scale = target_w / img_w

    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    scaled = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # Determine crop position
    if faces and len(faces) > 0:
        # Calculate bounding box containing all faces (in scaled coordinates)
        min_x = min(f.get("boundingBoxX1", 0.5) for f in faces) * new_w
        max_x = max(f.get("boundingBoxX2", 0.5) for f in faces) * new_w
        min_y = min(f.get("boundingBoxY1", 0.5) for f in faces) * new_h
        max_y = max(f.get("boundingBoxY2", 0.5) for f in faces) * new_h

        # Center of all faces
        face_center_x = (min_x + max_x) / 2
        face_center_y = (min_y + max_y) / 2

        # Position crop to center on faces
        crop_x = int(face_center_x - target_w / 2)
        crop_y = int(face_center_y - target_h / 2)

        # Clamp to image bounds
        crop_x = max(0, min(crop_x, new_w - target_w))
        crop_y = max(0, min(crop_y, new_h - target_h))
    else:
        # Center crop (fallback)
        crop_x = (new_w - target_w) // 2
        crop_y = (new_h - target_h) // 2

    # Crop to target size
    cropped = scaled.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))
    return cropped




# =============================================================================
# Trip Highlights Feature
# =============================================================================

def fetch_month_assets(immich_url: str, api_key: str, year: int, month: int, timeout: int = 30, size: int = 500) -> list:
    """Fetch IMAGE assets for a specific year+month using the search API."""
    import calendar
    headers = {"Accept": "application/json", "x-api-key": api_key}
    last_day = calendar.monthrange(year, month)[1]
    payload = {
        "takenAfter":  f"{year}-{month:02d}-01T00:00:00.000Z",
        "takenBefore": f"{year}-{month:02d}-{last_day:02d}T23:59:59.999Z",
        "type": "IMAGE",
        "size": size,
    }
    response = requests.post(
        f"{immich_url}/api/search/metadata",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    assets = data.get("assets", [])
    return assets.get("items", []) if isinstance(assets, dict) else assets


def _normalize_city(name: str) -> str:
    """Normalize city name: lowercase, strip diacritics, collapse whitespace."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", name.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


def _is_home_city(city: str, home_city: str) -> bool:
    """Check if city matches home_city using containment + fuzzy matching."""
    if not home_city:
        return False
    c = _normalize_city(city)
    h = _normalize_city(home_city)
    # Exact match
    if c == h:
        return True
    # Containment: only when the shorter string is at least 4 chars
    # to avoid false positives like "Al" matching "Dallas"
    if len(h) >= 4 and len(c) >= 4 and (h in c or c in h):
        return True
    from difflib import SequenceMatcher
    return SequenceMatcher(None, c, h).ratio() >= 0.8


def _cluster_trip_dates(assets_with_dates: list, max_gap_days: int = 5) -> list:
    """
    Given [(asset_id, date), ...] sorted by date, find the largest cluster
    where consecutive photos are within max_gap_days of each other.
    Returns list of asset_ids from the best cluster.
    """
    if not assets_with_dates:
        return []
    assets_with_dates.sort(key=lambda x: x[1])

    clusters = []
    current = [assets_with_dates[0]]
    for i in range(1, len(assets_with_dates)):
        prev_date = current[-1][1]
        curr_date = assets_with_dates[i][1]
        if (curr_date - prev_date).days <= max_gap_days:
            current.append(assets_with_dates[i])
        else:
            clusters.append(current)
            current = [assets_with_dates[i]]
    clusters.append(current)

    best = max(clusters, key=len)
    return [aid for aid, _ in best]


def find_trip_candidate(
    immich_url: str,
    api_key: str,
    target_date: date,
    home_city: str = "",
    min_photos: int = 5,
    year_range: int = 5,
    logger=None,
) -> Optional[dict]:
    """
    Scan past years (limited by year_range) for the same calendar month.
    Groups IMAGE assets by (city, country, year) using exifInfo.
    Photos must be taken within 5 days of each other to count as a trip.
    Returns the group with the most photos that meets the minimum threshold.
    """
    target_month = target_date.month
    current_year = target_date.year
    # (city, country, year) -> [(asset_id, date), ...]
    city_year_assets = {}

    for year in range(current_year - 1, current_year - year_range - 1, -1):
        try:
            assets = fetch_month_assets(immich_url, api_key, year, target_month)
            for asset in assets:
                exif = asset.get("exifInfo") or {}
                city = (exif.get("city") or "").strip()
                country = (exif.get("country") or "").strip()
                if not city:
                    continue
                if _is_home_city(city, home_city):
                    continue
                # Extract date for clustering
                raw_date = asset.get("localDateTime") or asset.get("fileCreatedAt") or asset.get("createdAt")
                try:
                    asset_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date()
                except (ValueError, TypeError):
                    asset_date = date(year, target_month, 1)
                key = (city, country, year)
                city_year_assets.setdefault(key, []).append((asset["id"], asset_date))
        except Exception as e:
            if logger:
                logger.debug(f"  Trip search {year}-{target_month:02d}: {e}")

    # Cluster each group by date proximity, then pick best
    best = None
    best_count = 0
    for (city, country, year), assets_dates in city_year_assets.items():
        cluster_ids = _cluster_trip_dates(assets_dates, max_gap_days=5)
        if len(cluster_ids) < min_photos:
            continue
        if len(cluster_ids) > best_count or (len(cluster_ids) == best_count and best and year < best["year"]):
            best_count = len(cluster_ids)
            best = {"city": city, "country": country, "year": year,
                    "gap": current_year - year, "asset_ids": cluster_ids}

    if best and logger:
        logger.info(f"  Trip candidate: {best['city']}, {best['country']} "
                    f"({best['year']}, {best_count} photos)")
    elif logger:
        logger.debug(f"  No trip candidate (need {min_photos}+ photos in same city within 5 days, past {year_range} years)")
    return best


def prepare_trip_notification(
    trip: dict,
    immich_url: str,
    api_key: str,
    messages: list,
    test_mode: bool,
    logger=None,
) -> Optional[dict]:
    """
    Build a collage from up to 4 trip photos, upload to a per-trip album, and
    return a notification dict that deep-links to a random original photo.
    """
    _logger = logger or logging.getLogger()
    city = trip["city"]
    country = trip["country"]
    year = trip["year"]
    gap = trip["gap"]
    asset_ids = trip["asset_ids"]

    selected_ids = random.sample(asset_ids, min(4, len(asset_ids)))

    # Fetch thumbnails for collage
    thumbnails = []
    valid_ids = []
    for aid in selected_ids:
        try:
            data = fetch_thumbnail(immich_url, api_key, aid, size="preview")
            thumbnails.append(data)
            valid_ids.append(aid)
        except Exception as e:
            _logger.debug(f"  Could not fetch thumbnail for {aid}: {e}")

    if not thumbnails:
        _logger.warning("  No thumbnails fetched for Trip Highlights collage")
        return None

    # Build collage — use first available custom template or a simple grid
    from PIL import Image as PILImage
    from io import BytesIO as _BytesIO

    def _simple_grid(images, names, w, h, faces=None):
        """Simple 2×2 (or fewer) grid collage with face-aware cropping."""
        if faces is None:
            faces = [[] for _ in images]
        n = len(images)
        cols = min(n, 2)
        rows = (n + cols - 1) // cols
        cell_w = w // cols
        cell_h = h // rows
        canvas = PILImage.new("RGB", (w, h), (30, 30, 30))
        for i, img in enumerate(images):
            col = i % cols
            row = i // cols
            img_cropped = cover_crop_image(img, cell_w, cell_h, faces=faces[i] if i < len(faces) else None)
            canvas.paste(img_cropped, (col * cell_w, row * cell_h))
        return canvas

    # Fetch face data for smart cropping
    faces_list = []
    for aid in valid_ids:
        try:
            faces_list.append(get_asset_people(immich_url, api_key, aid))
        except Exception:
            faces_list.append([])

    try:
        pil_images = [PILImage.open(_BytesIO(d)).convert("RGB") for d in thumbnails]
        canvas = _simple_grid(pil_images, [], 1080, 1080, faces=faces_list)
        buf = _BytesIO()
        canvas.save(buf, format="JPEG", quality=95)
        collage = buf.getvalue()
    except Exception as e:
        _logger.warning(f"  Could not create Trip Highlights collage: {e}")
        return None

    # Build message
    if messages:
        template = random.choice(messages)
        try:
            message = template.format(city=city, country=country, year=year, gap=gap)
        except KeyError:
            message = f"{gap} years ago in {city}, {country}!"
    else:
        message = f"{gap} years ago in {city}, {country}!"

    title = f"Trip to {city} \U0001f30d"
    if test_mode:
        title = "[TEST] " + title

    # Create/find per-trip album and add original photos
    album_name = f"Trip to {city}, {country} ({year})"
    uploaded_asset_id = None
    try:
        album_id = get_or_create_album(immich_url, api_key, album_name, _logger)
        if album_id:
            # Add original photos to album
            headers = {"Accept": "application/json", "x-api-key": api_key, "Content-Type": "application/json"}
            requests.put(
                f"{immich_url}/api/albums/{album_id}/assets",
                headers=headers,
                json={"ids": asset_ids},
                timeout=30,
            )
            # Upload collage to album
            uploaded_asset_id = upload_collage_to_album(immich_url, api_key, collage, album_id, _logger)
    except Exception as e:
        _logger.warning(f"  Could not upload Trip Highlights to album: {e}")

    click_asset = random.choice(valid_ids)

    return {
        "title": title,
        "message": message,
        "has_content": True,
        "asset_id": uploaded_asset_id,
        "click_url": f"https://my.immich.app/photos/{click_asset}",
        "is_trip": True,
        "is_video": False,
        "collage_data": collage,
    }


# =============================================================================
# Then & Now Feature
# =============================================================================

def find_then_and_now_candidate(
    immich_url: str,
    api_key: str,
    top_persons: list,
    target_date,
    min_gap: int = 3,
    year_range: int = 5,
    logger=None,
    used_person_ids: list = None,
) -> Optional[dict]:
    """
    Search top persons for the same person appearing in the same calendar month
    across multiple years with at least min_gap years between them.
    Only considers years within year_range of current year.
    Prefers persons not recently used (freshness), then largest year gap.
    Returns the best candidate or None.
    """
    from collections import defaultdict

    target_month = target_date.month
    target_year = target_date.year
    min_year = target_year - year_range
    used = set(used_person_ids or [])

    candidates = []

    for person in top_persons:
        person_id = person.get("id")
        pname = person.get("name", "").strip()
        if not person_id or not pname:
            continue

        try:
            assets = fetch_person_assets(immich_url, api_key, person_id)
        except Exception as e:
            if logger:
                logger.debug(f"  Then & Now: could not fetch assets for {pname}: {e}")
            continue

        # Group IMAGE assets by year
        year_assets: dict[int, list] = defaultdict(list)
        for asset in assets:
            if asset.get("type") == "VIDEO":
                continue
            asset_id = asset.get("id")
            if not asset_id:
                continue
            raw_date = asset.get("localDateTime") or asset.get("fileCreatedAt") or asset.get("createdAt")
            if not raw_date:
                continue
            try:
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                if dt.month != target_month:
                    continue
                year = dt.year
                if year >= target_year or year < min_year:
                    continue
                year_assets[year].append(asset_id)
            except (ValueError, TypeError):
                continue

        if len(year_assets) < 2:
            continue

        years = sorted(year_assets.keys())
        gap = max(years) - min(years)
        if gap < min_gap:
            continue

        then_year = min(years)
        now_year = max(years)

        then_asset_id = year_assets[then_year][0]
        now_asset_id = year_assets[now_year][-1]

        try:
            then_details = fetch_asset_details(immich_url, api_key, then_asset_id)
            now_details = fetch_asset_details(immich_url, api_key, now_asset_id)
        except Exception as e:
            if logger:
                logger.debug(f"  Then & Now: could not fetch details for {pname}: {e}")
            continue

        then_faces = [f for f in get_asset_people(immich_url, api_key, then_asset_id) if f.get("name") == pname]
        now_faces = [f for f in get_asset_people(immich_url, api_key, now_asset_id) if f.get("name") == pname]

        candidates.append({
            "person_name": pname,
            "person_id": person_id,
            "then_year": then_year,
            "now_year": now_year,
            "gap": gap,
            "then_asset_id": then_asset_id,
            "now_asset_id": now_asset_id,
            "then_faces": then_faces,
            "now_faces": now_faces,
        })

    if not candidates:
        if logger:
            logger.debug(f"  No Then & Now candidate found (need same person in same month across {min_gap}+ years)")
        return None

    # Sort: prefer unused persons first, then largest gap
    candidates.sort(key=lambda c: (c["person_id"] not in used, c["gap"]), reverse=True)
    best = candidates[0]

    if logger:
        logger.info(f"  Then & Now candidate: {best['person_name']} ({best['then_year']} → {best['now_year']}, {best['gap']} years)")

    return best


def _load_font(size: int = 36):
    """Load a TrueType font at the given size, falling back to Pillow's default."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def create_then_and_now_image(
    then_bytes: bytes,
    now_bytes: bytes,
    then_faces: list,
    now_faces: list,
    then_year: int,
    now_year: int,
    width: int = 1080,
    height: int = 540,
    logger=None,
) -> Optional[bytes]:
    """
    Compose a side-by-side Then & Now image from two photo thumbnails.
    Left panel = then (oldest year), right panel = now (most recent year).
    Face bounding boxes are used to center the crop on the person.
    """
    try:
        panel_w = width // 2

        then_img = Image.open(BytesIO(then_bytes)).convert("RGB")
        now_img = Image.open(BytesIO(now_bytes)).convert("RGB")

        then_panel = cover_crop_image(then_img, panel_w, height, faces=then_faces)
        now_panel = cover_crop_image(now_img, panel_w, height, faces=now_faces)

        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        canvas.paste(then_panel, (0, 0))
        canvas.paste(now_panel, (panel_w, 0))

        draw = ImageDraw.Draw(canvas, "RGBA")

        # White divider line at center
        draw.line([(panel_w - 2, 0), (panel_w - 2, height)], fill=(255, 255, 255, 220), width=4)

        # Year labels — semi-transparent pill at bottom of each panel
        font = _load_font(40)
        padding = 10

        for label, x_origin in [(str(then_year), 0), (str(now_year), panel_w)]:
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            lx = x_origin + 20
            ly = height - th - 20 - padding * 2
            draw.rectangle(
                [lx - padding, ly - padding, lx + tw + padding, ly + th + padding],
                fill=(0, 0, 0, 160),
            )
            draw.text((lx, ly), label, font=font, fill=(255, 255, 255, 255))

        buf = BytesIO()
        canvas.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        return buf.getvalue()

    except Exception as e:
        if logger:
            logger.error(f"Error creating Then & Now image: {e}")
        return None


def prepare_then_and_now_notification(
    candidate: dict,
    immich_url: str,
    api_key: str,
    messages: list,
    test_mode: bool,
    logger=None,
) -> Optional[dict]:
    """
    Fetch preview thumbnails, compose a high-res split image, upload it to the
    'Then & Now' album in Immich, and return a notification dict that deep-links
    directly to the uploaded composite.
    """
    try:
        then_bytes = fetch_thumbnail(immich_url, api_key, candidate["then_asset_id"], size="preview")
        now_bytes = fetch_thumbnail(immich_url, api_key, candidate["now_asset_id"], size="preview")
    except Exception as e:
        if logger:
            logger.warning(f"  Could not fetch Then & Now thumbnails: {e}")
        return None

    composite = create_then_and_now_image(
        then_bytes=then_bytes,
        now_bytes=now_bytes,
        then_faces=candidate["then_faces"],
        now_faces=candidate["now_faces"],
        then_year=candidate["then_year"],
        now_year=candidate["now_year"],
        width=1920,
        height=960,
        logger=logger,
    )
    if not composite:
        return None

    person_name = candidate["person_name"]
    gap = candidate["gap"]
    then_year = candidate["then_year"]
    now_year = candidate["now_year"]

    if messages:
        template = random.choice(messages)
        try:
            message = template.format(person_name=person_name, then_year=then_year, now_year=now_year, gap=gap)
        except KeyError:
            message = f"{gap} years between these moments with {person_name}"
    else:
        message = f"{gap} years between these moments with {person_name}"

    title = f"Then & Now — {person_name}"
    if test_mode:
        title = "[TEST] " + title

    # Upload composite to "Then & Now" album; click_url left unset so
    # send_single_notification builds the my.immich.app deep link automatically
    uploaded_asset_id = None
    if logger:
        logger.info(f"  Uploading Then & Now composite to Immich…")
    try:
        album_id = get_or_create_album(immich_url, api_key, "Then & Now", logger or logging.getLogger())
        if album_id:
            uploaded_asset_id = upload_collage_to_album(immich_url, api_key, composite, album_id, logger or logging.getLogger())
    except Exception as e:
        if logger:
            logger.warning(f"  Could not upload Then & Now composite: {e}")

    return {
        "title": title,
        "message": message,
        "has_content": True,
        "asset_id": uploaded_asset_id,
        "is_then_and_now": True,
        "is_video": False,
        "person_id": candidate.get("person_id", ""),
        "composite_image": composite,  # fallback thumbnail while Immich processes the upload
    }


COLLAGE_TEMPLATES = {
    # Built-in templates removed - using only custom templates with overlays
}


def load_custom_templates(templates_dir: str = "custom_templates"):
    """Load custom templates from Python files in templates_dir.

    Each custom template file should define a render(images, names, width, height) function.
    Template name is taken from the filename (without .py extension).
    """
    templates_path = Path(templates_dir)
    if not templates_path.exists():
        return

    import importlib.util
    import sys

    for template_file in templates_path.glob("*.py"):
        template_name = template_file.stem
        try:
            # Load module from file
            spec = importlib.util.spec_from_file_location(template_name, template_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[template_name] = module
            spec.loader.exec_module(module)

            # Get render function
            if hasattr(module, 'render'):
                COLLAGE_TEMPLATES[template_name] = module.render
                logging.getLogger("immich-memories-notify").info(
                    f"Loaded custom template: {template_name}"
                )
        except Exception as e:
            logging.getLogger("immich-memories-notify").warning(
                f"Failed to load custom template {template_name}: {e}"
            )


# Load custom templates at module level
load_custom_templates()


def get_template_photo_count(template_name: str, logger: logging.Logger) -> Optional[int]:
    """Get the number of photos a collage template needs from its layout JSON."""
    # Layout files use base name without _custom suffix (e.g. mosaic_layout.json, not mosaic_custom_layout.json)
    base_name = template_name.removesuffix("_custom")
    layout_path = os.path.join(os.path.dirname(__file__), "custom_templates", f"{base_name}_layout.json")
    try:
        with open(layout_path, "r") as f:
            layout = json.load(f)
        positions = layout.get("positions") or layout.get("photo_positions") or []
        return len(positions) if positions else None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def generate_weekly_collage(
    user: dict,
    config: dict,
    target_date: date,
    settings: dict,
    logger: logging.Logger,
    test_mode: bool = False
) -> Optional[dict]:
    """Generate a collage of top people's photos for weekly notification."""
    try:
        immich_url = config["immich"]["url"]
        api_key = user["immich_api_key"]
        limit = settings.get("collage_person_limit", 5)

        # Get top persons using existing function
        top_persons = get_top_persons(immich_url, api_key, limit=limit, logger=logger)
        if not top_persons:
            logger.info(f"No top people found for user {user['name']}")
            return None

        # Get one random photo per person
        image_data_list = []
        asset_ids = []
        person_names = []
        exclude_days = settings.get("exclude_recent_days", 30)

        for person in top_persons:
            result = get_random_person_photo(
                immich_url=immich_url,
                api_key=api_key,
                top_persons=[person],
                exclude_days=exclude_days,
                logger=logger,
            )
            if result:
                asset_id = result["asset"].get("id")
                if asset_id:
                    try:
                        # Use preview size for better quality collages
                        thumb_bytes = fetch_thumbnail(immich_url, api_key, asset_id, size="preview")
                        image_data_list.append(thumb_bytes)
                        asset_ids.append(asset_id)
                        person_names.append(result["person_name"])
                    except Exception as e:
                        logger.warning(f"Could not fetch image for {result['person_name']}: {e}")

        if not image_data_list:
            logger.info(f"No photos found for top people for user {user['name']}")
            return None

        # Resolve template name early so we know how many photos are needed
        template_name = settings.get("collage_template", "grid")
        if not COLLAGE_TEMPLATES:
            logger.error("No collage templates available. Check custom_templates/ directory.")
            return None
        if template_name == "random":
            template_name = random.choice(list(COLLAGE_TEMPLATES.keys()))
            logger.debug(f"Random template selected: {template_name}")

        # Fill additional slots if the template needs more photos than people
        needed = get_template_photo_count(template_name, logger)
        if needed and len(image_data_list) < needed:
            logger.info(
                f"Template '{template_name}' needs {needed} photos, have {len(image_data_list)}. "
                f"Fetching {needed - len(image_data_list)} more from same people."
            )
            used_asset_ids = set(asset_ids)
            person_index = 0
            max_attempts = needed * 3  # avoid infinite loop if photos exhausted
            attempts = 0
            while len(image_data_list) < needed and attempts < max_attempts:
                person = top_persons[person_index % len(top_persons)]
                person_index += 1
                attempts += 1
                result = get_random_person_photo(
                    immich_url=immich_url,
                    api_key=api_key,
                    top_persons=[person],
                    exclude_days=exclude_days,
                    exclude_asset_ids=used_asset_ids,
                    logger=logger,
                )
                if result:
                    asset_id = result["asset"].get("id")
                    if asset_id and asset_id not in used_asset_ids:
                        try:
                            thumb_bytes = fetch_thumbnail(immich_url, api_key, asset_id, size="preview")
                            image_data_list.append(thumb_bytes)
                            asset_ids.append(asset_id)
                            person_names.append(result["person_name"])
                            used_asset_ids.add(asset_id)
                        except Exception as e:
                            logger.warning(f"Could not fetch fill image for {result['person_name']}: {e}")

        # Create collage with high quality settings (portrait for mobile)
        collage_bytes = create_collage_image(
            image_data_list=image_data_list,
            asset_ids=asset_ids,
            person_names=person_names,
            template_name=template_name,
            logger=logger,
            immich_url=immich_url,
            api_key=api_key,
            width=1080,
            height=1920,
        )

        if not collage_bytes:
            logger.warning(f"Failed to create collage for user {user['name']}")
            return None

        # Upload collage to Immich album
        album_name = settings.get("collage_album_name", "Weekly Highlights")
        asset_id = None

        try:
            album_id = get_or_create_album(immich_url, api_key, album_name, logger)
            if album_id:
                asset_id = upload_collage_to_album(immich_url, api_key, collage_bytes, album_id, logger)
                if asset_id:
                    logger.info(f"Collage uploaded to album '{album_name}' with asset ID: {asset_id}")
        except Exception as e:
            logger.warning(f"Failed to upload collage to album: {e}")

        names_str = ", ".join(person_names[:3])
        if len(person_names) > 3:
            names_str += f" +{len(person_names) - 3} more"

        title = "Weekly Highlights"
        if test_mode:
            title = "[TEST] " + title

        return {
            "title": title,
            "message": f"Your weekly highlights with {names_str}",
            "has_content": True,
            "asset_id": asset_id,
            "is_collage": True,
            "is_video": False,
            "collage_data": collage_bytes if not asset_id else None,
        }

    except Exception as e:
        logger.error(f"Error generating collage for user {user['name']}: {e}")
        return None


def create_collage_image(
    image_data_list: List[bytes],
    person_names: List[str],
    template_name: str,
    logger: logging.Logger,
    asset_ids: List[str] = None,
    immich_url: str = None,
    api_key: str = None,
    width: int = 1080,
    height: int = 1920,
) -> Optional[bytes]:
    """Create a collage image from raw thumbnail bytes using the selected template."""
    try:
        # Convert bytes to PIL Images
        pil_images = []
        for data in image_data_list:
            img = Image.open(BytesIO(data)).convert("RGB")
            pil_images.append(img)

        if not pil_images:
            return None

        # Fetch face data for smart cropping
        faces_list = []
        if asset_ids and immich_url and api_key:
            for asset_id in asset_ids:
                try:
                    people = get_asset_people(immich_url, api_key, asset_id)
                    faces_list.append(people)
                except Exception as e:
                    logger.debug(f"Could not fetch faces for asset {asset_id}: {e}")
                    faces_list.append([])
        else:
            # No face data available, templates will use center crop
            faces_list = [[] for _ in pil_images]

        # Select template (random if requested)
        if not COLLAGE_TEMPLATES:
            logger.error("No collage templates available. Check custom_templates/ directory.")
            return None

        if template_name == "random":
            template_name = random.choice(list(COLLAGE_TEMPLATES.keys()))
            logger.debug(f"Random template selected: {template_name}")

        render_fn = COLLAGE_TEMPLATES.get(template_name)
        if not render_fn:
            logger.error(f"Template '{template_name}' not found. Available: {list(COLLAGE_TEMPLATES.keys())}")
            return None

        # Check if template accepts faces_list parameter (backward compatibility)
        import inspect
        sig = inspect.signature(render_fn)
        if len(sig.parameters) >= 5:
            # New signature with faces_list
            collage = render_fn(pil_images, person_names, width, height, faces_list)
        else:
            # Old signature without faces_list (custom templates)
            logger.debug(f"Template '{template_name}' uses old signature (no faces_list), using fallback")
            collage = render_fn(pil_images, person_names, width, height)

        # Save to JPEG bytes with high quality
        buf = BytesIO()
        collage.save(buf, format='JPEG', quality=95)
        buf.seek(0)
        return buf.getvalue()

    except Exception as e:
        logger.error(f"Error creating collage image: {e}")
        return None


def get_or_create_album(immich_url: str, api_key: str, album_name: str, logger: logging.Logger) -> Optional[str]:
    """Get or create an album with the given name."""
    try:
        headers = {"Accept": "application/json", "x-api-key": api_key}

        # List existing albums
        response = requests.get(f"{immich_url}/api/albums", headers=headers, timeout=30)
        if response.status_code == 200:
            albums = response.json()
            for album in albums:
                if album.get("albumName") == album_name:
                    return album.get("id")

        # Create new album
        response = requests.post(
            f"{immich_url}/api/albums",
            headers=headers,
            json={"albumName": album_name, "description": "Weekly highlights collage"},
            timeout=30,
        )
        if response.status_code in (200, 201):
            return response.json().get("id")
        else:
            logger.warning(f"Failed to create album '{album_name}': {response.status_code}")
            return None

    except Exception as e:
        logger.warning(f"Error with album handling: {e}")
        return None


def upload_collage_to_album(
    immich_url: str,
    api_key: str,
    collage_data: bytes,
    album_id: str,
    logger: logging.Logger,
) -> Optional[str]:
    """Upload collage image to Immich and add to album."""
    try:
        headers = {"x-api-key": api_key}
        now_iso = datetime.now().isoformat()
        device_asset_id = f"memnotify-collage-{int(time.time())}"

        # Upload via POST /api/assets with multipart
        files = {"assetData": ("collage.jpg", collage_data, "image/jpeg")}
        data = {
            "deviceAssetId": device_asset_id,
            "deviceId": "memnotify",
            "fileCreatedAt": now_iso,
            "fileModifiedAt": now_iso,
        }

        response = requests.post(
            f"{immich_url}/api/assets",
            headers=headers,
            files=files,
            data=data,
            timeout=60,
        )

        if response.status_code not in (200, 201):
            logger.warning(f"Failed to upload collage: {response.status_code}")
            return None

        asset_id = response.json().get("id")
        if not asset_id:
            return None

        # Add to album via PUT /api/albums/{id}/assets
        add_headers = {"Accept": "application/json", "x-api-key": api_key, "Content-Type": "application/json"}
        response = requests.put(
            f"{immich_url}/api/albums/{album_id}/assets",
            headers=add_headers,
            json={"ids": [asset_id]},
            timeout=30,
        )

        if response.status_code == 200:
            logger.info(f"Collage added to album, asset ID: {asset_id}")
        else:
            logger.warning(f"Failed to add collage to album: {response.status_code} (asset still uploaded)")

        return asset_id

    except Exception as e:
        logger.error(f"Error uploading collage: {e}")
        return None


def process_collage_slot(
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
    """Process a collage notification for a user."""
    try:
        user_name = user["name"]
        ntfy_user = user.get("ntfy_username")
        ntfy_pass = user.get("ntfy_password")
        ntfy_auth = (ntfy_user, ntfy_pass) if ntfy_user and ntfy_pass else None

        # Check if slot already sent
        slots_sent = get_slots_sent_today(state, user_name, target_date)
        if not force and not test_mode and slot in slots_sent:
            logger.info(f"  [{user_name}] Collage slot {slot} already sent today")
            return {"success": True, "message": "Already sent"}

        settings = config.get("settings", {})
        collage_notification = generate_weekly_collage(
            user=user,
            config=config,
            target_date=target_date,
            settings=settings,
            logger=logger,
            test_mode=test_mode,
        )

        if not collage_notification or not collage_notification.get("has_content"):
            logger.info(f"  [{user_name}] No collage generated")
            return {"success": False, "message": "No collage generated"}

        if dry_run:
            logger.info(f"  [{user_name}] [DRY RUN] Would send collage: {collage_notification['title']}")
            return {"success": True, "message": "Dry run successful"}

        # Always provide collage_data as thumbnail fallback (Immich needs time to process uploads)
        thumbnail_override = collage_notification.get("collage_data")

        success = send_single_notification(
            user=user,
            notification=collage_notification,
            config=config,
            ntfy_auth=ntfy_auth,
            logger=logger,
            thumbnail_override=thumbnail_override,
        )

        if success:
            if not test_mode:
                mark_slot_sent(state, user_name, target_date, slot, collage_notification.get("asset_id"))
            logger.info(f"  [{user_name}] Collage sent for slot {slot}")
        else:
            logger.warning(f"  [{user_name}] Failed to send collage")

        return {"success": success, "message": "Sent" if success else "Failed"}

    except Exception as e:
        logger.error(f"Error processing collage slot for {user['name']}: {e}")
        return {"success": False, "message": str(e)}


def send_single_notification(
    user: dict,
    notification: dict,
    config: dict,
    ntfy_auth: tuple,
    logger: logging.Logger,
    thumbnail_override: bytes = None,
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
    # If a thumbnail_override is provided and preferred (e.g. Then & Now composite), use it directly.
    # Otherwise fetch from Immich and fall back to override on failure.
    thumbnail_data = None
    if thumbnail_override and not asset_id:
        # No asset to fetch — use override directly (Then & Now, failed collage upload, etc.)
        thumbnail_data = thumbnail_override
    elif asset_id:
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
            if thumbnail_override:
                thumbnail_data = thumbnail_override
                logger.debug(f"  [{name}] Using fallback thumbnail: {len(thumbnail_data):,} bytes")
    elif thumbnail_override:
        thumbnail_data = thumbnail_override

    # Send notification with retry
    try:
        # Use pre-built click_url from notification (e.g. Then & Now links to "now" photo)
        # or build from asset_id
        click_url = notification.get("click_url")
        if not click_url:
            if asset_id:
                click_url = f"https://my.immich.app/photos/{asset_id}"
            else:
                click_url = "https://my.immich.app/"
        is_video = notification.get("is_video", False)
        success = with_retry(
            lambda: send_notification(
                ntfy_url=ntfy_url,
                topic=topic,
                title=notification["title"],
                message=notification["message"],
                thumbnail_data=thumbnail_data,
                click_url=click_url,
                auth=ntfy_auth,
                is_video=is_video,
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

    # Handle overnight windows (e.g., 23:00 to 01:00)
    if window_end_time <= window_start_time:
        window_end_time += timedelta(days=1)

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
    state_file = settings.get("state_file", "state/state.json")
    state = load_state(state_file)

    # Check if this is a collage day
    collage_day = is_collage_day(settings, target_date)
    if collage_day:
        logger.info("Collage: YES (weekly collage day)")

    # Get enabled users
    users = [u for u in config.get("users", []) if u.get("enabled", True)]
    logger.info(f"Users:   {len(users)}")

    if not users:
        logger.warning("No enabled users found in config")
        return 0

    # Determine if this slot is a person-photo slot (eligible for collage replacement)
    memory_notifications = settings.get("memory_notifications", 3)
    person_notifications = settings.get("person_notifications", 1)
    total_slots = memory_notifications + person_notifications
    is_person_slot = args.slot > memory_notifications and args.slot <= total_slots

    # On collage day, replace person-photo slots with collage
    use_collage_for_slot = collage_day and is_person_slot

    # Process each user for this slot
    success_count = 0

    for user in users:
        if use_collage_for_slot:
            # Send collage instead of person photo for this slot
            result = process_collage_slot(
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
            if result.get("success"):
                success_count += 1
        else:
            # Normal notification (memory or person photo)
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

        # Save state after each user to avoid losing progress on crash
        if not args.dry_run:
            save_state(state_file, state)

    logger.info("=" * 60)
    logger.info(f"Complete: {success_count}/{len(users)} users successful")
    logger.info("=" * 60)

    return 0 if success_count == len(users) else 1


if __name__ == "__main__":
    sys.exit(main())
