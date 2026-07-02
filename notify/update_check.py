"""Check for new releases on GitHub and notify the admin."""

import logging
from pathlib import Path

import requests

from .config import load_state, save_state, load_config

GITHUB_REPO = "ismaildakrory/immich-memories-notify"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def get_current_version() -> str:
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "0.0.0"


def parse_version(v: str) -> tuple:
    """Parse version string like '1.2.3' into comparable tuple."""
    v = v.lstrip("v")
    parts = []
    for part in v.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_for_updates(config_path: str = "config.yaml", logger: logging.Logger = None):
    """Check GitHub for new release and notify admin if available."""
    if logger is None:
        logger = logging.getLogger("immich-memories-notify")

    config = load_config(config_path)
    state_file = config.get("settings", {}).get("state_file", "state/state.json")
    state = load_state(state_file)

    current_version = get_current_version()
    last_notified = state.get("update_notified_version")

    logger.info(f"Checking for updates (current: v{current_version})...")

    try:
        resp = requests.get(RELEASES_URL, timeout=10, headers={"Accept": "application/vnd.github.v3+json"})
        if resp.status_code == 404:
            logger.info("No releases found on GitHub yet")
            return
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Could not check for updates: {e}")
        return

    data = resp.json()
    latest_tag = data.get("tag_name", "")
    release_name = data.get("name", latest_tag)
    latest_version = latest_tag.lstrip("v")

    if not latest_version:
        logger.warning("Could not parse latest version from GitHub")
        return

    if parse_version(latest_version) <= parse_version(current_version):
        logger.info(f"Up to date (latest: v{latest_version})")
        return

    if last_notified == latest_version:
        logger.info(f"Update v{latest_version} available but already notified")
        return

    # New version available — notify the first user
    users = config.get("users", [])
    admin = next((u for u in users if u.get("enabled", True)), None)
    if not admin:
        logger.warning("No enabled users to notify about update")
        return

    ntfy_url = config.get("ntfy", {}).get("url", "")
    if not ntfy_url:
        logger.warning("ntfy URL not configured, cannot send update notification")
        return

    topic = admin.get("ntfy_topic", "")
    ntfy_user = admin.get("ntfy_username")
    ntfy_pass = admin.get("ntfy_password")
    auth = (ntfy_user, ntfy_pass) if ntfy_user and ntfy_pass else None

    title = f"Update Available: v{latest_version}"
    message = (
        f"A new version of Immich Memories Notify is available!\n\n"
        f"Current: v{current_version}\n"
        f"Latest:  v{latest_version}\n"
    )
    if release_name and release_name != latest_tag:
        message += f"Release: {release_name}\n"
    message += f"\nhttps://github.com/{GITHUB_REPO}/releases/latest"

    try:
        title_encoded = title
        try:
            title.encode('ascii')
        except UnicodeEncodeError:
            import base64
            title_encoded = f"=?UTF-8?B?{base64.b64encode(title.encode('utf-8')).decode('ascii')}?="

        headers = {
            "Title": title_encoded,
            "Tags": "arrow_up,package",
            "Priority": "default",
            "Click": f"https://github.com/{GITHUB_REPO}/releases/latest",
        }

        resp = requests.post(
            f"{ntfy_url}/{topic}",
            headers=headers,
            data=message.encode("utf-8"),
            auth=auth,
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"Update notification sent to {admin['name']} (v{current_version} -> v{latest_version})")
    except Exception as e:
        logger.error(f"Failed to send update notification: {e}")
        return

    # Mark as notified so we don't spam
    state["update_notified_version"] = latest_version
    save_state(state_file, state)
