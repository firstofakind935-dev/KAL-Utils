import asyncio

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from db.database import DB_PATH


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket 🔒", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        await interaction.response.send_message("Closing ticket in 5 seconds...", ephemeral=False)
        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException:
            pass


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ticket_config (
                    guild_id     INTEGER PRIMARY KEY,
                    category_id  INTEGER,
                    ticket_count INTEGER NOT NULL DEFAULT 0
                )
            """)
            await db.commit()
        self.bot.add_view(CloseTicketView())

    @commands.hybrid_command(name="ticket", description="Open a support ticket")
    @app_commands.describe(reason="The reason for opening a ticket")
    async def ticket(self, ctx: commands.Context, *, reason: str = "No reason provided"):
        guild = ctx.guild
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT category_id, ticket_count FROM ticket_config WHERE guild_id = ?",
                (guild.id,),
            ) as cur:
                row = await cur.fetchone()

        category_id = row[0] if row else None
        ticket_count = (row[1] if row else 0) + 1
        category = guild.get_channel(category_id) if category_id else None

        # Build overwrites: staff (manage_guild) and the ticket author can see; everyone cannot
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        for member in guild.members:
            if member.guild_permissions.manage_guild and not member.bot:
                overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel_name = f"ticket-{ticket_count:04d}"
        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                reason=f"Ticket opened by {ctx.author}",
            )
        except discord.Forbidden:
            return await ctx.send("I don't have permission to create channels.", ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO ticket_config (guild_id, category_id, ticket_count) VALUES (?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET ticket_count = excluded.ticket_count""",
                (guild.id, category_id, ticket_count),
            )
            await db.commit()

        embed = discord.Embed(
            title=f"Ticket #{ticket_count:04d}",
            description=f"**Opened by:** {ctx.author.mention}\n**Reason:** {reason}\n\nSupport staff will be with you shortly.",
            color=discord.Color.green(),
        )
        view = CloseTicketView()
        await ticket_channel.send(embed=embed, view=view)

        if ctx.interaction:
            await ctx.send(f"Ticket created: {ticket_channel.mention}", ephemeral=True)
        else:
            await ctx.send(f"Ticket created: {ticket_channel.mention}")

    @commands.hybrid_command(name="closeticket", description="Close the current ticket channel")
    @commands.has_permissions(manage_channels=True)
    @app_commands.default_permissions(manage_channels=True)
    async def closeticket(self, ctx: commands.Context):
        if not ctx.channel.name.startswith("ticket-"):
            return await ctx.send("This command can only be used in a ticket channel.", ephemeral=True)
        await ctx.send("Closing ticket in 5 seconds...")
        await asyncio.sleep(5)
        try:
            await ctx.channel.delete(reason=f"Ticket closed by {ctx.author}")
        except discord.HTTPException as e:
            await ctx.send(f"Failed to delete channel: {e}")

    @commands.hybrid_command(name="setticketcategory", description="[Admin] Set the category for new ticket channels")
    @app_commands.describe(category="The category where ticket channels will be created")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def setticketcategory(self, ctx: commands.Context, category: discord.CategoryChannel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO ticket_config (guild_id, category_id, ticket_count) VALUES (?, ?, 0)
                   ON CONFLICT(guild_id) DO UPDATE SET category_id = excluded.category_id""",
                (ctx.guild.id, category.id),
            )
            await db.commit()
        await ctx.send(f"Ticket channels will be created under **{category.name}**.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
