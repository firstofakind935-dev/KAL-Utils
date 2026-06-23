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
