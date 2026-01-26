"""Secrets/Environment management API endpoints."""

import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..utils.filelock import read_lock, write_lock

router = APIRouter()

# Path to .env file
ENV_PATH = os.environ.get("ENV_PATH", "/app/.env")


class ServerUrls(BaseModel):
    immich_url: Optional[str] = None
    immich_external_url: Optional[str] = None
    ntfy_url: Optional[str] = None
    ntfy_external_url: Optional[str] = None


class UserSecrets(BaseModel):
    name: str
    immich_api_key: Optional[str] = None  # Masked on read
    ntfy_password: Optional[str] = None   # Masked on read


class SecretsUpdate(BaseModel):
    """Update secrets - only non-None values are updated."""
    immich_url: Optional[str] = None
    immich_external_url: Optional[str] = None
    ntfy_url: Optional[str] = None
    ntfy_external_url: Optional[str] = None
    dashboard_token: Optional[str] = None
    # User-specific (keyed by user number)
    user1_api_key: Optional[str] = None
    user1_ntfy_password: Optional[str] = None
    user2_api_key: Optional[str] = None
    user2_ntfy_password: Optional[str] = None


def load_env_file(env_path: str) -> dict:
    """Load .env file into a dictionary."""
    env_vars = {}
    path = Path(env_path)

    if not path.exists():
        return env_vars

    with read_lock(env_path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    # Remove quotes if present
                    value = value.strip().strip('"').strip("'")
                    env_vars[key.strip()] = value

    return env_vars


def save_env_file(env_path: str, env_vars: dict):
    """Save dictionary to .env file, preserving comments and order."""
    path = Path(env_path)
    lines = []
    updated_keys = set()

    # Read existing file to preserve structure
    if path.exists():
        with read_lock(env_path):
            with open(path) as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#') and '=' in stripped:
                        key = stripped.split('=')[0].strip()
                        if key in env_vars:
                            lines.append(f'{key}="{env_vars[key]}"\n')
                            updated_keys.add(key)
                        else:
                            lines.append(line)
                    else:
                        lines.append(line)

    # Add any new keys not in original file
    for key, value in env_vars.items():
        if key not in updated_keys:
            lines.append(f'{key}="{value}"\n')

    with write_lock(env_path):
        with open(path, 'w') as f:
            f.writelines(lines)


def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret value, showing only last few characters."""
    if not value:
        return ""
    if len(value) <= show_chars:
        return "*" * len(value)
    return "*" * (len(value) - show_chars) + value[-show_chars:]


@router.get("/urls")
async def get_server_urls():
    """Get server URLs (from environment)."""
    return {
        "immich_url": os.environ.get("IMMICH_URL", ""),
        "immich_external_url": os.environ.get("IMMICH_EXTERNAL_URL", ""),
        "ntfy_url": os.environ.get("NTFY_URL", ""),
        "ntfy_external_url": os.environ.get("NTFY_EXTERNAL_URL", ""),
    }


@router.get("/")
async def get_secrets_masked():
    """Get all secrets with sensitive values masked."""
    env_vars = load_env_file(ENV_PATH)

    return {
        "urls": {
            "immich_url": env_vars.get("IMMICH_URL", os.environ.get("IMMICH_URL", "")),
            "immich_external_url": env_vars.get("IMMICH_EXTERNAL_URL", os.environ.get("IMMICH_EXTERNAL_URL", "")),
            "ntfy_url": env_vars.get("NTFY_URL", os.environ.get("NTFY_URL", "")),
            "ntfy_external_url": env_vars.get("NTFY_EXTERNAL_URL", os.environ.get("NTFY_EXTERNAL_URL", "")),
        },
        "dashboard": {
            "token_set": bool(env_vars.get("DASHBOARD_TOKEN") or os.environ.get("DASHBOARD_TOKEN")),
        },
        "users": {
            "user1": {
                "api_key": mask_secret(env_vars.get("IMMICH_API_KEY_USER1", "")),
                "api_key_set": bool(env_vars.get("IMMICH_API_KEY_USER1")),
                "ntfy_password": mask_secret(env_vars.get("NTFY_PASSWORD_ISMAIL", "")),
                "ntfy_password_set": bool(env_vars.get("NTFY_PASSWORD_ISMAIL")),
            },
            "user2": {
                "api_key": mask_secret(env_vars.get("IMMICH_API_KEY_USER2", "")),
                "api_key_set": bool(env_vars.get("IMMICH_API_KEY_USER2")),
                "ntfy_password": mask_secret(env_vars.get("NTFY_PASSWORD_RANYA", "")),
                "ntfy_password_set": bool(env_vars.get("NTFY_PASSWORD_RANYA")),
            },
        },
        "env_file_exists": Path(ENV_PATH).exists(),
        "restart_required_note": "Changes to secrets require container restart to take effect",
    }


@router.put("/")
async def update_secrets(update: SecretsUpdate):
    """Update secrets in .env file. Only non-empty values are updated."""
    env_vars = load_env_file(ENV_PATH)
    updated = []

    # Server URLs
    if update.immich_url is not None and update.immich_url:
        env_vars["IMMICH_URL"] = update.immich_url
        updated.append("IMMICH_URL")
    if update.immich_external_url is not None and update.immich_external_url:
        env_vars["IMMICH_EXTERNAL_URL"] = update.immich_external_url
        updated.append("IMMICH_EXTERNAL_URL")
    if update.ntfy_url is not None and update.ntfy_url:
        env_vars["NTFY_URL"] = update.ntfy_url
        updated.append("NTFY_URL")
    if update.ntfy_external_url is not None and update.ntfy_external_url:
        env_vars["NTFY_EXTERNAL_URL"] = update.ntfy_external_url
        updated.append("NTFY_EXTERNAL_URL")

    # Dashboard token
    if update.dashboard_token is not None and update.dashboard_token:
        env_vars["DASHBOARD_TOKEN"] = update.dashboard_token
        updated.append("DASHBOARD_TOKEN")

    # User 1 secrets
    if update.user1_api_key is not None and update.user1_api_key:
        env_vars["IMMICH_API_KEY_USER1"] = update.user1_api_key
        updated.append("IMMICH_API_KEY_USER1")
    if update.user1_ntfy_password is not None and update.user1_ntfy_password:
        env_vars["NTFY_PASSWORD_ISMAIL"] = update.user1_ntfy_password
        updated.append("NTFY_PASSWORD_ISMAIL")

    # User 2 secrets
    if update.user2_api_key is not None and update.user2_api_key:
        env_vars["IMMICH_API_KEY_USER2"] = update.user2_api_key
        updated.append("IMMICH_API_KEY_USER2")
    if update.user2_ntfy_password is not None and update.user2_ntfy_password:
        env_vars["NTFY_PASSWORD_RANYA"] = update.user2_ntfy_password
        updated.append("NTFY_PASSWORD_RANYA")

    if updated:
        save_env_file(ENV_PATH, env_vars)

    return {
        "message": "Secrets updated" if updated else "No changes made",
        "updated_fields": updated,
        "restart_required": bool(updated),
        "restart_command": "docker compose restart scheduler dashboard" if updated else None,
    }
