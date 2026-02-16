"""
Strip Template - Horizontal film strip layout
==============================================
Custom background support: strip_background.png (1920x1920)
Custom overlay support: strip_overlay.png (transparent PNG)
Custom layout: strip_layout.json (photo positions, sizes, rotation)
Auto-generated guide: strip_template.png (shows photo positions)
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
    """Strip layout with JSON-driven positioning."""
    if faces_list is None:
        faces_list = [[] for _ in images]

    template_dir = Path(__file__).parent
    bg_path = template_dir / "strip_background.png"
    guide_path = template_dir / "strip_template.png"
    layout_path = template_dir / "strip_layout.json"

    # Randomly select one of 3 overlays
    overlay_num = random.randint(1, 3)
    overlay_path = template_dir / f"strip_overlay{overlay_num}.png"
    if not overlay_path.exists():
        overlay_path = template_dir / "strip_overlay.png"  # Fallback

    # Load layout from JSON
    if layout_path.exists():
        with open(layout_path) as f:
            layout = json.load(f)
            positions = layout.get('positions', [])
    else:
        # Default strip positions (horizontal)
        count = len(images)
        padding = 8
        strip_w = (width - padding * (count + 1)) // count

        positions = []
        for i in range(count):
            positions.append({
                'x': padding + i * (strip_w + padding),
                'y': (height - strip_w) // 2,
                'width': strip_w,
                'height': strip_w,
                'rotation': 0,
                'z_order': i
            })

    # Sort by z_order
    positions = sorted(positions, key=lambda p: p.get('z_order', 0))

    # Generate guide
    if not guide_path.exists():
        guide = Image.new('RGB', (width, height), color=(30, 30, 50))
        draw = ImageDraw.Draw(guide)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        except:
            font = ImageFont.load_default()

        for i in range(min(len(positions), 5)):
            pos = positions[i]
            x, y = pos['x'], pos['y']
            w = int(pos.get('width', 100))
            h = int(pos.get('height', 100))
            draw.rectangle([x, y, x + w, y + h], outline='cyan', width=3)
            draw.text((x + 20, y + 20), f"Photo {i+1}", fill='cyan', font=font)

        draw.text((20, 20), "Strip Template Guide - Horizontal", fill='yellow', font=font)
        guide.save(guide_path)

    # Load background
    if bg_path.exists():
        canvas = Image.open(bg_path).resize((width, height)).convert('RGB')
    else:
        canvas = Image.new('RGB', (width, height), color=(30, 30, 50))

    # Place photos
    for i in range(min(len(images), len(positions))):
        pos = positions[i]
        current_photo_w = int(pos.get('width', 100))
        current_photo_h = int(pos.get('height', 100))

        faces = faces_list[i] if i < len(faces_list) else []
        photo = cover_crop_image(images[i], current_photo_w, current_photo_h, faces=faces)

        angle = pos.get('rotation', 0)

        if angle != 0:
            photo_rgba = photo.convert('RGBA')
            rotated = photo_rgba.rotate(angle, expand=True, fillcolor=(0, 0, 0, 0))
            x = int(pos['x']) - (rotated.width - current_photo_w) // 2
            y = int(pos['y']) - (rotated.height - current_photo_h) // 2
            x = max(0, min(x, width - rotated.width))
            y = max(0, min(y, height - rotated.height))
            canvas.paste(rotated, (x, y), rotated)
        else:
            x = int(pos['x'])
            y = int(pos['y'])
            canvas.paste(photo, (x, y))

    # Apply overlay
    if overlay_path.exists():
        overlay = Image.open(overlay_path).resize((width, height))
        canvas.paste(overlay, (0, 0), overlay)

    if canvas.mode != 'RGB':
        canvas = canvas.convert('RGB')

    return canvas
