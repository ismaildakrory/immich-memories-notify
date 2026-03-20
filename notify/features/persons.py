"""Person photo notification preparation."""

import logging
import random
from typing import Optional

from ..immich import fetch_asset_details, get_random_person_photo
from ..utils import format_location, get_primary_album


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
