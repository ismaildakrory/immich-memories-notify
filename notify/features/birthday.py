"""Birthday notification — send a photo when it's someone's birthday."""

import logging
import random
from datetime import date
from typing import List, Optional

from ..immich import fetch_people, get_random_person_photo


def find_birthday_people(
    immich_url: str,
    api_key: str,
    target_date: date = None,
    logger: logging.Logger = None,
    people: list = None,
) -> List[dict]:
    """Find people whose birthday matches today's month and day."""
    if target_date is None:
        target_date = date.today()

    if people is None:
        people = fetch_people(immich_url, api_key)
    matches = []

    for person in people:
        birth_date = person.get("birthDate")
        if not birth_date or not person.get("name"):
            continue
        try:
            bd = date.fromisoformat(birth_date.split("T")[0])
            if bd.month == target_date.month and bd.day == target_date.day:
                matches.append(person)
        except (ValueError, AttributeError):
            continue

    if logger:
        if matches:
            names = ", ".join(p["name"] for p in matches)
            logger.info(f"  Birthday today: {names}")
        else:
            logger.debug(f"  No birthdays today ({target_date.strftime('%b %d')})")

    return matches


def prepare_birthday_notification(
    birthday_person: dict,
    immich_url: str,
    api_key: str,
    messages: list,
    test_mode: bool,
    logger: logging.Logger = None,
    title_templates: list = None,
    exclude_asset_ids: set = None,
    exclude_days: int = 0,
) -> Optional[dict]:
    """Pick a photo of the birthday person and build the notification."""
    person_name = birthday_person["name"]
    person_id = birthday_person["id"]

    top_persons = [{"id": person_id, "name": person_name, "asset_count": 0}]
    result = get_random_person_photo(
        immich_url=immich_url,
        api_key=api_key,
        top_persons=top_persons,
        exclude_days=exclude_days,
        exclude_asset_ids=exclude_asset_ids,
        logger=logger,
    )

    if not result:
        if logger:
            logger.warning(f"  No photos found for birthday person {person_name}")
        return None

    asset = result["asset"]
    asset_id = asset.get("id")

    if messages:
        message = random.choice(messages).format(person_name=person_name)
    else:
        message = f"Happy Birthday, {person_name}! 🎂"

    if title_templates:
        try:
            title = random.choice(title_templates).format(person_name=person_name)
        except (KeyError, ValueError):
            title = f"Happy Birthday, {person_name}! 🎉"
    else:
        title = f"Happy Birthday, {person_name}! 🎉"

    if test_mode:
        title = "[TEST] " + title

    return {
        "title": title,
        "message": message,
        "has_content": True,
        "asset_id": asset_id,
        "person_name": person_name,
        "is_birthday": True,
        "is_video": asset.get("type") == "VIDEO",
    }
