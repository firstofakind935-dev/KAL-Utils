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


class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS event_details (
                    event_id        TEXT    NOT NULL,
                    guild_id        INTEGER NOT NULL,
                    gate_channel_id INTEGER NOT NULL,
                    departure       TEXT,
                    arrival         TEXT,
                    flight_time     TEXT,
                    cabin_classes   TEXT,
                    PRIMARY KEY (event_id, guild_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS event_reminders_sent (
                    guild_id  INTEGER NOT NULL,
                    event_id  TEXT    NOT NULL,
                    PRIMARY KEY (guild_id, event_id)
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
                """SELECT gate_channel_id, departure, arrival, flight_time, cabin_classes
                   FROM event_details WHERE event_id = ? AND guild_id = ?""",
                (event_id, guild_id),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "gate_channel_id": row[0],
            "departure":       row[1],
            "arrival":         row[2],
            "flight_time":     row[3],
            "cabin_classes":   row[4],
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

        events = await guild.fetch_scheduled_events()
        for event in events:
            if event.status != discord.ScheduledEventStatus.scheduled:
                continue
            if not (now < event.start_time <= window_end):
                continue
            if await self._already_reminded(guild.id, str(event.id)):
                continue

            await self._mark_reminded(guild.id, str(event.id))
            await self._send_reminders(guild, event)

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

        minutes_away = int((event.start_time - datetime.now(timezone.utc)).total_seconds() / 60)
        time_label = f"{minutes_away} minute{'s' if minutes_away != 1 else ''}"
        event_url = f"https://discord.com/events/{guild.id}/{event.id}"

        # Resolve gate channel from stored details (preferred) or from event itself
        gate_text = None
        if details and details["gate_channel_id"]:
            gate_ch = guild.get_channel(details["gate_channel_id"])
            gate_text = gate_ch.mention if gate_ch else f"<#{details['gate_channel_id']}>"
        elif event.channel:
            gate_text = event.channel.mention

        embed = discord.Embed(
            title="✈️ Gate Assignment — Your Gate Is Now Confirmed",
            description=(
                f"Your gate for **{event.name}** has been assigned.\n\n"
                f"Departure is in **{time_label}**. "
                f"Please join your gate at departure time.\n\n"
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
        if gate_text:
            embed.add_field(name="Gate", value=gate_text, inline=True)

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

        print(f"[Events] Boarding call for '{event.name}' in {guild.name}: {sent} sent, {failed} failed")

    # ── Commands ──────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="createevent", description="Create a new scheduled event in this server")
    @app_commands.describe(
        name="Event name",
        when='Date and time in UTC — e.g. "25/12 20:00" or "25/12/2026 20:00"',
        gate="Voice or stage channel — kept secret until the boarding call 70 min before",
        departure="Departure location (e.g. ICN — Seoul Incheon)",
        arrival="Arrival location (e.g. LAX — Los Angeles)",
        flight_time="Estimated flight time (e.g. 10h 30m)",
        cabin_classes="Available cabin classes (e.g. First · Prestige · Economy)",
        duration="Duration in minutes (default: 60)",
    )
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def createevent(
        self,
        ctx: commands.Context,
        name: str,
        when: str,
        gate: AnyVoiceChannel,
        departure: Optional[str] = None,
        arrival: Optional[str] = None,
        flight_time: Optional[str] = None,
        cabin_classes: Optional[str] = None,
        duration: int = 60,
    ):
        await ctx.defer(ephemeral=True)

        try:
            start = parse_when(when)
        except ValueError:
            return await ctx.send(
                'Invalid date/time. Examples: `25/12 20:00` · `25/12/2026 20:00` · `2026-12-25 20:00`',
                ephemeral=True,
            )

        if start < datetime.now(timezone.utc):
            return await ctx.send("Start time must be in the future.", ephemeral=True)

        end = start + timedelta(minutes=duration)

        # Build description from flight details — gate is NOT included here
        desc_parts = []
        if departure and arrival:
            desc_parts.append(f"✈️ {departure} → {arrival}")
        if flight_time:
            desc_parts.append(f"🕐 Flight time: {flight_time}")
        if cabin_classes:
            desc_parts.append(f"💺 Cabins: {cabin_classes}")
        desc_parts.append("🚪 Gate announced 60 minutes before departure.")
        description = "\n".join(desc_parts)

        try:
            data = await ctx.bot.http.create_guild_scheduled_event(
                ctx.guild.id,
                name=name,
                privacy_level=2,
                scheduled_start_time=start.isoformat(),
                scheduled_end_time=end.isoformat(),
                entity_type=3,
                entity_metadata={"location": f"{departure} → {arrival}" if (departure and arrival) else "See event details"},
                description=description,
            )
        except discord.Forbidden:
            return await ctx.send("I don't have permission to create events.", ephemeral=True)
        except Exception as e:
            return await ctx.send(f"Failed to create event: `{e}`", ephemeral=True)

        event_id = str(data["id"])

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO event_details
                   (event_id, guild_id, gate_channel_id, departure, arrival, flight_time, cabin_classes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (event_id, ctx.guild.id, gate.id, departure, arrival, flight_time, cabin_classes),
            )
            await db.commit()

        embed = discord.Embed(
            title="✅ Event Created",
            description=f"**{data['name']}**",
            color=discord.Color(0x00A4E4),
        )
        embed.add_field(name="Departure", value=f"<t:{int(start.timestamp())}:F>", inline=True)
        embed.add_field(name="Duration", value=f"{duration} min", inline=True)
        embed.add_field(name="Gate (hidden)", value=gate.mention, inline=True)
        if departure and arrival:
            embed.add_field(name="Route", value=f"{departure} → {arrival}", inline=False)
        if flight_time:
            embed.add_field(name="Flight Time", value=flight_time, inline=True)
        if cabin_classes:
            embed.add_field(name="Cabin Classes", value=cabin_classes, inline=True)
        embed.set_footer(text="Gate will be announced to interested members 60 minutes before departure.")

        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="testeventreminder",
        description="[Admin] Send a test gate assignment DM to yourself",
    )
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def testeventreminder(self, ctx: commands.Context):
        event_url = f"https://discord.com/events/{ctx.guild.id}/000000000000000000"

        embed = discord.Embed(
            title="✈️ Gate Assignment — Your Gate Is Now Confirmed",
            description=(
                f"Your gate for **TEST FLIGHT KE001** has been assigned.\n\n"
                f"Departure is in **60 minutes**. "
                f"Please join your gate at departure time.\n\n"
                f"[**→ View event**]({event_url})"
            ),
            color=discord.Color(0x00A4E4),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Departure Time", value=f"<t:{int(datetime.now(timezone.utc).timestamp()) + 3600}:F>", inline=True)
        embed.add_field(name="Gate", value="#gate-1 (test)", inline=True)
        embed.add_field(name="Route", value="ICN → LAX", inline=False)
        embed.add_field(name="Flight Time", value="10h 30m", inline=True)
        embed.add_field(name="Cabin Classes", value="First · Prestige · Economy", inline=True)
        embed.set_footer(text="Korean Air PTFS • You're receiving this because you marked yourself as interested.")

        try:
            await ctx.author.send(embed=embed)
            await ctx.send("✅ Test gate assignment DM sent — check your DMs.", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("❌ Couldn't DM you. Enable DMs from server members and try again.", ephemeral=True)

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
