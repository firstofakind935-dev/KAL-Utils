import os

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from db.database import DB_PATH

BANNER_URL = os.getenv(
    "BANNER_URL",
    "https://i.imgur.com/iNl6RZG.png"
)


def ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS welcome_config (
                    guild_id INTEGER PRIMARY KEY,
                    welcome_channel_id INTEGER,
                    helpdesk_channel_id INTEGER
                )
            """)
            await db.commit()

    async def get_config(self, guild_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT welcome_channel_id, helpdesk_channel_id FROM welcome_config WHERE guild_id = ?",
                (guild_id,)
            ) as cur:
                return await cur.fetchone()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = await self.get_config(member.guild.id)
        if not config or not config[0]:
            return

        welcome_channel_id, helpdesk_channel_id = config
        channel = member.guild.get_channel(welcome_channel_id)
        if not channel:
            return

        helpdesk = member.guild.get_channel(helpdesk_channel_id) if helpdesk_channel_id else None
        helpdesk_mention = helpdesk.mention if helpdesk else "#helpdesk"
        member_number = ordinal(member.guild.member_count)

        embed = discord.Embed(
            title="Korean Air Virtual Airlines • PTFS ATC24 ✈️",
            description=(
                f"환영합니다 **Welcome Aboard,**\n\n"
                f"We're pleased to have you here.\n\n"
                f"If you require any assistance, feel free to reach out at any time at "
                f"{helpdesk_mention}."
            ),
            color=discord.Color(0x00A4E4),
        )
        embed.set_image(url=BANNER_URL)

        await channel.send(
            f"Welcome to **Korean Air PTFS 대한항공** {member.mention}, "
            f"you are our **{member_number}** member!",
            embed=embed,
        )

    @commands.hybrid_command(name="setwelcome", description="Set the welcome channel for this server")
    @app_commands.describe(channel="The channel to send welcome messages in")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def setwelcome(self, ctx: commands.Context, channel: discord.TextChannel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO welcome_config (guild_id, welcome_channel_id)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET welcome_channel_id = ?
            """, (ctx.guild.id, channel.id, channel.id))
            await db.commit()
        await ctx.send(f"Welcome channel set to {channel.mention}.", ephemeral=True)

    @commands.hybrid_command(name="sethelpdesk", description="Set the helpdesk channel for this server")
    @app_commands.describe(channel="The helpdesk channel to link to in welcome messages")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def sethelpdesk(self, ctx: commands.Context, channel: discord.TextChannel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO welcome_config (guild_id, helpdesk_channel_id)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET helpdesk_channel_id = ?
            """, (ctx.guild.id, channel.id, channel.id))
            await db.commit()
        await ctx.send(f"Helpdesk channel set to {channel.mention}.", ephemeral=True)

    @commands.hybrid_command(name="testwelcome", description="Test the welcome message")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def testwelcome(self, ctx: commands.Context):
        """Send a test welcome message for the current user."""
        await self.on_member_join(ctx.author)
        await ctx.send("Test welcome sent!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
