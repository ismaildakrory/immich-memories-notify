"""Secrets/Environment management API endpoints."""

import os
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests as http_requests
import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..utils.filelock import read_lock, write_lock

router = APIRouter()

# Paths
ENV_PATH = os.environ.get("ENV_PATH", "/app/.env")
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config.yaml")


class ConnectionTestRequest(BaseModel):
    """Request body for connection test endpoints."""
    url: str


class SecretsUpdate(BaseModel):
    """Update secrets - only non-None values are updated."""
    immich_url: Optional[str] = None
    immich_external_url: Optional[str] = None
    ntfy_url: Optional[str] = None
    ntfy_external_url: Optional[str] = None
    dashboard_token: Optional[str] = None
    # Dynamic user secrets: {"USER_NAME": {"api_key": "...", "ntfy_password": "..."}}
    users: Optional[Dict[str, Dict[str, str]]] = None


class UserSecretUpdate(BaseModel):
    """Update a single user's secrets."""
    api_key: Optional[str] = None
    ntfy_password: Optional[str] = None


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    with read_lock(config_path):
        with open(config_path) as f:
            return yaml.safe_load(f) or {}


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
                            lines.append(f'{key}={env_vars[key]}\n')
                            updated_keys.add(key)
                        else:
                            lines.append(line)
                    else:
                        lines.append(line)

    # Add any new keys not in original file
    for key, value in env_vars.items():
        if key not in updated_keys:
            lines.append(f'{key}={value}\n')

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


def get_env_var_name(user_name: str, var_type: str) -> str:
    """Get environment variable name for a user.

    Looks at config.yaml to find what variable the user is configured to use,
    then extracts the variable name from ${VAR_NAME} format.
    """
    try:
        config = load_config(CONFIG_PATH)
        users = config.get("users", [])
        for user in users:
            if user.get("name") == user_name:
                if var_type == "api_key":
                    ref = user.get("immich_api_key", "")
                else:  # ntfy_password
                    ref = user.get("ntfy_password", "")
                # Extract var name from ${VAR_NAME}
                match = re.match(r'\$\{(\w+)\}', ref)
                if match:
                    return match.group(1)
    except Exception:
        pass

    # Fallback to standard naming
    safe_name = user_name.upper().replace(" ", "_")
    if var_type == "api_key":
        return f"IMMICH_API_KEY_{safe_name}"
    return f"NTFY_PASSWORD_{safe_name}"


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
async def get_secrets_masked(request: Request):
    """Get all secrets with sensitive values masked, based on users in config."""
    env_vars = load_env_file(ENV_PATH)

    # Load users from config
    try:
        config = load_config(CONFIG_PATH)
        config_users = config.get("users", [])
    except Exception:
        config_users = []

    # Build dynamic user secrets
    users_secrets = {}
    for user in config_users:
        user_name = user.get("name", "")
        if not user_name:
            continue

        api_key_var = get_env_var_name(user_name, "api_key")
        password_var = get_env_var_name(user_name, "ntfy_password")

        api_key_value = env_vars.get(api_key_var, "")
        password_value = env_vars.get(password_var, "")

        users_secrets[user_name] = {
            "api_key": mask_secret(api_key_value),
            "api_key_set": bool(api_key_value),
            "api_key_var": api_key_var,
            "ntfy_password": mask_secret(password_value),
            "ntfy_password_set": bool(password_value),
            "ntfy_password_var": password_var,
        }

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
        "users": users_secrets,
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

    # Dynamic user secrets
    if update.users:
        for user_name, secrets in update.users.items():
            if secrets.get("api_key"):
                var_name = get_env_var_name(user_name, "api_key")
                env_vars[var_name] = secrets["api_key"]
                updated.append(var_name)
            if secrets.get("ntfy_password"):
                var_name = get_env_var_name(user_name, "ntfy_password")
                env_vars[var_name] = secrets["ntfy_password"]
                updated.append(var_name)

    if updated:
        save_env_file(ENV_PATH, env_vars)

    return {
        "message": "Secrets updated" if updated else "No changes made",
        "updated_fields": updated,
        "restart_required": bool(updated),
        "restart_command": "docker compose restart scheduler dashboard" if updated else None,
    }


@router.put("/user/{user_name}")
async def update_user_secrets(user_name: str, update: UserSecretUpdate):
    """Update a single user's secrets."""
    env_vars = load_env_file(ENV_PATH)
    updated = []

    if update.api_key:
        var_name = get_env_var_name(user_name, "api_key")
        env_vars[var_name] = update.api_key
        updated.append(var_name)

    if update.ntfy_password:
        var_name = get_env_var_name(user_name, "ntfy_password")
        env_vars[var_name] = update.ntfy_password
        updated.append(var_name)

    if updated:
        save_env_file(ENV_PATH, env_vars)

    return {
        "message": f"Secrets for '{user_name}' updated" if updated else "No changes made",
        "updated_fields": updated,
        "restart_required": bool(updated),
    }


@router.post("/test/immich")
async def test_immich_connection(req: ConnectionTestRequest):
    """Test connectivity to the Immich server."""
    url = req.url.strip().rstrip("/")
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    test_url = f"{url}/api/server/ping"
    start = time.time()
    try:
        resp = http_requests.get(test_url, timeout=5)
        latency_ms = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            return {"success": True, "message": f"Immich is reachable ({latency_ms}ms)", "detail": f"GET {test_url} returned 200"}
        return {"success": False, "message": f"Immich returned HTTP {resp.status_code}", "detail": resp.text[:200]}
    except http_requests.exceptions.ConnectionError:
        return {"success": False, "message": "Connection refused — is Immich running at this address?", "detail": f"Could not connect to {url}"}
    except http_requests.exceptions.Timeout:
        return {"success": False, "message": "Connection timed out (5s) — check the host and port", "detail": f"Timeout connecting to {url}"}
    except Exception as e:
        return {"success": False, "message": f"Connection failed: {e}", "detail": str(e)}


@router.post("/test/ntfy")
async def test_ntfy_connection(req: ConnectionTestRequest):
    """Test connectivity to the ntfy server."""
    url = req.url.strip().rstrip("/")
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    test_url = f"{url}/v1/health"
    start = time.time()
    try:
        resp = http_requests.get(test_url, timeout=5)
        latency_ms = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            # Also test attachment support by attempting a small upload
            attach_warning = None
            try:
                test_topic = f"attach-test-{int(time.time())}"
                attach_resp = http_requests.put(
                    f"{url}/{test_topic}",
                    headers={"Filename": "test.txt"},
                    data=b"test",
                    timeout=5,
                )
                if attach_resp.status_code != 200:
                    body = attach_resp.text[:200].lower()
                    if "attachments not allowed" in body:
                        attach_warning = (
                            "Attachments not allowed — thumbnail previews won't work. "
                            "Set auth-file in server.yaml, create a user with 'ntfy user add <name>', "
                            "then run 'ntfy access <name> \"*\" read-write'"
                        )
                    else:
                        attach_warning = f"Attachment upload returned HTTP {attach_resp.status_code}"
            except Exception:
                attach_warning = "Could not test attachment support"

            if attach_warning:
                return {"success": True, "message": f"ntfy is reachable ({latency_ms}ms) — but: {attach_warning}", "detail": f"GET {test_url} returned 200. Warning: {attach_warning}"}
            return {"success": True, "message": f"ntfy is reachable ({latency_ms}ms) — attachments OK", "detail": f"GET {test_url} returned 200, attachment upload works"}
        # Some ntfy setups may not expose /v1/health, try root
        resp2 = http_requests.get(f"{url}/", timeout=5)
        latency_ms = int((time.time() - start) * 1000)
        if resp2.status_code == 200:
            return {"success": True, "message": f"ntfy is reachable ({latency_ms}ms)", "detail": f"Health endpoint returned {resp.status_code}, but root is OK"}
        return {"success": False, "message": f"ntfy returned HTTP {resp.status_code}", "detail": resp.text[:200]}
    except http_requests.exceptions.ConnectionError:
        return {"success": False, "message": "Connection refused — is ntfy running at this address?", "detail": f"Could not connect to {url}"}
    except http_requests.exceptions.Timeout:
        return {"success": False, "message": "Connection timed out (5s) — check the host and port", "detail": f"Timeout connecting to {url}"}
    except Exception as e:
        return {"success": False, "message": f"Connection failed: {e}", "detail": str(e)}
