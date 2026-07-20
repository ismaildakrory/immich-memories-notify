"""Apprise notification backend: sends notifications via Telegram, Discord, etc."""

import logging
import os
import tempfile

import apprise

from .immich import fetch_thumbnail
from .utils import with_retry


def send_single_notification(
    user: dict,
    notification: dict,
    config: dict,
    logger: logging.Logger,
    thumbnail_override: bytes = None,
) -> bool:
    """Send a notification via Apprise."""
    name = user["name"]
    asset_id = notification.get("asset_id")
    apprise_url = user.get("apprise_url", "")

    if not apprise_url:
        logger.error(f"  [{name}] No apprise_url configured")
        return False

    immich_url = config["immich"]["url"]
    click_base = config["immich"].get("external_url") or ""
    if click_base and not click_base.startswith(("http://", "https://")):
        click_base = f"https://{click_base}"
    retry_config = config["settings"]["retry"]
    api_key = user["immich_api_key"]

    # Fetch thumbnail
    thumbnail_data = None
    if thumbnail_override and not asset_id:
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
    elif thumbnail_override:
        thumbnail_data = thumbnail_override

    # Build message body — append click URL since Apprise has no Click header
    click_url = notification.get("click_url")
    if not click_url and click_base:
        if asset_id:
            click_url = f"{click_base}/photos/{asset_id}"
        else:
            click_url = f"{click_base}/"

    body = notification["message"]
    if click_url:
        body = f"{body}\n\n{click_url}"

    title = notification["title"]

    # Create Apprise instance and add URLs (whitespace-separated for multi-target)
    ap = apprise.Apprise()
    for url in apprise_url.split():
        if url.strip():
            ap.add(url.strip())

    if not ap:
        logger.error(f"  [{name}] No valid Apprise URLs configured")
        return False

    # Send with attachment if available
    tmp_path = None
    try:
        attach = None
        if thumbnail_data:
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="memnotify-")
            os.write(tmp_fd, thumbnail_data)
            os.close(tmp_fd)
            attach = apprise.AppriseAttachment()
            attach.add(tmp_path)

        success = with_retry(
            lambda: ap.notify(
                title=title,
                body=body,
                attach=attach,
            ),
            max_attempts=retry_config["max_attempts"],
            delay=retry_config["delay_seconds"],
            logger=logger,
        )
        return success

    except Exception as e:
        logger.error(f"  [{name}] Apprise notification failed: {e}")
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
