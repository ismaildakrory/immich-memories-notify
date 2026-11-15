from unittest.mock import MagicMock

from PIL import Image

from notify.features import collage
from notify.features.collage import cover_crop_image, resolve_template_name


def test_cover_crop_returns_exact_size_center_crop():
    img = Image.new("RGB", (400, 200))
    out = cover_crop_image(img, 100, 100)
    assert out.size == (100, 100)


def test_cover_crop_follows_faces():
    # Left half red, right half blue; a face on the right should keep blue pixels
    img = Image.new("RGB", (400, 200), (255, 0, 0))
    for x in range(200, 400):
        for y in range(200):
            img.putpixel((x, y), (0, 0, 255))
    faces = [{"boundingBoxX1": 0.8, "boundingBoxX2": 0.95, "boundingBoxY1": 0.3, "boundingBoxY2": 0.6}]
    out = cover_crop_image(img, 100, 100, faces=faces)
    assert out.getpixel((50, 50)) == (0, 0, 255)
    out_center = cover_crop_image(img, 100, 100)
    assert out_center.getpixel((5, 50)) == (255, 0, 0)
    assert out_center.getpixel((95, 50)) == (0, 0, 255)


def test_resolve_template_name(monkeypatch):
    monkeypatch.setattr(collage, "COLLAGE_TEMPLATES", {"grid_custom": object(), "strip_custom": object()})
    log = MagicMock()
    assert resolve_template_name("grid_custom", log) == "grid_custom"
    assert resolve_template_name("grid", log) == "grid_custom"
    assert resolve_template_name("random", log) in ("grid_custom", "strip_custom")
    assert resolve_template_name("nope", log) is None
    monkeypatch.setattr(collage, "COLLAGE_TEMPLATES", {})
    assert resolve_template_name("random", log) is None
