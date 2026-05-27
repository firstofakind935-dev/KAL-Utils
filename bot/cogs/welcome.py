import os

import discord
from discord import app_commands
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

    @app_commands.command(name="setwelcome", description="Show instructions to set the welcome channel")
    @app_commands.default_permissions(administrator=True)
    async def setwelcome(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Add this to your `.env` and restart the bot:\n"
            f"```\nWELCOME_CHANNEL_ID={interaction.channel_id}\n```",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
