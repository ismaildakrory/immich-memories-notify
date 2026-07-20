"""
Immich Memories Notify
======================
Sends daily memory notifications to all configured users.

Layered priority system:
  1. Window 1 always sends a memory (birthday pre-empts).
  2. Windows 2+: pending specials (T&N/Trip/Collage) claim the
     first eligible window. One special per day per user.
  3. Otherwise: pick from regular events (memory/person/album)
     with memory getting a 10% weight boost.
Fallback is always a person photo.

Usage:
    python -m notify --slot 1        # Send notifications for window 1
    python -m notify --slot 1 --test # Test mode (uses any available date)
    python -m notify --slot 1 --dry-run # Show what would be sent without sending
    python -m notify --check-updates # Check GitHub for new releases
"""

import argparse
import logging
import random
import sys
import time
from datetime import date, datetime

from .config import (
    get_assets_sent_today,
    get_slots_sent_today,
    get_window_events,
    is_feature_ready,
    load_config,
    load_state,
    mark_feature_fired,
    mark_slot_sent,
    mark_special_sent_today,
    save_state,
    setup_logging,
    was_special_sent_today,
)
from .features.albums import prepare_album_notification
from .features.birthday import find_birthday_people, prepare_birthday_notification
from .features.memories import prepare_memory_notification
from .features.persons import prepare_person_notification
from .features.then_and_now import find_then_and_now_candidate, prepare_then_and_now_notification
from .features.trip import find_trip_candidate, prepare_trip_notification
from .immich import (
    fetch_memories,
    fetch_people,
    filter_todays_memories,
    get_top_persons,
    parse_memories,
)
from .dispatcher import send_notification
from .utils import calculate_random_delay, with_retry


ALL_EVENTS = ["memory", "person", "album", "then_and_now", "trip_highlights", "collage"]
SPECIAL_EVENTS = {"then_and_now", "trip_highlights", "collage"}
REGULAR_EVENTS = {"memory", "person", "album"}

MEMORY_WEIGHT = 1.1
NORMAL_WEIGHT = 1.0


def select_event_type(eligible_events: list) -> str:
    """Pick a regular event type randomly. Memory gets 10% boost."""
    if not eligible_events:
        return "person"
    weights = [MEMORY_WEIGHT if e == "memory" else NORMAL_WEIGHT for e in eligible_events]
    return random.choices(eligible_events, weights=weights, k=1)[0]


def process_user_window(
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
    Process a single notification window for a user.

    Layer 1: Window 1 always sends memory (birthday pre-empts).
    Layer 2: Windows 2+ — if a special (T&N/Trip/Collage) is pending,
             it claims the window. One special per day per user.
    Layer 3: Otherwise, pick from regular events (memory/person/album)
             with memory getting a 10% boost.
    Fallback is always a person photo.

    Returns dict with 'success' bool and 'asset_id' if sent.
    """
    name = user["name"]
    api_key = user["immich_api_key"]
    enabled = user.get("enabled", True)

    result = {"success": True, "name": name, "asset_id": None}

    if not enabled:
        logger.info(f"  [{name}] Skipped (disabled)")
        return result

    if not api_key:
        logger.error(f"  [{name}] No API key configured")
        result["success"] = False
        return result

    # Check if window already sent today
    slots_sent = get_slots_sent_today(state, name, target_date)
    if not force and not test_mode and slot in slots_sent:
        logger.info(f"  [{name}] Window {slot} already sent today, skipping")
        return result

    immich_url = config["immich"]["url"]
    click_base = config["immich"].get("external_url") or ""
    if click_base and not click_base.startswith(("http://", "https://")):
        click_base = f"https://{click_base}"
    retry_config = config["settings"]["retry"]
    settings = config["settings"]

    messages = config.get("messages", [])
    person_messages = config.get("person_messages", [])
    video_messages = config.get("video_messages", [])
    video_person_messages = config.get("video_person_messages", [])
    memory_titles = config.get("memory_titles", [])
    person_titles = config.get("person_titles", [])
    album_messages = config.get("album_messages", [])
    video_album_messages = config.get("video_album_messages", [])
    album_titles = config.get("album_titles", [])
    tan_messages = config.get("then_and_now_messages", [])
    tan_titles = config.get("then_and_now_titles", [])
    trip_messages = config.get("trip_highlights_messages", [])
    trip_titles = config.get("trip_highlights_titles", [])

    top_persons_limit = settings.get("top_persons_limit", 5)
    exclude_recent_days = settings.get("exclude_recent_days", 30)
    user_album_names = user.get("album_names", [])

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
        logger.debug(f"  [{name}] Memories: {parsed['total_assets']} assets")

    # Fetch all people once (shared by birthday check and top persons)
    try:
        all_people = with_retry(
            lambda: fetch_people(immich_url, api_key),
            max_attempts=retry_config["max_attempts"],
            delay=retry_config["delay_seconds"],
            logger=logger,
        )
    except Exception as e:
        logger.warning(f"  [{name}] Could not fetch people: {e}")
        all_people = []

    # Get top persons for this user
    try:
        top_persons = get_top_persons(immich_url, api_key, limit=top_persons_limit, logger=logger, people=all_people)
        top_person_ids = {p["id"] for p in top_persons}
    except Exception as e:
        logger.warning(f"  [{name}] Could not fetch top persons: {e}")
        top_persons = []
        top_person_ids = set()

    notification = None

    # --- Birthday check (pre-empts everything on window 1) ---
    birthday_enabled = settings.get("birthday_enabled", True)
    if birthday_enabled and slot == 1:
        birthday_messages = config.get("birthday_messages", [])
        birthday_titles = config.get("birthday_titles", [])
        try:
            birthday_people = find_birthday_people(
                immich_url=immich_url,
                api_key=api_key,
                target_date=target_date,
                logger=logger,
                people=all_people,
            )
            if birthday_people:
                person = random.choice(birthday_people)
                notification = prepare_birthday_notification(
                    birthday_person=person,
                    immich_url=immich_url,
                    api_key=api_key,
                    messages=birthday_messages,
                    test_mode=test_mode,
                    logger=logger,
                    title_templates=birthday_titles,
                    exclude_asset_ids=assets_sent,
                    exclude_days=exclude_recent_days,
                )
                if notification:
                    logger.info(f"  [{name}] Sending birthday notification for {person['name']}")
        except Exception as e:
            logger.warning(f"  [{name}] Birthday check failed: {e}")

    # --- Layered event selection ---
    if not notification:
        window_events = get_window_events(config, slot)

        # Layer 1: Window 1 always sends memory
        if slot == 1:
            if has_memories:
                notification = _execute_event(
                    "memory", user=user, config=config, state=state,
                    target_date=target_date, slot=slot, parsed=parsed,
                    assets_sent=assets_sent, top_persons=top_persons,
                    top_person_ids=top_person_ids, test_mode=test_mode,
                    logger=logger, click_base=click_base,
                )
        else:
            # Layer 2: Special priority (one per day, windows 2+)
            tan_enabled = settings.get("then_and_now_enabled", True)
            trip_enabled = settings.get("trip_highlights_enabled", True)
            collage_enabled = settings.get("weekly_collage_enabled", False)
            tan_cooldown = settings.get("then_and_now_cooldown_days", 7)
            trip_cooldown = settings.get("trip_highlights_cooldown_days", 7)
            collage_cooldown = settings.get("collage_cooldown_days", 7)
            tan_ready = tan_enabled and (test_mode or is_feature_ready(state, name, "last_tan_date", tan_cooldown, target_date))
            trip_ready = trip_enabled and (test_mode or is_feature_ready(state, name, "last_trip_date", trip_cooldown, target_date))
            collage_ready = collage_enabled and (test_mode or is_feature_ready(state, name, "last_collage_date", collage_cooldown, target_date))

            special_already_sent = not test_mode and was_special_sent_today(state, name, target_date)

            if not special_already_sent:
                pending = []
                if tan_ready and "then_and_now" in window_events:
                    pending.append("then_and_now")
                if trip_ready and "trip_highlights" in window_events:
                    pending.append("trip_highlights")
                if collage_ready and "collage" in window_events:
                    pending.append("collage")

                if pending:
                    selected_special = random.choice(pending)
                    notification = _execute_event(
                        selected_special, user=user, config=config, state=state,
                        target_date=target_date, slot=slot, parsed=parsed,
                        assets_sent=assets_sent, top_persons=top_persons,
                        top_person_ids=top_person_ids, test_mode=test_mode,
                        logger=logger, click_base=click_base,
                    )

            # Layer 3: Regular events (memory/person/album)
            if not notification:
                eligible = [e for e in window_events
                            if e in REGULAR_EVENTS
                            and not (e == "memory" and not has_memories)
                            and not (e == "album" and not user_album_names)]

                for _attempt in range(3):
                    if not eligible:
                        break
                    selected = select_event_type(eligible)
                    notification = _execute_event(
                        selected, user=user, config=config, state=state,
                        target_date=target_date, slot=slot, parsed=parsed,
                        assets_sent=assets_sent, top_persons=top_persons,
                        top_person_ids=top_person_ids, test_mode=test_mode,
                        logger=logger, click_base=click_base,
                    )
                    if notification:
                        break
                    eligible.remove(selected)

        # Fallback: person photo
        if not notification:
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
                title_templates=person_titles,
            )

    if not notification or not notification.get("has_content"):
        logger.info(f"  [{name}] No content available for slot {slot}")
        return result

    if dry_run:
        logger.info(f"  [{name}] [DRY RUN] Would send: {notification['title']} - {notification['message']}")
        if notification.get("location"):
            logger.debug(f"  [{name}] Location: {notification['location']}")
        if notification.get("album_name"):
            logger.debug(f"  [{name}] Album: {notification['album_name']}")
        return result

    # Send the notification
    thumbnail_override = (
        notification.get("composite_image") if notification.get("is_then_and_now")
        else notification.get("collage_data") if notification.get("is_trip") or notification.get("is_collage")
        else None
    )
    success = send_notification(
        user=user,
        notification=notification,
        config=config,
        logger=logger,
        thumbnail_override=thumbnail_override,
    )

    if success:
        logger.info(f"  [{name}] Notification sent for slot {slot}!")
        result["asset_id"] = notification.get("asset_id")

        if not test_mode:
            mark_slot_sent(state, name, target_date, slot, notification.get("asset_id"))
            # Mark feature cooldowns
            if notification.get("is_trip"):
                mark_feature_fired(state, name, "last_trip_date", target_date)
                trip_key = notification.get("trip_key", "")
                if trip_key:
                    user_state = state.setdefault("users", {}).setdefault(name, {})
                    shown = user_state.setdefault("trips_shown", {})
                    shown[trip_key] = target_date.isoformat()
                    repeat_days = settings.get("trip_highlights_repeat_days", 90)
                    for key in list(shown):
                        try:
                            if (target_date - date.fromisoformat(shown[key])).days >= repeat_days:
                                del shown[key]
                        except (ValueError, TypeError):
                            del shown[key]
            elif notification.get("is_then_and_now"):
                mark_feature_fired(state, name, "last_tan_date", target_date)
                user_state = state.setdefault("users", {}).setdefault(name, {})
                person_id = notification.get("person_id", "")
                if person_id:
                    used = user_state.setdefault("tan_persons_used", [])
                    used.append(person_id)
                    user_state["tan_persons_used"] = used[-20:]
                pair_key = notification.get("tan_pair_key", "")
                if pair_key:
                    pairs = user_state.setdefault("tan_pairs_used", [])
                    pairs.append(pair_key)
                    user_state["tan_pairs_used"] = pairs[-50:]
            elif notification.get("is_collage"):
                mark_feature_fired(state, name, "last_collage_date", target_date)
            # Track that a special fired today (one per day)
            if notification.get("is_trip") or notification.get("is_then_and_now") or notification.get("is_collage"):
                mark_special_sent_today(state, name, target_date)
    else:
        result["success"] = False

    return result


def _execute_event(
    event_type: str,
    user: dict,
    config: dict,
    state: dict,
    target_date: date,
    slot: int,
    parsed: dict,
    assets_sent: set,
    top_persons: list,
    top_person_ids: set,
    test_mode: bool,
    logger: logging.Logger,
    click_base: str,
) -> dict:
    """Execute a specific event type and return notification dict or None."""
    immich_url = config["immich"]["url"]
    api_key = user["immich_api_key"]
    settings = config["settings"]
    name = user["name"]

    messages = config.get("messages", [])
    person_messages = config.get("person_messages", [])
    video_messages = config.get("video_messages", [])
    video_person_messages = config.get("video_person_messages", [])
    memory_titles = config.get("memory_titles", [])
    person_titles = config.get("person_titles", [])
    album_messages = config.get("album_messages", [])
    video_album_messages = config.get("video_album_messages", [])
    album_titles = config.get("album_titles", [])
    tan_messages = config.get("then_and_now_messages", [])
    tan_titles = config.get("then_and_now_titles", [])
    trip_messages = config.get("trip_highlights_messages", [])
    trip_titles = config.get("trip_highlights_titles", [])

    exclude_recent_days = settings.get("exclude_recent_days", 30)
    user_album_names = user.get("album_names", [])

    if event_type == "memory":
        return prepare_memory_notification(
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
            title_templates=memory_titles,
        )

    elif event_type == "person":
        return prepare_person_notification(
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
            title_templates=person_titles,
        )

    elif event_type == "album":
        return prepare_album_notification(
            album_names=user_album_names,
            assets_sent=assets_sent,
            immich_url=immich_url,
            api_key=api_key,
            album_messages=album_messages,
            test_mode=test_mode,
            logger=logger,
            settings=settings,
            video_album_messages=video_album_messages,
            title_templates=album_titles,
            target_date=target_date,
        )

    elif event_type == "then_and_now":
        tan_min_gap = settings.get("then_and_now_min_gap", 3)
        year_range = settings.get("year_range", 5)
        try:
            user_tan_state = state.get("users", {}).get(name, {})
            used_persons = user_tan_state.get("tan_persons_used", [])
            used_pairs = user_tan_state.get("tan_pairs_used", [])
            candidate = find_then_and_now_candidate(
                immich_url=immich_url,
                api_key=api_key,
                top_persons=top_persons,
                target_date=target_date,
                min_gap=tan_min_gap,
                year_range=year_range,
                logger=logger,
                used_person_ids=used_persons,
                used_pairs=used_pairs,
            )
            if candidate:
                notification = prepare_then_and_now_notification(
                    candidate=candidate,
                    immich_url=immich_url,
                    api_key=api_key,
                    messages=tan_messages,
                    test_mode=test_mode,
                    logger=logger,
                    title_templates=tan_titles,
                )
                if notification:
                    logger.info(f"  [{name}] Sending Then & Now ({candidate['then_year']} → {candidate['now_year']})")
                return notification
        except Exception as e:
            logger.warning(f"  [{name}] Then & Now failed: {e}")
        return None

    elif event_type == "trip_highlights":
        home_cities = user.get("home_cities") or ([user["home_city"]] if user.get("home_city") else [])
        trip_min_photos = settings.get("trip_highlights_min_photos", 5)
        year_range = settings.get("year_range", 5)
        trip_repeat_days = settings.get("trip_highlights_repeat_days", 90)
        try:
            trips_shown = state.get("users", {}).get(name, {}).get("trips_shown", {})
            trip = find_trip_candidate(
                immich_url=immich_url,
                api_key=api_key,
                target_date=target_date,
                home_cities=home_cities,
                min_photos=trip_min_photos,
                year_range=year_range,
                logger=logger,
                used_trips=trips_shown,
                repeat_days=trip_repeat_days,
            )
            if trip:
                notification = prepare_trip_notification(
                    trip=trip,
                    immich_url=immich_url,
                    api_key=api_key,
                    messages=trip_messages,
                    test_mode=test_mode,
                    logger=logger,
                    title_templates=trip_titles,
                    click_base=click_base,
                )
                if notification:
                    logger.info(f"  [{name}] Sending Trip Highlights ({trip['city']}, {trip['year']})")
                return notification
        except Exception as e:
            logger.warning(f"  [{name}] Trip Highlights failed: {e}")
        return None

    elif event_type == "collage":
        from .features.collage import generate_weekly_collage
        try:
            collage_notification = generate_weekly_collage(
                user=user,
                config=config,
                target_date=target_date,
                settings=settings,
                logger=logger,
                test_mode=test_mode,
            )
            if collage_notification and collage_notification.get("has_content"):
                collage_notification["is_collage"] = True
                logger.info(f"  [{name}] Sending Weekly Collage")
                return collage_notification
        except Exception as e:
            logger.warning(f"  [{name}] Collage failed: {e}")
        return None

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Send Immich memory notifications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m notify --slot 1          # Send window 1 notification (with random delay)
  python -m notify --slot 2 --test   # Test window 2 (minimal delay)
  python -m notify --slot 1 --dry-run # Preview window 1 without sending
  python -m notify --slot 1 --force   # Force send even if already sent
  python -m notify --slot 1 --no-delay # Send immediately without random delay
        """,
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--slot", type=int, help="Notification window number (1, 2, 3, ...)")
    parser.add_argument("--check-updates", action="store_true", help="Check for new releases on GitHub")
    parser.add_argument("--test", action="store_true", help="Test mode (minimal delays, use any date)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent")
    parser.add_argument("--force", action="store_true", help="Force send even if already sent today")
    parser.add_argument("--no-delay", action="store_true", help="Skip random delay, send immediately")
    parser.add_argument("--date", help="Specific date to check (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.check_updates:
        from .update_check import check_for_updates
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        logger = logging.getLogger("immich-memories-notify")
        return check_for_updates(config_path=args.config, logger=logger)

    if not args.slot:
        parser.error("--slot is required (unless using --check-updates)")

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

    # Calculate and apply random delay for this window
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

    # Get enabled users
    users = [u for u in config.get("users", []) if u.get("enabled", True)]
    logger.info(f"Users:   {len(users)}")

    if not users:
        logger.warning("No enabled users found in config")
        return 0

    # Process each user for this window
    success_count = 0

    for user in users:
        result = process_user_window(
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

        # Save state after each user
        if not args.dry_run:
            save_state(state_file, state)

    logger.info("=" * 60)
    logger.info(f"Complete: {success_count}/{len(users)} users successful")
    logger.info("=" * 60)

    return 0 if success_count == len(users) else 1


if __name__ == "__main__":
    sys.exit(main())
