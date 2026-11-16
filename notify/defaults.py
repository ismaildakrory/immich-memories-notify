"""Single source of truth for configuration defaults.

Used by the engine (notify/config.py), the dashboard models and routers, and
the first-run config written by the dashboard. Change a default here and every
layer picks it up.
"""

ALL_EVENTS = ["memory", "person", "album", "then_and_now", "trip_highlights", "collage"]

DEFAULT_WINDOWS = [
    {"start": "08:00", "end": "09:00", "events": list(ALL_EVENTS)},
    {"start": "10:00", "end": "12:00", "events": list(ALL_EVENTS)},
    {"start": "13:00", "end": "15:00", "events": list(ALL_EVENTS)},
    {"start": "17:00", "end": "19:00", "events": list(ALL_EVENTS)},
    {"start": "20:00", "end": "22:00", "events": list(ALL_EVENTS)},
]

# Every key the engine or dashboard reads from `settings`.
DEFAULT_SETTINGS = {
    "retry": {"max_attempts": 3, "delay_seconds": 5},
    "state_file": "state/state.json",
    "log_level": "INFO",
    "top_persons_limit": 5,
    "exclude_recent_days": 30,
    "asset_repeat_days": 60,
    "skip_screenshots": True,
    "include_location": True,
    "include_album": True,
    "video_emoji": True,
    "prefer_group_photos": True,
    "min_group_size": 2,
    "year_range": 20,
    "weekly_collage_enabled": True,
    "collage_cooldown_days": 7,
    "collage_person_limit": 5,
    "collage_template": "random",
    "collage_album_name": "Weekly Highlights",
    "then_and_now_enabled": True,
    "then_and_now_min_gap": 3,
    "then_and_now_cooldown_days": 7,
    "trip_highlights_enabled": True,
    "trip_highlights_cooldown_days": 7,
    "trip_highlights_min_photos": 5,
    "trip_highlights_repeat_days": 90,
    "birthday_enabled": True,
    "notification_windows": DEFAULT_WINDOWS,
}

# Settings keys that were removed by the layered engine (v3.0) and are dropped on load.
DEPRECATED_SETTINGS = [
    "memory_notifications",
    "person_notifications",
    "fallback_notifications",
    "then_and_now_slot",
    "weekly_collage_slots",
    "weekly_collage_day",
]

# Message / title template lists, keyed by their config.yaml name.
DEFAULT_TEMPLATES = {
    "messages": [
        "A little trip back to {year}...",
        "Remember this day {years_ago} years ago?",
        "Some memories from {year} want to say hello",
        "Throwback to {year}! Take a moment to smile",
        "Once upon a time in {year}...",
        "A cozy memory from {years_ago} years ago",
        "{year} called, it has something beautiful to show you",
        "Let's revisit {year} together",
        "A gentle reminder of {year}",
        "Look what we found from {year}!",
    ],
    "person_messages": [
        "A lovely moment with {person_name}...",
        "Remember this time with {person_name}?",
        "A random treasure featuring {person_name}",
        "Look who we found! {person_name} says hello",
        "A cozy memory with {person_name}",
        "Here's a favorite moment with {person_name}",
        "{person_name} wanted to brighten your day",
        "Throwback featuring {person_name}!",
    ],
    "video_messages": [
        "Watch this moment from {year}...",
        "A video memory from {years_ago} years ago",
        "Relive this video from {year}",
        "Press play on {year}",
        "A moving memory from {years_ago} years ago",
    ],
    "video_person_messages": [
        "Watch this moment with {person_name}...",
        "A video featuring {person_name}",
        "Press play on this memory with {person_name}",
        "Relive this moment with {person_name}",
    ],
    "then_and_now_messages": [
        "Look how much {person_name} has changed! {then_year} vs {now_year}",
        "{gap} years between these moments with {person_name}",
        "Then and now — {person_name}, {gap} years apart",
        "Time flies... {person_name} in {then_year} and {now_year}",
        "From {then_year} to {now_year} with {person_name}",
    ],
    "trip_highlights_messages": [
        "{gap} years ago in {city}, {country}! \U0001f30d",
        "Remember this trip to {city}? Back in {year}!",
        "{city}, {country} — {gap} years have passed",
        "Flashback to {city}, {year} ✈️",
        "What a trip! {city}, {country} — {year}",
    ],
    "album_messages": [
        "A random moment from {album_name}",
        "Something from {album_name} to brighten your day",
        "From your {album_name} collection...",
        "A surprise from {album_name}!",
    ],
    "video_album_messages": [
        "Watch this clip from {album_name}...",
        "A video from your {album_name} album",
    ],
    "memory_titles": ["{years_ago} years ago today"],
    "person_titles": ["A memory with {person_name}"],
    "collage_titles": ["Weekly Highlights"],
    "then_and_now_titles": ["Then & Now — {person_name}"],
    "trip_highlights_titles": ["Trip Highlights"],
    "album_titles": ["{album_name}"],
    "birthday_messages": [
        "Happy Birthday, {person_name}! \U0001f382",
        "It's {person_name}'s special day! \U0001f389",
        "Wishing {person_name} a wonderful birthday! \U0001f381",
        "Cheers to {person_name} on their birthday! \U0001f973",
    ],
    "birthday_titles": ["Happy Birthday, {person_name}! \U0001f389"],
}


def _deep_copy(value):
    import copy

    return copy.deepcopy(value)


def build_default_config() -> dict:
    """Full config.yaml content for a fresh install (no users)."""
    return {
        "immich": {"url": "${IMMICH_URL}", "external_url": "${IMMICH_EXTERNAL_URL}"},
        "ntfy": {"url": "${NTFY_URL}", "external_url": "${NTFY_EXTERNAL_URL}"},
        "users": [],
        "settings": _deep_copy(DEFAULT_SETTINGS),
        **_deep_copy(DEFAULT_TEMPLATES),
    }


def apply_setting_defaults(settings: dict) -> dict:
    """Fill missing settings keys in place (deep-copied so callers can't mutate the defaults)."""
    for key, value in DEFAULT_SETTINGS.items():
        settings.setdefault(key, _deep_copy(value))
    return settings


def apply_template_defaults(config: dict) -> dict:
    """Fill missing template lists in place. An explicitly empty list is respected."""
    for key, value in DEFAULT_TEMPLATES.items():
        config.setdefault(key, list(value))
    return config
