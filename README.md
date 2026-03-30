# Serial Fork

A Discord bot + web registry for issuing serial numbers to makers who build a 3D printer. Inspired by the Voron community serial system, Serial Fork provides native Discord integration with a dedicated web registry for the [Baby Belt Pro](https://github.com/RobMink/BabyBeltPro) community.

- Moderators receive approval requests directly in Discord with one-click Approve/Reject buttons
- Users can track their request status via the web app
- All issued serials are publicly searchable

**Links:** [forkweld.com](https://forkweld.com) &nbsp;|&nbsp; [Baby Belt Pro on GitHub](https://github.com/RobMink/BabyBeltPro) &nbsp;|&nbsp; [Discord](https://discord.gg/NTDZMsCwXh)

---

## Quick Start

### Docker Compose

The fastest way to run Serial Fork locally or on a single server.

**1. Copy and edit the config:**

```bash
cp config.example.toml config.toml
# Edit config.toml with your Discord credentials and settings
```

**2. Start the stack:**

```bash
docker compose up -d
```

The web app will be available at `http://localhost:8000`.

> **First run:** After startup, run the following to register Discord slash commands:
> ```bash
> docker compose run --rm bot python -m bot.main --sync-commands
> ```
> This only needs to be done once (or after adding new commands).

---

### Helm (Kubernetes)

For production deployments on Kubernetes.

**1. Copy and edit the values file:**

```bash
cp helm/serial-fork/values.example.yaml my-values.yaml
# Fill in your Discord credentials, domain name, and other settings
```

**2. Install the chart:**

```bash
helm install serial-fork ./helm/serial-fork -f my-values.yaml -n serial-fork --create-namespace
```

**3. Register Discord slash commands** (one-time, after first deploy):

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

## Detailed Deployment Guide

See [DEPLOYMENT.md](DEPLOYMENT.md) for full instructions covering:

- Discord application setup (bot token, OAuth2, permissions)
- All configuration options
- Database and migration management
- Upgrading between versions

---

## Architecture

Serial Fork consists of two services that share a SQLite database:

| Service | Description |
|---------|-------------|
| `serial-fork-bot` | discord.py bot — handles slash commands and mod interactions |
| `serial-fork-web` | FastAPI web app — public registry, OAuth2 login, admin UI |

Container images are published to GitHub Container Registry:
- `ghcr.io/hanzov69/serial-fork-bot`
- `ghcr.io/hanzov69/serial-fork-web`
