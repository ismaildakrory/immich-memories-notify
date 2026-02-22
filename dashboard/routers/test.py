"""Test notification trigger API endpoints."""

import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Query

from ..models import TestTriggerResponse

ENV_PATH = os.environ.get("ENV_PATH", "/app/.env")


def load_env_for_subprocess() -> dict:
    """Load .env file and merge with current environment.

    The dashboard container's os.environ is frozen at startup, so secrets
    added after startup (e.g. via the wizard) won't be present. This reads
    the .env file fresh every time so notify.py gets up-to-date values.
    """
    env = os.environ.copy()
    env_file = Path(ENV_PATH)
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    env[key.strip()] = value.strip().strip('"').strip("'")
    return env

router = APIRouter()


def get_config_path(request: Request) -> str:
    """Get config path from app state."""
    return request.app.state.config_path


@router.post("/trigger/{slot}", response_model=TestTriggerResponse)
async def trigger_test_notification(
    request: Request,
    slot: int,
    dry_run: bool = Query(False, description="Preview without sending"),
    user: str = Query(None, description="Specific user to notify (optional)"),
):
    """
    Trigger a test notification for a specific slot.

    Args:
        slot: The notification slot number (1-5)
        dry_run: If true, preview what would be sent without actually sending
        user: Optionally target a specific user
    """
    if slot < 1 or slot > 10:
        raise HTTPException(status_code=400, detail="Slot must be between 1 and 10")

    config_path = get_config_path(request)

    # Build command
    cmd = [
        sys.executable,
        "/app/notify.py",
        "--config", config_path,
        "--slot", str(slot),
        "--test",
        "--no-delay",
    ]

    if dry_run:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
            cwd="/app",
            env=load_env_for_subprocess(),
        )

        success = result.returncode == 0
        output = result.stdout + result.stderr

        if success:
            message = f"Test notification for slot {slot} {'simulated' if dry_run else 'sent'} successfully"
        else:
            message = f"Test notification failed with return code {result.returncode}"

        return TestTriggerResponse(
            success=success,
            message=message,
            output=output[-2000:] if output else None,  # Limit output size
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Notification script timed out")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Notification script not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running notification: {str(e)}")


@router.get("/slots")
async def get_available_slots(request: Request):
    """Get information about available notification slots."""
    # This could be enhanced to read from config
    return {
        "slots": [
            {"number": 1, "description": "Morning notification"},
            {"number": 2, "description": "Late morning notification"},
            {"number": 3, "description": "Afternoon notification"},
            {"number": 4, "description": "Evening notification"},
            {"number": 5, "description": "Night notification"},
        ],
        "note": "Slots 1-3 typically send memories, slots 4-5 send person photos (configurable)",
    }
