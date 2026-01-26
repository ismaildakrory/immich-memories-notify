"""State management API endpoints."""

import json
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

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
    """Save state to JSON file."""
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with write_lock(state_path):
        with open(path, 'w') as f:
            json.dump(state, f, indent=2)


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
