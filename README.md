# Immich Memories Notify

Daily "On This Day" push notifications from your [Immich](https://immich.app/) server — like Google Photos memories, but self-hosted.

## Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Docker Image](#docker-image)
- [Screenshots](#screenshots)
- [Common Commands](#common-commands)
- [Configuration](#configuration)
- [Self-Hosting ntfy](#self-hosting-ntfy)
- [Dashboard](#dashboard)
- [Immich API Key Permissions](#immich-api-key-permissions)
- [Troubleshooting](#troubleshooting)
- [Requirements](#requirements)
- [Contributing](#contributing)

## Features

- **Daily Memories** — Photos from this day in previous years, with face preference and location context
- **Then & Now** — Side-by-side comparison of the same person across years
- **Trip Highlights** — Collage from a past trip (same city, same month), with smart date clustering
- **Weekly Collages** — 12 template combinations (Grid, Mosaic, Polaroid, Strip) with face-based smart cropping
- **Birthdays & Albums** — Birthday greetings for people with a birth date in Immich, plus surprise photos from albums you pick
- **Web Dashboard** — Manage settings, users, messages, and trigger tests from a browser
- **Multi-User** — Each user gets personalized notifications from their own library
- **Guided Setup** — `setup.sh` + first-run wizard, with an optional bundled ntfy server
- **Privacy First** — Everything runs on your network

## Quick Start

```bash
git clone https://github.com/ismaildakrory/immich-memories-notify.git
cd immich-memories-notify
bash setup.sh
```

The setup script generates your config, optionally starts a bundled ntfy server, and launches the dashboard. A wizard walks you through connecting Immich, ntfy, and adding your first user. The scheduler runs automatically inside the dashboard container.

## Docker Image

Pre-built images are available on GHCR for `linux/amd64` and `linux/arm64`:

```bash
docker pull ghcr.io/ismaildakrory/immich-memories-notify:latest
```

During [Quick Start](#quick-start) setup, choose option 2 (pre-built image) to pull from GHCR instead of building locally.

<details>
<summary><strong>Standalone setup (Unraid, Portainer, etc.)</strong></summary>

```bash
mkdir -p immich-memories-notify && cd immich-memories-notify
mkdir -p state
touch .env config.yaml

docker run -d \
  --name immich-memories-dashboard \
  --network host \
  --restart unless-stopped \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -v $(pwd)/state:/app/state \
  -v $(pwd)/.env:/app/.env \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /etc/localtime:/etc/localtime:ro \
  -e TZ=$(cat /etc/timezone 2>/dev/null || echo UTC) \
  -e CONFIG_PATH=/app/config.yaml \
  -e STATE_PATH=/app/state/state.json \
  -e ENV_PATH=/app/.env \
  ghcr.io/ismaildakrory/immich-memories-notify:latest
```

Then open `http://your-server-ip:5000` — the setup wizard will guide you through the rest.

</details>

<details>
<summary><strong>Compose stack managers (Dockge, Portainer stacks, etc.)</strong></summary>

Paste [`docker-compose.ghcr.yml`](docker-compose.ghcr.yml) as your stack, then create the mounted files inside the stack folder (for Dockge: `/opt/stacks/<stack-name>/`) **before first start** — otherwise Docker auto-creates `config.yaml` as a *directory* and the container fails with `"Are you trying to mount a directory onto a file?"`:

```bash
cd /opt/stacks/<stack-name>
touch config.yaml .env && mkdir -p state
```

An empty `config.yaml` is fine — defaults are filled in on first start and the wizard guides you through the rest. Already hit the error? `rm -rf config.yaml && touch config.yaml`, then start again.

</details>

## Screenshots

![ntfy](https://github.com/user-attachments/assets/b685ebab-2256-4da4-8b80-e00d4d110cd0)
![expand](https://github.com/user-attachments/assets/f039766a-5b87-4bbd-8965-3e1cad0da19f)
<img width="1256" height="590" alt="Status" src="https://github.com/user-attachments/assets/9d00c677-5124-4617-b89f-9468b279e818" />
<img width="1031" height="1201" alt="Settings" src="https://github.com/user-attachments/assets/829b0fc4-4af3-45e7-a4e0-0e8cfe9221d4" />
<img width="1257" height="1115" alt="Messages" src="https://github.com/user-attachments/assets/94df34a8-17d9-47c3-a865-ea3286fd5516" />
<img width="1242" height="1196" alt="Secrets" src="https://github.com/user-attachments/assets/732ace52-0ea0-4ab7-bb42-82c543beaae2" />
<img width="1250" height="1115" alt="Test" src="https://github.com/user-attachments/assets/2ea0e52e-4854-4268-8b79-a14905428e71" />
<img width="1148" height="285" alt="Then & Now and Trip Highlights" src="https://github.com/user-attachments/assets/10127da5-35ee-4057-b2c0-230e5fc53dc4" />
<img width="1148" height="292" alt="City picker" src="https://github.com/user-attachments/assets/9d625ed5-7962-44c5-8e22-00cf88bc8f87" />

<img width="1716" height="927" alt="Collage templates" src="https://github.com/user-attachments/assets/33e533c7-f397-444c-b795-6fc6f0979175" />

## Common Commands

```bash
# Test a specific slot
docker compose run --rm notify --slot 1 --test --no-delay
# (pre-built GHCR image — no notify service, run inside the dashboard container)
docker compose exec dashboard python -m notify --slot 1 --test --no-delay

# Dry run (preview without sending)
docker compose run --rm notify --slot 1 --dry-run --no-delay

# Force resend
docker compose run --rm notify --slot 1 --force --no-delay

# Logs
docker compose logs -f dashboard

# Rebuild after code changes
docker compose down dashboard && docker compose up -d --build dashboard
```

## Configuration

All settings are manageable from the **web dashboard**. For manual editing:

| File | Purpose |
|------|---------|
| `.env` | Secrets — API keys, passwords, server URLs, dashboard port |
| `config.yaml` | Everything else — users, settings, messages |
| `state/state.json` | Notification tracking (auto-generated) |

<details>
<summary><strong>Settings reference (config.yaml)</strong></summary>

```yaml
settings:
  memory_notifications: 3       # Memory slots per day
  person_notifications: 2       # Person/album photo slots (when memories exist)
  fallback_notifications: 4     # Person photos when no memories today
  top_persons_limit: 5          # Top N named people to feature
  exclude_recent_days: 30       # Skip recent photos for person notifications
  year_range: 20                # How far back to look (collage, trip, TaN)
  include_location: true        # Add city/country context
  include_album: true           # Show album name
  video_emoji: true             # Add film emoji for videos
  prefer_group_photos: true     # Prioritize multi-person photos
  min_group_size: 2             # Min faces for "group photo"
  birthday_enabled: true        # Birthday greetings (takes slot 1 priority)

  # Then & Now
  then_and_now_enabled: true
  then_and_now_cooldown_days: 7
  then_and_now_min_gap: 3       # Min years between "then" and "now"

  # Trip Highlights
  trip_highlights_enabled: true
  trip_highlights_cooldown_days: 7
  trip_highlights_min_photos: 5
  trip_highlights_repeat_days: 90  # Don't show the same trip again for N days

  # Weekly Collage
  weekly_collage_enabled: true
  weekly_collage_day: 6         # 0=Sun, 6=Sat
  weekly_collage_slots: 2       # How many person slots become collages
  collage_person_limit: 5       # Max people per collage
  collage_template: random      # or: grid_custom, mosaic_custom, polaroid_custom, strip_custom
  collage_album_name: Weekly Highlights

  # Notification windows — one per slot: you need
  # memory_notifications + person_notifications windows in total
  notification_windows:
    - start: "08:00"
      end: "10:00"
    - start: "12:00"
      end: "14:00"
```

</details>

<details>
<summary><strong>Message templates</strong></summary>

```yaml
messages:                    # {year} {years_ago} {location} {album_name}
  - "Remember this day {years_ago} years ago?"
person_messages:             # {person_name} {location} {album_name}
  - "A lovely moment with {person_name}..."
album_messages:              # {album_name} {location}
  - "A surprise from {album_name}!"
birthday_messages:           # {person_name}
  - "Happy Birthday, {person_name}! 🎂"
then_and_now_messages:       # {person_name} {then_year} {now_year} {gap}
  - "Then and now — {person_name}, {gap} years apart"
trip_highlights_messages:    # {city} {country} {year} {gap}
  - "Remember this trip to {city}? Back in {year}!"
```

Memory, person, and album messages also have `video_*` variants (used when a video is picked), and every type has a `*_titles` list for notification titles (e.g. `memory_titles`, `person_titles`, `album_titles`) with the same core placeholders.

</details>

## Self-Hosting ntfy

**Bundled (easiest):** Say yes when `setup.sh` asks. Everything is configured automatically.

**Bring your own:** Your ntfy `server.yaml` needs attachment support for thumbnail previews:
```yaml
base-url: "https://notify.yourdomain.com"
auth-file: /var/lib/ntfy/user.db
auth-default-access: deny-all
attachment-cache-dir: /var/lib/ntfy/attachments
attachment-total-size: 5G
attachment-file-size: 15M
attachment-expiry-duration: 3h
```

## Dashboard

Set in `.env` to customize the dashboard:
```
DASHBOARD_TOKEN=your-secret-token   # Dashboard password — strongly recommended,
                                    # the container has Docker access
DASHBOARD_PORT=8080                 # Change port (default: 5000)
```

## Immich API Key Permissions

When creating an API key in Immich, grant these permissions:

| Permission | Used for |
|---|---|
| `memory.read` | On-this-day notifications |
| `person.read` | Face recognition features |
| `asset.read` | Asset details and metadata search |
| `asset.view` | Thumbnail previews in notifications |
| `asset.upload` | Weekly collage upload |
| `album.read` | Album notifications |
| `album.create` | Creating the collage album |
| `albumAsset.create` | Adding collages to the album |

If you don't use the Weekly Collage, Trip Highlights, or Then & Now features, you can skip `asset.upload`, `album.create`, and `albumAsset.create` (all three features upload their composites to albums).

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Clicking notification doesn't open Immich app | Set `IMMICH_EXTERNAL_URL=https://my.immich.app` in `.env` — the Immich mobile app only handles links from this domain |
| No notifications | `docker compose run --rm notify --slot 1 --dry-run --no-delay` to check for memories |
| No thumbnails | Run with `--test --force`, look for upload warnings in output |
| No person photos | Name your people in Immich, ensure photos older than 30 days exist |
| Already sent today | Use `--force` flag, or delete `state/state.json` |
| Dashboard not loading | `docker compose logs dashboard` to check errors |
| `mount ... Are you trying to mount a directory onto a file?` | Host `config.yaml` or `.env` was missing at first start, so Docker created a directory. Stop, `rm -rf config.yaml && touch config.yaml` (same for `.env`), start again |
| `git pull` fails with local changes | `git stash && git pull && git stash pop` — your `.env` and `config.yaml` are preserved |

## Requirements

- [Immich](https://immich.app/) (self-hosted)
- [ntfy](https://ntfy.sh/) (self-hosted or bundled)
- Docker & Docker Compose
- ntfy mobile app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/app/ntfy/id1625396347))
- Named people in Immich for face features

## Contributing

Built with AI assistance, manually reviewed and tested. PRs, issues, and feedback welcome!

See [CONTRIBUTORS.md](CONTRIBUTORS.md) for a list of contributors.

## License

MIT — see [LICENSE](LICENSE).

---

**Made with love for the Immich community**
