# Immich Memories Notify

Daily "On This Day" push notifications from your [Immich](https://immich.app/) server — like Google Photos memories, but self-hosted.

## Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Screenshots](#screenshots)
- [Common Commands](#common-commands)
- [Configuration](#configuration)
- [Self-Hosting ntfy](#self-hosting-ntfy)
- [Dashboard Authentication](#dashboard-authentication)
- [Troubleshooting](#troubleshooting)
- [Requirements](#requirements)
- [Contributing](#contributing)

## Features

- **Daily Memories** — Photos from this day in previous years, with face preference and location context
- **Then & Now** — Side-by-side comparison of the same person across years
- **Trip Highlights** — Collage from a past trip (same city, same month), with smart date clustering
- **Weekly Collages** — 12 template combinations (Grid, Mosaic, Polaroid, Strip) with face-based smart cropping
- **Web Dashboard** — Manage settings, users, messages, and trigger tests from a browser
- **Multi-User** — Each user gets personalized notifications from their own library
- **Guided Setup** — `setup.sh` + first-run dashboard wizard
- **Bundled ntfy** — Optionally spin up a pre-configured ntfy server
- **Privacy First** — Everything runs on your network

## Quick Start

```bash
git clone https://github.com/ismaildakrory/immich-memories-notify.git
cd immich-memories-notify
bash setup.sh
```

The setup script generates your config, optionally starts a bundled ntfy server, and launches the dashboard. A wizard walks you through connecting Immich, ntfy, and adding your first user.

Then start the scheduler:
```bash
docker compose up -d scheduler
```

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

# Dry run (preview without sending)
docker compose run --rm notify --slot 1 --dry-run --no-delay

# Force resend
docker compose run --rm notify --slot 1 --force --no-delay

# Logs
docker compose logs -f scheduler

# Rebuild dashboard after code changes
docker compose down dashboard && docker compose up -d --build dashboard
```

## Configuration

All settings are manageable from the **web dashboard**. For manual editing:

| File | Purpose |
|------|---------|
| `.env` | Secrets — API keys, passwords, server URLs |
| `config.yaml` | Everything else — users, settings, messages |
| `state/state.json` | Notification tracking (auto-generated) |

<details>
<summary><strong>Settings reference (config.yaml)</strong></summary>

```yaml
settings:
  memory_notifications: 3       # Memory slots per day
  person_notifications: 1       # Person photo slots (when memories exist)
  fallback_notifications: 3     # Person photos when no memories today
  top_persons_limit: 5          # Top N named people to feature
  exclude_recent_days: 30       # Skip recent photos for person notifications
  year_range: 20                # How far back to look (collage, trip, TaN)
  include_location: true        # Add city/country context
  include_album: true           # Show album name
  video_emoji: true             # Add film emoji for videos
  prefer_group_photos: true     # Prioritize multi-person photos
  min_group_size: 2             # Min faces for "group photo"

  # Then & Now
  then_and_now_enabled: true
  then_and_now_cooldown_days: 7
  then_and_now_min_gap: 3       # Min years between "then" and "now"

  # Trip Highlights
  trip_highlights_enabled: true
  trip_highlights_cooldown_days: 7
  trip_highlights_min_photos: 5

  # Weekly Collage
  weekly_collage_enabled: true
  weekly_collage_day: 6         # 0=Sun, 6=Sat
  weekly_collage_slots: 1
  collage_template: random      # or: grid_custom, mosaic_custom, polaroid_custom, strip_custom
  collage_album_name: Weekly Highlights

  # Notification windows (one per slot)
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
messages:
  - "A little trip back to {year}..."
  - "Remember this day {years_ago} years ago?"

person_messages:
  - "A lovely moment with {person_name}..."

video_messages:
  - "Watch this moment from {year}..."

then_and_now_messages:
  - "Look how much {person_name} has changed! {then_year} vs {now_year}"

trip_highlights_messages:
  - "Remember this trip to {city}? Back in {year}!"
```

Placeholders: `{year}`, `{years_ago}`, `{person_name}`, `{city}`, `{country}`, `{gap}`, `{then_year}`, `{now_year}`

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

## Dashboard Authentication

Set in `.env` to password-protect the dashboard:
```
DASHBOARD_TOKEN=your-secret-token
```
If not set, the dashboard is open (fine for local network).

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No notifications | `docker compose run --rm notify --slot 1 --dry-run --no-delay` to check for memories |
| No thumbnails | Run with `--test --force`, look for upload warnings in output |
| No person photos | Name your people in Immich, ensure photos older than 30 days exist |
| Already sent today | Use `--force` flag, or delete `state/state.json` |
| Dashboard not loading | `docker compose logs dashboard` to check errors |
| `git pull` fails with local changes | `git stash && git pull && git stash pop` — your `.env` and `config.yaml` are preserved |

## Requirements

- [Immich](https://immich.app/) (self-hosted)
- [ntfy](https://ntfy.sh/) (self-hosted or bundled)
- Docker & Docker Compose
- ntfy mobile app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/app/ntfy/id1625396347))
- Named people in Immich for face features

## Contributing

Built this mostly vibe coding! Been running smoothly on my setup. PRs and feedback welcome!

## License

MIT — see [LICENSE](LICENSE).

---

**Made with love for the Immich community**
