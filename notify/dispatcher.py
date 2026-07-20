"""Notification dispatcher: routes to ntfy or apprise backend based on user config."""

import logging


def send_notification(
    user: dict,
    notification: dict,
    config: dict,
    logger: logging.Logger,
    thumbnail_override: bytes = None,
) -> bool:
    """Route notification to the appropriate backend."""
    service = user.get("notification_service", "ntfy")

    if service == "apprise":
        from .apprise_backend import send_single_notification
        return send_single_notification(user, notification, config, logger, thumbnail_override)

    from .ntfy import send_single_notification
    ntfy_user = user.get("ntfy_username")
    ntfy_pass = user.get("ntfy_password")
    ntfy_auth = (ntfy_user, ntfy_pass) if ntfy_user and ntfy_pass else None
    return send_single_notification(user, notification, config, ntfy_auth, logger, thumbnail_override)
