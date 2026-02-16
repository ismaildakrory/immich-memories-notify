"""
Polaroid Template - Photos with white frames, slightly rotated
===============================================================
Custom background support: polaroid_background.png (1920x1920)
Custom overlay support: polaroid_overlay.png (transparent PNG)
Custom layout: polaroid_layout.json (photo positions, sizes, rotation)
Auto-generated guide: polaroid_template.png (shows photo positions)
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import json
import random


def cover_crop_image(img, target_w, target_h, faces=None):
    """Smart crop with face detection."""
    img_w, img_h = img.size
    img_ratio = img_w / img_h
    target_ratio = target_w / target_h

    if img_ratio > target_ratio:
        scale = target_h / img_h
    else:
        scale = target_w / img_w

    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    scaled = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    if faces and len(faces) > 0:
        min_x = min(f.get("boundingBoxX1", 0.5) for f in faces) * new_w
        max_x = max(f.get("boundingBoxX2", 0.5) for f in faces) * new_w
        min_y = min(f.get("boundingBoxY1", 0.5) for f in faces) * new_h
        max_y = max(f.get("boundingBoxY2", 0.5) for f in faces) * new_h

        face_center_x = (min_x + max_x) / 2
        face_center_y = (min_y + max_y) / 2

        crop_x = int(face_center_x - target_w / 2)
        crop_y = int(face_center_y - target_h / 2)

        crop_x = max(0, min(crop_x, new_w - target_w))
        crop_y = max(0, min(crop_y, new_h - target_h))
    else:
        crop_x = (new_w - target_w) // 2
        crop_y = (new_h - target_h) // 2

    return scaled.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))


def render(images, names, width, height, faces_list=None):
    """Polaroid frames spread across canvas."""
    if faces_list is None:
        faces_list = [[] for _ in images]

    template_dir = Path(__file__).parent
    bg_path = template_dir / "polaroid_background.png"
    guide_path = template_dir / "polaroid_template.png"
    layout_path = template_dir / "polaroid_layout.json"

    # Randomly select one of 3 overlays
    overlay_num = random.randint(1, 3)
    overlay_path = template_dir / f"polaroid_overlay{overlay_num}.png"
    if not overlay_path.exists():
        overlay_path = template_dir / "polaroid_overlay.png"  # Fallback

    # Polaroid dimensions (defaults)
    photo_w = 380
    photo_h = int(photo_w * 1.1)
    border = 15
    bottom_border = 60

    count = len(images)

    # Load positions from JSON if exists, otherwise use defaults
    if layout_path.exists():
        with open(layout_path) as f:
            layout_data = json.load(f)
            positions = layout_data.get('photo_positions', [])
            # Sort by z_order to handle overlaps (lower z_order rendered first)
            positions = sorted(positions, key=lambda p: p.get('z_order', 0))
    else:
        # Default predefined positions for scattered polaroid look (5 photos max)
        positions = [
            {'x': 50, 'y': 100, 'width': 380, 'height': 418, 'rotation': -5, 'z_order': 1},
            {'x': 550, 'y': 150, 'width': 380, 'height': 418, 'rotation': 8, 'z_order': 2},
            {'x': 100, 'y': 700, 'width': 380, 'height': 418, 'rotation': -3, 'z_order': 3},
            {'x': 500, 'y': 800, 'width': 380, 'height': 418, 'rotation': 5, 'z_order': 4},
            {'x': 280, 'y': 1400, 'width': 380, 'height': 418, 'rotation': -7, 'z_order': 5}
        ]

    # Generate guide (without rotation for clarity)
    if not guide_path.exists():
        guide = Image.new('RGB', (width, height), color=(60, 50, 40))
        draw = ImageDraw.Draw(guide)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        except:
            font = ImageFont.load_default()

        frame_w = photo_w + border * 2
        frame_h = photo_h + border + bottom_border

        for i in range(min(count, 5)):
            pos = positions[i]
            x, y = pos['x'], pos['y']
            w = int(pos.get('width', photo_w))
            h = int(pos.get('height', photo_h))

            # Just show the photo area (no borders)
            draw.rectangle([x, y, x + w, y + h], outline='cyan', width=3)
            draw.text((x + 20, y + 20), f"Photo {i+1}", fill='cyan', font=font)

        draw.text((20, 20), "Photo Positions Guide (No Borders)", fill='yellow', font=font)
        guide.save(guide_path)

    # Load background (convert to RGB to avoid RGBA issues)
    if bg_path.exists():
        canvas = Image.open(bg_path).resize((width, height)).convert('RGB')
    else:
        canvas = Image.new('RGB', (width, height), color=(60, 50, 40))

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except:
        font = ImageFont.load_default()

    # Place photos (sorted by z_order, lower values rendered first)
    for i in range(min(len(images), len(positions))):
        pos = positions[i]

        # Get dimensions from JSON or use defaults (convert to int for PIL)
        current_photo_w = int(pos.get('width', photo_w))
        current_photo_h = int(pos.get('height', photo_h))

        # Crop photo to size with smart face detection
        faces = faces_list[i] if i < len(faces_list) else []
        photo = cover_crop_image(images[i], current_photo_w, current_photo_h, faces=faces)

        # Get rotation from JSON or use random
        angle = pos.get('rotation', random.uniform(-8, 8))

        # Rotate with transparency so corners don't block photos behind
        photo_rgba = photo.convert('RGBA')
        rotated = photo_rgba.rotate(angle, expand=True, fillcolor=(0, 0, 0, 0))

        # Use position from JSON (convert to int for PIL)
        # Adjust for expansion during rotation
        x = int(pos['x']) - (rotated.width - current_photo_w) // 2
        y = int(pos['y']) - (rotated.height - current_photo_h) // 2
        x = max(0, min(x, width - rotated.width))
        y = max(0, min(y, height - rotated.height))

        # Paste with alpha mask to preserve transparency
        canvas.paste(rotated, (x, y), rotated)

    # Apply overlay
    if overlay_path.exists():
        overlay = Image.open(overlay_path).resize((width, height))
        canvas.paste(overlay, (0, 0), overlay)

    # Ensure canvas is RGB mode (not RGBA) for JPEG compatibility
    if canvas.mode != 'RGB':
        canvas = canvas.convert('RGB')

    return canvas
