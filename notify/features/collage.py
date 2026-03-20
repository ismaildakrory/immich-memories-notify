"""Weekly collage: templates, image processing, generation."""

import inspect
import json
import logging
import os
import random
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from PIL import Image

from ..config import get_slots_sent_today, mark_slot_sent
from ..immich import (
    fetch_thumbnail,
    get_asset_people,
    get_or_create_album,
    get_random_person_photo,
    get_top_persons,
    upload_collage_to_album,
)
from ..ntfy import send_single_notification


def cover_crop_image(img: Image.Image, target_w: int, target_h: int, faces: list = None) -> Image.Image:
    """Scale image to cover target dimensions and crop intelligently.

    Uses face bounding boxes to position the crop, ensuring faces are visible.
    Falls back to center crop if no faces provided.

    Args:
        img: Source image
        target_w: Target width
        target_h: Target height
        faces: List of face dicts with boundingBoxX1, boundingBoxY1, boundingBoxX2, boundingBoxY2 (normalized 0-1)
    """
    img_w, img_h = img.size
    img_ratio = img_w / img_h
    target_ratio = target_w / target_h

    # Scale to cover (fill the space completely)
    if img_ratio > target_ratio:
        # Image is wider - fit to height and crop width
        scale = target_h / img_h
    else:
        # Image is taller - fit to width and crop height
        scale = target_w / img_w

    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    scaled = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # Determine crop position
    if faces and len(faces) > 0:
        # Calculate bounding box containing all faces (in scaled coordinates)
        min_x = min(f.get("boundingBoxX1", 0.5) for f in faces) * new_w
        max_x = max(f.get("boundingBoxX2", 0.5) for f in faces) * new_w
        min_y = min(f.get("boundingBoxY1", 0.5) for f in faces) * new_h
        max_y = max(f.get("boundingBoxY2", 0.5) for f in faces) * new_h

        # Center of all faces
        face_center_x = (min_x + max_x) / 2
        face_center_y = (min_y + max_y) / 2

        # Position crop to center on faces
        crop_x = int(face_center_x - target_w / 2)
        crop_y = int(face_center_y - target_h / 2)

        # Clamp to image bounds
        crop_x = max(0, min(crop_x, new_w - target_w))
        crop_y = max(0, min(crop_y, new_h - target_h))
    else:
        # Center crop (fallback)
        crop_x = (new_w - target_w) // 2
        crop_y = (new_h - target_h) // 2

    # Crop to target size
    cropped = scaled.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))
    return cropped


def is_collage_day(settings: dict, target_date: date) -> bool:
    """Check if today is the configured collage day.

    Config uses Sun=0, Sat=6 convention.
    Python weekday() uses Mon=0, Sun=6.
    Convert Python weekday to config convention: (weekday + 1) % 7
    """
    if not settings.get("weekly_collage_enabled", False):
        return False

    collage_day = settings.get("weekly_collage_day", 6)  # Saturday in Sun=0 convention
    python_as_config = (target_date.weekday() + 1) % 7
    return python_as_config == collage_day


# =============================================================================
# Collage Template System
# =============================================================================

COLLAGE_TEMPLATES = {
    # Built-in templates removed - using only custom templates with overlays
}


def load_custom_templates(templates_dir: str = "custom_templates"):
    """Load custom templates from Python files in templates_dir.

    Each custom template file should define a render(images, names, width, height) function.
    Template name is taken from the filename (without .py extension).
    """
    templates_path = Path(templates_dir)
    if not templates_path.exists():
        return

    import importlib.util
    import sys

    for template_file in templates_path.glob("*.py"):
        template_name = template_file.stem
        try:
            # Load module from file
            spec = importlib.util.spec_from_file_location(template_name, template_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[template_name] = module
            spec.loader.exec_module(module)

            # Get render function
            if hasattr(module, 'render'):
                COLLAGE_TEMPLATES[template_name] = module.render
                logging.getLogger("immich-memories-notify").info(
                    f"Loaded custom template: {template_name}"
                )
        except Exception as e:
            logging.getLogger("immich-memories-notify").warning(
                f"Failed to load custom template {template_name}: {e}"
            )


# Load custom templates at module level
load_custom_templates()


def get_template_photo_count(template_name: str, logger: logging.Logger) -> Optional[int]:
    """Get the number of photos a collage template needs from its layout JSON."""
    # Layout files use base name without _custom suffix (e.g. mosaic_layout.json, not mosaic_custom_layout.json)
    base_name = template_name.removesuffix("_custom")
    # custom_templates/ is at the app root, two levels up from notify/features/
    app_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    layout_path = os.path.join(app_root, "custom_templates", f"{base_name}_layout.json")
    try:
        with open(layout_path, "r") as f:
            layout = json.load(f)
        positions = layout.get("positions") or layout.get("photo_positions") or []
        return len(positions) if positions else None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def generate_weekly_collage(
    user: dict,
    config: dict,
    target_date: date,
    settings: dict,
    logger: logging.Logger,
    test_mode: bool = False
) -> Optional[dict]:
    """Generate a collage of top people's photos for weekly notification."""
    try:
        immich_url = config["immich"]["url"]
        api_key = user["immich_api_key"]
        limit = settings.get("collage_person_limit", 5)

        # Get top persons using existing function
        top_persons = get_top_persons(immich_url, api_key, limit=limit, logger=logger)
        if not top_persons:
            logger.info(f"No top people found for user {user['name']}")
            return None

        # Get one random photo per person
        image_data_list = []
        asset_ids = []
        person_names = []
        exclude_days = settings.get("exclude_recent_days", 30)

        for person in top_persons:
            result = get_random_person_photo(
                immich_url=immich_url,
                api_key=api_key,
                top_persons=[person],
                exclude_days=exclude_days,
                logger=logger,
            )
            if result:
                asset_id = result["asset"].get("id")
                if asset_id:
                    try:
                        # Use preview size for better quality collages
                        thumb_bytes = fetch_thumbnail(immich_url, api_key, asset_id, size="preview")
                        image_data_list.append(thumb_bytes)
                        asset_ids.append(asset_id)
                        person_names.append(result["person_name"])
                    except Exception as e:
                        logger.warning(f"Could not fetch image for {result['person_name']}: {e}")

        if not image_data_list:
            logger.info(f"No photos found for top people for user {user['name']}")
            return None

        # Resolve template name early so we know how many photos are needed
        template_name = settings.get("collage_template", "grid")
        if not COLLAGE_TEMPLATES:
            logger.error("No collage templates available. Check custom_templates/ directory.")
            return None
        if template_name == "random":
            template_name = random.choice(list(COLLAGE_TEMPLATES.keys()))
            logger.debug(f"Random template selected: {template_name}")

        # Fill additional slots if the template needs more photos than people
        needed = get_template_photo_count(template_name, logger)
        if needed and len(image_data_list) < needed:
            logger.info(
                f"Template '{template_name}' needs {needed} photos, have {len(image_data_list)}. "
                f"Fetching {needed - len(image_data_list)} more from same people."
            )
            used_asset_ids = set(asset_ids)
            person_index = 0
            max_attempts = needed * 3  # avoid infinite loop if photos exhausted
            attempts = 0
            while len(image_data_list) < needed and attempts < max_attempts:
                person = top_persons[person_index % len(top_persons)]
                person_index += 1
                attempts += 1
                result = get_random_person_photo(
                    immich_url=immich_url,
                    api_key=api_key,
                    top_persons=[person],
                    exclude_days=exclude_days,
                    exclude_asset_ids=used_asset_ids,
                    logger=logger,
                )
                if result:
                    asset_id = result["asset"].get("id")
                    if asset_id and asset_id not in used_asset_ids:
                        try:
                            thumb_bytes = fetch_thumbnail(immich_url, api_key, asset_id, size="preview")
                            image_data_list.append(thumb_bytes)
                            asset_ids.append(asset_id)
                            person_names.append(result["person_name"])
                            used_asset_ids.add(asset_id)
                        except Exception as e:
                            logger.warning(f"Could not fetch fill image for {result['person_name']}: {e}")

        # Create collage with high quality settings (portrait for mobile)
        collage_bytes = create_collage_image(
            image_data_list=image_data_list,
            asset_ids=asset_ids,
            person_names=person_names,
            template_name=template_name,
            logger=logger,
            immich_url=immich_url,
            api_key=api_key,
            width=1080,
            height=1920,
        )

        if not collage_bytes:
            logger.warning(f"Failed to create collage for user {user['name']}")
            return None

        # Upload collage to Immich album
        album_name = settings.get("collage_album_name", "Weekly Highlights")
        asset_id = None

        try:
            album_id = get_or_create_album(immich_url, api_key, album_name, logger)
            if album_id:
                asset_id = upload_collage_to_album(immich_url, api_key, collage_bytes, album_id, logger)
                if asset_id:
                    logger.info(f"Collage uploaded to album '{album_name}' with asset ID: {asset_id}")
        except Exception as e:
            logger.warning(f"Failed to upload collage to album: {e}")

        names_str = ", ".join(person_names[:3])
        if len(person_names) > 3:
            names_str += f" +{len(person_names) - 3} more"

        title = "Weekly Highlights"
        if test_mode:
            title = "[TEST] " + title

        return {
            "title": title,
            "message": f"Your weekly highlights with {names_str}",
            "has_content": True,
            "asset_id": asset_id,
            "is_collage": True,
            "is_video": False,
            "collage_data": collage_bytes if not asset_id else None,
        }

    except Exception as e:
        logger.error(f"Error generating collage for user {user['name']}: {e}")
        return None


def create_collage_image(
    image_data_list: List[bytes],
    person_names: List[str],
    template_name: str,
    logger: logging.Logger,
    asset_ids: List[str] = None,
    immich_url: str = None,
    api_key: str = None,
    width: int = 1080,
    height: int = 1920,
) -> Optional[bytes]:
    """Create a collage image from raw thumbnail bytes using the selected template."""
    try:
        # Convert bytes to PIL Images
        pil_images = []
        for data in image_data_list:
            img = Image.open(BytesIO(data)).convert("RGB")
            pil_images.append(img)

        if not pil_images:
            return None

        # Fetch face data for smart cropping
        faces_list = []
        if asset_ids and immich_url and api_key:
            for asset_id in asset_ids:
                try:
                    people = get_asset_people(immich_url, api_key, asset_id)
                    faces_list.append(people)
                except Exception as e:
                    logger.debug(f"Could not fetch faces for asset {asset_id}: {e}")
                    faces_list.append([])
        else:
            # No face data available, templates will use center crop
            faces_list = [[] for _ in pil_images]

        # Select template (random if requested)
        if not COLLAGE_TEMPLATES:
            logger.error("No collage templates available. Check custom_templates/ directory.")
            return None

        if template_name == "random":
            template_name = random.choice(list(COLLAGE_TEMPLATES.keys()))
            logger.debug(f"Random template selected: {template_name}")

        render_fn = COLLAGE_TEMPLATES.get(template_name)
        if not render_fn:
            logger.error(f"Template '{template_name}' not found. Available: {list(COLLAGE_TEMPLATES.keys())}")
            return None

        # Check if template accepts faces_list parameter (backward compatibility)
        sig = inspect.signature(render_fn)
        if len(sig.parameters) >= 5:
            # New signature with faces_list
            collage = render_fn(pil_images, person_names, width, height, faces_list)
        else:
            # Old signature without faces_list (custom templates)
            logger.debug(f"Template '{template_name}' uses old signature (no faces_list), using fallback")
            collage = render_fn(pil_images, person_names, width, height)

        # Save to JPEG bytes with high quality
        buf = BytesIO()
        collage.save(buf, format='JPEG', quality=95)
        buf.seek(0)
        return buf.getvalue()

    except Exception as e:
        logger.error(f"Error creating collage image: {e}")
        return None


def process_collage_slot(
    user: dict,
    config: dict,
    state: dict,
    target_date: date,
    slot: int,
    test_mode: bool = False,
    dry_run: bool = False,
    force: bool = False,
    logger: logging.Logger = None,
) -> dict:
    """Process a collage notification for a user."""
    try:
        user_name = user["name"]
        ntfy_user = user.get("ntfy_username")
        ntfy_pass = user.get("ntfy_password")
        ntfy_auth = (ntfy_user, ntfy_pass) if ntfy_user and ntfy_pass else None

        # Check if slot already sent
        slots_sent = get_slots_sent_today(state, user_name, target_date)
        if not force and not test_mode and slot in slots_sent:
            logger.info(f"  [{user_name}] Collage slot {slot} already sent today")
            return {"success": True, "message": "Already sent"}

        settings = config.get("settings", {})
        collage_notification = generate_weekly_collage(
            user=user,
            config=config,
            target_date=target_date,
            settings=settings,
            logger=logger,
            test_mode=test_mode,
        )

        if not collage_notification or not collage_notification.get("has_content"):
            logger.info(f"  [{user_name}] No collage generated")
            return {"success": False, "message": "No collage generated"}

        if dry_run:
            logger.info(f"  [{user_name}] [DRY RUN] Would send collage: {collage_notification['title']}")
            return {"success": True, "message": "Dry run successful"}

        # Always provide collage_data as thumbnail fallback (Immich needs time to process uploads)
        thumbnail_override = collage_notification.get("collage_data")

        success = send_single_notification(
            user=user,
            notification=collage_notification,
            config=config,
            ntfy_auth=ntfy_auth,
            logger=logger,
            thumbnail_override=thumbnail_override,
        )

        if success:
            if not test_mode:
                mark_slot_sent(state, user_name, target_date, slot, collage_notification.get("asset_id"))
            logger.info(f"  [{user_name}] Collage sent for slot {slot}")
        else:
            logger.warning(f"  [{user_name}] Failed to send collage")

        return {"success": success, "message": "Sent" if success else "Failed"}

    except Exception as e:
        logger.error(f"Error processing collage slot for {user['name']}: {e}")
        return {"success": False, "message": str(e)}
