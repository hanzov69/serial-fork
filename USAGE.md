# Serial Fork — Usage Guide

This document covers day-to-day use of Serial Fork for everyone involved: builders requesting serials, moderators reviewing them, admins managing the system, and owners configuring it.

---

## Table of Contents

1. [Roles](#1-roles)
2. [For Users — Requesting a Serial Number](#2-for-users--requesting-a-serial-number)
3. [For Moderators — Reviewing Requests](#3-for-moderators--reviewing-requests)
4. [For Admins — Managing the System](#4-for-admins--managing-the-system)
5. [For Owners — Configuration and Ownership](#5-for-owners--configuration-and-ownership)
6. [Bot Slash Command Reference](#6-bot-slash-command-reference)
7. [Web Interface Reference](#7-web-interface-reference)

---

## 1. Roles

Serial Fork has four roles, each with progressively more access:

| Role | Who it's for | What they can do |
|------|-------------|-----------------|
| **User** | Anyone who has logged in | Submit requests, view their own requests, look up serials |
| **Moderator** | Trusted community members | Everything above + approve/reject requests |
| **Admin** | Server administrators | Everything above + manage users, printer types, reservations, serial rescission |
| **Owner** | The site operator (single account) | Everything above + system configuration, theme, database backup, ownership transfer |

Role assignments are managed by admins and owners via the web UI or bot commands. Roles are stored in the Serial Fork database separately from Discord server roles.

---

## 2. For Users — Requesting a Serial Number

### Prerequisites

- You must be a member of the Discord server
- Your build post must be in the designated **build showcase forum channel**
- Your forum post must include **at least one photo or video** of your completed build
- Your forum post must have the correct **printer type tag** applied

### Step-by-step

**1. Create your forum post**

Post in the build showcase forum channel. Write up your build, attach photos or a video, and apply the forum tag for your printer type (e.g. "Baby Belt Pro", "Crooked Crow"). The tag is what tells the bot which serial number sequence to use.

**2. Run `/request` in your thread**

Inside your own forum post thread (not in any other channel), type `/request`. The bot will:
- Confirm you are the thread owner
- Detect your printer type from the thread's tag
- Check that your post contains media
- Queue your request for moderator review

You will receive an ephemeral (visible only to you) confirmation message. If something is wrong — missing media, wrong channel, unrecognised tag — the bot will tell you what to fix.

**3. Wait for review**

A moderator will review your submission. You will receive a **direct message** from the bot when your request is approved or rejected.

- **Approved:** Your serial number is included in the DM. The bot also posts a congratulations message in your forum thread and assigns you the printer role in the Discord server.
- **Rejected:** The rejection reason (if provided) is included in the DM.

**4. If rejected — resubmit**

Address the moderator's feedback (update your post, add better photos, etc.), then run `/resubmit <request_id>` inside your forum thread, or use the **My Requests** page on the web app to resubmit.

### Tracking your request

Log in to the web app with your Discord account and visit **My Requests**. It shows all your pending, approved, and rejected requests with their current status and any rejection reasons.

---

## 3. For Moderators — Reviewing Requests

Moderators can review and act on requests through either Discord or the web interface.

### Via Discord

**Viewing the queue**

Run `/queue` in any channel. The bot responds with an ephemeral embed listing all pending requests, each with a link to the builder's forum thread.

**Approving a request**

```
/approve request_id:<id>
```

Or click the **✅ Approve** button on the notification embed in the mod channel.

On approval the bot will:
- Issue the next available serial number for that printer type
- DM the requester with their serial
- Post a congratulations message in their forum thread
- Assign the configured Discord role to the requester
- Update the mod channel embed to show the request as resolved

**Rejecting a request**

```
/reject request_id:<id> reason:<optional reason>
```

Or click the **❌ Reject** button on the mod channel embed, which opens a modal for the rejection reason.

The reason is sent to the requester via DM.

### Via the web interface

Go to **Queue** in the navigation bar (visible to moderators and above).

Each pending request is shown as a card with:
- Requester name and avatar
- Printer type
- Link to the forum post
- Submission date and notes
- **Approve** and **Reject** buttons

Rejecting from the web opens an inline form for the rejection reason.

---

## 4. For Admins — Managing the System

### User management

Navigate to **Config → Users** in the web UI.

- **Promote** a user to Moderator or Admin using the role dropdown next to their name
- **Demote** a user back to a lower role

You can also use bot commands:
```
/addmod @user     — promote to Moderator
/removemod @user  — demote to User
```

### Printer type management

Navigate to **Config** in the web UI and scroll to the **Printer Types** table.

Each printer type has:
- An **Identifier** (e.g. `BBP`) — used as the serial prefix, cannot be changed after creation
- A **Name** and optional **Description**
- A **Discord Role ID** — the server role assigned to users on approval
- A **Forum Tag ID** — the forum channel tag used to identify this type in `/request`

**Adding a printer type**

Fill in the "Add Printer Type" form on the Config page. The bot will attempt to create the corresponding forum tag automatically. If it fails (check that the bot has **Manage Channels** permission on the forum channel), you can set the Tag ID manually.

**Deactivating / deleting a printer type**

- **Deactivate** hides the type from new requests but preserves all history
- **Delete** permanently removes the type — only available if no serials have been issued for it

### Rescinding a serial

If a serial needs to be revoked (e.g. the build was not genuine), navigate to the serial's detail page on the web app and use the **Rescind** form, providing a reason. Or use the bot:

```
/rescind serial:<BBP-042> reason:<reason>
```

Rescinded serials remain visible in the registry but are marked as rescinded. The holder's Discord role is not automatically removed — do that manually if needed.

### Serial reservations

Navigate to **Reservations** in the web UI to manage blocked serial numbers.

**What reservations do:** Reserved numbers are skipped during automatic serial assignment. They can still be assigned explicitly (via the queue page Assign button or `/assign`). Use reservations for milestone numbers (100, 500, 1000), prototype units, contest prizes, etc.

**Single reservation:** Use the "Reserve a Number" form — choose a printer type, enter the serial number, and optionally add a reason.

**Bulk import:** Upload a CSV file using the "Bulk Import" panel. Download the example CSV for the correct format:

```csv
identifier,serial_number,reason
BBP,100,Milestone — first 100 builds
BBP,500,Milestone — 500 builds
CC,1,Prototype unit
```

If any rows collide (already issued, already reserved, unknown type), they are skipped and listed in a failure table. All other rows are processed normally.

**Removing a reservation:** Click the **Remove** button next to any reservation in the table.

### Manually assigning a serial number

From the web queue, each pending request has an **Assign** option where you can specify an exact serial number (including reserved ones). This is useful for milestone assignments or contest winners.

---

## 5. For Owners — Configuration and Ownership

### System configuration

Navigate to **Config** in the web UI. Owners see the full config page including:

**Site Theme**

Choose from the installed themes in the dropdown and click **Apply Theme**. The change takes effect immediately for all users.

Built-in themes:
- **BabyBelt** — deep navy and gold (default)
- **Printcepts** — dark professional with emerald green
- **Wave** — 80s vaporwave with neon pink and cyan

To add a custom theme, drop a CSS file into `web/static/css/themes/` following the format described in the [README](README.md#adding-a-custom-theme). It will appear in the dropdown on next restart.

**Discord Channel IDs**

Override the `discord_forum_channel_id` and `discord_mod_notify_channel_id` values from `config.toml` at runtime without restarting the containers. Leave blank to use the values from `config.toml`.

### Database backup

Navigate to **Config** and click **Backup DB** in the navigation bar. This downloads a ZIP archive containing a consistent snapshot of the SQLite database (using SQLite's online backup API — safe while the app is running).

Store backups in a safe location. The database contains all users, serials, requests, reservations, and audit logs.

> Admins can also be granted backup access by setting `backup_allow_admin = true` in `config.toml`.

### Transferring ownership

Run the bot command:

```
/transferownership @newowner
```

This moves the Owner role to the target user. There can only be one owner at a time. After transfer you will be downgraded to Admin.

---

## 6. Bot Slash Command Reference

### User commands

| Command | Description |
|---------|-------------|
| `/request` | Submit a serial number request. Must be run inside your own forum post thread. The bot detects your printer type from the thread's tag automatically. |
| `/resubmit request_id:<id>` | Re-submit a rejected request from your forum post thread. Updates the post URL if you have changed threads. |
| `/lookup printer_type:<type> serial_number:<n>` | Look up any issued serial number by type and number. Responds publicly. |
| `/serialfork` | Show Serial Fork version, total serials issued (with per-type breakdown), and links to the GitHub repo and project page. |

### Moderator commands

| Command | Who | Description |
|---------|-----|-------------|
| `/approve request_id:<id>` | Moderator+ | Approve a pending request and issue the next serial number. |
| `/reject request_id:<id> [reason:<text>]` | Moderator+ | Reject a request with an optional reason sent to the requester. |
| `/queue` | Moderator+ | Show all pending requests as an ephemeral embed. |

### Admin commands

| Command | Who | Description |
|---------|-----|-------------|
| `/addmod @user` | Admin+ | Promote a user to Moderator. |
| `/removemod @user` | Admin+ | Demote a Moderator back to User. |
| `/rescind serial:<type-number> reason:<text>` | Admin+ | Revoke an issued serial. |
| `/reserve printer_type:<type> serial_number:<n> [reason:<text>]` | Admin+ | Block a specific serial number from auto-assignment. |
| `/unreserve printer_type:<type> serial_number:<n>` | Admin+ | Remove a reservation. |
| `/reservations` | Admin+ | List all current reservations. |
| `/assign request_id:<id> serial_number:<n>` | Admin+ | Manually assign a specific serial number to a request. |
| `/addprinter identifier:<id> name:<name> [description:<text>]` | Admin+ | Create a new printer type and auto-create its forum tag. |
| `/printers` | Anyone | List all configured printer types and their status. |

### Owner commands

| Command | Who | Description |
|---------|-----|-------------|
| `/transferownership @user` | Owner | Transfer the Owner role to another user. |

---

## 7. Web Interface Reference

All pages are accessible at your configured `web_base_url`.

### Public pages (no login required)

| Page | URL | Description |
|------|-----|-------------|
| **Home** | `/` | Summary stats (total serials per type) and recently issued serials |
| **All Serials** | `/serials` | Paginated, searchable list of all issued serials. Filter by printer type. |
| **Serial Detail** | `/serial/<type>/<number>` | Full detail for a single serial — holder, issuer, build link, dates |
| **Info** | `/info` | How-to guide, community links, and credits |

### User pages (login required)

| Page | URL | Description |
|------|-----|-------------|
| **My Requests** | `/my-requests` | All your serial requests with their current status and any rejection reasons |

### Moderator pages

| Page | URL | Description |
|------|-----|-------------|
| **Queue** | `/admin/queue` | Review pending requests. Each card has Approve, Reject, and Assign (admin) controls. |

### Admin pages

| Page | URL | Description |
|------|-----|-------------|
| **Config** | `/admin/config` | Printer type management, Discord channel overrides, and (owner only) site theme |
| **Reservations** | `/admin/reservations` | View, add, remove, and bulk-import serial reservations |
| **Users** | `/admin/users` | View all users and change their roles |

### Owner pages

| Page | URL | Description |
|------|-----|-------------|
| **Backup DB** | `/admin/backup` | Download a database backup ZIP |
