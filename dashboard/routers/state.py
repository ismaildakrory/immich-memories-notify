"""State management API endpoints."""

import json
import os
import re
from datetime import date
from pathlib import Path

import requests as http_requests
from fastapi import APIRouter, HTTPException, Query, Request, Response

from ..models import StateResponse, UserSlotState
from ..utils.filelock import read_lock, write_lock

router = APIRouter()


def get_state_path(request: Request) -> str:
    """Get state path from app state."""
    return request.app.state.state_path


def load_state(state_path: str) -> dict:
    """Load state from JSON file."""
    path = Path(state_path)
    if not path.exists():
        return {"users": {}}

    with read_lock(state_path):
        with open(path) as f:
            return json.load(f)


def save_state(state_path: str, state: dict):
    """Save state to JSON file (atomic write, same lock as the notify engine)."""
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")

    with write_lock(state_path):
        with open(tmp_path, 'w') as f:
            json.dump(state, f, indent=2)
        tmp_path.replace(path)


@router.get("/", response_model=StateResponse)
async def get_state(request: Request):
    """Get full notification state."""
    state_path = get_state_path(request)

    try:
        state = load_state(state_path)
    except json.JSONDecodeError:
        return StateResponse(users={})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading state: {str(e)}")

    users_state = {}
    for name, user_state in state.get("users", {}).items():
        users_state[name] = UserSlotState(
            slots_date=user_state.get("slots_date"),
            slots_sent=user_state.get("slots_sent", []),
            assets_sent_today=user_state.get("assets_sent_today", []),
            last_slot_time=user_state.get("last_slot_time"),
        )

    return StateResponse(users=users_state)


@router.get("/user/{name}", response_model=UserSlotState)
async def get_user_state(request: Request, name: str):
    """Get state for a specific user."""
    state_path = get_state_path(request)

    try:
        state = load_state(state_path)
    except json.JSONDecodeError:
        return UserSlotState()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading state: {str(e)}")

    user_state = state.get("users", {}).get(name)
    if not user_state:
        return UserSlotState()

    return UserSlotState(
        slots_date=user_state.get("slots_date"),
        slots_sent=user_state.get("slots_sent", []),
        assets_sent_today=user_state.get("assets_sent_today", []),
        last_slot_time=user_state.get("last_slot_time"),
    )


@router.delete("/user/{name}/today")
async def clear_user_today(request: Request, name: str):
    """Clear today's state for a user (allows re-sending notifications)."""
    state_path = get_state_path(request)

    try:
        state = load_state(state_path)
    except json.JSONDecodeError:
        state = {"users": {}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading state: {str(e)}")

    if name not in state.get("users", {}):
        raise HTTPException(status_code=404, detail=f"User '{name}' not found in state")

    # Clear today's data
    user_state = state["users"][name]
    user_state["slots_sent"] = []
    user_state["assets_sent_today"] = []
    user_state["slots_date"] = None

    save_state(state_path, state)
    return {"message": f"Cleared today's state for user '{name}'"}


@router.delete("/")
async def clear_all_state(request: Request):
    """Clear all state (allows re-sending all notifications)."""
    state_path = get_state_path(request)

    save_state(state_path, {"users": {}})
    return {"message": "All state cleared"}


@router.get("/today")
async def get_today_summary(request: Request):
    """Get summary of today's notifications."""
    state_path = get_state_path(request)
    today = date.today().isoformat()

    try:
        state = load_state(state_path)
    except json.JSONDecodeError:
        return {"date": today, "users": {}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading state: {str(e)}")

    summary = {
        "date": today,
        "users": {},
    }

    for name, user_state in state.get("users", {}).items():
        if user_state.get("slots_date") == today:
            summary["users"][name] = {
                "slots_sent": user_state.get("slots_sent", []),
                "notification_count": len(user_state.get("slots_sent", [])),
                "last_sent": user_state.get("last_slot_time"),
            }
        else:
            summary["users"][name] = {
                "slots_sent": [],
                "notification_count": 0,
                "last_sent": None,
            }

    return summary


# =============================================================================
# Sent history (dashboard History tab)
# =============================================================================

_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


@router.get("/history")
async def get_history(
    request: Request,
    user: str = Query(None, description="Filter by user name"),
    limit: int = Query(100, ge=1, le=500),
):
    """Most recent sent notifications across users (newest first), with repeat markers."""
    state_path = get_state_path(request)
    try:
        state = load_state(state_path)
    except json.JSONDecodeError:
        return {"items": [], "users": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading state: {str(e)}")

    users_state = state.get("users", {})
    items = []
    for name, user_state in users_state.items():
        if user and name != user:
            continue
        seen_before = set()
        for rec in user_state.get("history", []):  # oldest → newest
            asset_id = rec.get("asset_id")
            items.append({**rec, "user": name, "repeat": bool(asset_id) and asset_id in seen_before})
            if asset_id:
                seen_before.add(asset_id)
    items.sort(key=lambda r: r.get("time") or "", reverse=True)
    return {"items": items[:limit], "users": sorted(users_state)}


@router.get("/thumbnail/{user}/{asset_id}")
def get_history_thumbnail(request: Request, user: str, asset_id: str):
    """Proxy an Immich thumbnail using the user's own API key (the browser never sees the key)."""
    from .settings import _resolve_user_api_key, load_config

    if not _UUID_RE.match(asset_id):
        raise HTTPException(status_code=400, detail="Invalid asset id")
    config = load_config(request.app.state.config_path)
    user_cfg = next((u for u in config.get("users", []) if u.get("name") == user), None)
    if not user_cfg:
        raise HTTPException(status_code=404, detail="User not found")
    api_key = _resolve_user_api_key(user_cfg)
    immich_url = os.environ.get("IMMICH_URL", "").rstrip("/")
    if not api_key or not immich_url:
        raise HTTPException(status_code=400, detail="Immich not configured for this user")
    try:
        resp = http_requests.get(
            f"{immich_url}/api/assets/{asset_id}/thumbnail",
            headers={"x-api-key": api_key},
            params={"size": "thumbnail"},
            timeout=15,
        )
    except Exception:
        raise HTTPException(status_code=502, detail="Could not reach Immich")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Thumbnail not available")
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "private, max-age=86400"},
    )
