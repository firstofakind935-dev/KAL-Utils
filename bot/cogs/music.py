import asyncio

import discord
import yt_dlp
from discord.ext import commands

AIRPORT_URL = "https://www.youtube.com/watch?v=zQG5OdBnYfA"

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    async def airportsound(self, ctx: commands.Context):
        """Play the airport sound in your voice channel."""
        if not ctx.author.voice:
            return await ctx.send("You need to be in a voice channel first.")

        vc = ctx.voice_client
        if vc and vc.is_playing():
            return await ctx.send("Already playing.")

        if not vc:
            vc = await ctx.author.voice.channel.connect()

        async with ctx.typing():
            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                info = await loop.run_in_executor(
                    None, lambda: ydl.extract_info(AIRPORT_URL, download=False)
                )
            stream_url = info["url"]

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS),
            volume=0.5,
        )

        def after(error):
            asyncio.run_coroutine_threadsafe(vc.disconnect(), self.bot.loop)

        vc.play(source, after=after)
        await ctx.send("Playing airport sound!")

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
