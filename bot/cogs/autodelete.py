import asyncio

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from db.database import DB_PATH


class AutoDelete(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {(guild_id, channel_id): delay_seconds}
        self._cache: dict[tuple[int, int], int] = {}

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS autodelete (
                    guild_id   INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    delay      INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, channel_id)
                )
            """)
            await db.commit()

            async with db.execute("SELECT guild_id, channel_id, delay FROM autodelete") as cur:
                rows = await cur.fetchall()
        for guild_id, channel_id, delay in rows:
            self._cache[(guild_id, channel_id)] = delay

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        key = (message.guild.id, message.channel.id)
        delay = self._cache.get(key)
        if delay is None:
            return

        async def _delete_later():
            await asyncio.sleep(delay)
            try:
                await message.delete()
            except discord.HTTPException:
                pass

        asyncio.create_task(_delete_later())

    @commands.hybrid_command(name="autodelete", description="Auto-delete messages in a channel after X seconds")
    @app_commands.describe(
        channel="The channel to enable auto-delete in",
        seconds="Seconds before messages are deleted (minimum 5)",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def autodelete(self, ctx: commands.Context, channel: discord.TextChannel, seconds: int):
        if seconds < 5:
            return await ctx.send("Minimum delay is 5 seconds.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO autodelete (guild_id, channel_id, delay) VALUES (?, ?, ?)
                   ON CONFLICT(guild_id, channel_id) DO UPDATE SET delay = excluded.delay""",
                (ctx.guild.id, channel.id, seconds),
            )
            await db.commit()
        self._cache[(ctx.guild.id, channel.id)] = seconds
        await ctx.send(f"Messages in {channel.mention} will be deleted after **{seconds}** seconds.")

    @commands.hybrid_command(name="autodeleteoff", description="Disable auto-delete in a channel")
    @app_commands.describe(channel="The channel to disable auto-delete in")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def autodeleteoff(self, ctx: commands.Context, channel: discord.TextChannel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM autodelete WHERE guild_id = ? AND channel_id = ?",
                (ctx.guild.id, channel.id),
            )
            await db.commit()
        self._cache.pop((ctx.guild.id, channel.id), None)
        await ctx.send(f"Auto-delete disabled in {channel.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoDelete(bot))
