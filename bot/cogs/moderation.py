import discord
from discord import app_commands
from discord.ext import commands


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="promote", description="Promote a member by assigning them a role")
    @app_commands.describe(member="The member to promote", role="The role to assign")
    @app_commands.default_permissions(manage_roles=True)
    async def promote(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                "I can't assign a role at or above my highest role.", ephemeral=True
            )
        if role in member.roles:
            return await interaction.response.send_message(
                f"{member.mention} already has **{role.name}**.", ephemeral=True
            )
        await member.add_roles(role, reason=f"Promoted by {interaction.user}")
        embed = discord.Embed(
            title="Promotion",
            description=f"{member.mention} has been promoted to **{role.name}**!",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Promoted by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="demote", description="Demote a member by removing a role from them")
    @app_commands.describe(member="The member to demote", role="The role to remove")
    @app_commands.default_permissions(manage_roles=True)
    async def demote(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                "I can't remove a role at or above my highest role.", ephemeral=True
            )
        if role not in member.roles:
            return await interaction.response.send_message(
                f"{member.mention} doesn't have **{role.name}**.", ephemeral=True
            )
        await member.remove_roles(role, reason=f"Demoted by {interaction.user}")
        embed = discord.Embed(
            title="Demotion",
            description=f"{member.mention} has been demoted from **{role.name}**.",
            color=discord.Color.red(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Demoted by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roles", description="List all assignable server roles")
    async def roles(self, interaction: discord.Interaction):
        assignable = [
            r for r in reversed(interaction.guild.roles)
            if r.name != "@everyone" and r < interaction.guild.me.top_role
        ]
        if not assignable:
            return await interaction.response.send_message("No assignable roles found.")
        embed = discord.Embed(title="Server Roles", color=discord.Color.blurple())
        lines = [f"{r.mention} (`{r.id}`)" for r in assignable[:25]]
        embed.description = "\n".join(lines)
        if len(assignable) > 25:
            embed.set_footer(text=f"... and {len(assignable) - 25} more")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
