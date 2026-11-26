"""Context theme notifications: a memory lane of photos found with Immich's context search.

A theme is a free-text query ("sunset", "snow", ...). The best matches are spread over as many
different years as possible, turned into an Immich memory (the swipeable lane in the app) and the
notification opens that lane.
"""

import logging
import random
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests

from ..defaults import DEFAULT_SETTINGS
from ..immich import DEFAULT_POLICY, create_memory, delete_memory, fetch_memory, search_smart

MIN_LANE_PHOTOS = 3  # fewer usable matches than this and the theme is skipped
MAX_THEMES_PER_RUN = 3  # themes searched per notification, so a slow server cannot stall a window
POOL_FACTOR = 3  # only the best lane_photos * POOL_FACTOR matches are spread over the years


def _utc_now() -> datetime:
    """Naive UTC "now", the form the Immich helpers expect."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_timeline(asset: dict) -> bool:
    """Only photos in the normal timeline (never archived, hidden or locked ones)."""
    return asset.get("visibility", "timeline") == "timeline"


def order_themes(themes: list, last_used: dict) -> list:
    """Themes to try, least recently used first (never used first), random among equals."""
    shuffled = random.sample(list(themes), len(themes))
    return sorted(shuffled, key=lambda theme: last_used.get(theme, ""))


def pick_spread(assets: list, count: int, policy=DEFAULT_POLICY) -> list:
    """Pick up to `count` assets spread over as many different years as possible.

    Round robin over the years (oldest first). Within a year the policy's weighted order is
    used, so never-sent photos and favourites come first. The result is in date order.
    """
    by_year = {}
    for asset in assets:
        by_year.setdefault((asset.get("localDateTime") or "")[:4], []).append(asset)
    queues = [policy.ordered(by_year[year], len(by_year[year])) for year in sorted(by_year)]
    picked = []
    while len(picked) < count and any(queues):
        for queue in queues:
            if queue and len(picked) < count:
                picked.append(queue.pop(0))
    return sorted(picked, key=lambda a: a.get("localDateTime") or "")


def _year_of(asset: dict) -> Optional[int]:
    year = (asset.get("localDateTime") or "")[:4]
    return int(year) if year.isdigit() else None


def _parse_moment(value: str, fallback: datetime) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except (AttributeError, ValueError):
        return fallback


def _format(template: str, fallback: str, **kwargs) -> str:
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError, IndexError):
        return fallback


def prepare_context_notification(
    themes: list,
    assets_sent: set,
    immich_url: str,
    api_key: str,
    messages: list,
    test_mode: bool,
    logger: logging.Logger,
    settings: dict = None,
    title_templates: list = None,
    last_used: dict = None,
    upload: bool = True,
    now: datetime = None,
    policy=None,
) -> Optional[dict]:
    """Prepare a notification for the next context theme that has enough photos.

    With `upload` (a real run) the photos are turned into an Immich memory lane and the
    notification opens it. Without (test / dry run) nothing is written to Immich. If the lane
    cannot be created (for example the API key lacks memory.create) the notification still goes
    out and opens the cover photo.
    """
    if not themes:
        return None
    settings = settings or {}
    policy = policy or DEFAULT_POLICY
    now = now or _utc_now()
    lane_photos = max(MIN_LANE_PHOTOS, int(settings.get("lane_photos", DEFAULT_SETTINGS["lane_photos"])))

    for theme in order_themes(themes, last_used or {})[:MAX_THEMES_PER_RUN]:
        try:
            results = search_smart(immich_url, api_key, theme)
        except requests.RequestException as e:
            if logger:
                logger.warning(f"  Context search for '{theme}' failed: {e}")
            continue

        candidates = [
            a for a in results
            if isinstance(a, dict) and a.get("id") and a["id"] not in assets_sent and _is_timeline(a) and policy.allowed(a)
        ]
        # Context search always returns something, best matches first: keep only the strongest ones so a
        # year whose only hit is a weak match cannot take a slot.
        candidates = candidates[:lane_photos * POOL_FACTOR]
        if len(candidates) < MIN_LANE_PHOTOS:
            if logger:
                logger.info(f"  Context '{theme}': only {len(candidates)} usable photos, trying the next theme")
            continue

        chosen = pick_spread(candidates, lane_photos, policy)
        asset_ids = [a["id"] for a in chosen]
        cover = policy.choose(chosen) or chosen[0]
        years = [y for y in (_year_of(a) for a in chosen) if y is not None]
        first_year, last_year = (min(years), max(years)) if years else (now.year, now.year)

        lane_id = None
        if upload:
            # The Immich app lists a memory in its memory bar only if showAt is at or before the start of
            # the phone's local day (read as UTC) and hideAt is not before it. A showAt of "now" would hide
            # the lane until tomorrow, so it starts a day early and ends after tomorrow: it shows today
            # and tomorrow in every timezone.
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            try:
                lane_id = create_memory(
                    immich_url, api_key, asset_ids, last_year,
                    memory_at=_parse_moment(chosen[-1].get("localDateTime"), now),
                    show_at=day_start - timedelta(days=1), hide_at=day_start + timedelta(days=2),
                )
            except (requests.RequestException, KeyError, ValueError) as e:
                if logger:
                    logger.warning(f"  Could not create the memory lane (does the API key have memory.create?): {e}")

        fields = {
            "theme": theme,
            "theme_title": theme.capitalize(),
            "count": len(asset_ids),
            "first_year": first_year,
            "last_year": last_year,
        }
        default_message = f"{len(asset_ids)} photos of {theme}, {first_year} to {last_year}"
        message = _format(random.choice(messages), default_message, **fields) if messages else default_message
        default_title = f"{theme.capitalize()}, across the years"
        title = _format(random.choice(title_templates), default_title, **fields) if title_templates else default_title
        if test_mode:
            title = "[TEST] " + title

        if logger:
            logger.info(
                f"  Context notification: '{theme}' ({len(asset_ids)} photos, {first_year}-{last_year}, "
                f"lane {lane_id or 'not created'})"
            )

        result = {
            "title": title,
            "message": message,
            "has_content": True,
            "asset_id": cover["id"],
            "asset_ids": asset_ids,
            "year": last_year,
            "is_context": True,
            "context_theme": theme,
            "lane_id": lane_id,
            "is_video": False,
        }
        if lane_id:
            result["app_click_url"] = f"immich://memory?id={lane_id}"
        return result

    if logger:
        logger.info("No context theme had enough photos")
    return None


def cleanup_lanes(
    immich_url: str,
    api_key: str,
    state: dict,
    user_name: str,
    keep_days: int,
    target_date: date,
    logger: logging.Logger,
) -> int:
    """Delete lanes this app created more than `keep_days` ago. Returns how many were deleted.

    A lane the user saved in Immich is left alone and no longer tracked. A lane that cannot be
    checked right now (network error) stays tracked and is retried on the next run.
    """
    user_state = state.get("users", {}).get(user_name, {})
    keep, deleted = [], 0
    for lane in user_state.get("lanes", []):
        try:
            age_days = (target_date - date.fromisoformat(lane["created"])).days
        except (KeyError, ValueError, TypeError):
            continue  # unreadable entry: drop it
        if age_days < keep_days:
            keep.append(lane)
            continue
        try:
            memory = fetch_memory(immich_url, api_key, lane["id"])
            if memory is not None and not memory.get("isSaved"):
                delete_memory(immich_url, api_key, lane["id"])
                deleted += 1
        except requests.RequestException as e:
            if logger:
                logger.warning(f"  Could not clean up memory lane {lane['id']}, will retry: {e}")
            keep.append(lane)
    if "lanes" in user_state:
        user_state["lanes"] = keep
    if deleted and logger:
        logger.info(f"  [{user_name}] Removed {deleted} old memory lane(s)")
    return deleted
