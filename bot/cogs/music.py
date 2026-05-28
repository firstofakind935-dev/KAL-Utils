import asyncio
from pathlib import Path

import discord
import imageio_ffmpeg
from discord import app_commands
from discord.ext import commands

SOUNDS_DIR = Path(__file__).resolve().parent.parent / "sounds"
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

SOUND_FILES = {
    "airport":  SOUNDS_DIR / "airport.mp3",
    "boarding": SOUNDS_DIR / "boarding.mp3",
    "anywhere": SOUNDS_DIR / "anywhere.mp3",
}


async def play_sound(ctx: commands.Context, bot: commands.Bot, channel: discord.VoiceChannel, sound_key: str, label: str):
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

        source = discord.FFmpegOpusAudio(
            str(path),
            executable=FFMPEG_EXE,
            bitrate=128,
            before_options="-nostdin",
            options="-vn -af aresample=48000",
        )

        def after(error):
            if error:
                print(f"[Music] Playback error: {error}")
            asyncio.run_coroutine_threadsafe(vc.disconnect(), bot.loop)

        vc.play(source, after=after)
        await ctx.send(f"Playing **{label}** in **{channel.name}**!")
    except Exception as e:
        await ctx.send(f"Playback error: `{e}`")


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="airportsound", description="Play airport ambience in a voice channel")
    @app_commands.describe(channel="The voice channel to play in")
    async def airportsound(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """Play airport ambience."""
        await play_sound(ctx, self.bot, channel, "airport", "Airport Ambience")

    @commands.hybrid_command(name="boarding", description="Play Korean Air boarding music in a voice channel")
    @app_commands.describe(channel="The voice channel to play in")
    async def boarding(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """Play Korean Air boarding music."""
        await play_sound(ctx, self.bot, channel, "boarding", "Korean Air Boarding Music")

    @commands.hybrid_command(name="anywhere", description="Play Korean Air – Anywhere is Possible in a voice channel")
    @app_commands.describe(channel="The voice channel to play in")
    async def anywhere(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """Play Korean Air – Anywhere is Possible."""
        await play_sound(ctx, self.bot, channel, "anywhere", "Korean Air – Anywhere is Possible")

    @commands.hybrid_command(name="stopsound", description="Stop the current sound and disconnect")
    async def stopsound(self, ctx: commands.Context):
        """Stop playback."""
        vc = ctx.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
            await ctx.send("Stopped.")
        else:
            await ctx.send("Nothing is playing.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
