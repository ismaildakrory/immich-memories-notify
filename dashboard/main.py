"""
Immich Memories Notify - Dashboard
==================================
FastAPI web dashboard for managing notifications.
"""

import logging
import os
import secrets as stdlib_secrets
import subprocess
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

from .models import HealthResponse
from .routers import settings, state, test, secrets, restart, ntfy

# App configuration
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config.yaml")
STATE_PATH = os.environ.get("STATE_PATH", "/app/state/state.json")
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")
DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "admin")

# Read version from VERSION file
_version_file = Path(__file__).parent.parent / "VERSION"
APP_VERSION = _version_file.read_text().strip() if _version_file.exists() else "1.0.0"

# Create FastAPI app
app = FastAPI(
    title="Immich Memories Notify Dashboard",
    description="Web dashboard for managing Immich memory notifications",
    version=APP_VERSION,
)

# Security - auto_error=False allows unauthenticated requests when no token is configured
security = HTTPBasic(auto_error=False)


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Verify HTTP Basic Auth credentials."""
    # If no token configured, allow all access
    if not DASHBOARD_TOKEN:
        return credentials.username if credentials else "anonymous"

    # Token is configured, require valid credentials
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Basic"},
        )

    is_username_correct = stdlib_secrets.compare_digest(
        credentials.username.encode("utf8"),
        DASHBOARD_USER.encode("utf8"),
    )
    is_password_correct = stdlib_secrets.compare_digest(
        credentials.password.encode("utf8"),
        DASHBOARD_TOKEN.encode("utf8"),
    )

    if not (is_username_correct and is_password_correct):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


# Include routers
app.include_router(
    settings.router,
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(verify_credentials)],
)
app.include_router(
    state.router,
    prefix="/api/state",
    tags=["state"],
    dependencies=[Depends(verify_credentials)],
)
app.include_router(
    test.router,
    prefix="/api/test",
    tags=["test"],
    dependencies=[Depends(verify_credentials)],
)
app.include_router(
    secrets.router,
    prefix="/api/secrets",
    tags=["secrets"],
    dependencies=[Depends(verify_credentials)],
)
app.include_router(
    restart.router,
    prefix="/api/restart",
    tags=["restart"],
    dependencies=[Depends(verify_credentials)],
)
app.include_router(
    ntfy.router,
    prefix="/api/ntfy",
    tags=["ntfy"],
    dependencies=[Depends(verify_credentials)],
)


# Health endpoint (no auth required)
@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint — includes crond liveness."""
    result = subprocess.run(["pidof", "crond"], capture_output=True, text=True)
    crond_ok = False
    if result.returncode == 0:
        for pid in result.stdout.strip().split():
            try:
                stat = Path(f"/proc/{pid}/status").read_text()
                if "zombie" not in stat.lower():
                    crond_ok = True
                    break
            except (FileNotFoundError, PermissionError):
                pass
    if not crond_ok:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "version": APP_VERSION, "detail": "crond not running"},
        )
    return HealthResponse(status="healthy", version=APP_VERSION)


# Dashboard UI
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)


@app.get("/", response_class=HTMLResponse, tags=["ui"])
async def dashboard_ui(username: str = Depends(verify_credentials)):
    """Serve the dashboard HTML."""
    template_path = Path(__file__).parent / "templates" / "index.html"
    if template_path.exists():
        return FileResponse(template_path, media_type="text/html")
    return HTMLResponse(content="<h1>Dashboard</h1><p>Template not found</p>", status_code=500)


# Make paths available to routers
@app.on_event("startup")
async def startup_event():
    """Initialize app state."""
    from .crontab import ensure_config
    ensure_config(CONFIG_PATH)
    app.state.config_path = CONFIG_PATH
    app.state.state_path = STATE_PATH
    if not DASHBOARD_TOKEN:
        logging.getLogger("dashboard").warning(
            "DASHBOARD_TOKEN is not set — dashboard is running without authentication"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
