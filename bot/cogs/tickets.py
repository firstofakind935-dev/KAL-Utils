import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from db.database import DB_PATH


class TicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open a Ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="ticket:open",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT channel_id FROM tickets WHERE guild_id = ? AND user_id = ? AND closed = 0",
                (guild.id, user.id),
            ) as cur:
                existing = await cur.fetchone()

        if existing:
            ch = guild.get_channel(existing[0])
            if ch:
                return await interaction.response.send_message(
                    f"You already have an open ticket: {ch.mention}", ephemeral=True
                )

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT support_role_id FROM ticket_config WHERE guild_id = ?",
                (guild.id,),
            ) as cur:
                config = await cur.fetchone()

        support_role = guild.get_role(config[0]) if config and config[0] else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        channel = await guild.create_text_channel(
            f"ticket-{user.name}",
            overwrites=overwrites,
            topic=f"Support ticket for {user} ({user.id})",
        )

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO tickets (guild_id, user_id, channel_id) VALUES (?, ?, ?)",
                (guild.id, user.id, channel.id),
            )
            await db.commit()

        embed = discord.Embed(
            title="🎫 Support Ticket",
            description=(
                f"Welcome {user.mention}! Please describe your issue and a staff member will assist you shortly.\n\n"
                f"To close this ticket, use `/closeticket`."
            ),
            color=discord.Color(0x00A4E4),
        )
        close_view = CloseTicketView()
        await channel.send(embed=embed, view=close_view)
        if support_role:
            await channel.send(support_role.mention, delete_after=3)

        await interaction.response.send_message(f"Ticket opened: {channel.mention}", ephemeral=True)


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="ticket:close",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await close_ticket_channel(interaction.channel, interaction.user)


async def close_ticket_channel(channel: discord.TextChannel, closer: discord.User):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM tickets WHERE channel_id = ? AND closed = 0",
            (channel.id,),
        ) as cur:
            row = await cur.fetchone()

    if not row:
        return

    embed = discord.Embed(
        description=f"🔒 Ticket closed by {closer.mention}.",
        color=discord.Color.red(),
    )
    await channel.send(embed=embed)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET closed = 1 WHERE channel_id = ?",
            (channel.id,),
        )
        await db.commit()

    await channel.delete(reason=f"Ticket closed by {closer}")


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ticket_config (
                    guild_id        INTEGER PRIMARY KEY,
                    support_role_id INTEGER
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id   INTEGER NOT NULL,
                    user_id    INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    closed     INTEGER NOT NULL DEFAULT 0
                )
            """)
            await db.commit()

        self.bot.add_view(TicketButton())
        self.bot.add_view(CloseTicketView())

    @commands.hybrid_command(name="settickets", description="Post a ticket panel in a channel")
    @app_commands.describe(
        channel="Channel to post the ticket panel in",
        support_role="Role to ping and grant access to tickets",
    )
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def settickets(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        support_role: discord.Role = None,
    ):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO ticket_config (guild_id, support_role_id)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET support_role_id = excluded.support_role_id
            """, (ctx.guild.id, support_role.id if support_role else None))
            await db.commit()

        embed = discord.Embed(
            title="🎫 Korean Air Support",
            description="Need help? Click the button below to open a private support ticket.",
            color=discord.Color(0x00A4E4),
        )
        await channel.send(embed=embed, view=TicketButton())
        await ctx.send(f"Ticket panel posted in {channel.mention}.", ephemeral=True)

    @commands.hybrid_command(name="closeticket", description="Close the current support ticket")
    async def closeticket(self, ctx: commands.Context):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_id FROM tickets WHERE channel_id = ? AND closed = 0",
                (ctx.channel.id,),
            ) as cur:
                row = await cur.fetchone()

        if not row:
            return await ctx.send("This is not an open ticket channel.", ephemeral=True)

        await ctx.send("Closing ticket...")
        await close_ticket_channel(ctx.channel, ctx.author)

    @commands.hybrid_command(name="addtoticket", description="Add a user to the current ticket")
    @app_commands.describe(user="User to add to this ticket")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def addtoticket(self, ctx: commands.Context, user: discord.Member):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id FROM tickets WHERE channel_id = ? AND closed = 0",
                (ctx.channel.id,),
            ) as cur:
                row = await cur.fetchone()

        if not row:
            return await ctx.send("This is not an open ticket channel.", ephemeral=True)

        await ctx.channel.set_permissions(user, view_channel=True, send_messages=True)
        await ctx.send(f"Added {user.mention} to the ticket.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
