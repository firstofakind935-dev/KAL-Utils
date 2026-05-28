import os

import discord
from discord import app_commands
from discord.ext import commands

VERIFY_CHANNEL_ID = 1485862684300935319
HELPDESK_CHANNEL_ID = 1499251791689416705
BANNER_URL = os.getenv(
    "BANNER_URL",
    "https://media.discordapp.net/attachments/1402619298618540093/1505494648830038036/"
    "file_00000000dcb47206bb98e9594c22843f.png?format=webp&quality=lossless"
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
        raw = os.getenv("WELCOME_CHANNEL_ID", "")
        self.channel_id: int | None = int(raw) if raw.isdigit() else None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not self.channel_id:
            return
        channel = member.guild.get_channel(self.channel_id)
        if not channel:
            return

        verify = member.guild.get_channel(VERIFY_CHANNEL_ID)
        helpdesk = member.guild.get_channel(HELPDESK_CHANNEL_ID)
        verify_mention = verify.mention if verify else "#verify-here"
        helpdesk_mention = helpdesk.mention if helpdesk else "#helpdesk"

        member_number = ordinal(member.guild.member_count)

        embed = discord.Embed(
            title="Korean Air Virtual Airlines • PTFS ATC24 ✈️",
            description=(
                f"환영합니다 **Welcome Aboard,**\n\n"
                f"We're pleased to have you here. Kindly proceed to "
                f"{verify_mention} to complete your verification and gain full access.\n\n"
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

    @commands.hybrid_command(name="setwelcome", description="Show instructions to set the welcome channel")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def setwelcome(self, ctx: commands.Context):
        """Show welcome channel setup instructions."""
        await ctx.send(
            f"Add this to your `.env` and restart the bot:\n"
            f"```\nWELCOME_CHANNEL_ID={ctx.channel.id}\n```",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
