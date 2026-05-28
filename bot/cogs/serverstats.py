import aiosqlite
import discord
from discord.ext import commands, tasks

from db.database import DB_PATH


class ServerStats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS serverstats (
                    guild_id          INTEGER PRIMARY KEY,
                    members_channel_id INTEGER NOT NULL,
                    bots_channel_id   INTEGER NOT NULL
                )
            """)
            await db.commit()
        self.update_stats.start()

    def cog_unload(self):
        self.update_stats.cancel()

    @tasks.loop(minutes=15)
    async def update_stats(self):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT guild_id, members_channel_id, bots_channel_id FROM serverstats"
            ) as cur:
                rows = await cur.fetchall()

        for guild_id, members_ch_id, bots_ch_id in rows:
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            members_count = sum(1 for m in guild.members if not m.bot)
            bots_count = sum(1 for m in guild.members if m.bot)
            members_channel = guild.get_channel(members_ch_id)
            bots_channel = guild.get_channel(bots_ch_id)
            if members_channel:
                try:
                    await members_channel.edit(name=f"👥 Members: {members_count}")
                except discord.HTTPException:
                    pass
            if bots_channel:
                try:
                    await bots_channel.edit(name=f"🤖 Bots: {bots_count}")
                except discord.HTTPException:
                    pass

    @update_stats.before_loop
    async def before_update_stats(self):
        await self.bot.wait_until_ready()

    @commands.hybrid_command(name="setupstats", description="Create a server stats category with live member/bot counts")
    @commands.has_permissions(manage_guild=True)
    async def setupstats(self, ctx: commands.Context):
        guild = ctx.guild
        members_count = sum(1 for m in guild.members if not m.bot)
        bots_count = sum(1 for m in guild.members if m.bot)

        # View-only overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                connect=False, view_channel=True
            )
        }

        try:
            category = await guild.create_category("📊 Server Stats", overwrites=overwrites)
            members_channel = await guild.create_voice_channel(
                f"👥 Members: {members_count}",
                category=category,
                overwrites=overwrites,
            )
            bots_channel = await guild.create_voice_channel(
                f"🤖 Bots: {bots_count}",
                category=category,
                overwrites=overwrites,
            )
        except discord.Forbidden:
            return await ctx.send("I don't have permission to create channels.", ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO serverstats (guild_id, members_channel_id, bots_channel_id) VALUES (?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                       members_channel_id = excluded.members_channel_id,
                       bots_channel_id    = excluded.bots_channel_id""",
                (guild.id, members_channel.id, bots_channel.id),
            )
            await db.commit()

        await ctx.send("Server stats channels created! They will update every 15 minutes.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerStats(bot))
