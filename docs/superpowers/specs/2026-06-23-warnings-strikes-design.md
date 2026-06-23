# Warnings & Strikes Feature — Design Spec
_Date: 2026-06-23_

## Overview

A warning and strike system for KAL-Utils. Admins issue warnings against members; warnings accumulate into strikes according to a defined threshold. All moderation actions (role removal, kick, ban) remain manual — the bot tracks and surfaces information, admins execute consequences.

---

## Commands

All commands require `administrator` permission.

| Command | Arguments | Description |
|---|---|---|
| `/warn` | `@member`, `reason`, `[amount]`, `[unit]` | Issues a warning. Duration is optional (amount + unit e.g. `3 days`, `1 hour`, `2 weeks`). If omitted, warning is permanent. |
| `/removewarn` | `@member`, `warn_id` | Removes one specific warning by its ID. |
| `/removestrike` | `@member` | Removes the most recent warning that caused a strike threshold to be crossed, effectively dropping the member back one strike level. |
| `/clearstrikes` | `@member` | Clears all warnings and strikes for a member. |
| `/warnings` | `@member` | Shows the member's full warn/strike history (active and expired). |
| `/setwarnlog` | `#channel` | One-time setup — sets the channel where warn/strike embeds are posted. |
| `/testwarn` | _(none)_ | Posts a fake warn embed to the log channel to verify setup. No DB changes. |

---

## Strike Thresholds

Active warning count (unexpired only) determines strike level:

| Active Warns | Strike |
|---|---|
| 3 | Strike 1 |
| 6 | Strike 2 |
| 8 | Strike 3 — admin action required |

- First two strikes require 3 warns each.
- Third strike requires only 2 additional warns.
- Strike 3 embed explicitly flags that admin action (role removal or termination) is needed.

---

## Data

### `warn_config` table
Stores per-guild log channel. One row per guild.

| Column | Type | Notes |
|---|---|---|
| `guild_id` | INTEGER PRIMARY KEY | |
| `log_channel_id` | INTEGER | Channel ID for embed output |

### `warnings` table
One row per warning issued.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Used by `/removewarn` |
| `guild_id` | INTEGER | |
| `user_id` | INTEGER | The warned member |
| `reason` | TEXT | |
| `issued_by` | INTEGER | Admin user ID |
| `issued_at` | TEXT | ISO 8601 timestamp |
| `expires_at` | TEXT (nullable) | NULL = permanent; ISO 8601 if timed |

Tables are created in `cog_load` (same pattern as `security.py`).

---

## Strike Calculation Logic

Runs whenever a warn is issued or `/warnings` is viewed:

1. Fetch all warning rows for `(guild_id, user_id)`.
2. Filter to active: `expires_at IS NULL OR expires_at > now`.
3. Count active warns → map to strike level per threshold table above.
4. If the new warn pushed the count to exactly 3, 6, or 8 — the posted embed switches to a Strike embed instead of a Warn embed.

---

## Embed Layout

Posted to the configured log channel on every `/warn`, `/removewarn`, `/removestrike`, and `/clearstrikes` action.

Custom emojis are looked up dynamically via `discord.utils.get(guild.emojis, name="...")`.

### Warn embed
```
:KE_Exclamation:  Warning #<n>
:KE_User:  User: @member
:KE_Badge:  Position: @their_top_role
:KE_Arrow:  Reason: <reason>

Expires: <X days/hours/weeks>  |  Permanent
Issued by: @admin
```
Colour: **yellow** (`0xF1C40F`)

### Strike embed (replaces warn embed when threshold is crossed)
```
:KE_Exclamation:  Strike #<n>
:KE_User:  User: @member
:KE_Badge:  Position: @their_top_role
:KE_Arrow:  Reason: <reason>

Active Warnings: <count>
Expires: <X days/hours/weeks>  |  Permanent
Issued by: @admin
```
Colour: **orange** (`0xE67E22`) for strikes 1–2, **red** (`0xE74C3C`) for strike 3.

Strike 3 embed adds an extra field:
```
⚠️ Action Required: This member has reached 3 strikes. Admin action (role removal or termination) is required.
```

### Removal/clear embed
```
:KE_Exclamation:  Warning Removed  /  Strike Removed  /  All Cleared
:KE_User:  User: @member
:KE_Arrow:  Action by: @admin
```
Colour: **green** (`0x2ECC71`)

---

## File Structure

- `bot/cogs/warnings.py` — new cog, all warn/strike commands and embed logic
- `bot/db/database.py` — add `warnings` and `warn_config` table creation to `init_db()`
- `bot/main.py` — add `"cogs.warnings"` to the `COGS` list

---

## Error Handling

- If no log channel is configured, commands respond ephemerally: _"No warn log channel set. Use `/setwarnlog` first."_
- If `warn_id` doesn't exist or belongs to a different guild, respond ephemerally: _"Warning not found."_
- If `/removestrike` is used on a member with fewer than 3 active warns (no strike yet), respond ephemerally: _"This member has no strikes to remove."_
- Bot missing permissions to send in the log channel → ephemeral error to the admin.
