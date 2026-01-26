"""Settings management API endpoints."""

import json
from pathlib import Path
from typing import List

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..models import (
    FullConfig,
    NotificationWindow,
    Settings,
    SettingsUpdate,
    UserInfo,
    WindowsUpdate,
    MessagesUpdate,
    UserEnabledUpdate,
)
from ..utils.filelock import read_lock, write_lock

router = APIRouter()


def get_config_path(request: Request) -> str:
    """Get config path from app state."""
    return request.app.state.config_path


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    with read_lock(config_path):
        with open(config_path) as f:
            return yaml.safe_load(f)


def save_config(config_path: str, config: dict):
    """Save configuration to YAML file."""
    with write_lock(config_path):
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


@router.get("/", response_model=FullConfig)
async def get_settings(request: Request):
    """Get full configuration (with sensitive fields redacted)."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading config: {str(e)}")

    # Build settings
    settings_data = config.get("settings", {})
    settings = Settings(
        retry=settings_data.get("retry", {}),
        state_file=settings_data.get("state_file", "state.json"),
        log_level=settings_data.get("log_level", "INFO"),
        memory_notifications=settings_data.get("memory_notifications", 3),
        person_notifications=settings_data.get("person_notifications", 2),
        fallback_notifications=settings_data.get("fallback_notifications", 3),
        top_persons_limit=settings_data.get("top_persons_limit", 5),
        exclude_recent_days=settings_data.get("exclude_recent_days", 30),
        include_location=settings_data.get("include_location", True),
        include_album=settings_data.get("include_album", True),
        video_emoji=settings_data.get("video_emoji", True),
        prefer_group_photos=settings_data.get("prefer_group_photos", True),
        min_group_size=settings_data.get("min_group_size", 2),
        notification_windows=[
            NotificationWindow(**w) for w in settings_data.get("notification_windows", [])
        ],
    )

    # Redact sensitive user info
    users = [
        UserInfo(
            name=u.get("name", ""),
            ntfy_topic=u.get("ntfy_topic", ""),
            enabled=u.get("enabled", True),
        )
        for u in config.get("users", [])
    ]

    return FullConfig(
        settings=settings,
        users=users,
        messages=config.get("messages", []),
        person_messages=config.get("person_messages", []),
        video_messages=config.get("video_messages", []),
        video_person_messages=config.get("video_person_messages", []),
    )


@router.get("/windows", response_model=List[NotificationWindow])
async def get_windows(request: Request):
    """Get notification windows."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    windows = config.get("settings", {}).get("notification_windows", [])
    return [NotificationWindow(**w) for w in windows]


@router.put("/windows")
async def update_windows(request: Request, update: WindowsUpdate):
    """Update notification windows."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    if "settings" not in config:
        config["settings"] = {}

    config["settings"]["notification_windows"] = [
        {"start": w.start, "end": w.end} for w in update.notification_windows
    ]

    save_config(config_path, config)
    return {"message": "Windows updated", "count": len(update.notification_windows)}


@router.get("/messages")
async def get_messages(request: Request):
    """Get all message templates."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    return {
        "messages": config.get("messages", []),
        "person_messages": config.get("person_messages", []),
        "video_messages": config.get("video_messages", []),
        "video_person_messages": config.get("video_person_messages", []),
    }


@router.put("/messages")
async def update_messages(request: Request, update: MessagesUpdate):
    """Update message templates."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    if update.messages is not None:
        config["messages"] = update.messages
    if update.person_messages is not None:
        config["person_messages"] = update.person_messages
    if update.video_messages is not None:
        config["video_messages"] = update.video_messages
    if update.video_person_messages is not None:
        config["video_person_messages"] = update.video_person_messages

    save_config(config_path, config)
    return {"message": "Messages updated"}


@router.put("/")
async def update_settings(request: Request, update: SettingsUpdate):
    """Update general settings."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    if "settings" not in config:
        config["settings"] = {}

    settings = config["settings"]
    update_dict = update.model_dump(exclude_none=True)

    for key, value in update_dict.items():
        settings[key] = value

    save_config(config_path, config)
    return {"message": "Settings updated", "updated_fields": list(update_dict.keys())}


@router.get("/users", response_model=List[UserInfo])
async def get_users(request: Request):
    """Get users (with sensitive fields redacted)."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    return [
        UserInfo(
            name=u.get("name", ""),
            ntfy_topic=u.get("ntfy_topic", ""),
            enabled=u.get("enabled", True),
        )
        for u in config.get("users", [])
    ]


@router.put("/users/{name}/enabled")
async def toggle_user(request: Request, name: str, update: UserEnabledUpdate):
    """Toggle user enabled status."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    users = config.get("users", [])
    user_found = False

    for user in users:
        if user.get("name") == name:
            user["enabled"] = update.enabled
            user_found = True
            break

    if not user_found:
        raise HTTPException(status_code=404, detail=f"User '{name}' not found")

    save_config(config_path, config)
    return {"message": f"User '{name}' enabled={update.enabled}"}


class NewUser(BaseModel):
    name: str
    ntfy_topic: str
    ntfy_username: str = ""
    enabled: bool = True


class RenameUser(BaseModel):
    new_name: str


@router.post("/users")
async def add_user(request: Request, user: NewUser):
    """Add a new user."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    users = config.get("users", [])

    # Check if user already exists
    for u in users:
        if u.get("name") == user.name:
            raise HTTPException(status_code=400, detail=f"User '{user.name}' already exists")

    # Add new user with placeholder for secrets
    new_user = {
        "name": user.name,
        "immich_api_key": "${IMMICH_API_KEY_" + user.name.upper().replace(" ", "_") + "}",
        "ntfy_topic": user.ntfy_topic,
        "ntfy_username": user.ntfy_username or user.name.lower(),
        "ntfy_password": "${NTFY_PASSWORD_" + user.name.upper().replace(" ", "_") + "}",
        "enabled": user.enabled,
    }

    users.append(new_user)
    config["users"] = users
    save_config(config_path, config)

    return {
        "message": f"User '{user.name}' added",
        "note": "Remember to add API key and password to .env file",
        "env_vars_needed": [
            f"IMMICH_API_KEY_{user.name.upper().replace(' ', '_')}",
            f"NTFY_PASSWORD_{user.name.upper().replace(' ', '_')}",
        ],
    }


@router.delete("/users/{name}")
async def delete_user(request: Request, name: str):
    """Delete a user."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    users = config.get("users", [])
    original_count = len(users)

    users = [u for u in users if u.get("name") != name]

    if len(users) == original_count:
        raise HTTPException(status_code=404, detail=f"User '{name}' not found")

    config["users"] = users
    save_config(config_path, config)

    return {"message": f"User '{name}' deleted"}


@router.put("/users/{name}/rename")
async def rename_user(request: Request, name: str, update: RenameUser):
    """Rename a user."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    users = config.get("users", [])

    # Check if new name already exists
    for u in users:
        if u.get("name") == update.new_name:
            raise HTTPException(status_code=400, detail=f"User '{update.new_name}' already exists")

    # Find and rename user
    user_found = False
    for u in users:
        if u.get("name") == name:
            u["name"] = update.new_name
            user_found = True
            break

    if not user_found:
        raise HTTPException(status_code=404, detail=f"User '{name}' not found")

    save_config(config_path, config)
    return {"message": f"User '{name}' renamed to '{update.new_name}'"}
