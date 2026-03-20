"""Immich API: memories, people, assets, thumbnails, albums."""

import json
import logging
import os
import random
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import List, Optional

import requests


# =============================================================================
# Memories API
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
# Album Management
# =============================================================================

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
