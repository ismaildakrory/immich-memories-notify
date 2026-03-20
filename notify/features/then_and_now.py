"""Then & Now feature: find candidates, compose images, prepare notifications."""

import logging
import random
from collections import defaultdict
from datetime import date, datetime
from io import BytesIO
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from ..immich import (
    fetch_asset_details,
    fetch_person_assets,
    fetch_thumbnail,
    get_asset_people,
    get_or_create_album,
    upload_collage_to_album,
)
from .collage import cover_crop_image


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
