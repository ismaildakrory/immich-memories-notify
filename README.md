# Immich Memories Notify

Get daily push notifications when you have photo memories in [Immich](https://immich.app/) - just like Google Photos!

![Notification Example](https://via.placeholder.com/400x200?text=Memory+Notification+Preview)

## Features

- **Daily Memory Notifications** - Get notified when you have photos from this day in previous years
- **Face Preference** - Prefers photos with recognized faces (your top 5 named people)
- **Person Photos** - Random photos of your favorite people when no memories exist
- **Smart Scheduling** - 4 notification slots with random timing within configurable windows
- **Cozy Messages** - Randomized warm message templates (customizable)
- **Multi-User Support** - Each user gets their own top people and personalized notifications
- **Rich Notifications** - Includes thumbnail preview with person names
- **Click to Open** - Tap notification to open Immich app directly
- **Self-Hosted** - Works with your self-hosted Immich and ntfy instances
- **Docker Ready** - Easy deployment with Docker Compose
- **Privacy First** - Your photos never leave your network

## How It Works

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   Immich    │ ───> │   Script    │ ───> │    ntfy     │
│   Server    │      │  (Python)   │      │   Server    │
└─────────────┘      └─────────────┘      └─────────────┘
                                                │
                                                ▼
                                          ┌─────────────┐
                                          │  Mobile App │
                                          │ Notification│
                                          └─────────────┘
```

### Notification Logic

| Scenario | Slots 1-3 | Slot 4 |
|----------|-----------|--------|
| Has memories today | Memory photo (prefers faces) | Random person photo |
| No memories today | Random person photo | Random person photo |

**Key features:**
- Photos with recognized faces from your top 5 named people are prioritized
- Person photos exclude the last 30 days (configurable)
- Each slot sends at a random time within its window (e.g., 8-10 AM)
- Per-user top people based on their own photo library

## Requirements

- [Immich](https://immich.app/) server (self-hosted)
- [ntfy](https://ntfy.sh/) server (self-hosted or use ntfy.sh)
- Docker & Docker Compose (recommended) OR Python 3.8+
- ntfy mobile app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/app/ntfy/id1625396347))
- **Named people in Immich** - For face preference and person photos, name your frequently appearing people in Immich

## Disclaimer

Built this mostly vibe coding! Been running smoothly on my setup. PRs and feedback welcome!

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/ismaildakrory/immich-memories-notify.git
cd immich-memories-notify
```

### 2. Configure

**Step A: Create `.env` for secrets only:**

```bash
cp .env.example .env
```

```bash
# Server URLs
IMMICH_URL=http://192.168.1.100:2283
NTFY_URL=http://192.168.1.100:8090

# API Keys (get from Immich: Account Settings → API Keys)
IMMICH_API_KEY_USER1=your-api-key-here
IMMICH_API_KEY_USER2=another-api-key

# ntfy Passwords
NTFY_PASSWORD_USER1=your-ntfy-password
NTFY_PASSWORD_USER2=another-password
```

**Step B: Edit `config.yaml` for everything else:**

```yaml
users:
  - name: "User1"
    immich_api_key: "${IMMICH_API_KEY_USER1}"
    ntfy_topic: "immich-memories-user1"
    ntfy_username: "user1"
    ntfy_password: "${NTFY_PASSWORD_USER1}"
    enabled: true

settings:

  # Notification slot settings
  memory_notifications: 3       # Number of memory notifications when memories exist
  person_notifications: 1       # Number of person photo notifications (added after memories)
  fallback_notifications: 3     # Number of person photos when no memories for today

  # Person photo settings
  top_persons_limit: 5          # Number of top named persons to consider
  exclude_recent_days: 30       # Exclude photos from last N days for person photos


  # Time windows - script triggers at start, sends randomly within window
  notification_windows:
    - start: "08:00"
      end: "10:00"
    - start: "12:00"
      end: "14:00"
    - start: "16:00"
      end: "18:00"
    - start: "19:00"
      end: "20:00"
```

### 3. Subscribe to ntfy Topic

Open the ntfy app on your phone and subscribe to your topic (e.g., `immich-memories-user1`) on your ntfy server.

### 4. Run with Docker

```bash
# Test it first
docker compose run --rm notify --slot 1 --test --no-delay

# Start the daily scheduler
docker compose up -d scheduler
```

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

# Start scheduler (runs all 4 slots daily)
docker compose up -d scheduler

# View scheduler logs
docker compose logs -f scheduler

# Stop scheduler
docker compose down
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
```

**Placeholders:**
- `{year}` - The year (e.g., 2020)
- `{years_ago}` - Years since (e.g., 4)
- `{person_name}` - Person's name from Immich

## Multi-User Setup

Each user gets personalized notifications based on their own Immich library:

**Step 1:** Get API key from Immich (Account Settings → API Keys)

**Step 2:** Add to `.env`:
```bash
IMMICH_API_KEY_USER2=their-api-key-here
NTFY_PASSWORD_USER2=their-ntfy-password
```

**Step 3:** Add to `config.yaml`:
```yaml
users:
  - name: "Mom"
    immich_api_key: "${IMMICH_API_KEY_USER2}"
    ntfy_topic: "immich-memories-mom"
    ntfy_username: "mom"
    ntfy_password: "${NTFY_PASSWORD_USER2}"
    enabled: true
```

**Step 4:** Restart scheduler:
```bash
docker compose restart scheduler
```

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

## Development

Source files are mounted as volumes, so you can edit them without rebuilding:

```
.
├── notify.py          # Main script
├── config.yaml        # Configuration (users, schedules, settings)
├── .env               # Secrets only (API keys, passwords, URLs)
├── state.json         # Tracks sent notifications (auto-generated)
├── Dockerfile         # Container definition
└── docker-compose.yml # Service definitions
```

After editing, changes take effect immediately on next run.

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
