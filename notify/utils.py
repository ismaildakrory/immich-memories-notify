"""Utility functions: retry logic, location formatting, delay calculation."""

import random
import time
from datetime import datetime, timedelta


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


def get_primary_album(asset_details: dict) -> str | None:
    """
    Get the first album name from asset's albums array.
    Returns album name or None if not in any album.
    """
    albums = asset_details.get("albums", [])
    if albums and len(albums) > 0:
        return albums[0].get("albumName")
    return None


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
