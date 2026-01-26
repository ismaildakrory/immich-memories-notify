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
    state_file: str = "state.json"
    log_level: str = "INFO"
    memory_notifications: int = 3
    person_notifications: int = 2
    fallback_notifications: int = 3
    top_persons_limit: int = 5
    exclude_recent_days: int = 30
    include_location: bool = True
    include_album: bool = True
    video_emoji: bool = True
    prefer_group_photos: bool = True
    min_group_size: int = 2
    notification_windows: List[NotificationWindow] = Field(default_factory=list)


class UserInfo(BaseModel):
    """User info with sensitive fields redacted."""
    name: str
    ntfy_topic: str
    enabled: bool = True


class FullConfig(BaseModel):
    """Full configuration response."""
    settings: Settings
    users: List[UserInfo]
    messages: List[str]
    person_messages: List[str]
    video_messages: List[str]
    video_person_messages: List[str]


# Update Models
class WindowsUpdate(BaseModel):
    notification_windows: List[NotificationWindow]


class MessagesUpdate(BaseModel):
    messages: Optional[List[str]] = None
    person_messages: Optional[List[str]] = None
    video_messages: Optional[List[str]] = None
    video_person_messages: Optional[List[str]] = None


class SettingsUpdate(BaseModel):
    """Partial settings update."""
    memory_notifications: Optional[int] = None
    person_notifications: Optional[int] = None
    fallback_notifications: Optional[int] = None
    top_persons_limit: Optional[int] = None
    exclude_recent_days: Optional[int] = None
    include_location: Optional[bool] = None
    include_album: Optional[bool] = None
    video_emoji: Optional[bool] = None
    prefer_group_photos: Optional[bool] = None
    min_group_size: Optional[int] = None


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
    version: str = "1.0.0"
