"""ntfy API: upload images, send notifications."""

import logging
import uuid

import requests

from .immich import fetch_thumbnail
from .utils import with_retry


def upload_image_to_ntfy(ntfy_url: str, image_data: bytes, auth: tuple = None, timeout: int = 30) -> str | None:
    """Upload an image to ntfy and return the URL."""
    logger = logging.getLogger("immich-memories-notify")
    temp_topic = f"upload-{uuid.uuid4().hex[:12]}"
    url = f"{ntfy_url}/{temp_topic}"

    headers = {"Filename": "memory.jpg"}
    response = requests.put(url, headers=headers, data=image_data, auth=auth, timeout=timeout)

    if response.status_code == 200:
        data = response.json()
        attachment = data.get("attachment", {})
        attachment_url = attachment.get("url")
        if not attachment_url:
            logger.warning("ntfy upload returned 200 but no attachment URL — check that NTFY_BASE_URL and NTFY_ATTACHMENT_CACHE_SIZE are set on your ntfy server")
        return attachment_url

    body = response.text[:200]
    if "attachments not allowed" in body.lower():
        logger.warning(
            "ntfy rejected attachment upload: attachments not allowed. "
            "Fix: set auth-file in your ntfy server.yaml, create a user with "
            "'ntfy user add <username>', then grant access with "
            "'ntfy access <username> \"*\" read-write'. "
            "See: https://docs.ntfy.sh/config/#attachments"
        )
    elif response.status_code in (401, 403):
        logger.warning(
            f"ntfy rejected upload ({response.status_code}): check that NTFY_USER and "
            "NTFY_PASSWORD in your .env match a valid ntfy user, and that the user has "
            "read-write access: ntfy access <username> '*' read-write"
        )
    else:
        logger.warning(f"ntfy upload failed: {response.status_code} — {body}")
    return None


def send_notification(
    ntfy_url: str,
    topic: str,
    title: str,
    message: str,
    thumbnail_data: bytes = None,
    click_url: str = None,
    auth: tuple = None,
    timeout: int = 10,
    is_video: bool = False,
) -> bool:
    """Send a notification to ntfy."""
    url = f"{ntfy_url}/{topic}"

    # Use different tags for videos
    tags = "movie,calendar" if is_video else "camera,calendar"

    # Encode title for HTTP header (RFC 2047 for non-ASCII)
    try:
        # Try latin-1 encoding first (fast path)
        title.encode('latin-1')
        encoded_title = title
    except UnicodeEncodeError:
        # Contains non-ASCII, use base64 encoding for header
        import base64
        encoded_title = f"=?UTF-8?B?{base64.b64encode(title.encode('utf-8')).decode('ascii')}?="

    headers = {
        "Title": encoded_title,
        "Tags": tags,
        "Priority": "default",
    }

    if click_url:
        headers["Click"] = click_url

    # Upload thumbnail and attach it
    if thumbnail_data:
        image_url = upload_image_to_ntfy(ntfy_url, thumbnail_data, auth=auth)
        if image_url:
            headers["Attach"] = image_url
        else:
            logging.getLogger("immich-memories-notify").warning(
                f"Thumbnail upload failed for topic '{topic}' — notification will be sent without preview ({len(thumbnail_data):,} bytes attempted)"
            )

    response = requests.post(url, headers=headers, data=message.encode("utf-8"), auth=auth, timeout=timeout)
    response.raise_for_status()
    return True


def send_single_notification(
    user: dict,
    notification: dict,
    config: dict,
    ntfy_auth: tuple,
    logger: logging.Logger,
    thumbnail_override: bytes = None,
) -> bool:
    """Send a single notification."""
    name = user["name"]
    asset_id = notification.get("asset_id")

    immich_url = config["immich"]["url"]
    ntfy_url = config["ntfy"]["url"]
    topic = user["ntfy_topic"]
    retry_config = config["settings"]["retry"]
    api_key = user["immich_api_key"]

    # Fetch thumbnail with retry
    # If a thumbnail_override is provided and preferred (e.g. Then & Now composite), use it directly.
    # Otherwise fetch from Immich and fall back to override on failure.
    thumbnail_data = None
    if thumbnail_override and not asset_id:
        # No asset to fetch — use override directly (Then & Now, failed collage upload, etc.)
        thumbnail_data = thumbnail_override
    elif asset_id:
        try:
            thumbnail_data = with_retry(
                lambda: fetch_thumbnail(immich_url, api_key, asset_id),
                max_attempts=retry_config["max_attempts"],
                delay=retry_config["delay_seconds"],
                logger=logger,
            )
            logger.debug(f"  [{name}] Thumbnail: {len(thumbnail_data):,} bytes")
        except Exception as e:
            logger.warning(f"  [{name}] Could not fetch thumbnail: {e}")
            if thumbnail_override:
                thumbnail_data = thumbnail_override
                logger.debug(f"  [{name}] Using fallback thumbnail: {len(thumbnail_data):,} bytes")
    elif thumbnail_override:
        thumbnail_data = thumbnail_override

    # Send notification with retry
    try:
        # Use pre-built click_url from notification (e.g. Then & Now links to "now" photo)
        # or build from asset_id
        click_url = notification.get("click_url")
        if not click_url:
            if asset_id:
                click_url = f"https://my.immich.app/photos/{asset_id}"
            else:
                click_url = "https://my.immich.app/"
        is_video = notification.get("is_video", False)
        success = with_retry(
            lambda: send_notification(
                ntfy_url=ntfy_url,
                topic=topic,
                title=notification["title"],
                message=notification["message"],
                thumbnail_data=thumbnail_data,
                click_url=click_url,
                auth=ntfy_auth,
                is_video=is_video,
            ),
            max_attempts=retry_config["max_attempts"],
            delay=retry_config["delay_seconds"],
            logger=logger,
        )
        return success
    except Exception as e:
        logger.error(f"  [{name}] Error sending notification: {e}")
        return False
