import asyncio
from collections import deque

import discord
import imageio_ffmpeg
import yt_dlp
from discord import app_commands
from discord.ext import commands

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extractaudio": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
}

FFMPEG_OPTIONS = {
    "executable": FFMPEG_EXE,
    "before_options": "-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -af aresample=48000",
}


def fetch_info(query: str) -> dict:
    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return info


class GuildPlayer:
    def __init__(self):
        self.queue: deque = deque()
        self.current: dict | None = None
        self.loop: bool = False


class YouTube(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildPlayer] = {}

    def get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self.players:
            self.players[guild_id] = GuildPlayer()
        return self.players[guild_id]

    async def _advance(self, guild_id: int):
        player = self.get_player(guild_id)
        guild = self.bot.get_guild(guild_id)
        vc = guild.voice_client if guild else None

        if not vc:
            return

        if not player.queue:
            player.current = None
            await asyncio.sleep(300)
            if not vc.is_playing() and vc.is_connected():
                await vc.disconnect()
            return

        info = player.queue.popleft()
        player.current = info

        source = discord.FFmpegOpusAudio(info["url"], **FFMPEG_OPTIONS)

        def after(error):
            if error:
                print(f"[YouTube] Playback error: {error}")
            asyncio.run_coroutine_threadsafe(self._advance(guild_id), self.bot.loop)

        vc.play(source, after=after)

    @commands.hybrid_command(name="play", description="Play a song from YouTube by URL or search query")
    @app_commands.describe(query="YouTube URL or search terms")
    async def play(self, ctx: commands.Context, *, query: str):
        if not ctx.author.voice:
            return await ctx.send("You need to be in a voice channel.")

        await ctx.defer()

        vc = ctx.guild.voice_client
        if vc and vc.channel != ctx.author.voice.channel:
            await vc.move_to(ctx.author.voice.channel)
        elif not vc:
            vc = await ctx.author.voice.channel.connect()

        try:
            info = await asyncio.get_event_loop().run_in_executor(None, fetch_info, query)
        except Exception as e:
            return await ctx.send(f"Could not fetch audio: `{e}`")

        player = self.get_player(ctx.guild.id)
        player.queue.append(info)

        if not vc.is_playing():
            await self._advance(ctx.guild.id)
            await ctx.send(f"🎵 Now playing: **{info['title']}**")
        else:
            await ctx.send(f"📋 Added to queue: **{info['title']}** (position {len(player.queue)})")

    @commands.hybrid_command(name="next", description="Skip to the next song in the queue")
    async def next(self, ctx: commands.Context):
        vc = ctx.guild.voice_client
        if not vc or not vc.is_playing():
            return await ctx.send("Nothing is playing.")
        vc.stop()
        await ctx.send("⏭️ Skipped.")

    @commands.hybrid_command(name="queue", description="Show the current music queue")
    async def queue(self, ctx: commands.Context):
        player = self.get_player(ctx.guild.id)

        if not player.current and not player.queue:
            return await ctx.send("The queue is empty.")

        embed = discord.Embed(title="🎵 Music Queue", color=discord.Color(0x00A4E4))

        if player.current:
            embed.add_field(
                name="Now Playing",
                value=f"[{player.current['title']}]({player.current.get('webpage_url', '')})",
                inline=False,
            )

        if player.queue:
            lines = []
            for i, info in enumerate(list(player.queue)[:10], 1):
                lines.append(f"`{i}.` {info['title']}")
            if len(player.queue) > 10:
                lines.append(f"...and {len(player.queue) - 10} more")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="nowplaying", description="Show what's currently playing")
    async def nowplaying(self, ctx: commands.Context):
        player = self.get_player(ctx.guild.id)
        if not player.current:
            return await ctx.send("Nothing is playing.")

        info = player.current
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**[{info['title']}]({info.get('webpage_url', '')})**",
            color=discord.Color(0x00A4E4),
        )
        if info.get("thumbnail"):
            embed.set_thumbnail(url=info["thumbnail"])
        if info.get("duration"):
            mins, secs = divmod(info["duration"], 60)
            embed.add_field(name="Duration", value=f"{mins}:{secs:02d}")
        if info.get("uploader"):
            embed.add_field(name="Channel", value=info["uploader"])

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="pause", description="Pause the current song")
    async def pause(self, ctx: commands.Context):
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send("⏸️ Paused.")
        else:
            await ctx.send("Nothing is playing.")

    @commands.hybrid_command(name="resume", description="Resume the paused song")
    async def resume(self, ctx: commands.Context):
        vc = ctx.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await ctx.send("▶️ Resumed.")
        else:
            await ctx.send("Nothing is paused.")


async def setup(bot: commands.Bot):
    await bot.add_cog(YouTube(bot))
