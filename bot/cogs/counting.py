import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from db.database import DB_PATH


class Counting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS counting (
                    guild_id     INTEGER PRIMARY KEY,
                    channel_id   INTEGER NOT NULL,
                    count        INTEGER NOT NULL DEFAULT 0,
                    last_user_id INTEGER
                )
            """)
            await db.commit()

    async def _get_config(self, guild_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT channel_id, count, last_user_id FROM counting WHERE guild_id = ?",
                (guild_id,),
            ) as cur:
                return await cur.fetchone()

    async def _reset_count(self, guild_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE counting SET count = 0, last_user_id = NULL WHERE guild_id = ?",
                (guild_id,),
            )
            await db.commit()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        row = await self._get_config(message.guild.id)
        if not row:
            return

        channel_id, count, last_user_id = row
        if message.channel.id != channel_id:
            return

        # Delete non-number messages silently
        try:
            number = int(message.content.strip())
        except ValueError:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return

        expected = count + 1
        wrong = number != expected or message.author.id == last_user_id

        if wrong:
            try:
                await message.add_reaction("❌")
            except discord.HTTPException:
                pass
            await self._reset_count(message.guild.id)
            reason = (
                "You can't count twice in a row!"
                if message.author.id == last_user_id
                else f"Wrong number! The count resets to 0. Next number is **1**."
            )
            await message.channel.send(reason, delete_after=5)
        else:
            try:
                await message.add_reaction("✅")
            except discord.HTTPException:
                pass
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE counting SET count = ?, last_user_id = ? WHERE guild_id = ?",
                    (number, message.author.id, message.guild.id),
                )
                await db.commit()

    @commands.hybrid_command(name="setcounting", description="[Admin] Set the counting channel")
    @app_commands.describe(channel="The channel to use for counting")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def setcounting(self, ctx: commands.Context, channel: discord.TextChannel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO counting (guild_id, channel_id, count, last_user_id) VALUES (?, ?, 0, NULL)
                   ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id""",
                (ctx.guild.id, channel.id),
            )
            await db.commit()
        await ctx.send(f"Counting channel set to {channel.mention}. Start counting from **1**!")

    @commands.hybrid_command(name="countingreset", description="[Admin] Reset the counting channel count to 0")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def countingreset(self, ctx: commands.Context):
        row = await self._get_config(ctx.guild.id)
        if not row:
            return await ctx.send("No counting channel configured. Use `/setcounting` first.")
        await self._reset_count(ctx.guild.id)
        await ctx.send("Count reset to **0**. Next number is **1**.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Counting(bot))
