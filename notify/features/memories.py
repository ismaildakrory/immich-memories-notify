"""Memory notification preparation with face preference."""

import logging
import random
from datetime import date
from typing import Optional

from ..immich import fetch_asset_details, select_asset_with_face_preference
from ..utils import format_location, get_primary_album


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
