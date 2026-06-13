"""Pydantic models for the dashboard API."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# Settings Models
class RetrySettings(BaseModel):
    max_attempts: int = 3
    delay_seconds: int = 5


class NotificationWindow(BaseModel):
    start: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="Start time (HH:MM)")
    end: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="End time (HH:MM)")


class Settings(BaseModel):
    retry: RetrySettings = Field(default_factory=RetrySettings)
    state_file: str = Field("state/state.json", max_length=256)
    log_level: str = Field("INFO", max_length=10)
    memory_notifications: int = Field(3, ge=0, le=20)
    person_notifications: int = Field(2, ge=0, le=20)
    fallback_notifications: int = Field(3, ge=0, le=20)
    top_persons_limit: int = Field(5, ge=1, le=50)
    exclude_recent_days: int = Field(30, ge=0, le=3650)
    include_location: bool = True
    include_album: bool = True
    video_emoji: bool = True
    prefer_group_photos: bool = True
    min_group_size: int = Field(2, ge=1, le=20)
    year_range: int = Field(5, ge=1, le=50)
    notification_windows: List[NotificationWindow] = Field(default_factory=list)
    weekly_collage_enabled: bool = False
    weekly_collage_day: int = Field(6, ge=0, le=6)
    weekly_collage_slots: int = Field(1, ge=1, le=10)
    collage_person_limit: int = Field(5, ge=1, le=20)
    collage_template: str = Field("grid", max_length=64)
    collage_album_name: str = Field("Weekly Highlights", max_length=128)
    then_and_now_enabled: bool = True
    then_and_now_cooldown_days: int = Field(7, ge=0, le=365)
    then_and_now_min_gap: int = Field(3, ge=1, le=50)
    trip_highlights_enabled: bool = True
    trip_highlights_cooldown_days: int = Field(7, ge=0, le=365)
    trip_highlights_min_photos: int = Field(5, ge=1, le=100)
    birthday_enabled: bool = True


class UserInfo(BaseModel):
    """User info with sensitive fields redacted."""
    name: str
    ntfy_topic: str
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
    birthday_messages: Optional[List[str]] = None
    birthday_titles: Optional[List[str]] = None


class SettingsUpdate(BaseModel):
    """Partial settings update."""
    memory_notifications: Optional[int] = Field(None, ge=0, le=20)
    person_notifications: Optional[int] = Field(None, ge=0, le=20)
    fallback_notifications: Optional[int] = Field(None, ge=0, le=20)
    top_persons_limit: Optional[int] = Field(None, ge=1, le=50)
    exclude_recent_days: Optional[int] = Field(None, ge=0, le=3650)
    include_location: Optional[bool] = None
    include_album: Optional[bool] = None
    video_emoji: Optional[bool] = None
    prefer_group_photos: Optional[bool] = None
    min_group_size: Optional[int] = Field(None, ge=1, le=20)
    year_range: Optional[int] = Field(None, ge=1, le=50)
    weekly_collage_enabled: Optional[bool] = None
    weekly_collage_day: Optional[int] = Field(None, ge=0, le=6)
    weekly_collage_slots: Optional[int] = Field(None, ge=1, le=10)
    collage_person_limit: Optional[int] = Field(None, ge=1, le=20)
    collage_template: Optional[str] = Field(None, max_length=64)
    collage_album_name: Optional[str] = Field(None, max_length=128)
    then_and_now_enabled: Optional[bool] = None
    then_and_now_cooldown_days: Optional[int] = Field(None, ge=0, le=365)
    then_and_now_min_gap: Optional[int] = Field(None, ge=1, le=50)
    trip_highlights_enabled: Optional[bool] = None
    trip_highlights_cooldown_days: Optional[int] = Field(None, ge=0, le=365)
    trip_highlights_min_photos: Optional[int] = Field(None, ge=1, le=100)
    birthday_enabled: Optional[bool] = None


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
