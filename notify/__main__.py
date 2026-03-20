"""
Immich Memories Notify
======================
Sends daily memory notifications to all configured users.

Usage:
    python -m notify                 # Send notifications for today
    python -m notify --test          # Test mode (uses any available date)
    python -m notify --dry-run       # Show what would be sent without sending
    python -m notify --force         # Force send even if already sent today
    python -m notify --config FILE   # Use custom config file
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime

from .config import (
    get_assets_sent_today,
    get_slots_sent_today,
    is_feature_ready,
    load_config,
    load_state,
    mark_feature_fired,
    mark_slot_sent,
    save_state,
    setup_logging,
)
from .features.collage import is_collage_day, process_collage_slot
from .features.memories import prepare_memory_notification
from .features.persons import prepare_person_notification
from .features.then_and_now import find_then_and_now_candidate, prepare_then_and_now_notification
from .features.trip import find_trip_candidate, prepare_trip_notification
from .immich import (
    fetch_memories,
    filter_todays_memories,
    get_top_persons,
    parse_memories,
)
from .ntfy import send_single_notification
from .utils import calculate_random_delay, with_retry


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


def main():
    parser = argparse.ArgumentParser(
        description="Send Immich memory notifications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m notify --slot 1          # Send slot 1 notification (with random delay)
  python -m notify --slot 2 --test   # Test slot 2 (minimal delay)
  python -m notify --slot 1 --dry-run # Preview slot 1 without sending
  python -m notify --slot 1 --force   # Force send even if already sent
  python -m notify --slot 1 --no-delay # Send immediately without random delay
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
