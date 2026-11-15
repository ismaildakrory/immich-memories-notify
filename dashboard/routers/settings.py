"""Settings management API endpoints."""

import os
import re
from pathlib import Path
from typing import List

import requests as http_requests
import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from notify.defaults import DEFAULT_SETTINGS, DEFAULT_TEMPLATES

from ..crontab import reload_scheduler
from ..models import (
    FullConfig,
    MessagesUpdate,
    NotificationWindow,
    Settings,
    SettingsUpdate,
    UserEnabledUpdate,
    UserInfo,
    WindowsUpdate,
)
from ..utils.filelock import exclusive_lock, read_lock, write_lock

router = APIRouter()


def build_settings_model(settings_data: dict) -> Settings:
    """Merge stored settings over the shared defaults and validate.

    Handles the legacy collage_year_range key and drops unknown keys so a
    stray field in config.yaml can't break the dashboard.
    """
    data = dict(settings_data)
    if "collage_year_range" in data and "year_range" not in data:
        data["year_range"] = data.pop("collage_year_range")
    merged = {**DEFAULT_SETTINGS, **{k: v for k, v in data.items() if k in DEFAULT_SETTINGS}}
    merged["notification_windows"] = [NotificationWindow(**w) for w in merged.get("notification_windows") or []]
    return Settings(**merged)


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


def load_config_exclusive(config_path: str) -> dict:
    """Read config without acquiring a lock — caller must hold exclusive_lock(config_path).

    Usage:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
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

    settings = build_settings_model(config.get("settings") or {})

    # Redact sensitive user info
    users = [
        UserInfo(
            name=u.get("name", ""),
            ntfy_topic=u.get("ntfy_topic", ""),
            ntfy_priority=u.get("ntfy_priority", "default"),
            notification_service=u.get("notification_service", "ntfy"),
            enabled=u.get("enabled", True),
            home_cities=u.get("home_cities") or ([u["home_city"]] if u.get("home_city") else []),
            album_names=u.get("album_names", []),
        )
        for u in config.get("users", [])
    ]

    templates = {key: config.get(key, list(default)) for key, default in DEFAULT_TEMPLATES.items()}
    return FullConfig(settings=settings, users=users, **templates)


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
                {"start": w.start, "end": w.end, "events": w.events} for w in update.notification_windows
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

    return {key: config.get(key, list(default)) for key, default in DEFAULT_TEMPLATES.items()}


@router.put("/messages")
async def update_messages(request: Request, update: MessagesUpdate):
    """Update message templates."""
    config_path = get_config_path(request)

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            for key, value in update.model_dump(exclude_none=True).items():
                config[key] = value
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
            ntfy_priority=u.get("ntfy_priority", "default"),
            notification_service=u.get("notification_service", "ntfy"),
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
    notification_service: str = Field("ntfy", pattern=r"^(ntfy|apprise)$")
    ntfy_topic: str = Field("", max_length=256)
    ntfy_username: str = Field("", max_length=64)
    ntfy_priority: str = Field("default", pattern=r"^(min|low|default|high|max)$")
    enabled: bool = True


class RenameUser(BaseModel):
    new_name: str = Field(..., max_length=64, pattern=r"^[a-zA-Z0-9 _\-؀-ۿ]+$")


@router.post("/users")
async def add_user(request: Request, user: NewUser):
    """Add a new user."""
    config_path = get_config_path(request)
    safe_name = user.name.upper().replace(" ", "_")

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            users = config.get("users", [])

            for u in users:
                if u.get("name") == user.name:
                    raise HTTPException(status_code=400, detail=f"User '{user.name}' already exists")

            new_user = {
                "name": user.name,
                "immich_api_key": "${IMMICH_API_KEY_" + safe_name + "}",
                "enabled": user.enabled,
            }

            env_vars_needed = [f"IMMICH_API_KEY_{safe_name}"]

            if user.notification_service == "apprise":
                new_user["notification_service"] = "apprise"
                new_user["apprise_url"] = "${APPRISE_URL_" + safe_name + "}"
                env_vars_needed.append(f"APPRISE_URL_{safe_name}")
            else:
                new_user["ntfy_topic"] = user.ntfy_topic
                new_user["ntfy_username"] = user.ntfy_username or user.name.lower()
                new_user["ntfy_password"] = "${NTFY_PASSWORD_" + safe_name + "}"
                if user.ntfy_priority != "default":
                    new_user["ntfy_priority"] = user.ntfy_priority
                env_vars_needed.append(f"NTFY_PASSWORD_{safe_name}")

            users.append(new_user)
            config["users"] = users
            _write_yaml(config_path, config)
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    return {
        "message": f"User '{user.name}' added",
        "note": "Remember to add secrets to .env file",
        "env_vars_needed": env_vars_needed,
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
    from .secrets import ENV_PATH, load_env_file
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


class NotificationServiceUpdate(BaseModel):
    notification_service: str = Field(..., pattern=r"^(ntfy|apprise)$")
    ntfy_topic: str = Field("", max_length=256)
    ntfy_username: str = Field("", max_length=64)


@router.put("/users/{name}/notification_service")
async def set_user_notification_service(request: Request, name: str, body: NotificationServiceUpdate):
    """Switch a user's notification service (ntfy or apprise)."""
    config_path = get_config_path(request)

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            users = config.get("users", [])
            user = next((u for u in users if u.get("name") == name), None)
            if not user:
                raise HTTPException(status_code=404, detail=f"User '{name}' not found")

            safe_name = name.upper().replace(" ", "_")

            if body.notification_service == "apprise":
                user["notification_service"] = "apprise"
                user["apprise_url"] = user.get("apprise_url") or "${APPRISE_URL_" + safe_name + "}"
                user.pop("ntfy_topic", None)
                user.pop("ntfy_username", None)
                user.pop("ntfy_password", None)
                user.pop("ntfy_priority", None)
            else:
                user["notification_service"] = "ntfy"
                user["ntfy_topic"] = body.ntfy_topic or user.get("ntfy_topic", "")
                user["ntfy_username"] = body.ntfy_username or user.get("ntfy_username", name.lower())
                user["ntfy_password"] = user.get("ntfy_password") or "${NTFY_PASSWORD_" + safe_name + "}"
                user.pop("apprise_url", None)

            _write_yaml(config_path, config)
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    return {"message": f"User '{name}' notification service set to '{body.notification_service}'"}


class NtfyPriorityUpdate(BaseModel):
    ntfy_priority: str = Field(..., pattern=r"^(min|low|default|high|max)$")


@router.put("/users/{name}/ntfy_priority")
async def set_user_ntfy_priority(request: Request, name: str, body: NtfyPriorityUpdate):
    """Set ntfy message priority for a user."""
    config_path = get_config_path(request)

    try:
        with exclusive_lock(config_path):
            config = load_config_exclusive(config_path)
            users = config.get("users", [])
            user = next((u for u in users if u.get("name") == name), None)
            if not user:
                raise HTTPException(status_code=404, detail=f"User '{name}' not found")

            if user.get("notification_service", "ntfy") != "ntfy":
                raise HTTPException(status_code=400, detail="ntfy priority is only applicable to ntfy users")

            if body.ntfy_priority == "default":
                user.pop("ntfy_priority", None)
            else:
                user["ntfy_priority"] = body.ntfy_priority

            _write_yaml(config_path, config)
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    return {"message": f"User '{name}' ntfy priority set to '{body.ntfy_priority}'"}


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
