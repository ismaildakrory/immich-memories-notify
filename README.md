# Immich Memories Notify

Get daily push notifications when you have photo memories in [Immich](https://immich.app/) - just like Google Photos!

![Notification Example](https://via.placeholder.com/400x200?text=Memory+Notification+Preview)

## Features

- **Daily Memory Notifications** - Get notified when you have photos from this day in previous years
- **Face Preference** - Prefers photos with recognized faces (your top 5 named people)
- **Group Photo Priority** - Prioritizes photos with 2+ named people
- **Person Photos** - Random photos of your favorite people when no memories exist
- **Location Context** - Shows city/country when available (33% chance)
- **Album Awareness** - Displays album name when photo is in an album
- **Video Support** - Different emoji (🎬) and message templates for videos
- **Smart Scheduling** - Multiple notification slots with random timing within configurable windows
- **Web Dashboard** - Browser-based UI to manage settings, users, and trigger tests
- **Cozy Messages** - Randomized warm message templates (customizable)
- **Multi-User Support** - Each user gets their own top people and personalized notifications
- **Rich Notifications** - Includes thumbnail preview with person names
- **Click to Open** - Tap notification to open photo directly in Immich
- **Self-Hosted** - Works with your self-hosted Immich and ntfy instances
- **Docker Ready** - Easy deployment with Docker Compose
- **Privacy First** - Your photos never leave your network

## How It Works

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   Immich    │ ───> │   Script    │ ───> │    ntfy     │
│   Server    │      │  (Python)   │      │   Server    │
└─────────────┘      └─────────────┘      └─────────────┘
                            │                    │
                            ▼                    ▼
                     ┌─────────────┐      ┌─────────────┐
                     │  Dashboard  │      │  Mobile App │
                     │  (Web UI)   │      │ Notification│
                     └─────────────┘      └─────────────┘
```

### Notification Logic

| Scenario | Slots 1-3 | Slot 4 |
|----------|-----------|--------|
| Has memories today | Memory photo (prefers faces) | Random person photo |
| No memories today | Random person photo | Random person photo |

**Key features:**
- Photos with recognized faces from your top 5 named people are prioritized
- Group photos (2+ named people) get highest priority
- Person photos exclude the last 30 days (configurable)
- Each slot sends at a random time within its window (e.g., 8-10 AM)
- Per-user top people based on their own photo library
- Location and album info added when available

## Requirements

- [Immich](https://immich.app/) server (self-hosted)
- [ntfy](https://ntfy.sh/) server (self-hosted or use ntfy.sh)
- Docker & Docker Compose (recommended) OR Python 3.8+
- ntfy mobile app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/app/ntfy/id1625396347))
- **Named people in Immich** - For face preference and person photos, name your frequently appearing people in Immich

## Disclaimer

Built this mostly vibe coding! Been running smoothly on my setup. PRs and feedback welcome!

## Quick Start

```bash
# 1. Clone and start
git clone https://github.com/ismaildakrory/immich-memories-notify.git
cd immich-memories-notify
docker compose up -d dashboard

# Important Note for Updating:
# Rebuild after updates (must recreate container for volume mounts)
docker compose down dashboard && docker compose up -d --build dashboard

# 2. Open dashboard and configure
# http://localhost:5000
```

### Configure via Dashboard

1. **Secrets tab** → Add your server URLs and API keys
   - Get Immich API key from: Account Settings → API Keys

2. **Settings tab** → Add/edit users and notification times

3. **Test tab** → Send a test notification

4. **Start the scheduler:**
```bash
docker compose up -d scheduler
```

### Subscribe to ntfy

Open the ntfy app on your phone and subscribe to your topic (e.g., `immich-memories-user1`) on your ntfy server.

## Web Dashboard

Access the dashboard at `http://localhost:5000` to manage your setup through a browser interface.

### Features

- **Status Tab** - View today's sent notifications per user
- **Settings Tab** - Edit notification windows, manage users, toggle features
- **Messages Tab** - Customize message templates
- **Secrets Tab** - View/edit API keys and passwords (masked display)
- **Test Tab** - Trigger test notifications for any slot

### Screenshots
![ntfy](https://github.com/user-attachments/assets/b685ebab-2256-4da4-8b80-e00d4d110cd0)
![expand](https://github.com/user-attachments/assets/f039766a-5b87-4bbd-8965-3e1cad0da19f)
<img width="1256" height="590" alt="Status" src="https://github.com/user-attachments/assets/9d00c677-5124-4617-b89f-9468b279e818" />
<img width="1031" height="1201" alt="Settings" src="https://github.com/user-attachments/assets/829b0fc4-4af3-45e7-a4e0-0e8cfe9221d4" />
<img width="1257" height="1115" alt="Messages" src="https://github.com/user-attachments/assets/94df34a8-17d9-47c3-a865-ea3286fd5516" />
<img width="1242" height="1196" alt="Secrets" src="https://github.com/user-attachments/assets/732ace52-0ea0-4ab7-bb42-82c543beaae2" />
<img width="1250" height="1115" alt="Test" src="https://github.com/user-attachments/assets/2ea0e52e-4854-4268-8b79-a14905428e71" />
### Authentication

Set `DASHBOARD_TOKEN` in `.env` to enable authentication:

```bash
DASHBOARD_USER=admin
DASHBOARD_TOKEN=your-secret-token
```

If not set, the dashboard is open (suitable for local network use).

### Auto-Restart

When you save notification windows or secrets through the dashboard, the scheduler automatically restarts to apply changes.

## Usage

### Docker Commands

```bash
# Run a specific slot
docker compose run --rm notify --slot 1

# Test mode (uses any available date with memories)
docker compose run --rm notify --slot 1 --test

# Preview without sending (dry run)
docker compose run --rm notify --slot 1 --dry-run

# Skip random delay, send immediately
docker compose run --rm notify --slot 1 --no-delay

# Force send even if already sent today
docker compose run --rm notify --slot 1 --force

# Check specific date
docker compose run --rm notify --slot 1 --date 2024-12-25

# Start scheduler (runs all slots daily)
docker compose up -d scheduler

# Start dashboard
docker compose up -d dashboard

# View logs
docker compose logs -f scheduler
docker compose logs -f dashboard

# Stop services
docker compose down

# Rebuild after updates (must recreate container for volume mounts)
docker compose down dashboard && docker compose up -d --build dashboard
```

### Without Docker

```bash
# Install dependencies
pip install requests pyyaml

# Run
python notify.py --slot 1 --test --no-delay
```

## Configuration

### File Structure

| File | Purpose |
|------|---------|
| `.env` | **Secrets only** - API keys, passwords, server URLs |
| `config.yaml` | **All configuration** - users, schedules, settings, messages |
| `state.json` | Tracks sent notifications (auto-generated) |
| `dashboard/` | Web dashboard (FastAPI + HTML) |

### Notification Windows

Each slot triggers at the window start time, then sends at a random time within that window:

| Slot | Window | Purpose |
|------|--------|---------|
| 1 | 08:00-10:00 | Memory or person photo |
| 2 | 12:00-14:00 | Memory or person photo |
| 3 | 16:00-18:00 | Memory or person photo |
| 4 | 19:00-20:00 | Person photo (when memories exist) |

Configure windows in `config.yaml`:
```yaml
notification_windows:
  - start: "08:00"
    end: "10:00"
  # Add more as needed...
```

### Settings Reference

```yaml
settings:
  # Notification counts
  memory_notifications: 3       # Max memory notifications per day
  person_notifications: 1       # Person photo notifications (when memories exist)
  fallback_notifications: 3     # Person photos when no memories today

  # Person photo settings
  top_persons_limit: 5          # Consider top N named people
  exclude_recent_days: 30       # Skip photos from last N days

  # Enhanced features
  include_location: true        # Add city/country (33% random chance)
  include_album: true           # Show album name when in album
  video_emoji: true             # Add 🎬 emoji for video notifications
  prefer_group_photos: true     # Prioritize photos with multiple people
  min_group_size: 2             # Minimum faces for "group photo"

  # Retry settings
  retry:
    max_attempts: 3
    delay_seconds: 5

  # Other
  state_file: "state.json"
  log_level: "INFO"             # DEBUG, INFO, WARNING, ERROR
```

### Message Templates

Messages are randomly selected from customizable templates:

```yaml
# For "On This Day" memories
messages:
  - "A little trip back to {year}..."
  - "Remember this day {years_ago} years ago?"
  - "Throwback to {year}! Take a moment to smile"

# For random person photos
person_messages:
  - "A lovely moment with {person_name}..."
  - "Remember this time with {person_name}?"
  - "Here's a favorite moment with {person_name}"

# For video memories
video_messages:
  - "Watch this moment from {year}..."
  - "A video memory from {years_ago} years ago"

# For videos with people
video_person_messages:
  - "Watch this moment with {person_name}..."
  - "A video featuring {person_name} from {year}"
```

**Placeholders:**
- `{year}` - The year (e.g., 2020)
- `{years_ago}` - Years since (e.g., 4)
- `{person_name}` - Person's name from Immich

**Auto-appended context (when available):**
- Location: `📍 Cairo, Egypt` (33% chance)
- Album: `📁 Summer Vacation 2023`

## Multi-User Setup

Each user gets personalized notifications based on their own Immich library.

**Via Dashboard (recommended):**
1. Go to **Settings tab** → Click **Add User**
2. Go to **Secrets tab** → Add the user's API key and ntfy password
3. Scheduler auto-restarts with new user

**Manually:** Edit `config.yaml` and `.env` files, then restart scheduler.

Each user subscribes to their own ntfy topic in the app.

## Self-Hosting ntfy

If you don't have ntfy yet, here's a quick setup:

```yaml
# docker-compose.yml for ntfy
version: "3"
services:
  ntfy:
    image: binwiederhier/ntfy
    container_name: ntfy
    command: serve
    ports:
      - "8090:80"
    volumes:
      - ./ntfy-cache:/var/cache/ntfy
    restart: unless-stopped
```

```bash
docker compose up -d
```

Then install the ntfy app and add your server.

## Troubleshooting

### No notifications received

1. Check if you have memories for today: `docker compose run --rm notify --slot 1 --dry-run --no-delay`
2. Verify ntfy subscription in the app
3. Check logs: `docker compose logs scheduler`

### No person photos

1. Make sure you have **named people** in Immich (People → click face → add name)
2. Check you have photos older than 30 days for those people
3. Verify with: `docker compose run --rm notify --slot 4 --dry-run --no-delay`

### API key errors

1. Verify your API key in Immich web UI
2. Make sure the key has "Read" permissions
3. Check environment variable is set correctly in `.env`

### Already sent today

The script tracks sent notifications per slot to avoid duplicates. To resend:
```bash
docker compose run --rm notify --slot 1 --force --no-delay
```

Or delete `state.json` to reset all slots.

### Dashboard not loading

1. Check if container is running: `docker compose ps`
2. View logs: `docker compose logs dashboard`
3. Verify port 5000 is accessible

## Development

Source files are mounted as volumes, so you can edit them without rebuilding:

```
.
├── notify.py              # Main notification script
├── config.yaml            # Configuration (users, schedules, settings)
├── .env                   # Secrets only (API keys, passwords, URLs)
├── state.json             # Tracks sent notifications (auto-generated)
├── Dockerfile             # Main container definition
├── Dockerfile.dashboard   # Dashboard container
├── docker-compose.yml     # Service definitions
└── dashboard/             # Web dashboard
    ├── main.py            # FastAPI app
    ├── models.py          # Pydantic models
    ├── routers/           # API endpoints
    └── templates/         # HTML UI
```

After editing, changes take effect immediately on next run. For dashboard changes, rebuild with:
```bash
docker compose up -d --build dashboard
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Immich](https://immich.app/) - The amazing self-hosted photo solution
- [ntfy](https://ntfy.sh/) - Simple push notification service
- Inspired by Google Photos' "Memories" feature

---

**Made with love for the Immich community**
