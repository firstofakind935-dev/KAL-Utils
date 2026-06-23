# Warnings & Strikes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a warning and strike system to KAL-Utils where admins issue warnings that accumulate into strikes (3→strike1, 6→strike2, 8→strike3), all tracked in SQLite and surfaced via Discord embeds posted to a configured log channel.

**Architecture:** A new `bot/cogs/warnings.py` cog holds all commands and DB queries. Tables are created in `cog_load` (same pattern as `security.py`). Strike threshold logic is isolated in pure module-level helper functions so they can be unit-tested without Discord. All commands are admin-only hybrid commands.

**Tech Stack:** discord.py (hybrid commands + app_commands), aiosqlite, pytest

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `bot/cogs/warnings.py` | All warn/strike commands, embed builders, DB queries, pure helpers |
| Create | `tests/conftest.py` | Add `bot/` to sys.path so test imports resolve |
| Create | `tests/test_warnings_logic.py` | Unit tests for pure helper functions |
| Create | `pytest.ini` | Configure pytest root |
| Modify | `bot/main.py` | Add `"cogs.warnings"` to COGS list |

---

## Task 1: Test infrastructure

**Files:**
- Create: `pytest.ini`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pytest.ini` at the repo root**

```ini
[pytest]
testpaths = tests
```

- [ ] **Step 2: Create `tests/conftest.py`**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "bot"))
```

- [ ] **Step 3: Verify pytest runs (no tests yet = OK)**

```bash
pytest -v
```
Expected: `no tests ran` or `collected 0 items` — no errors.

- [ ] **Step 4: Commit**

```bash
git add pytest.ini tests/conftest.py
git commit -m "chore: add pytest infrastructure"
```

---

## Task 2: Pure helper functions + unit tests

**Files:**
- Create: `bot/cogs/warnings.py` (helpers only for now)
- Create: `tests/test_warnings_logic.py`

- [ ] **Step 1: Create `bot/cogs/warnings.py` with only the pure helpers**

```python
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from db.database import DB_PATH

STRIKE_THRESHOLDS = [3, 6, 8]  # warn counts that trigger strikes 1, 2, 3


def _get_strike_level(active_warn_count: int) -> int:
    """Returns current strike level (0-3) based on active warning count."""
    level = 0
    for t in STRIKE_THRESHOLDS:
        if active_warn_count >= t:
            level += 1
    return level


def _threshold_crossed(old_count: int, new_count: int) -> Optional[int]:
    """Returns strike number (1-3) if new_count crossed a threshold, else None."""
    for i, t in enumerate(STRIKE_THRESHOLDS, 1):
        if old_count < t <= new_count:
            return i
    return None


def _parse_expires_at(amount: int, unit: str) -> Optional[str]:
    """Returns ISO 8601 expiry timestamp string, or None for unknown unit."""
    unit_seconds = {"hours": 3600, "days": 86400, "weeks": 604800}
    seconds = unit_seconds.get(unit)
    if seconds is None:
        return None
    dt = datetime.now(timezone.utc) + timedelta(seconds=amount * seconds)
    return dt.isoformat()


async def setup(bot: commands.Bot):
    pass  # placeholder — replaced in Task 3
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_warnings_logic.py`:

```python
import pytest
from cogs.warnings import _get_strike_level, _threshold_crossed, _parse_expires_at
from datetime import datetime, timezone


# --- _get_strike_level ---

def test_strike_level_zero_at_zero_warns():
    assert _get_strike_level(0) == 0

def test_strike_level_zero_below_first_threshold():
    assert _get_strike_level(2) == 0

def test_strike_level_one_at_threshold():
    assert _get_strike_level(3) == 1

def test_strike_level_one_between_thresholds():
    assert _get_strike_level(5) == 1

def test_strike_level_two_at_threshold():
    assert _get_strike_level(6) == 2

def test_strike_level_two_between_thresholds():
    assert _get_strike_level(7) == 2

def test_strike_level_three_at_threshold():
    assert _get_strike_level(8) == 3

def test_strike_level_three_above_threshold():
    assert _get_strike_level(10) == 3


# --- _threshold_crossed ---

def test_no_threshold_crossed_below_first():
    assert _threshold_crossed(0, 2) is None

def test_no_threshold_crossed_between_thresholds():
    assert _threshold_crossed(3, 5) is None

def test_threshold_crossed_strike_1():
    assert _threshold_crossed(2, 3) == 1

def test_threshold_crossed_strike_2():
    assert _threshold_crossed(5, 6) == 2

def test_threshold_crossed_strike_3():
    assert _threshold_crossed(7, 8) == 3

def test_threshold_crossed_when_count_jumps():
    # warn count going from 2 to 4 still crosses the 3-warn threshold
    assert _threshold_crossed(2, 4) == 1

def test_no_threshold_when_already_past():
    # already at 3, adding one more (4) does not cross a new threshold
    assert _threshold_crossed(3, 4) is None


# --- _parse_expires_at ---

def test_parse_expires_at_days():
    result = _parse_expires_at(3, "days")
    assert result is not None
    dt = datetime.fromisoformat(result)
    assert dt > datetime.now(timezone.utc)

def test_parse_expires_at_hours():
    result = _parse_expires_at(1, "hours")
    assert result is not None
    dt = datetime.fromisoformat(result)
    assert dt > datetime.now(timezone.utc)

def test_parse_expires_at_weeks():
    result = _parse_expires_at(2, "weeks")
    assert result is not None
    dt = datetime.fromisoformat(result)
    assert dt > datetime.now(timezone.utc)

def test_parse_expires_at_unknown_unit_returns_none():
    assert _parse_expires_at(1, "minutes") is None

def test_parse_expires_at_unknown_unit_2():
    assert _parse_expires_at(5, "years") is None
```

- [ ] **Step 3: Run tests — expect them to FAIL (function not importable yet)**

```bash
pytest tests/test_warnings_logic.py -v
```
Expected: ImportError or similar — that's correct, the functions don't exist yet.

- [ ] **Step 4: Run tests again after Step 1 is done — expect PASS**

```bash
pytest tests/test_warnings_logic.py -v
```
Expected: All 20 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/cogs/warnings.py tests/test_warnings_logic.py
git commit -m "feat: add warnings cog helpers + unit tests"
```

---

## Task 3: DB tables + cog skeleton

**Files:**
- Modify: `bot/cogs/warnings.py` (replace `setup` placeholder, add `Warnings` class with `cog_load`)

- [ ] **Step 1: Replace `bot/cogs/warnings.py` with the full skeleton**

Keep the helpers from Task 2 at the top. Add below them:

```python
class Warnings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS warn_config (
                    guild_id       INTEGER PRIMARY KEY,
                    log_channel_id INTEGER NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id   INTEGER NOT NULL,
                    user_id    INTEGER NOT NULL,
                    reason     TEXT NOT NULL,
                    issued_by  INTEGER NOT NULL,
                    issued_at  TEXT NOT NULL,
                    expires_at TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS strikes (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id           INTEGER NOT NULL,
                    user_id            INTEGER NOT NULL,
                    strike_number      INTEGER NOT NULL,
                    reason             TEXT NOT NULL,
                    issued_by          INTEGER NOT NULL,
                    issued_at          TEXT NOT NULL,
                    triggering_warn_id INTEGER NOT NULL
                )
            """)
            await db.commit()

    async def _get_log_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT log_channel_id FROM warn_config WHERE guild_id = ?",
                (guild.id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return guild.get_channel(row[0])

    async def _get_active_warn_count(self, guild_id: int, user_id: int) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                """SELECT COUNT(*) FROM warnings
                   WHERE guild_id = ? AND user_id = ?
                   AND (expires_at IS NULL OR expires_at > ?)""",
                (guild_id, user_id, now),
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row else 0

    async def _post_embed(self, channel: discord.TextChannel, embed: discord.Embed):
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Warnings(bot))
```

- [ ] **Step 2: Run existing tests to confirm nothing broke**

```bash
pytest tests/test_warnings_logic.py -v
```
Expected: All 20 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add bot/cogs/warnings.py
git commit -m "feat: add Warnings cog skeleton and DB tables"
```

---

## Task 4: Embed builders

**Files:**
- Modify: `bot/cogs/warnings.py` (add three embed builder methods to `Warnings` class)

- [ ] **Step 1: Add embed builder methods inside the `Warnings` class, after `_post_embed`**

```python
    def _warn_embed(
        self,
        guild: discord.Guild,
        member: discord.Member,
        warn_num: int,
        reason: str,
        expires_at: Optional[str],
        issued_by: discord.Member,
    ) -> discord.Embed:
        ex = discord.utils.get(guild.emojis, name="KE_Exclamation")
        eu = discord.utils.get(guild.emojis, name="KE_User")
        eb = discord.utils.get(guild.emojis, name="KE_Badge")
        ea = discord.utils.get(guild.emojis, name="KE_Arrow")

        top_role = next((r for r in reversed(member.roles) if r.name != "@everyone"), None)
        position = top_role.mention if top_role else "No role"

        if expires_at:
            dt = datetime.fromisoformat(expires_at)
            expires_str = discord.utils.format_dt(dt, style="R")
        else:
            expires_str = "Permanent"

        embed = discord.Embed(
            title=f"{ex or '⚠️'} Warning #{warn_num}",
            color=0xF1C40F,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name=f"{eu or ''} User", value=member.mention, inline=False)
        embed.add_field(name=f"{eb or ''} Position", value=position, inline=False)
        embed.add_field(name=f"{ea or ''} Reason", value=reason, inline=False)
        embed.add_field(name="Expires", value=expires_str, inline=True)
        embed.add_field(name="Issued by", value=issued_by.mention, inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        return embed

    def _strike_embed(
        self,
        guild: discord.Guild,
        member: discord.Member,
        strike_num: int,
        warn_count: int,
        reason: str,
        expires_at: Optional[str],
        issued_by: discord.Member,
    ) -> discord.Embed:
        ex = discord.utils.get(guild.emojis, name="KE_Exclamation")
        eu = discord.utils.get(guild.emojis, name="KE_User")
        eb = discord.utils.get(guild.emojis, name="KE_Badge")
        ea = discord.utils.get(guild.emojis, name="KE_Arrow")

        top_role = next((r for r in reversed(member.roles) if r.name != "@everyone"), None)
        position = top_role.mention if top_role else "No role"

        color = 0xE74C3C if strike_num == 3 else 0xE67E22

        if expires_at:
            dt = datetime.fromisoformat(expires_at)
            expires_str = discord.utils.format_dt(dt, style="R")
        else:
            expires_str = "Permanent"

        embed = discord.Embed(
            title=f"{ex or '🚨'} Strike #{strike_num}",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name=f"{eu or ''} User", value=member.mention, inline=False)
        embed.add_field(name=f"{eb or ''} Position", value=position, inline=False)
        embed.add_field(name=f"{ea or ''} Reason", value=reason, inline=False)
        embed.add_field(name="Active Warnings", value=str(warn_count), inline=True)
        embed.add_field(name="Expires", value=expires_str, inline=True)
        embed.add_field(name="Issued by", value=issued_by.mention, inline=True)
        if strike_num == 3:
            embed.add_field(
                name="⚠️ Action Required",
                value="This member has reached 3 strikes. Admin action (role removal or termination) is required.",
                inline=False,
            )
        embed.set_thumbnail(url=member.display_avatar.url)
        return embed

    def _removal_embed(
        self,
        guild: discord.Guild,
        member: discord.Member,
        action: str,
        issued_by: discord.Member,
    ) -> discord.Embed:
        ex = discord.utils.get(guild.emojis, name="KE_Exclamation")
        eu = discord.utils.get(guild.emojis, name="KE_User")
        ea = discord.utils.get(guild.emojis, name="KE_Arrow")

        embed = discord.Embed(
            title=f"{ex or '✅'} {action}",
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name=f"{eu or ''} User", value=member.mention, inline=False)
        embed.add_field(name=f"{ea or ''} Action by", value=issued_by.mention, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        return embed
```

- [ ] **Step 2: Run tests to confirm nothing broke**

```bash
pytest tests/test_warnings_logic.py -v
```
Expected: All 20 PASS.

- [ ] **Step 3: Commit**

```bash
git add bot/cogs/warnings.py
git commit -m "feat: add warn/strike/removal embed builders"
```

---

## Task 5: `/setwarnlog` command

**Files:**
- Modify: `bot/cogs/warnings.py` (add command inside `Warnings` class)

- [ ] **Step 1: Add `/setwarnlog` inside the `Warnings` class, after the embed builders**

```python
    @commands.hybrid_command(name="setwarnlog", description="[Admin] Set the channel for warn/strike logs")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel="Channel to post warn/strike embeds in")
    async def setwarnlog(self, ctx: commands.Context, channel: discord.TextChannel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO warn_config (guild_id, log_channel_id) VALUES (?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET log_channel_id = excluded.log_channel_id""",
                (ctx.guild.id, channel.id),
            )
            await db.commit()
        await ctx.send(f"Warn log channel set to {channel.mention}.", ephemeral=True)
```

- [ ] **Step 2: Commit**

```bash
git add bot/cogs/warnings.py
git commit -m "feat: add /setwarnlog command"
```

---

## Task 6: `/warn` command

**Files:**
- Modify: `bot/cogs/warnings.py` (add command inside `Warnings` class)

- [ ] **Step 1: Add `/warn` inside the `Warnings` class**

```python
    @commands.hybrid_command(name="warn", description="[Admin] Issue a warning to a member")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        member="The member to warn",
        reason="Reason for the warning",
        amount="Duration amount (e.g. 3) — leave blank for permanent",
        unit="Duration unit — leave blank for permanent",
        strike_reason="Reason for the strike if this warn triggers one (defaults to warn reason)",
    )
    async def warn(
        self,
        ctx: commands.Context,
        member: discord.Member,
        reason: str,
        amount: Optional[int] = None,
        unit: Optional[Literal["hours", "days", "weeks"]] = None,
        strike_reason: Optional[str] = None,
    ):
        log_channel = await self._get_log_channel(ctx.guild)
        if not log_channel:
            return await ctx.send("No warn log channel set. Use `/setwarnlog` first.", ephemeral=True)

        expires_at = _parse_expires_at(amount, unit) if (amount and unit) else None
        now = datetime.now(timezone.utc).isoformat()
        old_count = await self._get_active_warn_count(ctx.guild.id, member.id)

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """INSERT INTO warnings (guild_id, user_id, reason, issued_by, issued_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ctx.guild.id, member.id, reason, ctx.author.id, now, expires_at),
            )
            warn_id = cursor.lastrowid
            await db.commit()

        new_count = old_count + 1
        strike_num = _threshold_crossed(old_count, new_count)

        if strike_num:
            effective_reason = strike_reason or reason
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """INSERT INTO strikes
                       (guild_id, user_id, strike_number, reason, issued_by, issued_at, triggering_warn_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (ctx.guild.id, member.id, strike_num, effective_reason, ctx.author.id, now, warn_id),
                )
                await db.commit()
            embed = self._strike_embed(ctx.guild, member, strike_num, new_count, effective_reason, expires_at, ctx.author)
            label = f"Strike #{strike_num}"
        else:
            embed = self._warn_embed(ctx.guild, member, new_count, reason, expires_at, ctx.author)
            label = f"Warning #{new_count}"

        await self._post_embed(log_channel, embed)
        await ctx.send(f"{label} issued for {member.mention}.", ephemeral=True)
```

- [ ] **Step 2: Commit**

```bash
git add bot/cogs/warnings.py
git commit -m "feat: add /warn command with strike threshold logic"
```

---

## Task 7: `/warnings` command

**Files:**
- Modify: `bot/cogs/warnings.py` (add command inside `Warnings` class)

- [ ] **Step 1: Add `/warnings` inside the `Warnings` class**

```python
    @commands.hybrid_command(name="warnings", description="[Admin] View a member's warn/strike history")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="The member to check")
    async def warnings(self, ctx: commands.Context, member: discord.Member):
        now = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                """SELECT id, reason, issued_at, expires_at FROM warnings
                   WHERE guild_id = ? AND user_id = ? ORDER BY issued_at""",
                (ctx.guild.id, member.id),
            ) as cur:
                warn_rows = await cur.fetchall()
            async with db.execute(
                """SELECT id, strike_number, reason, issued_at FROM strikes
                   WHERE guild_id = ? AND user_id = ? ORDER BY issued_at""",
                (ctx.guild.id, member.id),
            ) as cur:
                strike_rows = await cur.fetchall()

        active_count = sum(
            1 for _, _, _, expires_at in warn_rows
            if expires_at is None or expires_at > now
        )

        embed = discord.Embed(
            title=f"Warn/Strike History — {member.display_name}",
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Active Warnings", value=str(active_count), inline=True)
        embed.add_field(name="Total Strikes", value=str(len(strike_rows)), inline=True)

        if warn_rows:
            warn_lines = []
            for wid, reason, issued_at, expires_at in warn_rows:
                status = "✅" if (expires_at is None or expires_at > now) else "❌ Expired"
                warn_lines.append(f"`ID {wid}` {status} — {reason[:50]}")
            embed.add_field(name="Warnings", value="\n".join(warn_lines[:10]), inline=False)

        if strike_rows:
            strike_lines = [
                f"`ID {sid}` Strike #{snum} — {reason[:50]}"
                for sid, snum, reason, _ in strike_rows
            ]
            embed.add_field(name="Strikes", value="\n".join(strike_lines), inline=False)

        if not warn_rows and not strike_rows:
            embed.description = "No warnings or strikes on record."

        await ctx.send(embed=embed, ephemeral=True)
```

- [ ] **Step 2: Commit**

```bash
git add bot/cogs/warnings.py
git commit -m "feat: add /warnings history command"
```

---

## Task 8: `/removewarn` command

**Files:**
- Modify: `bot/cogs/warnings.py` (add command inside `Warnings` class)

- [ ] **Step 1: Add `/removewarn` inside the `Warnings` class**

```python
    @commands.hybrid_command(name="removewarn", description="[Admin] Remove a specific warning by ID")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        member="The member to remove the warning from",
        warn_id="The warning ID — use /warnings to find it",
    )
    async def removewarn(self, ctx: commands.Context, member: discord.Member, warn_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id FROM warnings WHERE id = ? AND guild_id = ? AND user_id = ?",
                (warn_id, ctx.guild.id, member.id),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return await ctx.send("Warning not found for this member.", ephemeral=True)
            await db.execute("DELETE FROM warnings WHERE id = ?", (warn_id,))
            await db.commit()

        log_channel = await self._get_log_channel(ctx.guild)
        if log_channel:
            embed = self._removal_embed(ctx.guild, member, f"Warning #{warn_id} Removed", ctx.author)
            await self._post_embed(log_channel, embed)

        await ctx.send(f"Warning `{warn_id}` removed for {member.mention}.", ephemeral=True)
```

- [ ] **Step 2: Commit**

```bash
git add bot/cogs/warnings.py
git commit -m "feat: add /removewarn command"
```

---

## Task 9: `/removestrike` command

**Files:**
- Modify: `bot/cogs/warnings.py` (add command inside `Warnings` class)

- [ ] **Step 1: Add `/removestrike` inside the `Warnings` class**

```python
    @commands.hybrid_command(name="removestrike", description="[Admin] Remove a specific strike by ID")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        member="The member to remove the strike from",
        strike_id="The strike ID — use /warnings to find it",
    )
    async def removestrike(self, ctx: commands.Context, member: discord.Member, strike_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                """SELECT id, strike_number FROM strikes
                   WHERE id = ? AND guild_id = ? AND user_id = ?""",
                (strike_id, ctx.guild.id, member.id),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return await ctx.send("Strike not found for this member.", ephemeral=True)
            strike_num = row[1]
            await db.execute("DELETE FROM strikes WHERE id = ?", (strike_id,))
            await db.commit()

        log_channel = await self._get_log_channel(ctx.guild)
        if log_channel:
            embed = self._removal_embed(ctx.guild, member, f"Strike #{strike_num} Removed", ctx.author)
            await self._post_embed(log_channel, embed)

        await ctx.send(f"Strike `{strike_id}` removed for {member.mention}.", ephemeral=True)
```

- [ ] **Step 2: Commit**

```bash
git add bot/cogs/warnings.py
git commit -m "feat: add /removestrike command"
```

---

## Task 10: `/clearstrikes` command

**Files:**
- Modify: `bot/cogs/warnings.py` (add command inside `Warnings` class)

- [ ] **Step 1: Add `/clearstrikes` inside the `Warnings` class**

```python
    @commands.hybrid_command(name="clearstrikes", description="[Admin] Clear all warnings and strikes for a member")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="The member to clear")
    async def clearstrikes(self, ctx: commands.Context, member: discord.Member):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, member.id),
            )
            await db.execute(
                "DELETE FROM strikes WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, member.id),
            )
            await db.commit()

        log_channel = await self._get_log_channel(ctx.guild)
        if log_channel:
            embed = self._removal_embed(ctx.guild, member, "All Warnings & Strikes Cleared", ctx.author)
            await self._post_embed(log_channel, embed)

        await ctx.send(f"All warnings and strikes cleared for {member.mention}.", ephemeral=True)
```

- [ ] **Step 2: Commit**

```bash
git add bot/cogs/warnings.py
git commit -m "feat: add /clearstrikes command"
```

---

## Task 11: `/testwarn` command

**Files:**
- Modify: `bot/cogs/warnings.py` (add command inside `Warnings` class)

- [ ] **Step 1: Add `/testwarn` inside the `Warnings` class**

```python
    @commands.hybrid_command(name="testwarn", description="[Admin] Post a fake warn embed to verify setup")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def testwarn(self, ctx: commands.Context):
        log_channel = await self._get_log_channel(ctx.guild)
        if not log_channel:
            return await ctx.send("No warn log channel set. Use `/setwarnlog` first.", ephemeral=True)

        embed = self._warn_embed(
            ctx.guild,
            ctx.author,
            warn_num=1,
            reason="TEST — This is a test warning. No DB changes were made.",
            expires_at=None,
            issued_by=ctx.author,
        )
        embed.title = embed.title.replace("Warning", "TEST Warning")
        embed.description = "This is a **test** triggered by staff. No action has been taken."
        embed.color = discord.Color.orange()

        await self._post_embed(log_channel, embed)
        await ctx.send(f"✅ Test embed posted to {log_channel.mention}.", ephemeral=True)
```

- [ ] **Step 2: Commit**

```bash
git add bot/cogs/warnings.py
git commit -m "feat: add /testwarn command"
```

---

## Task 12: Wire up cog in `main.py`

**Files:**
- Modify: `bot/main.py`

- [ ] **Step 1: Add `"cogs.warnings"` to the `COGS` list in `bot/main.py`**

Find this block:

```python
COGS = [
    "cogs.music",
    "cogs.economy",
    "cogs.moderation",
    "cogs.welcome",
    "cogs.events",
    "cogs.tickets",
    "cogs.youtube",
    "cogs.flightplan",
    "cogs.applications",
    "cogs.security",
]
```

Change it to:

```python
COGS = [
    "cogs.music",
    "cogs.economy",
    "cogs.moderation",
    "cogs.welcome",
    "cogs.events",
    "cogs.tickets",
    "cogs.youtube",
    "cogs.flightplan",
    "cogs.applications",
    "cogs.security",
    "cogs.warnings",
]
```

- [ ] **Step 2: Run all tests one final time**

```bash
pytest -v
```
Expected: All 20 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add bot/main.py
git commit -m "feat: register warnings cog in bot startup"
```

---

## Task 13: Manual verification in Discord

- [ ] Run the bot and confirm `[OK] Loaded: cogs.warnings` appears in startup logs.
- [ ] Run `/setwarnlog #your-log-channel` — confirm ephemeral success message.
- [ ] Run `/testwarn` — confirm test embed appears in the log channel with all four custom emojis.
- [ ] Run `/warn @member Breaking rule X` — confirm Warning #1 embed posts (yellow).
- [ ] Warn the same member twice more — confirm Warning #2, then on the 3rd warn the embed switches to **Strike #1** (orange).
- [ ] Run `/warnings @member` — confirm history shows all warns and the strike with IDs.
- [ ] Run `/removewarn @member <id>` — confirm removal embed posts (green).
- [ ] Run `/removestrike @member <id>` — confirm strike removal embed posts (green).
- [ ] Warn the member to 8 total active warns — confirm Strike #3 embed appears (red) with the "Action Required" field.
- [ ] Run `/clearstrikes @member` — confirm all cleared embed posts, then `/warnings @member` shows empty history.
