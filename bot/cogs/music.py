import asyncio
from pathlib import Path

import discord
import imageio_ffmpeg
from discord import app_commands
from discord.ext import commands

SOUNDS_DIR = Path(__file__).resolve().parent.parent / "sounds"
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

SOUND_FILES = {
    "airport":     SOUNDS_DIR / "airport.mp3",
    "boarding":    SOUNDS_DIR / "boarding.mp3",
    "anywhere":    SOUNDS_DIR / "anywhere.mp3",
    "safety":      SOUNDS_DIR / "safety.mp3",
    "enginestart": SOUNDS_DIR / "enginestart.mp3",
    "enginehum":   SOUNDS_DIR / "enginehum.mp3",
}

FLIGHT_SEQUENCE = [
    ("airport",     "Airport Ambience"),
    ("boarding",    "Korean Air Boarding Music"),
    ("anywhere",    "Korean Air – Anywhere is Possible"),
    ("safety",      "Korean Air Safety Briefing"),
    ("enginestart", "Engine Start"),
    ("enginehum",   "Engine Hum"),
]


def make_source(path: Path):
    return discord.FFmpegOpusAudio(
        str(path),
        executable=FFMPEG_EXE,
        bitrate=128,
        before_options="-nostdin",
        options="-vn -af aresample=48000",
    )


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _play_sequence(self, vc: discord.VoiceClient, index: int, channel: discord.TextChannel):
        """Recursively plays the flight sequence from the given index."""
        if index >= len(FLIGHT_SEQUENCE):
            await channel.send("✈️ Flight sequence complete. Safe travels!")
            await vc.disconnect()
            return

        sound_key, label = FLIGHT_SEQUENCE[index]
        path = SOUND_FILES.get(sound_key)

        if not path or not path.exists():
            # Skip missing sounds silently and move to next
            await self._play_sequence(vc, index + 1, channel)
            return

        source = make_source(path)
        total = sum(1 for k, _ in FLIGHT_SEQUENCE if SOUND_FILES.get(k) and SOUND_FILES[k].exists())
        current = sum(1 for i, (k, _) in enumerate(FLIGHT_SEQUENCE) if i <= index and SOUND_FILES.get(k) and SOUND_FILES[k].exists())

        def after(error):
            if error:
                print(f"[Music] Sequence error at {label}: {error}")
            asyncio.run_coroutine_threadsafe(
                self._play_sequence(vc, index + 1, channel), self.bot.loop
            )

        vc.play(source, after=after)
        await channel.send(f"🎵 Now playing **{label}** `[{current}/{total}]`")

    # ── Flight sequence ──────────────────────────────────────────────────────

    @commands.hybrid_command(name="flight", description="Play the full Korean Air flight sequence")
    @app_commands.describe(channel="The voice channel to play in")
    async def flight(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """Start the full flight sound sequence."""
        await ctx.defer()

        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            return await ctx.send("Already playing. Use `/stopsound` first.")

        if vc:
            await vc.move_to(channel)
        else:
            vc = await channel.connect()

        await ctx.send(f"✈️ Starting flight sequence in **{channel.name}**!")
        await self._play_sequence(vc, 0, ctx.channel)

    # ── Individual sounds ────────────────────────────────────────────────────

    @commands.hybrid_command(name="airportsound", description="Play airport ambience in a voice channel")
    @app_commands.describe(channel="The voice channel to play in")
    async def airportsound(self, ctx: commands.Context, channel: discord.VoiceChannel):
        await self._play_single(ctx, channel, "airport", "Airport Ambience")

    @commands.hybrid_command(name="boarding", description="Play Korean Air boarding music")
    @app_commands.describe(channel="The voice channel to play in")
    async def boarding(self, ctx: commands.Context, channel: discord.VoiceChannel):
        await self._play_single(ctx, channel, "boarding", "Korean Air Boarding Music")

    @commands.hybrid_command(name="anywhere", description="Play Korean Air – Anywhere is Possible")
    @app_commands.describe(channel="The voice channel to play in")
    async def anywhere(self, ctx: commands.Context, channel: discord.VoiceChannel):
        await self._play_single(ctx, channel, "anywhere", "Korean Air – Anywhere is Possible")

    @commands.hybrid_command(name="stopsound", description="Stop playback and disconnect")
    async def stopsound(self, ctx: commands.Context):
        vc = ctx.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
            await ctx.send("Stopped.")
        else:
            await ctx.send("Nothing is playing.")

    async def _play_single(self, ctx: commands.Context, channel: discord.VoiceChannel, sound_key: str, label: str):
        await ctx.defer()
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            return await ctx.send("Already playing.")

        path = SOUND_FILES[sound_key]
        if not path.exists():
            return await ctx.send(f"Audio file `{path.name}` not found. Contact an admin.")

        try:
            if vc:
                await vc.move_to(channel)
            else:
                vc = await channel.connect()

            def after(error):
                if error:
                    print(f"[Music] Playback error: {error}")
                asyncio.run_coroutine_threadsafe(vc.disconnect(), self.bot.loop)

            vc.play(make_source(path), after=after)
            await ctx.send(f"Playing **{label}** in **{channel.name}**!")
        except Exception as e:
            await ctx.send(f"Playback error: `{e}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
