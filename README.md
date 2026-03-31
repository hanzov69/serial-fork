# Serial Fork

A Discord bot + web registry for issuing serial numbers to makers who complete a 3D printer build. Inspired by the Voron community serial system, Serial Fork provides native Discord integration — moderators approve requests directly in Discord with one-click buttons — paired with a public web registry anyone can browse.

**Links:** [forkweld.com](https://forkweld.com) &nbsp;|&nbsp; [Baby Belt Pro on GitHub](https://github.com/RobMink/BabyBeltPro) &nbsp;|&nbsp; [Discord](https://discord.gg/NTDZMsCwXh)

---

## Features

- **Forum-native requests** — users run `/request` inside their forum post thread; the bot auto-detects the printer type from the thread's tag
- **One-click moderation** — approval embeds appear in a mod channel with Approve / Reject buttons; mods can also act from the web queue
- **Thread announcements** — approval congratulations are posted directly in the builder's forum thread so everyone can see
- **Multi-type serial sequences** — each printer model (BBP, CC, …) has its own independent serial sequence; `BBP-001` and `CC-001` are unrelated
- **Public registry** — searchable, filterable table of all issued serials with per-serial detail pages
- **Discord OAuth2 login** — web accounts are your Discord identity, no separate sign-up
- **Role assignment** — bot automatically grants the configured Discord role when a serial is approved
- **Serial reservations** — block specific numbers from auto-assignment; bulk import via CSV
- **Audit log** — every approval, rejection, rescission, and role change is recorded
- **Theme system** — site owners can switch between built-in themes or drop in a custom CSS theme file
- **Kubernetes-ready** — Helm chart included for production deployments

---

## Quick Start

### Docker Compose

**1. Copy and edit the config files:**

```bash
cp config.toml.example config.toml   # fill in guild ID, channel IDs, etc.
cp .env.example .env                  # fill in bot token, OAuth2 secret, session key
```

**2. Start the stack:**

```bash
docker compose up -d
```

The web app will be available at `http://localhost:8000`.

> **First run:** Register Discord slash commands once after startup:
> ```bash
> docker compose run --rm bot python -m bot.main --sync-commands
> ```

---

### Helm (Kubernetes)

**1. Copy and edit the values file:**

```bash
cp helm/serial-fork/values.example.yaml my-values.yaml
# Fill in credentials, domain, and settings
```

**2. Install the chart:**

```bash
helm install serial-fork ./helm/serial-fork -f my-values.yaml -n serial-fork --create-namespace
```

**3. Register slash commands** (one-time):

```bash
helm upgrade serial-fork ./helm/serial-fork --set config.syncCommands=true --reuse-values
# Wait ~30 seconds, then flip it back:
helm upgrade serial-fork ./helm/serial-fork --set config.syncCommands=false --reuse-values
```

**4. Register the OAuth2 redirect URI** in the Discord Developer Portal → OAuth2 → Redirects:

```
https://your-domain.com/auth/callback
```

---

## Theme System

Serial Fork ships with three built-in themes selectable by the site owner via **Config → Site Theme**:

| Theme | Description |
|-------|-------------|
| **BabyBelt** | Default — deep navy and gold, inspired by the BabyBelt logo |
| **Printcepts** | Dark professional — emerald green accent |
| **Wave** | 80s vaporwave — neon pink and electric cyan with a grid background |

### Adding a custom theme

Drop a CSS file into `web/static/css/themes/` with a metadata comment block at the top:

```css
/*
 * theme-name: My Theme
 * theme-id: mytheme
 * theme-dot: #ff0000
 * theme-description: A red accent dark theme
 */

body.theme-mytheme {
  --bg:           #0d0d0d;
  --surface:      #1a1a1a;
  --surface2:     #242424;
  --border:       #333333;
  --text:         #f5f5f5;
  --text-muted:   #888888;
  --accent:       #ff0000;
  --accent-hover: #cc0000;
  --accent-dim:   rgba(255, 0, 0, 0.12);
  --success:      #22c55e;
  --danger:       #ef4444;
  --warning:      #f59e0b;
  --blue:         #3b82f6;
  --blue-dim:     rgba(59, 130, 246, 0.15);
}
```

The theme appears in the dropdown automatically on next restart — no code changes required.

---

## Architecture

Serial Fork runs as two services sharing a single SQLite database:

| Service | Description |
|---------|-------------|
| `serial-fork-bot` | discord.py bot — slash commands, mod interactions, role assignment |
| `serial-fork-web` | FastAPI web app — public registry, Discord OAuth2 login, admin UI |

Container images are published to GitHub Container Registry:
- `ghcr.io/hanzov69/serial-fork-bot`
- `ghcr.io/hanzov69/serial-fork-web`

The database uses WAL mode so both services can read and write concurrently without locking.

---

## Documentation

| Document | Description |
|----------|-------------|
| [USAGE.md](USAGE.md) | User and admin workflows — how to request serials, moderate, and manage the system |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Full deployment guide — Discord setup, configuration reference, Kubernetes, operations |
