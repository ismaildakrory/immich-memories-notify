"""
Immich Memories Notify - Dashboard
==================================
FastAPI web dashboard for managing notifications.
"""

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

from .models import HealthResponse
from .routers import settings, state, test, secrets, restart

# App configuration
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config.yaml")
STATE_PATH = os.environ.get("STATE_PATH", "/app/state.json")
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")
DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "admin")

# Create FastAPI app
app = FastAPI(
    title="Immich Memories Notify Dashboard",
    description="Web dashboard for managing Immich memory notifications",
    version="1.0.0",
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

    is_username_correct = secrets.compare_digest(
        credentials.username.encode("utf8"),
        DASHBOARD_USER.encode("utf8"),
    )
    is_password_correct = secrets.compare_digest(
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


# Health endpoint (no auth required)
@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="healthy", version="1.0.0")


# Dashboard UI
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
    app.state.config_path = CONFIG_PATH
    app.state.state_path = STATE_PATH


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
