# Immich Memories Notify

Get daily push notifications when you have photo memories in [Immich](https://immich.app/) - just like Google Photos!

![Notification Example](https://via.placeholder.com/400x200?text=Memory+Notification+Preview)

## Features

- **Daily Memory Notifications** - Get notified when you have photos from this day in previous years
- **One Per Year** - Separate notification for each year, spaced throughout the day
- **Cozy Messages** - 10 randomized warm message templates (customizable)
- **Smart Limits** - Max 3 notifications per day (randomly selects years if you have more)
- **Multi-User Support** - Send personalized notifications to each family member
- **Rich Notifications** - Includes thumbnail preview from each year
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

1. Script fetches memories from Immich API
2. Filters for today's "On This Day" memories
3. Groups by year and selects up to 3 years (random if more)
4. Sends first notification immediately, then spaces the rest throughout the day
5. You receive cozy notifications with thumbnails from each year!

## Requirements

- [Immich](https://immich.app/) server (self-hosted)
- [ntfy](https://ntfy.sh/) server (self-hosted or use ntfy.sh)
- Docker & Docker Compose (recommended) OR Python 3.8+
- ntfy mobile app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/app/ntfy/id1625396347))

## Disclaimer

Built this mostly vibe coding! Been running smoothly on my setup. PRs and feedback welcome!

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/ismaildakrory/immich-memories-notify.git
cd immich-memories-notify
```

### 2. Configure

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

```bash
# Get your API key from Immich: Account Settings → API Keys
IMMICH_API_KEY_ISMAIL=your-api-key-here
```

Edit `config.yaml` with your server URLs:

```yaml
immich:
  url: "http://192.168.1.100:2283"        # Your Immich internal URL
  external_url: "https://photos.example.com"  # Your Immich external URL

ntfy:
  url: "http://192.168.1.100:8090"        # Your ntfy internal URL
  external_url: "https://ntfy.example.com"    # Your ntfy external URL

users:
  - name: "YourName"
    immich_api_key: "${IMMICH_API_KEY_ISMAIL}"
    ntfy_topic: "immich-memories-yourname"  # Unique topic for your notifications
    enabled: true
```

### 3. Subscribe to ntfy Topic

Open the ntfy app on your phone and subscribe to your topic (e.g., `immich-memories-yourname`) on your ntfy server.

### 4. Run with Docker

```bash
# Test it first
docker compose run --rm notify --test

# Start the daily scheduler (runs at 9:00 AM)
docker compose up -d scheduler
```

## Usage

### Docker Commands

```bash
# Run once (check for today's memories)
docker compose run --rm notify

# Test mode (uses any available date with memories)
docker compose run --rm notify --test

# Preview without sending (dry run)
docker compose run --rm notify --dry-run

# Force send even if already sent today
docker compose run --rm notify --force

# Check specific date
docker compose run --rm notify --date 2024-12-25

# Start scheduler (daily at 9 AM)
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

# Set environment variable
export IMMICH_API_KEY_ISMAIL="your-api-key"

# Run
python notify.py --test
```

### Cron Job (Alternative to Scheduler)

If you prefer using system cron instead of the Docker scheduler:

```bash
# Edit crontab
crontab -e

# Add this line (runs daily at 9:00 AM)
0 9 * * * cd /path/to/immich-memories-notify && docker compose run --rm notify
```

## Configuration

### config.yaml

```yaml
# Server settings
immich:
  url: "${IMMICH_URL:-http://localhost:2283}"
  external_url: "${IMMICH_EXTERNAL_URL:-https://photos.example.com}"

ntfy:
  url: "${NTFY_URL:-http://localhost:8090}"
  external_url: "${NTFY_EXTERNAL_URL:-https://ntfy.example.com}"

# Optional settings
settings:
  retry:
    max_attempts: 3      # Retry failed requests
    delay_seconds: 5     # Delay between retries
  state_file: "state.json"  # Tracks sent notifications
  log_level: "INFO"      # DEBUG, INFO, WARNING, ERROR
  max_notifications_per_day: 3  # Limit notifications (random selection if more years)
  interval_minutes: 60   # Time between notifications

# Users
users:
  - name: "User1"
    immich_api_key: "${IMMICH_API_KEY_USER1}"
    ntfy_topic: "immich-memories-user1"
    enabled: true
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `IMMICH_API_KEY_*` | Immich API keys for each user |
| `IMMICH_URL` | Override Immich internal URL |
| `NTFY_URL` | Override ntfy internal URL |
| `NOTIFY_SCHEDULE` | Cron schedule (default: `0 9 * * *`) |

## Multi-User Setup

Adding family members is simple - just 2 files to edit:

**Step 1:** Get API key from Immich (Account Settings → API Keys)

**Step 2:** Add to `.env`:
```bash
IMMICH_API_KEY_USER2=their-api-key-here
```

**Step 3:** Add to `config.yaml`:
```yaml
users:
  - name: "Mom"
    immich_api_key: "${IMMICH_API_KEY_USER2}"
    ntfy_topic: "immich-memories-mom"
    enabled: true
```

**Step 4:** Restart and subscribe:
```bash
docker compose restart scheduler
```
Each user subscribes to their own ntfy topic in the app

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

## Notification Features

| Feature | Description |
|---------|-------------|
| **Title** | "Memories from 2020" (one per year) |
| **Message** | Randomized cozy messages like "A little trip back to 2020..." |
| **Thumbnail** | Preview photo from that specific year |
| **Spacing** | Notifications spread throughout the day (default: 1 hour apart) |
| **Click Action** | Opens Immich app via my.immich.app |
| **Tags** | Camera and calendar emoji icons |

### Message Templates

Messages are randomly selected from customizable templates in `config.yaml`:

```yaml
messages:
  - "A little trip back to {year}..."
  - "Remember this day {years_ago} years ago?"
  - "Some memories from {year} want to say hello"
  - "Throwback to {year}! Take a moment to smile"
  - "Once upon a time in {year}..."
  # ... and more!
```

Placeholders: `{year}` (e.g., 2020) and `{years_ago}` (e.g., 4)

## Troubleshooting

### No notifications received

1. Check if you have memories for today: `docker compose run --rm notify --dry-run`
2. Verify ntfy subscription in the app
3. Check logs: `docker compose logs scheduler`

### API key errors

1. Verify your API key in Immich web UI
2. Make sure the key has "Read" permissions
3. Check environment variable is set: `echo $IMMICH_API_KEY_*`

### Network errors

1. Verify Immich URL is accessible from Docker
2. Check ntfy server is running
3. Try using internal IPs instead of hostnames

### Already sent today

The script tracks sent notifications to avoid duplicates. To resend:
```bash
docker compose run --rm notify --force
```

Or delete `state.json` to reset.

## Development

Source files are mounted as volumes, so you can edit them without rebuilding:

```
.
├── notify.py          # Main script (edit freely)
├── config.yaml        # Configuration (edit freely)
├── state.json         # Sent notification tracking
├── Dockerfile         # Container definition
├── docker-compose.yml # Service definitions
├── .env               # Your secrets (not in git)
└── .env.example       # Template for others
```

After editing `notify.py`, changes take effect immediately on next run.

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
