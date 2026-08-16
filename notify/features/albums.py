"""Album photo notification preparation."""

import logging
import random
from datetime import date
from typing import Optional

from ..immich import fetch_asset_details, get_album_assets, is_generated_asset
from ..utils import format_location, get_primary_album


def prepare_album_notification(
    album_names: list,
    assets_sent: set,
    immich_url: str,
    api_key: str,
    album_messages: list,
    test_mode: bool,
    logger: logging.Logger,
    settings: dict = None,
    video_album_messages: list = None,
    title_templates: list = None,
    target_date: date = None,
) -> Optional[dict]:
    """Prepare a notification from a user's configured albums.

    Tries "on this day" photos first, falls back to random.
    """
    if not album_names:
        return None

    if settings is None:
        settings = {}
    if video_album_messages is None:
        video_album_messages = []
    if target_date is None:
        target_date = date.today()

    shuffled = list(album_names)
    random.shuffle(shuffled)

    for album_name in shuffled:
        album_data = get_album_assets(immich_url, api_key, album_name, logger)
        if not album_data or not album_data["assets"]:
            continue

        all_assets = album_data["assets"]

        # Try "on this day" first — same month+day, any past year
        on_this_day = []
        for a in all_assets:
            created = a.get("localDateTime") or a.get("createdAt") or ""
            if len(created) >= 10:
                try:
                    asset_date = date.fromisoformat(created[:10])
                    if (asset_date.month == target_date.month
                            and asset_date.day == target_date.day
                            and asset_date.year < target_date.year):
                        on_this_day.append(a)
                except ValueError:
                    pass

        # Use "on this day" if available, otherwise all assets
        candidates = on_this_day if on_this_day else all_assets

        # Exclude already-sent and app-generated assets
        candidates = [a for a in candidates if a.get("id") not in assets_sent]
        candidates = [a for a in candidates
                     if not is_generated_asset(fetch_asset_details(immich_url, api_key, a["id"]))]
        if not candidates:
            continue

        asset = random.choice(candidates)
        asset_id = asset.get("id")
        is_video = asset.get("type") == "VIDEO"

        # Fetch asset details for location
        location_str = ""
        detail_album_name = None
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
                    detail_album_name = get_primary_album(asset_details)
            except Exception as e:
                if logger:
                    logger.debug(f"Could not fetch asset details for {asset_id}: {e}")

        # Choose message template
        if is_video and video_album_messages:
            message_template = random.choice(video_album_messages)
        elif album_messages:
            message_template = random.choice(album_messages)
        else:
            message_template = "A random moment from {album_name}"

        format_kwargs = {
            "album_name": album_name,
            "location": location_str,
        }

        try:
            message = message_template.format(**format_kwargs)
        except (KeyError, ValueError, IndexError):
            message = message_template.format(album_name=album_name)

        if location_str and location_str not in message and random.random() < 0.33:
            message = f"{message} 📍 {location_str}"

        # Build title
        video_emoji = settings.get("video_emoji", False)
        if title_templates:
            title_template = random.choice(title_templates)
            try:
                title = title_template.format(album_name=album_name)
            except (KeyError, ValueError, IndexError):
                title = album_name
        else:
            title = album_name
        if is_video and video_emoji:
            title = f"\U0001F3AC {title}"

        if test_mode:
            title = "[TEST] " + title

        source = "on-this-day" if on_this_day and asset in on_this_day else "random"
        if logger:
            logger.info(f"  Album notification: '{album_name}' ({source})")

        return {
            "title": title,
            "message": message,
            "has_content": True,
            "asset_id": asset_id,
            "album_name": detail_album_name or album_name,
            "is_album_photo": True,
            "is_video": is_video,
            "location": location_str,
        }

    if logger:
        logger.info("No content available from configured albums")
    return None
