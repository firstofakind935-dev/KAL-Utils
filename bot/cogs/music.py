import asyncio
import os
from pathlib import Path

import discord
from discord.ext import commands

SOUND_PATH = Path(__file__).parent.parent / "sounds" / "airport.mp3"

FFMPEG_OPTIONS = {
    "options": "-vn",
}


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    async def airportsound(self, ctx: commands.Context):
        """Play the airport sound — bot will ask which voice channel to use."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            return await ctx.send("Already playing.")

        # List available voice channels
        voice_channels = ctx.guild.voice_channels
        if not voice_channels:
            return await ctx.send("No voice channels found in this server.")

        lines = [f"`{i+1}.` {vc.name}" for i, vc in enumerate(voice_channels)]
        await ctx.send(
            f"Which voice channel should I play in?\n" + "\n".join(lines) +
            "\n\nReply with the number or channel name. (You have 30 seconds)"
        )

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=30.0)
        except asyncio.TimeoutError:
            return await ctx.send("Timed out. Use `!airportsound` again when ready.")

        # Match by number or name
        target_channel = None
        if reply.content.isdigit():
            idx = int(reply.content) - 1
            if 0 <= idx < len(voice_channels):
                target_channel = voice_channels[idx]
        else:
            name = reply.content.strip().lower()
            target_channel = discord.utils.find(
                lambda c: c.name.lower() == name, voice_channels
            )

        if not target_channel:
            return await ctx.send("Couldn't find that channel. Use `!airportsound` again.")

        vc = ctx.voice_client
        if vc:
            await vc.move_to(target_channel)
        else:
            vc = await target_channel.connect()

        if not SOUND_PATH.exists():
            return await ctx.send("Audio file not found. Add `airport.mp3` to `bot/sounds/`.")

        try:
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(str(SOUND_PATH), **FFMPEG_OPTIONS),
                volume=0.5,
            )

            def after(error):
                if error:
                    print(f"[Music] Playback error: {error}")
                asyncio.run_coroutine_threadsafe(vc.disconnect(), self.bot.loop)

            vc.play(source, after=after)
            await ctx.send("Playing airport sound!")
        except Exception as e:
            await ctx.send(f"Playback error: `{e}`")

    @commands.command()
    async def stopsound(self, ctx: commands.Context):
        """Stop the airport sound and disconnect."""
        if ctx.voice_client:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
            await ctx.send("Stopped.")
        else:
            await ctx.send("Nothing is playing.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
