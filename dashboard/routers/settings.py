"""Settings management API endpoints."""

import json
import os
import re
from pathlib import Path
from typing import List

import requests as http_requests
import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

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
from ..utils.filelock import exclusive_lock, read_lock, write_lock
from ..crontab import reload_scheduler

router = APIRouter()


def get_config_path(request: Request) -> str:
    """Get config path from app state."""
    return request.app.state.config_path


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file (shared lock)."""
    if not Path(config_path).is_file():
        return {"immich": {}, "ntfy": {}, "users": [], "settings": {}}
    with read_lock(config_path):
        with open(config_path) as f:
            return yaml.safe_load(f) or {}


def save_config(config_path: str, config: dict):
    """Save configuration to YAML file (exclusive lock)."""
    Path(config_path).parent.mkdir(parents=True, exist_ok=True)
    with write_lock(config_path):
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_config_exclusive(config_path: str) -> tuple:
    """Load config under exclusive lock for read-modify-write. Returns (config, lock_context).

    Usage:
        with exclusive_lock(config_path):
            config = _read_yaml(config_path)
            # modify config...
            _write_yaml(config_path, config)
    """
    if not Path(config_path).is_file():
        return {"immich": {}, "ntfy": {}, "users": [], "settings": {}}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def _write_yaml(config_path: str, config: dict):
    """Write config without acquiring a new lock (caller holds exclusive_lock)."""
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())


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
        state_file=settings_data.get("state_file", "state/state.json"),
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
        weekly_collage_enabled=settings_data.get("weekly_collage_enabled", False),
        weekly_collage_day=settings_data.get("weekly_collage_day", 6),
        weekly_collage_slots=settings_data.get("weekly_collage_slots", 1),
        collage_person_limit=settings_data.get("collage_person_limit", 5),
        year_range=settings_data.get("year_range",
                   settings_data.get("collage_year_range", 5)),
        collage_template=settings_data.get("collage_template", "grid"),
        collage_album_name=settings_data.get("collage_album_name", "Weekly Highlights"),
        then_and_now_enabled=settings_data.get("then_and_now_enabled", True),
        then_and_now_cooldown_days=settings_data.get("then_and_now_cooldown_days", 7),
        then_and_now_min_gap=settings_data.get("then_and_now_min_gap", 3),
        trip_highlights_enabled=settings_data.get("trip_highlights_enabled", True),
        trip_highlights_cooldown_days=settings_data.get("trip_highlights_cooldown_days", 7),
        trip_highlights_min_photos=settings_data.get("trip_highlights_min_photos", 5),
        birthday_enabled=settings_data.get("birthday_enabled", True),
    )

    # Redact sensitive user info
    users = [
        UserInfo(
            name=u.get("name", ""),
            ntfy_topic=u.get("ntfy_topic", ""),
            enabled=u.get("enabled", True),
            home_cities=u.get("home_cities") or ([u["home_city"]] if u.get("home_city") else []),
            album_names=u.get("album_names", []),
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
        then_and_now_messages=config.get("then_and_now_messages", []),
        trip_highlights_messages=config.get("trip_highlights_messages", []),
        album_messages=config.get("album_messages", []),
        video_album_messages=config.get("video_album_messages", []),
        memory_titles=config.get("memory_titles", []),
        person_titles=config.get("person_titles", []),
        collage_titles=config.get("collage_titles", []),
        then_and_now_titles=config.get("then_and_now_titles", []),
        trip_highlights_titles=config.get("trip_highlights_titles", []),
        album_titles=config.get("album_titles", []),
        birthday_messages=config.get("birthday_messages", []),
        birthday_titles=config.get("birthday_titles", []),
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
async def update_windows(request: Request, update: WindowsUpdate, background_tasks: BackgroundTasks):
    """Update notification windows."""
    config_path = get_config_path(request)

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            if "settings" not in config:
                config["settings"] = {}
            config["settings"]["notification_windows"] = [
                {"start": w.start, "end": w.end} for w in update.notification_windows
            ]
            _write_yaml(config_path, config)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    background_tasks.add_task(reload_scheduler, config_path)

    return {"message": "Windows updated, scheduler reloaded", "count": len(update.notification_windows)}


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
        "then_and_now_messages": config.get("then_and_now_messages", []),
        "trip_highlights_messages": config.get("trip_highlights_messages", []),
        "album_messages": config.get("album_messages", []),
        "video_album_messages": config.get("video_album_messages", []),
        "memory_titles": config.get("memory_titles", []),
        "person_titles": config.get("person_titles", []),
        "collage_titles": config.get("collage_titles", []),
        "then_and_now_titles": config.get("then_and_now_titles", []),
        "trip_highlights_titles": config.get("trip_highlights_titles", []),
        "album_titles": config.get("album_titles", []),
        "birthday_messages": config.get("birthday_messages", []),
        "birthday_titles": config.get("birthday_titles", []),
    }


@router.put("/messages")
async def update_messages(request: Request, update: MessagesUpdate):
    """Update message templates."""
    config_path = get_config_path(request)

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            if update.messages is not None:
                config["messages"] = update.messages
            if update.person_messages is not None:
                config["person_messages"] = update.person_messages
            if update.video_messages is not None:
                config["video_messages"] = update.video_messages
            if update.video_person_messages is not None:
                config["video_person_messages"] = update.video_person_messages
            if update.then_and_now_messages is not None:
                config["then_and_now_messages"] = update.then_and_now_messages
            if update.trip_highlights_messages is not None:
                config["trip_highlights_messages"] = update.trip_highlights_messages
            if update.album_messages is not None:
                config["album_messages"] = update.album_messages
            if update.video_album_messages is not None:
                config["video_album_messages"] = update.video_album_messages
            if update.memory_titles is not None:
                config["memory_titles"] = update.memory_titles
            if update.person_titles is not None:
                config["person_titles"] = update.person_titles
            if update.collage_titles is not None:
                config["collage_titles"] = update.collage_titles
            if update.then_and_now_titles is not None:
                config["then_and_now_titles"] = update.then_and_now_titles
            if update.trip_highlights_titles is not None:
                config["trip_highlights_titles"] = update.trip_highlights_titles
            if update.album_titles is not None:
                config["album_titles"] = update.album_titles
            if update.birthday_messages is not None:
                config["birthday_messages"] = update.birthday_messages
            if update.birthday_titles is not None:
                config["birthday_titles"] = update.birthday_titles
            _write_yaml(config_path, config)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    return {"message": "Messages updated"}


@router.put("/")
async def update_settings(request: Request, update: SettingsUpdate):
    """Update general settings."""
    config_path = get_config_path(request)
    update_dict = update.model_dump(exclude_none=True)

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            if "settings" not in config:
                config["settings"] = {}
            for key, value in update_dict.items():
                config["settings"][key] = value
            _write_yaml(config_path, config)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

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
            home_cities=u.get("home_cities") or ([u["home_city"]] if u.get("home_city") else []),
            album_names=u.get("album_names", []),
        )
        for u in config.get("users", [])
    ]


@router.put("/users/{name}/enabled")
async def toggle_user(request: Request, name: str, update: UserEnabledUpdate):
    """Toggle user enabled status."""
    config_path = get_config_path(request)

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            users = config.get("users", [])
            user_found = False
            for user in users:
                if user.get("name") == name:
                    user["enabled"] = update.enabled
                    user_found = True
                    break
            if not user_found:
                raise HTTPException(status_code=404, detail=f"User '{name}' not found")
            _write_yaml(config_path, config)
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    return {"message": f"User '{name}' enabled={update.enabled}"}


class NewUser(BaseModel):
    name: str = Field(..., max_length=64, pattern=r"^[a-zA-Z0-9 _\-؀-ۿ]+$")
    ntfy_topic: str = Field(..., max_length=256, pattern=r"^[a-zA-Z0-9_\-]+$")
    ntfy_username: str = Field("", max_length=64)
    enabled: bool = True


class RenameUser(BaseModel):
    new_name: str = Field(..., max_length=64, pattern=r"^[a-zA-Z0-9 _\-؀-ۿ]+$")


@router.post("/users")
async def add_user(request: Request, user: NewUser):
    """Add a new user."""
    config_path = get_config_path(request)

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            users = config.get("users", [])

            for u in users:
                if u.get("name") == user.name:
                    raise HTTPException(status_code=400, detail=f"User '{user.name}' already exists")

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
            _write_yaml(config_path, config)
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

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
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            users = config.get("users", [])
            original_count = len(users)
            users = [u for u in users if u.get("name") != name]
            if len(users) == original_count:
                raise HTTPException(status_code=404, detail=f"User '{name}' not found")
            config["users"] = users
            _write_yaml(config_path, config)
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    return {"message": f"User '{name}' deleted"}


@router.put("/users/{name}/home_cities")
async def set_user_home_cities(request: Request, name: str, body: dict):
    """Set home cities for a user (excluded from Trip Highlights)."""
    config_path = get_config_path(request)

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            users = config.get("users", [])
            user_found = False
            for user in users:
                if user.get("name") == name:
                    user["home_cities"] = body.get("home_cities", [])
                    user.pop("home_city", None)
                    user_found = True
                    break
            if not user_found:
                raise HTTPException(status_code=404, detail=f"User '{name}' not found")
            _write_yaml(config_path, config)
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    return {"message": f"User '{name}' home_cities updated"}


def _resolve_user_api_key(user: dict) -> str:
    """Resolve a user's Immich API key from env var reference."""
    from .secrets import load_env_file, ENV_PATH
    ref = user.get("immich_api_key", "")
    match = re.match(r'\$\{(\w+)\}', ref)
    if match:
        env_vars = load_env_file(ENV_PATH)
        return env_vars.get(match.group(1), "")
    return ref


@router.get("/users/{name}/cities")
async def get_user_cities(request: Request, name: str):
    """Fetch unique cities from a user's photos in Immich."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    user = next((u for u in config.get("users", []) if u.get("name") == name), None)
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{name}' not found")

    api_key = _resolve_user_api_key(user)
    if not api_key:
        raise HTTPException(status_code=400, detail="User has no API key configured")

    immich_url = os.environ.get("IMMICH_URL", "").rstrip("/")
    if not immich_url:
        raise HTTPException(status_code=400, detail="IMMICH_URL not configured")

    cities = set()
    try:
        headers = {"Accept": "application/json", "x-api-key": api_key}
        resp = http_requests.get(
            f"{immich_url}/api/search/cities",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        for asset in resp.json():
            exif = asset.get("exifInfo") or {}
            city = (exif.get("city") or "").strip()
            if city:
                cities.add(city)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from Immich: {e}")

    return {"cities": sorted(cities)}


@router.get("/users/{name}/albums")
async def get_user_albums(request: Request, name: str):
    """Fetch albums from Immich for a user."""
    config_path = get_config_path(request)

    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    user = next((u for u in config.get("users", []) if u.get("name") == name), None)
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{name}' not found")

    api_key = _resolve_user_api_key(user)
    if not api_key:
        raise HTTPException(status_code=400, detail="User has no API key configured")

    immich_url = os.environ.get("IMMICH_URL", "").rstrip("/")
    if not immich_url:
        raise HTTPException(status_code=400, detail="IMMICH_URL not configured")

    try:
        headers = {"Accept": "application/json", "x-api-key": api_key}
        resp = http_requests.get(f"{immich_url}/api/albums", headers=headers, timeout=30)
        resp.raise_for_status()
        albums = [
            {"id": a.get("id"), "name": a.get("albumName", ""), "count": a.get("assetCount", 0)}
            for a in resp.json()
            if a.get("albumName")
        ]
        albums.sort(key=lambda a: a["name"].lower())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch albums from Immich: {e}")

    return {"albums": albums}


@router.put("/users/{name}/album_names")
async def set_user_album_names(request: Request, name: str, body: dict):
    """Set the album names for a user (used for album notifications)."""
    config_path = get_config_path(request)

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            users = config.get("users", [])
            user_found = False
            for user in users:
                if user.get("name") == name:
                    user["album_names"] = body.get("album_names", [])
                    user_found = True
                    break
            if not user_found:
                raise HTTPException(status_code=404, detail=f"User '{name}' not found")
            _write_yaml(config_path, config)
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    return {"message": f"User '{name}' album_names updated"}


@router.put("/users/{name}/rename")
async def rename_user(request: Request, name: str, update: RenameUser):
    """Rename a user."""
    config_path = get_config_path(request)

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            users = config.get("users", [])

            for u in users:
                if u.get("name") == update.new_name:
                    raise HTTPException(status_code=400, detail=f"User '{update.new_name}' already exists")

            user_found = False
            for u in users:
                if u.get("name") == name:
                    u["name"] = update.new_name
                    user_found = True
                    break

            if not user_found:
                raise HTTPException(status_code=404, detail=f"User '{name}' not found")
            _write_yaml(config_path, config)
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    return {"message": f"User '{name}' renamed to '{update.new_name}'"}
