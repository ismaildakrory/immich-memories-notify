"""Trip Highlights feature: find trip candidates, prepare notifications."""

import logging
import random
from datetime import date, datetime
from io import BytesIO
from typing import Optional

import requests
from PIL import Image

from ..immich import (
    fetch_thumbnail,
    get_asset_people,
    get_or_create_album,
    upload_collage_to_album,
)
from .collage import cover_crop_image


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
    def _simple_grid(images, names, w, h, faces=None):
        """Simple 2×2 (or fewer) grid collage with face-aware cropping."""
        if faces is None:
            faces = [[] for _ in images]
        n = len(images)
        cols = min(n, 2)
        rows = (n + cols - 1) // cols
        cell_w = w // cols
        cell_h = h // rows
        canvas = Image.new("RGB", (w, h), (30, 30, 30))
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
        pil_images = [Image.open(BytesIO(d)).convert("RGB") for d in thumbnails]
        canvas = _simple_grid(pil_images, [], 1080, 1080, faces=faces_list)
        buf = BytesIO()
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
