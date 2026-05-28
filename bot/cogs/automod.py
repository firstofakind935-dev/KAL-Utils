import re
import time
from collections import defaultdict

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from db.database import DB_PATH

# URL regex pattern
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Spam tracking: {(guild_id, user_id): [timestamps]}
        self._spam_tracker: dict[tuple[int, int], list[float]] = defaultdict(list)

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS automod (
                    guild_id    INTEGER PRIMARY KEY,
                    anti_spam   INTEGER NOT NULL DEFAULT 0,
                    anti_links  INTEGER NOT NULL DEFAULT 0,
                    anti_caps   INTEGER NOT NULL DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS automod_badwords (
                    guild_id INTEGER NOT NULL,
                    word     TEXT NOT NULL,
                    PRIMARY KEY (guild_id, word)
                )
            """)
            await db.commit()

    async def _get_settings(self, guild_id: int) -> tuple[int, int, int]:
        """Returns (anti_spam, anti_links, anti_caps)."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT anti_spam, anti_links, anti_caps FROM automod WHERE guild_id = ?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        return row if row else (0, 0, 0)

    async def _get_badwords(self, guild_id: int) -> list[str]:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT word FROM automod_badwords WHERE guild_id = ?",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [r[0] for r in rows]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_guild:
            return

        guild_id = message.guild.id
        anti_spam, anti_links, anti_caps = await self._get_settings(guild_id)
        content = message.content

        # Anti-spam: 5 messages in 5 seconds
        if anti_spam:
            key = (guild_id, message.author.id)
            now = time.monotonic()
            timestamps = self._spam_tracker[key]
            timestamps.append(now)
            # Keep only messages within the last 5 seconds
            self._spam_tracker[key] = [t for t in timestamps if now - t <= 5]
            if len(self._spam_tracker[key]) > 5:
                try:
                    await message.delete()
                    await message.channel.send(
                        f"{message.author.mention} Slow down! You're sending messages too fast.",
                        delete_after=5,
                    )
                except discord.HTTPException:
                    pass
                return

        # Anti-links
        if anti_links and _URL_RE.search(content):
            try:
                await message.delete()
                await message.channel.send(
                    f"{message.author.mention} Links are not allowed in this server.",
                    delete_after=5,
                )
            except discord.HTTPException:
                pass
            return

        # Anti-caps: 70%+ caps in messages longer than 10 chars
        if anti_caps and len(content) > 10:
            letters = [c for c in content if c.isalpha()]
            if letters and sum(1 for c in letters if c.isupper()) / len(letters) >= 0.70:
                try:
                    await message.delete()
                    await message.channel.send(
                        f"{message.author.mention} Please avoid using excessive caps.",
                        delete_after=5,
                    )
                except discord.HTTPException:
                    pass
                return

        # Bad word filter
        badwords = await self._get_badwords(guild_id)
        if badwords:
            lower_content = content.lower()
            for word in badwords:
                if word.lower() in lower_content:
                    try:
                        await message.delete()
                        await message.channel.send(
                            f"{message.author.mention} Your message contained a prohibited word.",
                            delete_after=5,
                        )
                    except discord.HTTPException:
                        pass
                    return

    # ── Toggle commands ────────────────────────────────────────────────────────

    @commands.hybrid_command(name="automodspam", description="[Admin] Toggle anti-spam filter (5 msgs in 5s)")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def automodspam(self, ctx: commands.Context):
        anti_spam, anti_links, anti_caps = await self._get_settings(ctx.guild.id)
        new_val = 0 if anti_spam else 1
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO automod (guild_id, anti_spam, anti_links, anti_caps) VALUES (?, ?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET anti_spam = excluded.anti_spam""",
                (ctx.guild.id, new_val, anti_links, anti_caps),
            )
            await db.commit()
        state = "enabled" if new_val else "disabled"
        await ctx.send(f"Anti-spam filter **{state}**.")

    @commands.hybrid_command(name="automodlinks", description="[Admin] Toggle block links filter")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def automodlinks(self, ctx: commands.Context):
        anti_spam, anti_links, anti_caps = await self._get_settings(ctx.guild.id)
        new_val = 0 if anti_links else 1
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO automod (guild_id, anti_spam, anti_links, anti_caps) VALUES (?, ?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET anti_links = excluded.anti_links""",
                (ctx.guild.id, anti_spam, new_val, anti_caps),
            )
            await db.commit()
        state = "enabled" if new_val else "disabled"
        await ctx.send(f"Block links filter **{state}**.")

    @commands.hybrid_command(name="automodcaps", description="[Admin] Toggle block 70%+ caps filter")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def automodcaps(self, ctx: commands.Context):
        anti_spam, anti_links, anti_caps = await self._get_settings(ctx.guild.id)
        new_val = 0 if anti_caps else 1
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO automod (guild_id, anti_spam, anti_links, anti_caps) VALUES (?, ?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET anti_caps = excluded.anti_caps""",
                (ctx.guild.id, anti_spam, anti_links, new_val),
            )
            await db.commit()
        state = "enabled" if new_val else "disabled"
        await ctx.send(f"Anti-caps filter **{state}**.")

    # ── Bad word commands ──────────────────────────────────────────────────────

    @commands.hybrid_command(name="automodaddword", description="[Admin] Add a word to the bad word filter")
    @app_commands.describe(word="The word to add to the filter")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def automodaddword(self, ctx: commands.Context, word: str):
        word = word.lower().strip()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO automod_badwords (guild_id, word) VALUES (?, ?)",
                (ctx.guild.id, word),
            )
            await db.commit()
        await ctx.send(f"Added `{word}` to the bad word filter.")

    @commands.hybrid_command(name="automodremoveword", description="[Admin] Remove a word from the bad word filter")
    @app_commands.describe(word="The word to remove from the filter")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def automodremoveword(self, ctx: commands.Context, word: str):
        word = word.lower().strip()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM automod_badwords WHERE guild_id = ? AND word = ?",
                (ctx.guild.id, word),
            )
            await db.commit()
        await ctx.send(f"Removed `{word}` from the bad word filter.")

    # ── Status command ─────────────────────────────────────────────────────────

    @commands.hybrid_command(name="automodstatus", description="[Admin] Show current AutoMod settings")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def automodstatus(self, ctx: commands.Context):
        anti_spam, anti_links, anti_caps = await self._get_settings(ctx.guild.id)
        badwords = await self._get_badwords(ctx.guild.id)

        def toggle(val: int) -> str:
            return "✅ Enabled" if val else "❌ Disabled"

        embed = discord.Embed(title="AutoMod Settings", color=discord.Color.orange())
        embed.add_field(name="Anti-Spam (5 msgs/5s)", value=toggle(anti_spam), inline=True)
        embed.add_field(name="Block Links", value=toggle(anti_links), inline=True)
        embed.add_field(name="Anti-Caps (70%+)", value=toggle(anti_caps), inline=True)
        embed.add_field(
            name=f"Bad Words ({len(badwords)})",
            value=", ".join(f"`{w}`" for w in badwords) if badwords else "None",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
