# Hybrid Template System Guide

## What You Have Now

5 custom templates with full Photoshop customization support:
- `grid_custom` - 2-column equal grid
- `featured_custom` - One large + thumbnails below
- `strip_custom` - Vertical filmstrip
- `polaroid_custom` - Polaroid frames
- `mosaic_custom` - Varied tile sizes

## How It Works

Each template:
1. **Auto-generates a guide PNG** on first run showing photo positions
2. **Uses your custom background** if provided
3. **Applies smart face cropping** to all photos
4. **Loads optional overlay** for decorative elements

## File Structure

```
custom_templates/
├── grid_custom.py              # Template logic (don't edit)
├── grid_template.png           # Auto-generated guide (reference)
├── grid_background.png         # Your custom background (optional)
├── grid_overlay.png            # Your decorative overlay (optional)
└── (same for featured, strip, polaroid, mosaic...)
```

## Workflow

### Step 1: Generate Guide Files

Run a test to generate template guides:

```bash
# Set config to grid_custom
docker compose build notify
docker compose run --rm notify --slot 4 --test --no-delay --force
```

This creates `grid_template.png` showing where photos will be placed.

### Step 2: Create Custom Background in Photoshop

1. **Open** `/home/immich/immich/memnotify/custom_templates/grid_template.png`
2. **Design your background** (1080x1920):
   - Add gradients, textures, patterns
   - Keep photo areas empty (cyan rectangles show positions)
   - Add decorative elements around photos
3. **Save as** `grid_background.png` (hide the guide layer)

**Example edits:**
- Add a paper texture background
- Create vintage film borders
- Add custom title text "Weekly Memories"
- Add corner decorations

### Step 3: Optional Overlay (Advanced)

For elements that should appear **on top** of photos (frames, vignettes):

1. Create `grid_overlay.png` (1080x1920, transparent PNG)
2. Add frames, borders, or text overlays
3. Save with transparency

### Step 4: Rebuild & Test

```bash
docker compose build notify
docker compose run --rm notify --slot 4 --test --no-delay --force
```

## Photo Positions Reference

### Grid (2 columns)
- 5 photos: 2 cols × 3 rows, ~540×580px each

### Featured
- Photo 1: 1064×1045px (top 55%)
- Photos 2-4: 348×849px each (bottom, horizontal strip)

### Strip (filmstrip)
- 5 photos stacked vertically
- Each: 920×350px (between sprocket holes)

### Polaroid
- 5 polaroid frames, slightly rotated
- Photo area in each: 450×495px + white border

### Mosaic
- Varies by count:
  - 3 photos: 1 large top (60%), 2 small below
  - 4+ photos: 1 large top, 3 thumbnails in row below

## Tips

**Backgrounds:**
- Use 1080×1920px (portrait)
- Keep important elements away from photo areas
- Use subtle textures that don't compete with photos

**Overlays:**
- Export as PNG-24 with transparency
- Keep file sizes reasonable (<2MB)
- Test visibility on different photo types

**Colors:**
- Dark backgrounds work well with white text
- Consider photo variety when choosing colors
- Use semi-transparent elements for overlays

## Switching Templates

Edit `config.yaml`:
```yaml
collage_template: grid_custom      # or featured_custom, strip_custom, etc.
# collage_template: random         # random from all templates
```

Then rebuild:
```bash
docker compose build notify
```

## Debugging

**Template not loading?**
```bash
# Check if template is recognized
docker compose run --rm notify --slot 4 --dry-run
# Should show the template name in logs
```

**Background not appearing?**
- Check file name matches exactly (e.g., `grid_background.png`)
- Ensure file is in `custom_templates/` directory
- Verify dimensions are 1080×1920
- Rebuild container: `docker compose build notify`

**Photos in wrong positions?**
- Check the `*_template.png` guide file
- Verify your background doesn't cover photo areas
- Photos are placed according to predefined positions

## Advanced: Creating New Templates

1. Copy an existing template (e.g., `grid_custom.py`)
2. Modify the `positions` list to define photo areas
3. Update background/overlay/guide file names
4. Save as `my_template.py`
5. Set `collage_template: my_template` in config
6. Rebuild: `docker compose build notify`
