from datetime import date

import discord
from discord import app_commands
from discord.ext import commands

from db.database import (
    add_balance,
    get_balance,
    get_last_daily,
    get_leaderboard,
    set_balance,
    set_last_daily,
)

CURRENCY = "🪙"
DAILY_AMOUNT = 100


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="balance", description="Check your or another member's coin balance")
    @app_commands.describe(member="The member to check (leave empty for yourself)")
    async def balance(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        bal = await get_balance(target.id, interaction.guild_id)
        embed = discord.Embed(title=f"{target.display_name}'s Balance", color=discord.Color.gold())
        embed.add_field(name="Balance", value=f"{CURRENCY} **{bal:,}**")
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Claim your daily coin reward")
    async def daily(self, interaction: discord.Interaction):
        today = str(date.today())
        last = await get_last_daily(interaction.user.id, interaction.guild_id)
        if last == today:
            return await interaction.response.send_message(
                "You already claimed your daily reward today. Come back tomorrow!", ephemeral=True
            )
        new_bal = await add_balance(interaction.user.id, interaction.guild_id, DAILY_AMOUNT)
        await set_last_daily(interaction.user.id, interaction.guild_id, today)
        await interaction.response.send_message(
            f"{interaction.user.mention} claimed their daily {CURRENCY} **{DAILY_AMOUNT}**! "
            f"New balance: {CURRENCY} **{new_bal:,}**"
        )

    @app_commands.command(name="transfer", description="Transfer coins to another member")
    @app_commands.describe(member="Who to send coins to", amount="How many coins to send")
    async def transfer(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if member == interaction.user:
            return await interaction.response.send_message("You can't transfer to yourself.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("Amount must be positive.", ephemeral=True)

        sender_bal = await get_balance(interaction.user.id, interaction.guild_id)
        if sender_bal < amount:
            return await interaction.response.send_message(
                f"Insufficient funds. Your balance: {CURRENCY} **{sender_bal:,}**", ephemeral=True
            )

        await add_balance(interaction.user.id, interaction.guild_id, -amount)
        await add_balance(member.id, interaction.guild_id, amount)
        await interaction.response.send_message(
            f"{interaction.user.mention} transferred {CURRENCY} **{amount:,}** to {member.mention}."
        )

    @app_commands.command(name="leaderboard", description="Show the top 10 richest members")
    async def leaderboard(self, interaction: discord.Interaction):
        rows = await get_leaderboard(interaction.guild_id)
        if not rows:
            return await interaction.response.send_message(
                "No balances recorded yet. Use `/daily` to get started!"
            )
        embed = discord.Embed(title="💰 Leaderboard", color=discord.Color.gold())
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for i, (user_id, bal) in enumerate(rows, start=1):
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"Unknown ({user_id})"
            lines.append(f"{medals.get(i, f'`{i}.`')} **{name}** — {CURRENCY} {bal:,}")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="addmoney", description="[Admin] Add coins to a member")
    @app_commands.describe(member="The member to add coins to", amount="How many coins to add")
    @app_commands.default_permissions(administrator=True)
    async def addmoney(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            return await interaction.response.send_message("Amount must be positive.", ephemeral=True)
        new_bal = await add_balance(member.id, interaction.guild_id, amount)
        await interaction.response.send_message(
            f"Added {CURRENCY} **{amount:,}** to {member.mention}. New balance: {CURRENCY} **{new_bal:,}**"
        )

    @app_commands.command(name="removemoney", description="[Admin] Remove coins from a member")
    @app_commands.describe(member="The member to remove coins from", amount="How many coins to remove")
    @app_commands.default_permissions(administrator=True)
    async def removemoney(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            return await interaction.response.send_message("Amount must be positive.", ephemeral=True)
        new_bal = await add_balance(member.id, interaction.guild_id, -amount)
        await interaction.response.send_message(
            f"Removed {CURRENCY} **{amount:,}** from {member.mention}. New balance: {CURRENCY} **{new_bal:,}**"
        )

    @app_commands.command(name="setbalance", description="[Admin] Set a member's balance to an exact amount")
    @app_commands.describe(member="The member to set balance for", amount="The exact amount to set")
    @app_commands.default_permissions(administrator=True)
    async def setbalance(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount < 0:
            return await interaction.response.send_message("Balance cannot be negative.", ephemeral=True)
        await set_balance(member.id, interaction.guild_id, amount)
        await interaction.response.send_message(
            f"Set {member.mention}'s balance to {CURRENCY} **{amount:,}**."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
