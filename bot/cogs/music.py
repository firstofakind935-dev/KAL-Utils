import asyncio
from pathlib import Path

import discord
import imageio_ffmpeg
from discord import app_commands
from discord.ext import commands

SOUND_PATH = Path(__file__).resolve().parent.parent / "sounds" / "airport.mp3"
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="airportsound", description="Play the airport ambience sound in a voice channel")
    @app_commands.describe(channel="The voice channel to play the sound in")
    async def airportsound(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        await interaction.response.defer()

        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            return await interaction.followup.send("Already playing.")

        if not SOUND_PATH.exists():
            return await interaction.followup.send("Audio file not found. Contact an admin.")

        try:
            if vc:
                await vc.move_to(channel)
            else:
                vc = await channel.connect()

            source = discord.FFmpegOpusAudio(
                str(SOUND_PATH),
                executable=FFMPEG_EXE,
                bitrate=128,
                before_options="-nostdin",
                options="-vn -af aresample=48000",
            )

            def after(error):
                if error:
                    print(f"[Music] Playback error: {error}")
                asyncio.run_coroutine_threadsafe(vc.disconnect(), self.bot.loop)

            vc.play(source, after=after)
            await interaction.followup.send(f"Playing airport sound in **{channel.name}**!")
        except Exception as e:
            await interaction.followup.send(f"Playback error: `{e}`")

    @app_commands.command(name="stopsound", description="Stop the airport sound and disconnect")
    async def stopsound(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
            await interaction.response.send_message("Stopped.")
        else:
            await interaction.response.send_message("Nothing is playing.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
