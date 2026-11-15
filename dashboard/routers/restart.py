"""Scheduler reload and container restart endpoints."""

import os
import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from ..crontab import reload_scheduler

router = APIRouter()


class RestartResponse(BaseModel):
    success: bool
    message: str
    output: Optional[str] = None


def _delayed_exit():
    time.sleep(1)
    os._exit(1)


@router.post("/scheduler", response_model=RestartResponse)
async def restart_scheduler():
    """Reload the scheduler crontab."""
    try:
        reload_scheduler()
        return RestartResponse(success=True, message="Scheduler reloaded")
    except Exception as e:
        return RestartResponse(success=False, message=str(e))


@router.post("/all", response_model=RestartResponse)
async def restart_all(background_tasks: BackgroundTasks):
    """Reload scheduler and restart the container."""
    try:
        reload_scheduler()
    except Exception:
        pass
    background_tasks.add_task(_delayed_exit)
    return RestartResponse(success=True, message="Restarting container...")
