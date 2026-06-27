from datetime import datetime, timedelta, timezone
from typing import Optional, Union

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks

AnyVoiceChannel = Union[discord.VoiceChannel, discord.StageChannel]

from db.database import DB_PATH

GATE_ANNOUNCE_MINUTES = 60   # gate is always revealed exactly 60 min before

FORMATS = [
    "%d/%m/%Y %H:%M",
    "%d/%m/%y %H:%M",
    "%d/%m %H:%M",
    "%d-%m-%Y %H:%M",
    "%Y-%m-%d %H:%M",
]


def parse_when(when: str) -> datetime:
    """Try multiple date/time formats. Assumes current year if year is omitted."""
    when = when.strip()
    for fmt in FORMATS:
        try:
            dt = datetime.strptime(when, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now(timezone.utc).year)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Could not parse: {when}")


class CreateEventModal(discord.ui.Modal, title="✈️ Create New Flight Event"):
    event_name = discord.ui.TextInput(
        label="Flight Name",
        placeholder="e.g. KE3348",
        max_length=100,
    )
    when = discord.ui.TextInput(
        label="Date & Time (UTC)",
        placeholder="e.g. 25/12/2026 20:00  or  2026-12-25 20:00",
        max_length=25,
    )
    gate_input = discord.ui.TextInput(
        label="In-Game Gate (revealed 60 min before)",
        placeholder="e.g. Terminal 1, Gate B3",
        required=False,
        max_length=100,
    )
    route_details = discord.ui.TextInput(
        label="Route & Details",
        placeholder="ICN → LAX | 10h 30m | First · Prestige · Economy",
        required=False,
        max_length=300,
        style=discord.TextStyle.short,
    )
    server_link = discord.ui.TextInput(
        label="Server Link (sent at departure)",
        placeholder="https://www.roblox.com/share?code=...",
        required=False,
        max_length=500,
    )

    def __init__(self, channel: AnyVoiceChannel, duration: int):
        super().__init__()
        self.channel = channel
        self.duration = duration

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            start = parse_when(self.when.value)
        except ValueError:
            return await interaction.followup.send(
                'Invalid date/time. Examples: `25/12 20:00` · `25/12/2026 20:00` · `2026-12-25 20:00`',
                ephemeral=True,
            )

        if start < datetime.now(timezone.utc):
            return await interaction.followup.send("Start time must be in the future.", ephemeral=True)

        end = start + timedelta(minutes=self.duration)

        gate_text = self.gate_input.value.strip() or None

        # Parse "ICN → LAX | 10h 30m | First · Prestige · Economy"
        departure = arrival = flight_time = cabin_classes = None
        if self.route_details.value.strip():
            parts = [p.strip() for p in self.route_details.value.split("|")]
            if parts[0]:
                route_parts = parts[0].split("→", 1)
                departure = route_parts[0].strip() or None
                arrival = route_parts[1].strip() if len(route_parts) > 1 else None
            if len(parts) > 1 and parts[1]:
                flight_time = parts[1]
            if len(parts) > 2 and parts[2]:
                cabin_classes = parts[2]

        server_link = self.server_link.value.strip() or None

        desc_parts = []
        if departure and arrival:
            desc_parts.append(f"✈️ {departure} → {arrival}")
        elif departure:
            desc_parts.append(f"✈️ {departure}")
        if flight_time:
            desc_parts.append(f"🕐 Flight time: {flight_time}")
        if cabin_classes:
            desc_parts.append(f"💺 Cabins: {cabin_classes}")
        desc_parts.append("🚪 Gate announced 60 minutes before departure.")
        description = "\n".join(desc_parts)

        guild = interaction.guild
        entity_type = 1 if isinstance(self.channel, discord.StageChannel) else 2

        try:
            data = await interaction.client.http.create_guild_scheduled_event(
                guild.id,
                name=self.event_name.value,
                privacy_level=2,
                scheduled_start_time=start.isoformat(),
                scheduled_end_time=end.isoformat(),
                entity_type=entity_type,
                channel_id=self.channel.id,
                description=description,
            )
        except discord.Forbidden:
            return await interaction.followup.send("I don't have permission to create events.", ephemeral=True)
        except Exception as e:
            return await interaction.followup.send(f"Failed to create event: `{e}`", ephemeral=True)

        event_id = str(data["id"])

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO event_details
                   (event_id, guild_id, gate_channel_id, gate_text, departure, arrival, flight_time, cabin_classes, server_link)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_id, guild.id, 0, gate_text, departure, arrival, flight_time, cabin_classes, server_link),
            )
            await db.commit()

        embed = discord.Embed(
            title="✅ Event Created",
            description=f"**{data['name']}**",
            color=discord.Color(0x00A4E4),
        )
        embed.add_field(name="Departure", value=f"<t:{int(start.timestamp())}:F>", inline=True)
        embed.add_field(name="Duration", value=f"{self.duration} min", inline=True)
        embed.add_field(name="Voice Channel", value=self.channel.mention, inline=True)
        if gate_text:
            embed.add_field(name="In-Game Gate (hidden)", value=gate_text, inline=False)
        if departure and arrival:
            embed.add_field(name="Route", value=f"{departure} → {arrival}", inline=False)
        if flight_time:
            embed.add_field(name="Flight Time", value=flight_time, inline=True)
        if cabin_classes:
            embed.add_field(name="Cabin Classes", value=cabin_classes, inline=True)
        if server_link:
            embed.add_field(name="Server Link (sent at boarding)", value=server_link, inline=False)
        embed.set_footer(text="Gate revealed in DM 60 min before · Server link sent at departure time.")

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"[Events] CreateEventModal error: {error}")
        msg = "Something went wrong creating the event. Please try again."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS event_details (
                    event_id        TEXT    NOT NULL,
                    guild_id        INTEGER NOT NULL,
                    gate_channel_id INTEGER NOT NULL DEFAULT 0,
                    gate_text       TEXT,
                    departure       TEXT,
                    arrival         TEXT,
                    flight_time     TEXT,
                    cabin_classes   TEXT,
                    server_link     TEXT,
                    PRIMARY KEY (event_id, guild_id)
                )
            """)
            for col in ("server_link TEXT", "gate_text TEXT"):
                try:
                    await db.execute(f"ALTER TABLE event_details ADD COLUMN {col}")
                except Exception:
                    pass
            await db.execute("""
                CREATE TABLE IF NOT EXISTS event_reminders_sent (
                    guild_id  INTEGER NOT NULL,
                    event_id  TEXT    NOT NULL,
                    PRIMARY KEY (guild_id, event_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS event_boarding_sent (
                    guild_id  INTEGER NOT NULL,
                    event_id  TEXT    NOT NULL,
                    PRIMARY KEY (guild_id, event_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_event_config (
                    guild_id            INTEGER PRIMARY KEY,
                    boarding_channel_id INTEGER,
                    boarding_role_id    INTEGER,
                    support_channel_id  INTEGER
                )
            """)
            await db.commit()
        self._reminder_loop.start()

    async def cog_unload(self):
        self._reminder_loop.cancel()

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def _get_event_details(self, guild_id: int, event_id: str) -> Optional[dict]:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                """SELECT gate_channel_id, gate_text, departure, arrival, flight_time, cabin_classes, server_link
                   FROM event_details WHERE event_id = ? AND guild_id = ?""",
                (event_id, guild_id),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "gate_channel_id": row[0],
            "gate_text":       row[1],
            "departure":       row[2],
            "arrival":         row[3],
            "flight_time":     row[4],
            "cabin_classes":   row[5],
            "server_link":     row[6],
        }

    async def _already_reminded(self, guild_id: int, event_id: str) -> bool:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM event_reminders_sent WHERE guild_id = ? AND event_id = ?",
                (guild_id, event_id),
            ) as cur:
                return await cur.fetchone() is not None

    async def _mark_reminded(self, guild_id: int, event_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO event_reminders_sent (guild_id, event_id) VALUES (?, ?)",
                (guild_id, event_id),
            )
            await db.commit()

    async def _already_boarded(self, guild_id: int, event_id: str) -> bool:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM event_boarding_sent WHERE guild_id = ? AND event_id = ?",
                (guild_id, event_id),
            ) as cur:
                return await cur.fetchone() is not None

    async def _mark_boarded(self, guild_id: int, event_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO event_boarding_sent (guild_id, event_id) VALUES (?, ?)",
                (guild_id, event_id),
            )
            await db.commit()

    async def _get_guild_event_config(self, guild_id: int) -> Optional[dict]:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT boarding_channel_id, boarding_role_id, support_channel_id FROM guild_event_config WHERE guild_id = ?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "boarding_channel_id": row[0],
            "boarding_role_id":    row[1],
            "support_channel_id":  row[2],
        }

    # ── Reminder task ─────────────────────────────────────────────────────────

    @tasks.loop(minutes=5)
    async def _reminder_loop(self):
        for guild in self.bot.guilds:
            try:
                await self._check_guild_events(guild)
            except Exception as e:
                print(f"[Events] Reminder check failed for {guild.name}: {e}")

    @_reminder_loop.before_loop
    async def _before_reminder_loop(self):
        await self.bot.wait_until_ready()

    async def _check_guild_events(self, guild: discord.Guild):
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(minutes=GATE_ANNOUNCE_MINUTES)
        boarding_window = timedelta(minutes=10)

        events = await guild.fetch_scheduled_events()
        for event in events:
            # Gate assignment DM — 60 min before start
            if event.status == discord.ScheduledEventStatus.scheduled:
                if now < event.start_time <= window_end:
                    if not await self._already_reminded(guild.id, str(event.id)):
                        await self._mark_reminded(guild.id, str(event.id))
                        await self._send_reminders(guild, event)

            # Boarding DM — at event start time (10-min catch window for the loop)
            if event.status in (
                discord.ScheduledEventStatus.scheduled,
                discord.ScheduledEventStatus.active,
            ):
                if event.start_time <= now <= event.start_time + boarding_window:
                    if not await self._already_boarded(guild.id, str(event.id)):
                        await self._mark_boarded(guild.id, str(event.id))
                        await self._send_boarding(guild, event)

    def _resolve_gate(self, guild: discord.Guild, details: Optional[dict], event: discord.ScheduledEvent) -> Optional[str]:
        """Return the gate display string: in-game text if set, otherwise legacy channel mention."""
        if details:
            if details["gate_text"]:
                return details["gate_text"]
            if details["gate_channel_id"]:
                ch = guild.get_channel(details["gate_channel_id"])
                return ch.mention if ch else f"<#{details['gate_channel_id']}>"
        return None

    async def _send_reminders(self, guild: discord.Guild, event: discord.ScheduledEvent):
        try:
            data = await self.bot.http.get_scheduled_event_users(
                guild.id, event.id, limit=100, with_member=False,
            )
        except Exception as e:
            print(f"[Events] Could not fetch subscribers for '{event.name}': {e}")
            return

        if not data:
            return

        details = await self._get_event_details(guild.id, str(event.id))
        gate_display = self._resolve_gate(guild, details, event)

        minutes_away = int((event.start_time - datetime.now(timezone.utc)).total_seconds() / 60)
        time_label = f"{minutes_away} minute{'s' if minutes_away != 1 else ''}"
        event_url = f"https://discord.com/events/{guild.id}/{event.id}"

        embed = discord.Embed(
            title="✈️ Gate Assignment — Your Gate Is Now Confirmed",
            description=(
                f"Your gate for **{event.name}** has been assigned.\n\n"
                f"Departure is in **{time_label}**. "
                f"Please be at your gate at departure time.\n\n"
                f"[**→ View event**]({event_url})"
            ),
            color=discord.Color(0x00A4E4),
            timestamp=event.start_time,
        )

        embed.add_field(
            name="Departure Time",
            value=f"<t:{int(event.start_time.timestamp())}:F>",
            inline=True,
        )
        if gate_display:
            embed.add_field(name="In-Game Gate", value=gate_display, inline=True)

        if details:
            if details["departure"] and details["arrival"]:
                embed.add_field(
                    name="Route",
                    value=f"{details['departure']} → {details['arrival']}",
                    inline=False,
                )
            if details["flight_time"]:
                embed.add_field(name="Flight Time", value=details["flight_time"], inline=True)
            if details["cabin_classes"]:
                embed.add_field(name="Cabin Classes", value=details["cabin_classes"], inline=True)

        embed.set_footer(text="Korean Air PTFS • You're receiving this because you marked yourself as interested.")

        sent = 0
        failed = 0
        for entry in data:
            user_data = entry.get("user") or entry
            user_id = int(user_data["id"])
            try:
                user = await self.bot.fetch_user(user_id)
                await user.send(embed=embed)
                sent += 1
            except Exception:
                failed += 1

        print(f"[Events] Gate assignment DMs for '{event.name}' in {guild.name}: {sent} sent, {failed} failed")

    async def _send_boarding(self, guild: discord.Guild, event: discord.ScheduledEvent):
        details = await self._get_event_details(guild.id, str(event.id))
        config = await self._get_guild_event_config(guild.id)
        event_url = f"https://discord.com/events/{guild.id}/{event.id}"
        gate_display = self._resolve_gate(guild, details, event)

        # ── Channel announcement ───────────────────────────────────────────────
        if config and config["boarding_channel_id"]:
            boarding_ch = guild.get_channel(config["boarding_channel_id"])
            if boarding_ch:
                role_mention = f"<@&{config['boarding_role_id']}>" if config["boarding_role_id"] else ""
                support_mention = f"<#{config['support_channel_id']}>" if config["support_channel_id"] else ""

                spawn_parts = []
                if details and details["departure"]:
                    spawn_parts.append(details["departure"])
                if gate_display:
                    spawn_parts.append(gate_display)
                spawn = ", ".join(spawn_parts) if spawn_parts else "the departure gate"

                server_link_line = ""
                if details and details.get("server_link"):
                    server_link_line = f"\n\n[**Server Link**]({details['server_link']})"

                support_line = ""
                if support_mention:
                    support_line = f"\n\n🛬 If issues occur upon joining the server, please reach us in {support_mention}"

                announcement = (
                    f"## ✈️ {event.name} Is now ready for departure\n\n"
                    f"{role_mention}  {event.name} has begun check-in, please spawn at **{spawn}**"
                    f"{support_line}"
                    f"{server_link_line}"
                )
                try:
                    await boarding_ch.send(announcement)
                except Exception as e:
                    print(f"[Events] Could not post boarding announcement for '{event.name}': {e}")

        # ── DMs to interested members ──────────────────────────────────────────
        try:
            data = await self.bot.http.get_scheduled_event_users(
                guild.id, event.id, limit=100, with_member=False,
            )
        except Exception as e:
            print(f"[Events] Could not fetch subscribers for '{event.name}': {e}")
            return

        if not data:
            return

        embed = discord.Embed(
            title="🛫 Boarding Now — Join Your Gate",
            description=(
                f"**{event.name}** is now boarding!\n\n"
                f"Please make your way to your gate now.\n\n"
                f"[**→ View event**]({event_url})"
            ),
            color=discord.Color(0x00A4E4),
            timestamp=datetime.now(timezone.utc),
        )

        if gate_display:
            embed.add_field(name="In-Game Gate", value=gate_display, inline=True)

        if details:
            if details.get("server_link"):
                embed.add_field(name="Server Link", value=details["server_link"], inline=False)
            if details["departure"] and details["arrival"]:
                embed.add_field(
                    name="Route",
                    value=f"{details['departure']} → {details['arrival']}",
                    inline=False,
                )

        embed.set_footer(text="Korean Air PTFS • You're receiving this because you marked yourself as interested.")

        sent = 0
        failed = 0
        for entry in data:
            user_data = entry.get("user") or entry
            user_id = int(user_data["id"])
            try:
                user = await self.bot.fetch_user(user_id)
                await user.send(embed=embed)
                sent += 1
            except Exception:
                failed += 1

        print(f"[Events] Boarding DMs for '{event.name}' in {guild.name}: {sent} sent, {failed} failed")

    # ── Commands ──────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="createevent", description="Create a new scheduled event in this server")
    @app_commands.describe(
        channel="Voice or stage channel where pilots and hosts will speak",
        duration="Duration in minutes (default: 60)",
    )
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def createevent(
        self,
        ctx: commands.Context,
        channel: AnyVoiceChannel,
        duration: int = 60,
    ):
        if ctx.interaction is None:
            return await ctx.send("Please use this as a slash command: `/createevent`")
        await ctx.interaction.response.send_modal(CreateEventModal(channel=channel, duration=duration))

    @commands.hybrid_command(
        name="testeventreminder",
        description="[Admin] Send test gate assignment and boarding DMs to yourself",
    )
    @app_commands.describe(server_link="Optional server link to include in the test boarding DM")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def testeventreminder(self, ctx: commands.Context, server_link: Optional[str] = None):
        event_url = f"https://discord.com/events/{ctx.guild.id}/000000000000000000"
        now_ts = int(datetime.now(timezone.utc).timestamp())

        gate_embed = discord.Embed(
            title="✈️ Gate Assignment — Your Gate Is Now Confirmed",
            description=(
                f"Your gate for **TEST FLIGHT KE001** has been assigned.\n\n"
                f"Departure is in **60 minutes**. "
                f"Please be at your gate at departure time.\n\n"
                f"[**→ View event**]({event_url})"
            ),
            color=discord.Color(0x00A4E4),
            timestamp=datetime.now(timezone.utc),
        )
        gate_embed.add_field(name="Departure Time", value=f"<t:{now_ts + 3600}:F>", inline=True)
        gate_embed.add_field(name="In-Game Gate", value="Terminal 1, Gate B3", inline=True)
        gate_embed.add_field(name="Route", value="ICN → LAX", inline=False)
        gate_embed.add_field(name="Flight Time", value="10h 30m", inline=True)
        gate_embed.add_field(name="Cabin Classes", value="First · Prestige · Economy", inline=True)
        gate_embed.set_footer(text="Korean Air PTFS • You're receiving this because you marked yourself as interested.")

        boarding_embed = discord.Embed(
            title="🛫 Boarding Now — Join Your Gate",
            description=(
                f"**TEST FLIGHT KE001** is now boarding!\n\n"
                f"Please make your way to your gate now.\n\n"
                f"[**→ View event**]({event_url})"
            ),
            color=discord.Color(0x00A4E4),
            timestamp=datetime.now(timezone.utc),
        )
        boarding_embed.add_field(name="In-Game Gate", value="Terminal 1, Gate B3", inline=True)
        if server_link:
            boarding_embed.add_field(name="Server Link", value=server_link, inline=False)
        boarding_embed.add_field(name="Route", value="ICN → LAX", inline=False)
        boarding_embed.set_footer(text="Korean Air PTFS • You're receiving this because you marked yourself as interested.")

        try:
            await ctx.author.send(embed=gate_embed)
            await ctx.author.send(embed=boarding_embed)
            await ctx.send("✅ Test DMs sent (gate assignment + boarding) — check your DMs.", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("❌ Couldn't DM you. Enable DMs from server members and try again.", ephemeral=True)

    @commands.hybrid_command(name="eventsetup", description="Configure boarding announcements for this server")
    @app_commands.describe(
        boarding_channel="Channel where departure announcements are posted",
        boarding_role="Role to ping in departure announcements",
        support_channel="Support/help channel players should contact if they have issues joining",
    )
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def eventsetup(
        self,
        ctx: commands.Context,
        boarding_channel: discord.TextChannel,
        boarding_role: discord.Role,
        support_channel: discord.TextChannel,
    ):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO guild_event_config (guild_id, boarding_channel_id, boarding_role_id, support_channel_id)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                       boarding_channel_id = excluded.boarding_channel_id,
                       boarding_role_id    = excluded.boarding_role_id,
                       support_channel_id  = excluded.support_channel_id""",
                (ctx.guild.id, boarding_channel.id, boarding_role.id, support_channel.id),
            )
            await db.commit()

        embed = discord.Embed(
            title="✅ Boarding Config Saved",
            color=discord.Color(0x00A4E4),
        )
        embed.add_field(name="Boarding Channel", value=boarding_channel.mention, inline=True)
        embed.add_field(name="Boarding Role", value=boarding_role.mention, inline=True)
        embed.add_field(name="Support Channel", value=support_channel.mention, inline=True)
        embed.set_footer(text="These settings apply to all future departure announcements.")
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name="events", description="List all upcoming scheduled events in this server")
    async def events(self, ctx: commands.Context):
        await ctx.defer()

        scheduled = await ctx.guild.fetch_scheduled_events()
        upcoming = sorted(
            [e for e in scheduled if e.start_time > datetime.now(timezone.utc)],
            key=lambda e: e.start_time,
        )

        if not upcoming:
            return await ctx.send("No upcoming events scheduled.")

        embed = discord.Embed(
            title=f"📅 Upcoming Events — {ctx.guild.name}",
            color=discord.Color(0x00A4E4),
        )

        for event in upcoming[:10]:
            interested = event.user_count or 0
            embed.add_field(
                name=event.name,
                value=(
                    f"<t:{int(event.start_time.timestamp())}:F>\n"
                    f"{event.description or ''}\n"
                    f"👥 {interested} interested"
                ).strip(),
                inline=False,
            )

        if len(upcoming) > 10:
            embed.set_footer(text=f"Showing 10 of {len(upcoming)} events")
        else:
            embed.set_footer(text="Gate announced to interested members 60 min before departure")

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="cancelevent", description="Cancel a scheduled event by name")
    @app_commands.describe(name="The name of the event to cancel (case-insensitive)")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def cancelevent(self, ctx: commands.Context, *, name: str):
        await ctx.defer()

        scheduled = await ctx.guild.fetch_scheduled_events()
        matches = [e for e in scheduled if e.name.lower() == name.lower()]

        if not matches:
            close = [e for e in scheduled if name.lower() in e.name.lower()]
            if close:
                names = "\n".join(f"• {e.name}" for e in close[:5])
                return await ctx.send(f"No exact match found. Did you mean:\n{names}")
            return await ctx.send(f"No event named **{name}** found.")

        event = matches[0]
        await event.delete()
        await ctx.send(f"🗑️ Event **{event.name}** has been cancelled.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
