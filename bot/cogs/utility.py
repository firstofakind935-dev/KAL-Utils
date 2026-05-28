import discord
from discord import app_commands
from discord.ext import commands


class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="quote", description="Quote a message by its ID")
    @app_commands.describe(message_id="The ID of the message to quote")
    async def quote(self, ctx: commands.Context, message_id: str):
        try:
            msg_id = int(message_id)
        except ValueError:
            return await ctx.send("Invalid message ID.", ephemeral=True)

        message = None
        for channel in ctx.guild.text_channels:
            try:
                message = await channel.fetch_message(msg_id)
                break
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

        if message is None:
            return await ctx.send("Message not found.", ephemeral=True)

        embed = discord.Embed(
            description=message.content or "*No text content*",
            color=discord.Color.blurple(),
            timestamp=message.created_at,
        )
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url,
        )
        embed.add_field(name="Jump to Message", value=f"[Click here]({message.jump_url})", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="serverinfo", description="Show information about this server")
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        embed = discord.Embed(
            title=guild.name,
            color=discord.Color.blurple(),
            timestamp=guild.created_at,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        owner = guild.owner
        embed.add_field(name="Owner", value=owner.mention if owner else "Unknown", inline=True)
        embed.add_field(name="Members", value=f"{guild.member_count:,}", inline=True)
        embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, style="D"), inline=True)
        embed.set_footer(text=f"Guild ID: {guild.id}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="userinfo", description="Show information about a member")
    @app_commands.describe(member="The member to look up (leave empty for yourself)")
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        roles = [r.mention for r in reversed(target.roles) if r != ctx.guild.default_role]

        embed = discord.Embed(
            title=str(target),
            color=target.color if target.color.value else discord.Color.blurple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="ID", value=str(target.id), inline=True)
        embed.add_field(
            name="Nickname",
            value=target.nick if target.nick else "None",
            inline=True,
        )
        embed.add_field(
            name="Joined Server",
            value=discord.utils.format_dt(target.joined_at, style="D") if target.joined_at else "Unknown",
            inline=True,
        )
        embed.add_field(
            name="Account Created",
            value=discord.utils.format_dt(target.created_at, style="D"),
            inline=True,
        )
        embed.add_field(
            name=f"Roles ({len(roles)})",
            value=" ".join(roles[:20]) if roles else "None",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
