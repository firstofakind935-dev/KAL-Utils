import asyncio
from collections import deque

import discord
import yt_dlp
from discord.ext import commands

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class GuildQueue:
    def __init__(self):
        self.queue: deque[dict] = deque()
        self.current: dict | None = None
        self.loop: bool = False


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._queues: dict[int, GuildQueue] = {}

    def _queue(self, guild_id: int) -> GuildQueue:
        if guild_id not in self._queues:
            self._queues[guild_id] = GuildQueue()
        return self._queues[guild_id]

    async def _play_next(self, guild_id: int, channel: discord.TextChannel):
        q = self._queue(guild_id)
        vc = channel.guild.voice_client

        if not vc:
            return

        if q.loop and q.current:
            q.queue.appendleft(q.current)

        if not q.queue:
            q.current = None
            return

        q.current = q.queue.popleft()
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(q.current["url"], **FFMPEG_OPTIONS),
            volume=0.5,
        )

        def after(error):
            if error:
                print(f"[Music] Player error: {error}")
            asyncio.run_coroutine_threadsafe(
                self._play_next(guild_id, channel), self.bot.loop
            )

        vc.play(source, after=after)
        embed = discord.Embed(
            title="Now Playing",
            description=f"**{q.current['title']}**",
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"Requested by {q.current['requester']}")
        await channel.send(embed=embed)

    @commands.command()
    async def join(self, ctx: commands.Context):
        """Join your voice channel."""
        if not ctx.author.voice:
            return await ctx.send("You need to be in a voice channel first.")
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        await ctx.send(f"Joined **{channel.name}**.")

    @commands.command()
    async def play(self, ctx: commands.Context, *, query: str):
        """Play a song from YouTube — accepts a URL or search terms."""
        if not ctx.author.voice:
            return await ctx.send("Join a voice channel first.")

        if not ctx.voice_client:
            await ctx.author.voice.channel.connect()

        async with ctx.typing():
            loop = asyncio.get_event_loop()
            try:
                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                    info = await loop.run_in_executor(
                        None, lambda: ydl.extract_info(query, download=False)
                    )
            except yt_dlp.utils.DownloadError as e:
                return await ctx.send(f"Could not find that song: {e}")

            if "entries" in info:
                info = info["entries"][0]

            song = {
                "title": info.get("title", "Unknown"),
                "url": info["url"],
                "duration": info.get("duration", 0),
                "requester": ctx.author.display_name,
            }

        q = self._queue(ctx.guild.id)
        q.queue.append(song)
        mins, secs = divmod(song["duration"], 60)
        await ctx.send(f"Queued: **{song['title']}** `{mins}:{secs:02d}`")

        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await self._play_next(ctx.guild.id, ctx.channel)

    @commands.command()
    async def skip(self, ctx: commands.Context):
        """Skip the current song."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("Skipped.")
        else:
            await ctx.send("Nothing is playing.")

    @commands.command()
    async def pause(self, ctx: commands.Context):
        """Pause playback."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("Paused.")
        else:
            await ctx.send("Nothing to pause.")

    @commands.command()
    async def resume(self, ctx: commands.Context):
        """Resume playback."""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("Resumed.")
        else:
            await ctx.send("Nothing is paused.")

    @commands.command()
    async def stop(self, ctx: commands.Context):
        """Stop playback, clear the queue, and disconnect."""
        q = self._queue(ctx.guild.id)
        q.queue.clear()
        q.current = None
        if ctx.voice_client:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
        await ctx.send("Stopped and disconnected.")

    @commands.command(aliases=["np"])
    async def nowplaying(self, ctx: commands.Context):
        """Show the currently playing song."""
        q = self._queue(ctx.guild.id)
        if not q.current:
            return await ctx.send("Nothing is playing right now.")
        embed = discord.Embed(
            title="Now Playing",
            description=f"**{q.current['title']}**",
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"Requested by {q.current['requester']}")
        await ctx.send(embed=embed)

    @commands.command(aliases=["q"])
    async def queue(self, ctx: commands.Context):
        """Show the music queue."""
        q = self._queue(ctx.guild.id)
        if not q.current and not q.queue:
            return await ctx.send("The queue is empty.")

        embed = discord.Embed(title="Music Queue", color=discord.Color.blue())
        if q.current:
            embed.add_field(
                name="Now Playing", value=q.current["title"], inline=False
            )
        if q.queue:
            items = list(q.queue)[:10]
            lines = [f"`{i+1}.` {s['title']}" for i, s in enumerate(items)]
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
            if len(q.queue) > 10:
                embed.set_footer(text=f"... and {len(q.queue) - 10} more")
        await ctx.send(embed=embed)

    @commands.command()
    async def volume(self, ctx: commands.Context, vol: int):
        """Set volume 0–100."""
        if not ctx.voice_client or not ctx.voice_client.source:
            return await ctx.send("Nothing is playing.")
        if not 0 <= vol <= 100:
            return await ctx.send("Volume must be between 0 and 100.")
        ctx.voice_client.source.volume = vol / 100
        await ctx.send(f"Volume set to **{vol}%**.")

    @commands.command(name="loop")
    async def loop_cmd(self, ctx: commands.Context):
        """Toggle loop for the current song."""
        q = self._queue(ctx.guild.id)
        q.loop = not q.loop
        await ctx.send(f"Loop {'**enabled**' if q.loop else '**disabled**'}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
