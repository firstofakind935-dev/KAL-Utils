import random
import time

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from db.database import DB_PATH


def xp_to_level(xp: int) -> int:
    return int((xp ** 0.5) / 7)


def level_to_xp(level: int) -> int:
    return (level * 7) ** 2


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {(user_id, guild_id): last_message_timestamp}
        self._cooldowns: dict[tuple[int, int], float] = {}

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS leveling (
                    user_id  INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    xp       INTEGER NOT NULL DEFAULT 0,
                    level    INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS level_config (
                    guild_id   INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL
                )
            """)
            await db.commit()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        key = (message.author.id, message.guild.id)
        now = time.monotonic()
        if now - self._cooldowns.get(key, 0) < 60:
            return
        self._cooldowns[key] = now

        xp_gain = random.randint(15, 25)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO leveling (user_id, guild_id, xp, level)
                   VALUES (?, ?, ?, 0)
                   ON CONFLICT(user_id, guild_id) DO UPDATE SET xp = xp + excluded.xp""",
                (message.author.id, message.guild.id, xp_gain),
            )
            await db.commit()

            async with db.execute(
                "SELECT xp, level FROM leveling WHERE user_id = ? AND guild_id = ?",
                (message.author.id, message.guild.id),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return
            xp, old_level = row
            new_level = xp_to_level(xp)

            if new_level > old_level:
                await db.execute(
                    "UPDATE leveling SET level = ? WHERE user_id = ? AND guild_id = ?",
                    (new_level, message.author.id, message.guild.id),
                )
                await db.commit()

                async with db.execute(
                    "SELECT channel_id FROM level_config WHERE guild_id = ?",
                    (message.guild.id,),
                ) as cur:
                    cfg = await cur.fetchone()

            else:
                return

        channel = None
        if cfg:
            channel = message.guild.get_channel(cfg[0])
        if channel is None:
            channel = message.channel

        embed = discord.Embed(
            title="Level Up!",
            description=f"{message.author.mention} reached **Level {new_level}**!",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=message.author.display_avatar.url)
        await channel.send(embed=embed)

    @commands.hybrid_command(name="rank", description="Show your or another member's level and XP")
    @app_commands.describe(member="The member to check (leave empty for yourself)")
    async def rank(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT xp, level FROM leveling WHERE user_id = ? AND guild_id = ?",
                (target.id, ctx.guild.id),
            ) as cur:
                row = await cur.fetchone()

        xp, level = (row[0], row[1]) if row else (0, 0)
        current_level_xp = level_to_xp(level)
        next_level_xp = level_to_xp(level + 1)
        progress = xp - current_level_xp
        needed = next_level_xp - current_level_xp
        bar_filled = int((progress / needed) * 20) if needed > 0 else 20
        bar = "█" * bar_filled + "░" * (20 - bar_filled)

        embed = discord.Embed(title=f"{target.display_name}'s Rank", color=discord.Color.blurple())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Level", value=str(level), inline=True)
        embed.add_field(name="Total XP", value=f"{xp:,}", inline=True)
        embed.add_field(
            name=f"Progress to Level {level + 1}",
            value=f"`{bar}` {progress:,}/{needed:,} XP",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="xpleaderboard", description="Show the top 10 members by XP")
    async def xpleaderboard(self, ctx: commands.Context):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_id, xp, level FROM leveling WHERE guild_id = ? ORDER BY xp DESC LIMIT 10",
                (ctx.guild.id,),
            ) as cur:
                rows = await cur.fetchall()

        if not rows:
            return await ctx.send("No XP recorded yet. Start chatting to earn XP!")

        embed = discord.Embed(title="XP Leaderboard", color=discord.Color.blurple())
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for i, (user_id, xp, level) in enumerate(rows, start=1):
            m = ctx.guild.get_member(user_id)
            name = m.display_name if m else f"Unknown ({user_id})"
            prefix = medals.get(i, f"`{i}.`")
            lines.append(f"{prefix} **{name}** — Level {level} | {xp:,} XP")
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="setlevelchannel", description="[Admin] Set the level-up notification channel")
    @app_commands.describe(channel="The channel to send level-up notifications to")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def setlevelchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO level_config (guild_id, channel_id) VALUES (?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id""",
                (ctx.guild.id, channel.id),
            )
            await db.commit()
        await ctx.send(f"Level-up notifications will be sent to {channel.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
