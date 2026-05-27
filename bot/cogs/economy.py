from datetime import date

import discord
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

    @commands.command(aliases=["bal"])
    async def balance(self, ctx: commands.Context, member: discord.Member = None):
        """Check your balance (or another member's)."""
        target = member or ctx.author
        bal = await get_balance(target.id, ctx.guild.id)
        embed = discord.Embed(
            title=f"{target.display_name}'s Balance",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Balance", value=f"{CURRENCY} **{bal:,}**")
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command()
    async def daily(self, ctx: commands.Context):
        """Claim your daily coin reward."""
        today = str(date.today())
        last = await get_last_daily(ctx.author.id, ctx.guild.id)
        if last == today:
            return await ctx.send(
                "You already claimed your daily reward today. Come back tomorrow!"
            )
        new_bal = await add_balance(ctx.author.id, ctx.guild.id, DAILY_AMOUNT)
        await set_last_daily(ctx.author.id, ctx.guild.id, today)
        await ctx.send(
            f"{ctx.author.mention} claimed their daily {CURRENCY} **{DAILY_AMOUNT}**! "
            f"New balance: {CURRENCY} **{new_bal:,}**"
        )

    @commands.command()
    async def transfer(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Transfer coins to another member."""
        if member == ctx.author:
            return await ctx.send("You can't transfer to yourself.")
        if amount <= 0:
            return await ctx.send("Amount must be a positive number.")

        sender_bal = await get_balance(ctx.author.id, ctx.guild.id)
        if sender_bal < amount:
            return await ctx.send(
                f"Insufficient funds. Your balance: {CURRENCY} **{sender_bal:,}**"
            )

        await add_balance(ctx.author.id, ctx.guild.id, -amount)
        await add_balance(member.id, ctx.guild.id, amount)
        await ctx.send(
            f"{ctx.author.mention} transferred {CURRENCY} **{amount:,}** to {member.mention}."
        )

    @commands.command(aliases=["lb"])
    async def leaderboard(self, ctx: commands.Context):
        """Show the top 10 richest members."""
        rows = await get_leaderboard(ctx.guild.id)
        if not rows:
            return await ctx.send("No balances recorded yet. Use `!daily` to get started!")

        embed = discord.Embed(title="💰 Leaderboard", color=discord.Color.gold())
        lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, (user_id, bal) in enumerate(rows, start=1):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"Unknown ({user_id})"
            prefix = medals.get(i, f"`{i}.`")
            lines.append(f"{prefix} **{name}** — {CURRENCY} {bal:,}")
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def addmoney(self, ctx: commands.Context, member: discord.Member, amount: int):
        """[Admin] Add coins to a member."""
        if amount <= 0:
            return await ctx.send("Amount must be positive.")
        new_bal = await add_balance(member.id, ctx.guild.id, amount)
        await ctx.send(
            f"Added {CURRENCY} **{amount:,}** to {member.mention}. New balance: {CURRENCY} **{new_bal:,}**"
        )

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def removemoney(self, ctx: commands.Context, member: discord.Member, amount: int):
        """[Admin] Remove coins from a member."""
        if amount <= 0:
            return await ctx.send("Amount must be positive.")
        new_bal = await add_balance(member.id, ctx.guild.id, -amount)
        await ctx.send(
            f"Removed {CURRENCY} **{amount:,}** from {member.mention}. New balance: {CURRENCY} **{new_bal:,}**"
        )

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setbalance(self, ctx: commands.Context, member: discord.Member, amount: int):
        """[Admin] Set a member's balance to an exact amount."""
        if amount < 0:
            return await ctx.send("Balance cannot be negative.")
        await set_balance(member.id, ctx.guild.id, amount)
        await ctx.send(f"Set {member.mention}'s balance to {CURRENCY} **{amount:,}**.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
