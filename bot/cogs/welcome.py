import os

import discord
from discord.ext import commands


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

        embed = discord.Embed(
            title=f"Welcome to {member.guild.name}!",
            description=(
                f"Hey {member.mention}, we're glad you're here!\n"
                f"You're member **#{member.guild.member_count}**."
            ),
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if member.joined_at:
            embed.set_footer(text=f"Joined {member.joined_at.strftime('%B %d, %Y')}")
        await channel.send(embed=embed)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setwelcome(self, ctx: commands.Context):
        """Show instructions for setting the welcome channel."""
        await ctx.send(
            f"Add this to your `.env` and restart the bot:\n"
            f"```\nWELCOME_CHANNEL_ID={ctx.channel.id}\n```"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
