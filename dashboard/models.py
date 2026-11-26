"""Pydantic models for the dashboard API."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from notify.defaults import ALL_EVENTS, DEFAULT_SETTINGS

# Settings Models
D = DEFAULT_SETTINGS


class RetrySettings(BaseModel):
    max_attempts: int = D["retry"]["max_attempts"]
    delay_seconds: int = D["retry"]["delay_seconds"]


class NotificationWindow(BaseModel):
    start: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="Start time (HH:MM)")
    end: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="End time (HH:MM)")
    events: List[str] = Field(
        default_factory=lambda: list(ALL_EVENTS),
        description="Event types this window can send",
    )


class Settings(BaseModel):
    """Full settings block. Defaults come from notify/defaults.py; bounds are enforced here."""

    retry: RetrySettings = Field(default_factory=RetrySettings)
    state_file: str = Field(D["state_file"], max_length=256)
    log_level: str = Field(D["log_level"], max_length=10)
    top_persons_limit: int = Field(D["top_persons_limit"], ge=1, le=50)
    exclude_recent_days: int = Field(D["exclude_recent_days"], ge=0, le=3650)
    asset_repeat_days: int = Field(D["asset_repeat_days"], ge=0, le=3650)
    skip_screenshots: bool = D["skip_screenshots"]
    click_links: str = Field(D["click_links"], pattern=r"^(app|web)$")
    include_location: bool = D["include_location"]
    include_album: bool = D["include_album"]
    video_emoji: bool = D["video_emoji"]
    prefer_group_photos: bool = D["prefer_group_photos"]
    min_group_size: int = Field(D["min_group_size"], ge=1, le=20)
    year_range: int = Field(D["year_range"], ge=1, le=100)
    notification_windows: List[NotificationWindow] = Field(default_factory=list)
    weekly_collage_enabled: bool = D["weekly_collage_enabled"]
    collage_cooldown_days: int = Field(D["collage_cooldown_days"], ge=1, le=365)
    collage_person_limit: int = Field(D["collage_person_limit"], ge=1, le=20)
    collage_template: str = Field(D["collage_template"], max_length=64)
    collage_album_name: str = Field(D["collage_album_name"], max_length=128)
    then_and_now_enabled: bool = D["then_and_now_enabled"]
    then_and_now_cooldown_days: int = Field(D["then_and_now_cooldown_days"], ge=0, le=365)
    then_and_now_min_gap: int = Field(D["then_and_now_min_gap"], ge=1, le=50)
    trip_highlights_enabled: bool = D["trip_highlights_enabled"]
    trip_highlights_cooldown_days: int = Field(D["trip_highlights_cooldown_days"], ge=0, le=365)
    trip_highlights_min_photos: int = Field(D["trip_highlights_min_photos"], ge=1, le=100)
    trip_highlights_repeat_days: int = Field(D["trip_highlights_repeat_days"], ge=0, le=3650)
    birthday_enabled: bool = D["birthday_enabled"]
    context_themes: List[str] = Field(default_factory=lambda: list(D["context_themes"]))
    lane_photos: int = Field(D["lane_photos"], ge=3, le=20)
    lane_keep_days: int = Field(D["lane_keep_days"], ge=1, le=90)


class UserInfo(BaseModel):
    """User info with sensitive fields redacted."""
    name: str
    ntfy_topic: str = ""
    ntfy_priority: str = "default"
    notification_service: str = "ntfy"
    enabled: bool = True
    home_cities: List[str] = Field(default_factory=list)
    album_names: List[str] = Field(default_factory=list)


class FullConfig(BaseModel):
    """Full configuration response."""
    settings: Settings
    users: List[UserInfo]
    messages: List[str]
    person_messages: List[str]
    video_messages: List[str]
    video_person_messages: List[str]
    then_and_now_messages: List[str]
    trip_highlights_messages: List[str]
    album_messages: List[str]
    video_album_messages: List[str]
    memory_titles: List[str]
    person_titles: List[str]
    collage_titles: List[str]
    then_and_now_titles: List[str]
    trip_highlights_titles: List[str]
    album_titles: List[str]
    context_messages: List[str]
    context_titles: List[str]
    birthday_messages: List[str]
    birthday_titles: List[str]


# Update Models
class WindowsUpdate(BaseModel):
    notification_windows: List[NotificationWindow]


class MessagesUpdate(BaseModel):
    messages: Optional[List[str]] = None
    person_messages: Optional[List[str]] = None
    video_messages: Optional[List[str]] = None
    video_person_messages: Optional[List[str]] = None
    then_and_now_messages: Optional[List[str]] = None
    trip_highlights_messages: Optional[List[str]] = None
    album_messages: Optional[List[str]] = None
    video_album_messages: Optional[List[str]] = None
    memory_titles: Optional[List[str]] = None
    person_titles: Optional[List[str]] = None
    collage_titles: Optional[List[str]] = None
    then_and_now_titles: Optional[List[str]] = None
    trip_highlights_titles: Optional[List[str]] = None
    album_titles: Optional[List[str]] = None
    context_messages: Optional[List[str]] = None
    context_titles: Optional[List[str]] = None
    birthday_messages: Optional[List[str]] = None
    birthday_titles: Optional[List[str]] = None


class SettingsUpdate(BaseModel):
    """Partial settings update."""
    top_persons_limit: Optional[int] = Field(None, ge=1, le=50)
    exclude_recent_days: Optional[int] = Field(None, ge=0, le=3650)
    asset_repeat_days: Optional[int] = Field(None, ge=0, le=3650)
    skip_screenshots: Optional[bool] = None
    click_links: Optional[str] = Field(None, pattern=r"^(app|web)$")
    include_location: Optional[bool] = None
    include_album: Optional[bool] = None
    video_emoji: Optional[bool] = None
    prefer_group_photos: Optional[bool] = None
    min_group_size: Optional[int] = Field(None, ge=1, le=20)
    year_range: Optional[int] = Field(None, ge=1, le=100)
    weekly_collage_enabled: Optional[bool] = None
    collage_cooldown_days: Optional[int] = Field(None, ge=1, le=365)
    collage_person_limit: Optional[int] = Field(None, ge=1, le=20)
    collage_template: Optional[str] = Field(None, max_length=64)
    collage_album_name: Optional[str] = Field(None, max_length=128)
    then_and_now_enabled: Optional[bool] = None
    then_and_now_cooldown_days: Optional[int] = Field(None, ge=0, le=365)
    then_and_now_min_gap: Optional[int] = Field(None, ge=1, le=50)
    trip_highlights_enabled: Optional[bool] = None
    trip_highlights_cooldown_days: Optional[int] = Field(None, ge=0, le=365)
    trip_highlights_min_photos: Optional[int] = Field(None, ge=1, le=100)
    trip_highlights_repeat_days: Optional[int] = Field(None, ge=0, le=3650)
    birthday_enabled: Optional[bool] = None
    context_themes: Optional[List[str]] = None
    lane_photos: Optional[int] = Field(None, ge=3, le=20)
    lane_keep_days: Optional[int] = Field(None, ge=1, le=90)


class UserEnabledUpdate(BaseModel):
    enabled: bool


# State Models
class UserSlotState(BaseModel):
    slots_date: Optional[str] = None
    slots_sent: List[int] = Field(default_factory=list)
    assets_sent_today: List[str] = Field(default_factory=list)
    last_slot_time: Optional[str] = None


class StateResponse(BaseModel):
    users: Dict[str, UserSlotState] = Field(default_factory=dict)


# Test Models
class TestTriggerResponse(BaseModel):
    success: bool
    message: str
    output: Optional[str] = None


# Health Model
class HealthResponse(BaseModel):
    status: str
    version: str
