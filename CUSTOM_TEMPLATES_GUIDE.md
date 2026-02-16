# Custom Collage Templates - Quick Guide

## ✅ What's Fixed

1. **Aspect Ratio** - Photos now maintain their original proportions (no more stretching!)
2. **Custom Templates** - You can now create your own designs from PSD files

## 📁 File Structure

```
memnotify/
├── custom_templates/          # ← Put your custom templates here
│   ├── README.md             # Detailed guide
│   ├── example_magazine.py   # Working example
│   └── your_template/        # Your custom design
│       ├── your_template.py  # Template code
│       ├── background.png    # Exported from PSD
│       └── overlays.png      # Frames/decorations
└── config.yaml
```

## 🎨 Creating Templates from PSD

### Step-by-Step Workflow

**1. Design in Photoshop (1920x1080)**
   - Create your collage layout
   - Use separate layers for:
     - Background
     - Decorative elements
     - Text/titles
     - Photo placeholder rectangles (to mark positions)

**2. Export Layers as PNG**
   ```
   File > Export > Layers to Files...
   Format: PNG-24
   Destination: memnotify/custom_templates/my_design/
   ```

**3. Note Photo Positions**
   - Use Photoshop's Info panel (Window > Info)
   - Click on each photo placeholder and note:
     - X, Y position (top-left corner)
     - Width, Height

**4. Create Python Template**

Create `custom_templates/my_design/my_design.py`:

```python
from PIL import Image
from pathlib import Path

def render(images, names, width, height):
    """Your custom template."""
    template_dir = Path(__file__).parent

    # Load your background
    canvas = Image.open(template_dir / "background.png")

    # Helper to fit images (maintains aspect ratio)
    def fit_image(img, w, h):
        img_ratio = img.size[0] / img.size[1]
        target_ratio = w / h
        if img_ratio > target_ratio:
            new_w, new_h = w, int(w / img_ratio)
        else:
            new_w, new_h = int(h * img_ratio), h
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        result = Image.new('RGB', (w, h), (0, 0, 0))
        result.paste(resized, ((w - new_w) // 2, (h - new_h) // 2))
        return result

    # Place photos at positions from your PSD
    if len(images) >= 1:
        photo1 = fit_image(images[0], 800, 600)  # Your measured size
        canvas.paste(photo1, (100, 200))  # Your measured position

    if len(images) >= 2:
        photo2 = fit_image(images[1], 400, 300)
        canvas.paste(photo2, (1000, 200))

    # Overlay decorative elements (with transparency)
    overlay = Image.open(template_dir / "overlays.png")
    canvas.paste(overlay, (0, 0), overlay)  # Third param = transparency mask

    return canvas
```

**5. Test**
```bash
docker compose build notify
docker compose run --rm notify --slot 4 --test --no-delay --force
```

**6. Select in Dashboard**
- Go to Settings → Collage Template
- Your template appears as "my_design"

## 📐 PSD Layer Export Tips

**What to export:**
- ✅ Background gradients/colors
- ✅ Decorative frames/borders
- ✅ Text overlays (as transparent PNG)
- ✅ Any static design elements
- ❌ Don't export photo placeholders (Python will place real photos)

**Export Settings:**
- Format: PNG-24 (32-bit with transparency)
- Color Profile: sRGB
- Resolution: 1920x1080 @ 72 DPI

## 🔍 Measuring Photo Positions in Photoshop

1. Open Info panel: `Window > Info`
2. Select Rectangle tool
3. Draw over your photo placeholder
4. Note the values:
   - **X:** Left edge position
   - **Y:** Top edge position
   - **W:** Width
   - **H:** Height

## 💡 Example: Magazine Cover

**PSD Setup:**
```
Layers:
├── Title Text (transparent PNG with "WEEKLY MEMORIES")
├── Red Line (decorative element)
├── Photo Frame (decorative border)
├── Main Photo Placeholder [X:100, Y:200, W:1200, H:700]
├── Thumb 1 Placeholder [X:1400, Y:200, W:400, H:250]
├── Thumb 2 Placeholder [X:1400, Y:470, W:400, H:250]
└── Background (gradient)
```

**Export:**
- `background.png` - Just the gradient
- `title.png` - Text with transparency
- `frame.png` - Decorative border with transparency

**Python:** See `example_magazine.py` in `custom_templates/`

## 🚀 Quick Template (No PSD)

Pure Python design without PSD:

```python
from PIL import Image, ImageDraw, ImageFont

def render(images, names, width, height):
    canvas = Image.new('RGB', (width, height), (245, 245, 250))

    # Simple 2-column layout
    if images:
        # Left column
        left = fit_image(images[0], width//2 - 20, height - 40)
        canvas.paste(left, (10, 20))

        # Right column (stacked)
        y = 20
        for img in images[1:4]:
            thumb = fit_image(img, width//2 - 20, (height - 60) // 3)
            canvas.paste(thumb, (width//2 + 10, y))
            y += (height - 60) // 3 + 10

    return canvas
```

## 🎯 Testing Your Template

1. **Dry run** (preview without sending):
   ```bash
   docker compose run --rm notify --slot 4 --test --dry-run --no-delay
   ```

2. **Send test** (actual notification):
   ```bash
   docker compose run --rm notify --slot 4 --test --no-delay --force
   ```

3. **Check results**:
   - Notification on your phone
   - "Weekly Highlights" album in Immich

## 📚 Resources

- Full guide: `custom_templates/README.md`
- Example code: `custom_templates/example_magazine.py`
- Pillow docs: https://pillow.readthedocs.io/
- Available fonts: `/usr/share/fonts/truetype/dejavu/`

## ⚡ Pro Tips

- Design at 1920x1080 for best quality
- Use `fit_image()` to maintain photo aspect ratios
- Test with photos of different orientations (portrait/landscape)
- Use transparency for overlays (PNG alpha channel)
- Keep file sizes reasonable (<5MB per layer)
