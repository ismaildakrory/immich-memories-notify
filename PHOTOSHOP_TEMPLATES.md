# Photoshop Template Guide

## 📱 Portrait Mode - 1080 × 1920

All collages are now **portrait orientation** for optimal mobile viewing!

## 🎨 Template Reference Images

Located in `custom_templates/`:

| File | Description |
|------|-------------|
| **all_templates_overview.png** | Shows all 5 layouts side-by-side |
| **template_grid.png** | Grid layout guide (2 columns) |
| **template_featured.png** | Featured layout guide (1 large + smaller below) |
| **template_strip.png** | Film strip layout guide (vertical) |
| **template_polaroid.png** | Polaroid layout guide (stacked) |
| **template_mosaic.png** | Mosaic layout guide (varied sizes) |

## 📐 Using Templates in Photoshop

### Step 1: Open Template in Photoshop
```
File > Open > custom_templates/template_grid.png
(or whichever template you want to customize)
```

### Step 2: Understanding the Template
Each template shows:
- **Blue rectangles** = Photo placement areas
- **Dimensions** = Width × Height for each photo
- **Positions** = (X, Y) coordinates for top-left corner
- **Crosshairs** = Center of each photo area
- **Labels** = "Photo 1", "Photo 2", etc.

### Step 3: Add Your Design
```
Canvas Size: 1080 × 1920 pixels @ 72 DPI

Create new layers BELOW or ABOVE the guide:
- Background layer (gradients, colors, textures)
- Decorative frames
- Text overlays
- Graphic elements
- Borders/shadows

Keep the template guide visible to see photo positions!
```

### Step 4: Export Your Design Layers
```
1. Hide/delete the template guide layer
2. File > Export > Layers to Files
3. Format: PNG-24
4. Destination: custom_templates/my_design/
5. Export:
   - background.png (your background)
   - overlays.png (frames, text - with transparency)
   - Any other decorative layers
```

## 📏 Template Specifications

### Grid Layout
```
Dimensions: 1080 × 1920
Photos: 2 columns × 3 rows (for 6 photos)
Cell Size: ~520 × 580 px each
Padding: 16px between cells
Use for: Equal importance to all photos
```

### Featured Layout
```
Dimensions: 1080 × 1920
Main Photo: 1048 × 1024 px (top 55%)
Thumbnails: 320 × 808 px each (bottom row)
Use for: Highlighting one main photo
```

### Strip Layout
```
Dimensions: 1080 × 1920
Photos: 4 stacked vertically
Photo Area: 888 × 380 px each
Sprocket holes on sides
Use for: Vintage film aesthetic
```

### Polaroid Layout
```
Dimensions: 1080 × 1920
Photo Size: 450 × 540 px
Frame: 510 × 710 px (with border + caption area)
Rotation: ±12 degrees random
Use for: Casual, scrapbook feel
```

### Mosaic Layout
```
Dimensions: 1080 × 1920
Top Photo: 1064 × 1120 px (60% height)
Bottom 3: 341 × 768 px each
Use for: Dynamic, modern layout
```

## 🎯 Example Workflow: Custom Magazine Cover

### 1. Photoshop Design
```
File > New > 1080 × 1920 px

Layers:
├── Title Text ("WEEKLY MEMORIES")
├── Decorative Elements (lines, shapes)
├── Photo Frames/Borders
└── Background Gradient
```

### 2. Open Template Guide
```
File > Place Embedded > template_featured.png
(Use as reference for photo positions)
```

### 3. Design Around Photo Areas
- Add background gradient
- Add title text at top
- Add decorative borders matching photo positions
- Add any graphic elements

### 4. Export Layers
```
Hide template guide layer
Export to: custom_templates/magazine_cover/
- background.png
- title.png (with transparency)
- frames.png (with transparency)
```

### 5. Create Python Template
See `CUSTOM_TEMPLATES_GUIDE.md` for code examples

## 💡 Design Tips

### Colors & Contrast
- Use dark backgrounds for light photos
- Use light backgrounds for dark photos
- Add subtle shadows for depth

### Typography
- Title: 48-60pt bold
- Names: 20-24pt regular
- Keep text away from photo edges

### Photo Frames
- 8-16px borders work well
- Use subtle shadows: 0-4px blur, 20% opacity
- Rounded corners: 4-8px radius

### Decorative Elements
- Keep it minimal - photos are the focus
- Use transparency (PNG alpha channel)
- Match colors to photo tones

### Mobile Optimization
- Test at actual size (1080×1920)
- Ensure text is readable on small screens
- Use high contrast for important elements

## 🔧 Layer Organization

### Recommended Layer Structure
```
Photoshop Layers:
├── [EXPORT] Overlays (frames, text)
│   └── Decorative borders
│   └── Title text
│   └── Accent graphics
├── [GUIDE] Template Reference
│   └── Photo placement guide (hide before export)
└── [EXPORT] Background
    └── Gradient or solid color
    └── Background texture
```

## 📤 Export Settings

### PNG-24 (Recommended)
```
Format: PNG-24
Color Profile: sRGB IEC61966-2.1
Bit Depth: 32-bit (8 bits × 4 channels)
Transparency: Yes
Compression: Smallest File
```

### For Overlays (Transparency)
```
Make sure:
- Background layer is hidden/deleted
- Only export layers with transparency needs
- Use PNG-24 format
```

## 🚀 Quick Start Templates

Copy one of these into Photoshop to start:

### Minimal Design
- White background
- Photos only
- Clean and simple

### Magazine Style
- Bold title at top
- Colored accent lines
- Modern typography

### Scrapbook Style
- Textured background
- Polaroid-style frames
- Handwritten-style fonts

### Dark Mode
- Black/dark gray background
- Thin white borders
- Glowing text

## 📱 Testing Your Design

1. **In Photoshop**: View at 100% zoom on your monitor
2. **Export test**: Save as JPEG at 1080×1920
3. **View on phone**: Transfer to your phone to check readability
4. **Adjust**: Increase text size or contrast if needed

## 🎨 Color Palettes

### Warm & Cozy
```
Background: #F5F1E8
Accent: #D4A574
Text: #4A4238
```

### Cool & Modern
```
Background: #1E2432
Accent: #4A9FD9
Text: #E8E8F0
```

### Vibrant & Fun
```
Background: #FFF8F0
Accent: #FF6B6B
Text: #2C3E50
```

## 📚 Resources

- Template guides: `custom_templates/template_*.png`
- Code examples: `custom_templates/example_magazine.py`
- Detailed guide: `CUSTOM_TEMPLATES_GUIDE.md`

## ✨ Final Notes

- **Aspect ratio is preserved** - photos won't stretch!
- **High quality** - 1080×1920 portrait, JPEG quality 95
- **Auto-loads** - just add .py file to custom_templates/
- **Test easily** - `docker compose run --rm notify --slot 4 --test --no-delay --force`

Happy designing! 🎨
