"""ntfy management API endpoints (bundled ntfy support)."""

import subprocess
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

NTFY_CONTAINER_NAME = "immich-memories-ntfy"
NTFY_CONFIG_PATH = "/etc/ntfy/server.yaml"


class NtfyCreateUserRequest(BaseModel):
    """Request body for creating a ntfy user."""
    username: str
    password: str
    topic: str = "*"


class NtfyCreateUserResponse(BaseModel):
    """Response from ntfy user creation."""
    success: bool
    message: str
    commands_run: list[str]
    output: Optional[str] = None


def _run_docker_exec(container: str, args: list[str]) -> tuple[int, str, str]:
    """Run a command in a Docker container via docker exec."""
    cmd = ["docker", "exec", container] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timed out after 15 seconds"
    except FileNotFoundError:
        return 1, "", "docker command not found — is Docker installed?"
    except Exception as e:
        return 1, "", str(e)


@router.get("/status")
async def get_ntfy_status():
    """Check if the bundled ntfy container is running."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", NTFY_CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=5,
        )
        is_running = result.returncode == 0 and result.stdout.strip() == "true"
        return {
            "container_name": NTFY_CONTAINER_NAME,
            "running": is_running,
            "available": result.returncode == 0,
        }
    except FileNotFoundError:
        return {"container_name": NTFY_CONTAINER_NAME, "running": False, "available": False}
    except Exception as e:
        return {"container_name": NTFY_CONTAINER_NAME, "running": False, "available": False, "error": str(e)}


@router.post("/create-user", response_model=NtfyCreateUserResponse)
async def create_ntfy_user(req: NtfyCreateUserRequest):
    """
    Create a ntfy user in the bundled ntfy container and grant topic access.

    Runs:
      docker exec <container> ntfy user add --password <password> <username>
      docker exec <container> ntfy access <username> <topic> read-write
    """
    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="username and password are required")

    # Sanitize inputs — no shell injection
    safe_username = req.username.strip()
    safe_topic = req.topic.strip() or "*"
    if not safe_username.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="username may only contain letters, numbers, hyphens, and underscores")

    commands_run = []
    output_lines = []

    # Check container is running first
    status_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", NTFY_CONTAINER_NAME],
        capture_output=True, text=True, timeout=5,
    )
    if status_result.returncode != 0 or status_result.stdout.strip() != "true":
        return NtfyCreateUserResponse(
            success=False,
            message=f"Container '{NTFY_CONTAINER_NAME}' is not running. Start it with: docker compose up -d ntfy",
            commands_run=[],
        )

    # Step 1: Create user (pass --config so ntfy finds the auth-file)
    add_cmd = ["ntfy", "--config", NTFY_CONFIG_PATH, "user", "add", "--password", req.password, safe_username]
    cmd_display = f"docker exec {NTFY_CONTAINER_NAME} ntfy --config {NTFY_CONFIG_PATH} user add --password ***** {safe_username}"
    commands_run.append(cmd_display)

    rc, stdout, stderr = _run_docker_exec(NTFY_CONTAINER_NAME, add_cmd)
    combined = (stdout + stderr).strip()
    if combined:
        output_lines.append(combined)

    if rc != 0:
        # Check if user already exists (that's OK)
        combined_lower = combined.lower()
        if "already exists" not in combined_lower and "duplicate" not in combined_lower:
            return NtfyCreateUserResponse(
                success=False,
                message=f"Failed to create user '{safe_username}': {combined}",
                commands_run=commands_run,
                output="\n".join(output_lines),
            )
        output_lines.append(f"(User '{safe_username}' already exists — updating access)")

    # Step 2: Grant access (pass --config so ntfy finds the auth-file)
    access_cmd = ["ntfy", "--config", NTFY_CONFIG_PATH, "access", safe_username, safe_topic, "read-write"]
    access_cmd_display = f"docker exec {NTFY_CONTAINER_NAME} ntfy --config {NTFY_CONFIG_PATH} access {safe_username} {safe_topic} read-write"
    commands_run.append(access_cmd_display)

    rc2, stdout2, stderr2 = _run_docker_exec(NTFY_CONTAINER_NAME, access_cmd)
    combined2 = (stdout2 + stderr2).strip()
    if combined2:
        output_lines.append(combined2)

    if rc2 != 0:
        return NtfyCreateUserResponse(
            success=False,
            message=f"User created but failed to grant access: {combined2}",
            commands_run=commands_run,
            output="\n".join(output_lines),
        )

    return NtfyCreateUserResponse(
        success=True,
        message=f"User '{safe_username}' created with read-write access to topic '{safe_topic}'",
        commands_run=commands_run,
        output="\n".join(output_lines) or None,
    )
