"""Docker restart API endpoints."""

import subprocess
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()


class RestartRequest(BaseModel):
    services: List[str]


class RestartResponse(BaseModel):
    success: bool
    message: str
    output: Optional[str] = None


def docker_compose_restart(services: List[str]) -> dict:
    """Restart Docker Compose services."""
    try:
        # Use docker compose restart from project directory
        project_dir = os.environ.get("PROJECT_DIR", "/app/project")
        cmd = ["docker", "compose", "restart"] + services
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=project_dir,
        )

        success = result.returncode == 0
        output = result.stdout + result.stderr

        return {
            "success": success,
            "message": f"Services {', '.join(services)} restarted" if success else "Restart failed",
            "output": output[-1000:] if output else None,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "message": "Restart timed out",
            "output": None,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "message": "Docker not available",
            "output": None,
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "output": None,
        }


@router.post("/", response_model=RestartResponse)
async def restart_services(request: RestartRequest):
    """Restart specified Docker Compose services."""
    valid_services = ["scheduler", "dashboard", "notify"]

    # Validate services
    for service in request.services:
        if service not in valid_services:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid service '{service}'. Valid services: {valid_services}"
            )

    if not request.services:
        raise HTTPException(status_code=400, detail="No services specified")

    result = docker_compose_restart(request.services)
    return RestartResponse(**result)


@router.post("/scheduler", response_model=RestartResponse)
async def restart_scheduler():
    """Restart the scheduler service."""
    result = docker_compose_restart(["scheduler"])
    return RestartResponse(**result)


@router.post("/all", response_model=RestartResponse)
async def restart_all():
    """Restart scheduler and dashboard services."""
    result = docker_compose_restart(["scheduler", "dashboard"])
    return RestartResponse(**result)
