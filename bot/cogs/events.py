import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

import discord
from discord import app_commands
from discord.ext import commands


def parse_datetime(date_str: str, time_str: str) -> datetime:
    """Parse date (YYYY-MM-DD or DD/MM/YYYY) and time (HH:MM) into a UTC-aware datetime."""
    date_str = date_str.strip()
    time_str = time_str.strip()

    if re.match(r"\d{2}/\d{2}/\d{4}", date_str):
        dt = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
    else:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")

    return dt.replace(tzinfo=timezone.utc)


class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="createevent", description="Create a new scheduled event in this server")
    @app_commands.describe(
        name="Event name",
        date="Date (YYYY-MM-DD or DD/MM/YYYY)",
        time="Start time in UTC (HH:MM, 24-hour)",
        description="Event description",
        duration="Duration in minutes (default: 60)",
        channel="Voice or stage channel (leave blank for external event)",
        location="Location name if not in a channel",
    )
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def createevent(
        self,
        ctx: commands.Context,
        name: str,
        date: str,
        time: str,
        description: str = "",
        duration: int = 60,
        channel: Optional[Union[discord.VoiceChannel, discord.StageChannel]] = None,
        location: str = "",
    ):
        await ctx.defer()

        try:
            start = parse_datetime(date, time)
        except ValueError:
            return await ctx.send("Invalid date/time. Use `YYYY-MM-DD` and `HH:MM` (24-hour UTC).")

        if start < datetime.now(timezone.utc):
            return await ctx.send("Start time must be in the future.")

        end = start + timedelta(minutes=duration)

        try:
            if channel:
                entity_type = (
                    discord.EntityType.stage_instance
                    if isinstance(channel, discord.StageChannel)
                    else discord.EntityType.voice
                )
                event = await ctx.guild.create_scheduled_event(
                    name=name,
                    description=description or None,
                    start_time=start,
                    end_time=end,
                    entity_type=entity_type,
                    channel=channel,
                )
            else:
                event = await ctx.guild.create_scheduled_event(
                    name=name,
                    description=description or None,
                    start_time=start,
                    end_time=end,
                    entity_type=discord.EntityType.external,
                    location=location or "TBD",
                )
        except discord.Forbidden:
            return await ctx.send("I don't have permission to create events.")
        except Exception as e:
            return await ctx.send(f"Failed to create event: `{e}`")

        embed = discord.Embed(
            title="✅ Event Created",
            description=f"**{event.name}**",
            color=discord.Color(0x00A4E4),
        )
        embed.add_field(name="Start", value=f"<t:{int(start.timestamp())}:F>", inline=True)
        embed.add_field(name="Duration", value=f"{duration} min", inline=True)
        if channel:
            embed.add_field(name="Channel", value=channel.mention, inline=True)
        elif location:
            embed.add_field(name="Location", value=location, inline=True)
        if description:
            embed.add_field(name="Description", value=description, inline=False)

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
