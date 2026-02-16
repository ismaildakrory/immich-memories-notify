# Custom Collage Templates

This directory is for your custom collage designs. Add Python files here to create new templates that will automatically appear in the dashboard.

## Quick Start

1. **Copy the example**: `cp example_magazine.py my_template.py`
2. **Edit the `render()` function** to create your design
3. **Rebuild**: `docker compose build notify`
4. **Select in dashboard**: Your template will appear as "my_template"

## Creating Templates from PSD Files

### Method 1: Layer Export + Python Compositing

**Best for**: Complex designs with fixed backgrounds, frames, or overlays

**Steps:**

1. **Design in Photoshop/Figma**
   - Create your design at 1920x1080 (Full HD)
   - Use layers for background, frames, decorative elements
   - Leave photo areas empty or use placeholder rectangles

2. **Export Layers**
   ```
   File > Export > Layers to Files...
   - Format: PNG-24 (with transparency if needed)
   - Save to: custom_templates/my_design/
   ```

3. **Note Photo Positions**
   - Write down the X, Y, Width, Height of each photo area
   - Example: Photo 1 at (100, 200), size 800x600

4. **Create Python Template**
   ```python
   from PIL import Image
   from pathlib import Path

   def render(images, names, width, height):
       template_dir = Path(__file__).parent / "my_design"

       # Load background layer
       canvas = Image.open(template_dir / "background.png")

       # Place photos in specific positions
       if len(images) >= 1:
           photo1 = fit_image(images[0], 800, 600)
           canvas.paste(photo1, (100, 200))

       if len(images) >= 2:
           photo2 = fit_image(images[1], 400, 300)
           canvas.paste(photo2, (1000, 200))

       # Optional: overlay frames/decorations
       # frame = Image.open(template_dir / "frame.png")
       # canvas.paste(frame, (0, 0), frame)  # Use frame as mask for transparency

       return canvas
   ```

### Method 2: Pure Python Design

**Best for**: Dynamic layouts, programmatic designs

See `example_magazine.py` for a complete example.

**Key functions available:**
```python
# Fit image maintaining aspect ratio
photo = fit_image(images[0], target_width, target_height, bg_color=(r,g,b))

# Draw shapes
from PIL import ImageDraw
draw = ImageDraw.Draw(canvas)
draw.rectangle([x1, y1, x2, y2], fill=(r, g, b))
draw.ellipse([x1, y1, x2, y2], fill=(r, g, b))
draw.text((x, y), "Text", fill=(r, g, b), font=font)

# Load fonts
from PIL import ImageFont
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
```

### Method 3: Template Definition (Coming Soon)

JSON-based template definitions for non-programmers.

## Template Function Signature

```python
def render(images: list, names: list, width: int, height: int) -> Image:
    """
    Args:
        images: List of PIL Image objects (high-res photos)
        names: List of person names (strings)
        width: Canvas width (1920 for HD)
        height: Canvas height (1080 for HD)

    Returns:
        PIL Image object (final collage)
    """
    pass
```

## Example PSD Workflow

**Scenario**: Magazine cover with 1 large photo + 3 small photos

1. **Photoshop Setup**
   - Canvas: 1920x1080px
   - Layers:
     - Background (gradient)
     - Title text "WEEKLY MEMORIES"
     - Photo frame decorations
     - Photo placeholder rectangles (to mark positions)

2. **Export**
   ```
   Layers to export:
   - background.png (just the gradient)
   - title.png (text with transparency)
   - frames.png (decorative frames, transparent)
   ```

3. **Measure Placeholders** (in Photoshop)
   - Main photo: X=100, Y=200, W=1200, H=700
   - Thumb 1: X=1400, Y=200, W=400, H=250
   - Thumb 2: X=1400, Y=470, W=400, H=250
   - Thumb 3: X=1400, Y=740, W=400, H=250

4. **Python Template**
   ```python
   def render(images, names, width, height):
       template_dir = Path(__file__).parent / "magazine_cover"
       canvas = Image.open(template_dir / "background.png")

       # Main photo
       if images:
           main = fit_image(images[0], 1200, 700)
           canvas.paste(main, (100, 200))

       # Thumbnails
       thumb_positions = [(1400, 200), (1400, 470), (1400, 740)]
       for i, pos in enumerate(thumb_positions):
           if i + 1 < len(images):
               thumb = fit_image(images[i + 1], 400, 250)
               canvas.paste(thumb, pos)

       # Overlay decorative frames
       frames = Image.open(template_dir / "frames.png")
       canvas.paste(frames, (0, 0), frames)

       # Overlay title
       title = Image.open(template_dir / "title.png")
       canvas.paste(title, (0, 0), title)

       return canvas
   ```

## Tips

- **Use high-res assets**: Design at 1920x1080 minimum
- **Test with `fit_image()`**: It maintains aspect ratio and centers photos
- **Transparency**: Use PNG with alpha channel for overlays
- **Fonts**: Installed fonts available at `/usr/share/fonts/truetype/dejavu/`
- **Colors**: Use RGB tuples: `(255, 0, 0)` for red
- **Debug**: Print dimensions to verify positioning

## File Structure Example

```
custom_templates/
├── README.md
├── example_magazine.py
└── my_magazine_cover/
    ├── my_magazine_cover.py
    ├── background.png
    ├── title.png
    └── frames.png
```

## Testing Your Template

```bash
# Rebuild container
docker compose build notify

# Test with dry run
docker compose run --rm notify --slot 4 --test --dry-run --no-delay --force

# Send actual test
docker compose run --rm notify --slot 4 --test --no-delay --force
```

## Advanced: Masks and Effects

```python
from PIL import ImageFilter, ImageEnhance

# Apply blur to background
bg = bg.filter(ImageFilter.GaussianBlur(radius=10))

# Adjust brightness
enhancer = ImageEnhance.Brightness(photo)
photo = enhancer.enhance(1.2)

# Create circular mask for photo
from PIL import ImageDraw
mask = Image.new('L', (400, 400), 0)
draw = ImageDraw.Draw(mask)
draw.ellipse([0, 0, 400, 400], fill=255)
canvas.paste(photo, (100, 100), mask)
```

## Need Help?

- Check `example_magazine.py` for working code
- Pillow documentation: https://pillow.readthedocs.io/
- Image positioning: Use Photoshop ruler/info panel for exact coordinates
