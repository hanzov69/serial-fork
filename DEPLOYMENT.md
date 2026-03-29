# BB-Serial Deployment Guide

This guide covers everything needed to deploy BB-Serial in your environment. It is written for administrators who are setting up the system for the first time.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Discord Application Setup](#2-discord-application-setup)
3. [Getting the Code](#3-getting-the-code)
4. [Configuration](#4-configuration)
5. [First Deployment](#5-first-deployment)
6. [Bootstrapping Your First Admin](#6-bootstrapping-your-first-admin)
7. [Syncing Bot Commands](#7-syncing-bot-commands)
8. [Verifying the Installation](#8-verifying-the-installation)
9. [Ongoing Operations](#9-ongoing-operations)
10. [Production Hardening](#10-production-hardening)
11. [Updating the Application](#11-updating-the-application)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

You will need:

- **Docker** and **Docker Compose** (v2.x, i.e. `docker compose` not `docker-compose`)
- A **Discord account** with permission to create applications at [discord.com/developers](https://discord.com/developers/applications)
- A **Discord server** where you have Administrator permission
- A machine with internet access (the bot needs to reach Discord's API)

Verify your Docker installation:

```bash
docker --version          # Docker 24.x or newer recommended
docker compose version    # v2.x required
```

---

## 2. Discord Application Setup

You need to create two things in the Discord Developer Portal: a **bot** (for slash commands) and an **OAuth2 application** (for web login). Both live under the same Application.

### 2a. Create the Application

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application**, give it a name (e.g. `BB Serials`), and click Create
3. Under **General Information**, note down the **Application ID** — this is your `discord_client_id`

### 2b. Create the Bot

1. In the left sidebar, click **Bot**
2. Click **Add Bot** → **Yes, do it!**
3. Under **Token**, click **Reset Token** and copy the token — this is your `DISCORD_TOKEN`. **Store it securely; you cannot view it again.**
4. Under **Privileged Gateway Intents**, enable:
   - **Server Members Intent** (needed to look up member details)
   - **Message Content Intent** (needed if you use prefix commands)
5. Click **Save Changes**

### 2c. Configure OAuth2

1. In the left sidebar, click **OAuth2** → **General**
2. Copy the **Client Secret** — this is your `DISCORD_CLIENT_SECRET`
3. Under **Redirects**, click **Add Redirect** and add:
   ```
   http://localhost:8000/auth/callback
   ```
   In production, replace `http://localhost:8000` with your public URL (e.g. `https://serials.yoursite.com`)
4. Click **Save Changes**

### 2d. Invite the Bot to Your Server

1. In the left sidebar, click **OAuth2** → **URL Generator**
2. Under **Scopes**, check: `bot` and `applications.commands`
3. Under **Bot Permissions**, check:
   - Send Messages
   - Send Messages in Threads
   - Embed Links
   - Read Message History
   - Use Application Commands
4. Copy the generated URL, open it in your browser, and invite the bot to your server

### 2e. Find Your Discord IDs

You need three channel/server IDs. To get them:

1. In Discord, go to **Settings → Advanced** and enable **Developer Mode**
2. Right-click your server name → **Copy Server ID** — this is `discord_guild_id`
3. Right-click the channel where users will post requests → **Copy Channel ID** — this is `discord_request_channel_id`
4. Right-click the channel where moderators will receive notifications → **Copy Channel ID** — this is `discord_mod_notify_channel_id`

> **Tip:** You can use the same channel for both requests and mod notifications, or separate channels — whichever fits your server layout.

---

## 3. Getting the Code

```bash
git clone <your-repo-url> bb-serial
cd bb-serial
```

---

## 4. Configuration

The application reads configuration from two files: `config.toml` (non-secret settings) and `.env` (secrets). Environment variables always override `config.toml` values, which in turn override built-in defaults.

Load order (highest → lowest priority):
1. Environment variables
2. `.env` file
3. `config.toml`
4. Built-in defaults

### 4a. Create `config.toml`

```bash
cp config.toml.example config.toml
```

Edit `config.toml` and fill in your values. The table below documents every available setting.

### 4b. Create `.env`

```bash
cp .env.example .env
```

Edit `.env` and fill in your secrets:

```bash
# From Discord Developer Portal → Bot → Token
DISCORD_TOKEN=your-bot-token-here

# From Discord Developer Portal → OAuth2 → Client Secret
DISCORD_CLIENT_SECRET=your-oauth2-client-secret-here

# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
WEB_SECRET_KEY=a-long-random-string-here
```

Generate a secure session key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> **Security:** Never commit `.env` or `config.toml` to version control. Both are in `.gitignore` by default.

### 4c. Complete Configuration Reference

Every setting can be placed in `config.toml` (snake_case key) or set as an environment variable (UPPER_CASE). Environment variables always win.

#### Discord — Bot

| Setting | Env var | Required | Description |
|---|---|---|---|
| `discord_token` | `DISCORD_TOKEN` | **Yes** | Bot token from Discord Developer Portal → Bot → Token |
| `discord_guild_id` | `DISCORD_GUILD_ID` | **Yes** | Numeric ID of the Discord server the bot operates in |
| `discord_request_channel_id` | `DISCORD_REQUEST_CHANNEL_ID` | **Yes** | Channel where users submit `/request` commands |
| `discord_mod_notify_channel_id` | `DISCORD_MOD_NOTIFY_CHANNEL_ID` | **Yes** | Channel where moderators receive approval notification embeds |

#### Discord — OAuth2 (web login)

| Setting | Env var | Required | Description |
|---|---|---|---|
| `discord_client_id` | `DISCORD_CLIENT_ID` | **Yes** | Application ID from Discord Developer Portal → General Information |
| `discord_client_secret` | `DISCORD_CLIENT_SECRET` | **Yes** | Client secret from Discord Developer Portal → OAuth2 |

#### Web Application

| Setting | Env var | Default | Description |
|---|---|---|---|
| `web_secret_key` | `WEB_SECRET_KEY` | **Required** | Random secret used to sign session cookies. Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `web_base_url` | `WEB_BASE_URL` | `http://localhost:8000` | Public base URL of the web app (no trailing slash). Must match the OAuth2 redirect URI registered in Discord. Include port if non-standard (e.g. `http://localhost:8000`). |
| `web_host` | `WEB_HOST` | `0.0.0.0` | Network interface for the web server to bind to. Use `0.0.0.0` to accept external connections or `127.0.0.1` for localhost-only (e.g. behind a local reverse proxy). |
| `web_port` | `WEB_PORT` | `8000` | TCP port the web server listens on. |

#### Database

| Setting | Env var | Default | Description |
|---|---|---|---|
| `db_path` | `DB_PATH` | `/data/bb_serial.db` | Absolute path to the SQLite database file. In Docker, this should be inside the named volume (e.g. `/data/bb_serial.db`). Change only if you have a custom volume mount. |

#### Serial Number Display

| Setting | Env var | Default | Description |
|---|---|---|---|
| `serial_pad_width` | `SERIAL_PAD_WIDTH` | `3` | Minimum digit width for all serial numbers. `3` → `BB-001`; `4` → `BB-0001`. The number automatically expands beyond the pad width (e.g. serial 1000 displays as `BB-1000` with `serial_pad_width = 3`). Serial prefixes are set per printer type via `/addprinter` or the web UI. |

#### Bootstrap Owner

These settings are used **once** on first startup to create the initial owner account. They are safe to leave set permanently — if an owner already exists in the database, they are ignored.

| Setting | Env var | Default | Description |
|---|---|---|---|
| `initial_owner_discord_id` | `INITIAL_OWNER_DISCORD_ID` | _(none)_ | Discord user ID of the first owner. If set and no owner exists yet, this user is automatically created with the Owner role on startup. Right-click your username in Discord (Developer Mode on) to copy your ID. |
| `initial_owner_username` | `INITIAL_OWNER_USERNAME` | `Owner` | Display name stored for the auto-created owner. Can be any string; the actual Discord username is used after the user first logs in. |

#### Housekeeping

| Setting | Env var | Default | Description |
|---|---|---|---|
| `rejected_request_purge_days` | `REJECTED_REQUEST_PURGE_DAYS` | `30` | Automatically delete rejected requests older than this many days. Set to `0` to disable automatic purging. |

#### Backup

| Setting | Env var | Default | Description |
|---|---|---|---|
| `backup_allow_admin` | `BACKUP_ALLOW_ADMIN` | `false` | When `true`, admin-role users can download a database backup from the web UI in addition to the owner. The owner can always download a backup regardless of this setting. See [Section 9 — Database Backups](#database-backups) for details. |

#### Developer / Operations

| Setting | Env var | Default | Description |
|---|---|---|---|
| `sync_commands` | `SYNC_COMMANDS` | `false` | When `true`, the bot registers all slash commands with Discord on startup. Only needed after adding or changing commands. Set back to `false` after syncing to avoid hitting Discord rate limits. See [Section 7](#7-syncing-bot-commands). |
| `debug` | `DEBUG` | `false` | Enables verbose logging and FastAPI debug mode. Do not use in production. |

---

## 5. First Deployment

Build and start both containers:

```bash
docker compose up --build -d
```

This will:
1. Build the `bot` and `web` Docker images
2. Create a named Docker volume (`bb-serial_db_data`) for the SQLite database
3. Start both containers; each runs `alembic upgrade head` on startup to initialize the database schema
4. Expose the web app on port `8000` (configurable via `WEB_PORT` in `.env`)

Check that both containers are running:

```bash
docker compose ps
```

View logs:

```bash
docker compose logs -f          # all containers
docker compose logs -f bot      # bot only
docker compose logs -f web      # web only
```

---

## 6. Bootstrapping Your First Owner

The database starts empty. Before anyone can use moderator or admin features, you need to designate the first owner.

### Recommended: config-based bootstrap

Set the following in `config.toml` (or as environment variables) before first startup:

```toml
initial_owner_discord_id = "123456789012345678"
initial_owner_username = "Alice"
```

Find your Discord user ID: in Discord with Developer Mode enabled, right-click your username → **Copy User ID**.

On startup, if no owner exists yet, BB-Serial automatically creates this user with the Owner role. These settings are safe to leave in place permanently — they are ignored once an owner exists.

After the owner account is created, log in to the web app with that Discord account to activate it, then manage all further roles from `/admin/users` or via bot commands (`/addmod`, `/removemod`).

---

## 7. Syncing Bot Commands

Slash commands must be explicitly registered with Discord before they appear in your server. This only needs to be done **once** (or after you add/change commands).

**Method A — One-time sync via environment variable:**

1. In `.env`, temporarily set: `SYNC_COMMANDS=true`
2. Restart the bot: `docker compose restart bot`
3. Watch the logs for `Slash commands synced to guild ...`
4. Set `SYNC_COMMANDS=false` again and restart: `docker compose restart bot`

**Method B — Override for a single restart:**

```bash
docker compose run --rm -e SYNC_COMMANDS=true bot python -m bot.main
```

> **Why not always sync?** Discord rate-limits command syncs. Syncing on every startup would cause errors. Only sync when you've changed command definitions.

After syncing, type `/` in your Discord server to confirm the commands appear.

---

## 8. Verifying the Installation

### Test the bot

1. In your request channel, type `/request` — the slash command should appear in Discord's autocomplete
2. Submit a test request with a printer model name
3. Check the mod notify channel — you should see a notification embed with Approve/Reject buttons
4. Click **Approve** — you should receive a DM with the issued serial number
5. Run `/lookup 1` — you should see serial `BB-001` details

### Test the web app

1. Open `http://localhost:8000` in your browser
2. Click **Login with Discord** — you should be redirected to Discord and then back
3. After logging in, if you're an admin, you should see **Users** and **Reservations** in the navbar
4. Visit `/admin/queue` to see the moderator queue

---

## 9. Ongoing Operations

### Role Management

#### Granting moderator access

**Via bot (admin only):**
```
/addmod @username
```

**Via web (admin only):**
Go to `/admin/users`, find the user, change their role to `moderator`, and click Save.

#### Granting admin access

Admin role can only be set via the web interface at `/admin/users` or via the bootstrap script. There is intentionally no `/addadmin` bot command to reduce accident risk.

### Reviewing Serial Requests

Moderators can review requests in two ways:

**Via Discord:** Approval notifications appear in the mod notify channel with **Approve** and **Reject** buttons. Clicking Approve issues the next available serial. Clicking Reject opens a modal for an optional reason.

**Via web:** Visit `/admin/queue`. Each pending request shows the photo, model, and submitter. Use the **Approve** button for automatic serial assignment, or enter a specific serial number in the **Assign #** field (admin only).

### Serial Number Reservations

Admins can reserve serial numbers to prevent them from being auto-assigned (e.g. to hold milestone numbers for special ceremonies):

**Via bot:**
```
/reserve 100 "Milestone - 100th build"
/reserve 500
/unreserve 100
/reservations          # list all reserved numbers
```

**Via web:** Visit `/admin/reservations`. Enter a number and optional reason in the form on the right.

Reserved numbers are skipped during automatic approval. They can still be explicitly assigned using `/assign` (bot) or the **Assign #** field in the web queue (admin only).

### Assigning Specific Serial Numbers

To assign a specific serial number to a pending request (e.g. a reserved milestone number):

**Via bot (admin only):**
```
/assign <request_id> <serial_number>
```
Example: `/assign 42 100` assigns serial `BB-100` to request `#42`.

**Via web (admin only):**
On the queue page, enter the desired number in the **Assign #** input next to the request and click the button.

If the number was reserved, the reservation is automatically removed when it is assigned.

### Rescinding a Serial

If a serial needs to be revoked (fraudulent build, rule violation, etc.):

**Via bot (admin only):**
```
/rescind 42 "Build did not meet community standards"
```

**Via web (admin only):**
Visit `/serial/<id>` and use the Rescind form at the bottom of the page.

Rescinded serials are **not deleted** — the record remains with a `rescinded_at` timestamp and the reason. The serial number is permanently retired and will not be reissued.

---

## 10. Production Hardening

### TLS / HTTPS

The web container does not handle TLS termination. In production, place a reverse proxy in front of it:

**Nginx example** (`/etc/nginx/sites-available/bb-serial`):
```nginx
server {
    listen 443 ssl;
    server_name serials.yoursite.com;

    ssl_certificate     /etc/letsencrypt/live/serials.yoursite.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/serials.yoursite.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Update `web_base_url` in `config.toml` to your HTTPS URL, and add the HTTPS callback URL to your Discord OAuth2 redirect URIs.

### Firewall

Only port 8000 (or 443 via the reverse proxy) needs to be internet-accessible. The SQLite database file is in a Docker volume and is never exposed externally.

### Database Backups

The SQLite database lives in the Docker volume `bb-serial_db_data`, mounted at `/data/bb_serial.db` inside the containers.

#### Web UI download (recommended for ad-hoc backups)

BB-Serial has a built-in hot backup endpoint. Navigate to **Backup** in the navbar (visible to owners, and to admins if `backup_allow_admin = true`). Clicking the link downloads a timestamped `.db` file (`bb_serial_backup_YYYYMMDD_HHMMSS.db`) that is a fully consistent snapshot safe to take while the app is running.

To enable backup downloads for admin-role users, add to `config.toml`:

```toml
backup_allow_admin = true
```

#### Manual backup via the host

```bash
docker compose exec web sqlite3 /data/bb_serial.db ".backup '/data/backup_$(date +%Y%m%d).db'"
```

#### Automated daily backup (host crontab)

```bash
0 3 * * * docker exec bb-serial-web-1 sqlite3 /data/bb_serial.db ".backup '/data/backup_$(date +\%Y\%m\%d).db'" && docker cp bb-serial-web-1:/data/backup_$(date +%Y%m%d).db /your/backup/path/
```

#### Restoring from backup

```bash
docker compose down
docker run --rm -v bb-serial_db_data:/data -v /your/backup/path:/backup alpine \
  cp /backup/backup_20240101.db /data/bb_serial.db
docker compose up -d
```

### Resource Limits

Add resource limits to `docker-compose.yml` if running on a shared host:

```yaml
services:
  bot:
    deploy:
      resources:
        limits:
          memory: 256M
  web:
    deploy:
      resources:
        limits:
          memory: 512M
```

---

## 11. Updating the Application

```bash
# Pull latest code
git pull

# Rebuild and restart (database migrations run automatically on startup)
docker compose up --build -d
```

If slash commands changed, re-sync them once (see [Section 7](#7-syncing-bot-commands)).

---

## 12. Troubleshooting

### Bot is online but slash commands don't appear

The commands need to be synced. See [Section 7](#7-syncing-bot-commands). Note that Discord can take up to an hour to propagate guild-scoped commands, though it's usually instant.

### "Interaction failed" when clicking Approve/Reject buttons

The bot is not running or lost connection. Check `docker compose ps` and `docker compose logs bot`.

### OAuth2 login returns an error

- Verify `DISCORD_CLIENT_SECRET` in `.env` matches the secret in the Discord Developer Portal
- Verify the redirect URI in the Discord Developer Portal exactly matches `web_base_url` + `/auth/callback`
- Check that `web_base_url` in `config.toml` does not have a trailing slash

### "Database migration failed" in logs

The database file may be locked by another process, or the volume path may not be writable. Check:

```bash
docker compose logs bot | grep -i migrat
docker compose logs web | grep -i migrat
```

If both containers try to migrate at exactly the same time, one may fail. A restart usually resolves it since Alembic is idempotent.

### Resetting the database (development only)

```bash
docker compose down -v          # WARNING: destroys all data
docker compose up --build -d
```

### Viewing the database directly

```bash
docker compose exec web sqlite3 /data/bb_serial.db
```

Useful queries:
```sql
SELECT COUNT(*) FROM serials WHERE rescinded_at IS NULL;  -- active serial count
SELECT * FROM users WHERE role != 'user';                  -- moderators and admins
SELECT * FROM serial_reservations ORDER BY serial_number;  -- reserved numbers
```
