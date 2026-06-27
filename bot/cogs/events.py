from datetime import datetime, timedelta, timezone
from typing import Union

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks

AnyVoiceChannel = Union[discord.VoiceChannel, discord.StageChannel]

from db.database import DB_PATH

DEFAULT_REMINDER_MINUTES = 60

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
                CREATE TABLE IF NOT EXISTS event_reminder_config (
                    guild_id         INTEGER PRIMARY KEY,
                    reminder_minutes INTEGER NOT NULL DEFAULT 30
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

    # ── DB helpers ───────────────────────────────────────────────────────────

    async def _get_reminder_minutes(self, guild_id: int) -> int:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT reminder_minutes FROM event_reminder_config WHERE guild_id = ?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row else DEFAULT_REMINDER_MINUTES

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
        reminder_minutes = await self._get_reminder_minutes(guild.id)
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(minutes=reminder_minutes)

        events = await guild.fetch_scheduled_events()
        for event in events:
            if event.status != discord.ScheduledEventStatus.scheduled:
                continue
            if not (now < event.start_time <= window_end):
                continue
            if await self._already_reminded(guild.id, str(event.id)):
                continue

            # Mark before sending to prevent duplicate runs if the loop fires twice
            await self._mark_reminded(guild.id, str(event.id))
            await self._send_reminders(guild, event, reminder_minutes)

    async def _send_reminders(self, guild: discord.Guild, event: discord.ScheduledEvent, reminder_minutes: int):
        try:
            data = await self.bot.http.get_scheduled_event_users(
                guild.id, event.id, limit=100, with_member=False,
            )
        except Exception as e:
            print(f"[Events] Could not fetch subscribers for '{event.name}': {e}")
            return

        if not data:
            return

        minutes_away = int((event.start_time - datetime.now(timezone.utc)).total_seconds() / 60)
        time_label = f"{minutes_away} minute{'s' if minutes_away != 1 else ''}"
        event_url = f"https://discord.com/events/{guild.id}/{event.id}"

        embed = discord.Embed(
            title="✈️ Boarding Call — All Passengers Please Proceed",
            description=(
                f"This is your boarding call for **{event.name}**.\n\n"
                f"Departure is in **{time_label}**. "
                f"Please make your way to the gate now.\n\n"
                f"[**→ Join the event**]({event_url})"
            ),
            color=discord.Color(0x00A4E4),
            timestamp=event.start_time,
        )
        embed.add_field(
            name="Departure",
            value=f"<t:{int(event.start_time.timestamp())}:F>",
            inline=True,
        )
        if event.location:
            embed.add_field(name="Gate", value=event.location, inline=True)
        elif event.channel:
            embed.add_field(name="Gate", value=event.channel.name, inline=True)
        if event.description:
            embed.add_field(name="Flight Details", value=event.description[:500], inline=False)
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

        print(f"[Events] Reminder for '{event.name}' in {guild.name}: {sent} sent, {failed} failed")

    # ── Commands ──────────────────────────────────────────────────────────────

    @commands.hybrid_command(
        name="seteventreminder",
        description="[Admin] Set how many minutes before an event to DM interested members",
    )
    @app_commands.describe(minutes="Minutes before the event to send the reminder (e.g. 30, 60)")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def seteventreminder(self, ctx: commands.Context, minutes: int):
        if minutes < 5:
            return await ctx.send("Minimum reminder time is 5 minutes.", ephemeral=True)
        if minutes > 1440:
            return await ctx.send("Maximum reminder time is 1440 minutes (24 hours).", ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO event_reminder_config (guild_id, reminder_minutes) VALUES (?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET reminder_minutes = excluded.reminder_minutes""",
                (ctx.guild.id, minutes),
            )
            await db.commit()

        await ctx.send(
            f"Event reminders will be sent **{minutes} minute{'s' if minutes != 1 else ''}** before each event starts.",
            ephemeral=True,
        )

    @commands.hybrid_command(name="createevent", description="Create a new scheduled event in this server")
    @app_commands.describe(
        name="Event name",
        when='Date and time in UTC — e.g. "25/12 20:00" or "25/12/2026 20:00"',
        gate="The voice or stage channel where the event takes place",
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
        duration: int = 60,
    ):
        await ctx.defer()

        try:
            start = parse_when(when)
        except ValueError:
            return await ctx.send(
                'Invalid date/time. Examples: `25/12 20:00` · `25/12/2026 20:00` · `2026-12-25 20:00`'
            )

        if start < datetime.now(timezone.utc):
            return await ctx.send("Start time must be in the future.")

        end = start + timedelta(minutes=duration)
        entity_type = 1 if isinstance(gate, discord.StageChannel) else 2

        try:
            data = await ctx.bot.http.create_guild_scheduled_event(
                ctx.guild.id,
                name=name,
                privacy_level=2,
                scheduled_start_time=start.isoformat(),
                scheduled_end_time=end.isoformat(),
                entity_type=entity_type,
                channel_id=gate.id,
            )
        except discord.Forbidden:
            return await ctx.send("I don't have permission to create events.")
        except Exception as e:
            return await ctx.send(f"Failed to create event: `{e}`")

        embed = discord.Embed(
            title="✅ Event Created",
            description=f"**{data['name']}**",
            color=discord.Color(0x00A4E4),
        )
        embed.add_field(name="Start", value=f"<t:{int(start.timestamp())}:F>", inline=True)
        embed.add_field(name="Duration", value=f"{duration} min", inline=True)
        embed.add_field(name="Gate", value=gate.mention, inline=True)

        await ctx.send(embed=embed)

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

        reminder_minutes = await self._get_reminder_minutes(ctx.guild.id)

        embed = discord.Embed(
            title=f"📅 Upcoming Events — {ctx.guild.name}",
            color=discord.Color(0x00A4E4),
        )

        for event in upcoming[:10]:
            location = ""
            if event.channel:
                location = f" • {event.channel.name}"
            elif event.location:
                location = f" • {event.location}"

            interested = event.user_count or 0
            embed.add_field(
                name=event.name,
                value=(
                    f"<t:{int(event.start_time.timestamp())}:F>\n"
                    f"{event.description or ''}"
                    f"{location}\n"
                    f"👥 {interested} interested"
                ).strip(),
                inline=False,
            )

        if len(upcoming) > 10:
            embed.set_footer(text=f"Showing 10 of {len(upcoming)} events")
        embed.set_footer(text=f"Boarding calls sent {reminder_minutes} min before departure")

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
