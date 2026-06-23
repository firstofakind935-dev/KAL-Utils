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
