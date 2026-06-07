import asyncio
import os
import tempfile
from collections import deque
from pathlib import Path

import discord
import imageio_ffmpeg
import yt_dlp
from discord import app_commands
from discord.ext import commands

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

def _resolve_cookies() -> str | None:
    """Write YOUTUBE_COOKIES env var to a temp file, or use cookies.txt if present."""
    env_cookies = os.getenv("YOUTUBE_COOKIES")
    if env_cookies:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        tmp.write(env_cookies)
        tmp.close()
        return tmp.name
    local = Path(__file__).resolve().parent.parent.parent / "cookies.txt"
    return str(local) if local.exists() else None

_COOKIES_PATH = _resolve_cookies()

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "nocheckcertificate": True,
    "ignoreerrors": False,
    **({"cookiefile": _COOKIES_PATH} if _COOKIES_PATH else {}),
}

FFMPEG_OPTIONS = {
    "executable": FFMPEG_EXE,
    "before_options": "-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -af aresample=48000",
}


def fetch_info(query: str) -> dict:
    """Extract info and return a fresh stream URL."""
    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return info


def fetch_stream_url(webpage_url: str) -> str:
    """Re-fetch a fresh stream URL right before playback."""
    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
        info = ydl.extract_info(webpage_url, download=False)
        return info["url"]


class QueueEntry:
    def __init__(self, title: str, webpage_url: str, thumbnail: str = None,
                 duration: int = None, uploader: str = None):
        self.title = title
        self.webpage_url = webpage_url
        self.thumbnail = thumbnail
        self.duration = duration
        self.uploader = uploader


class GuildPlayer:
    def __init__(self):
        self.queue: deque[QueueEntry] = deque()
        self.current: QueueEntry | None = None
        self.text_channel: discord.TextChannel | None = None


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

        entry = player.queue.popleft()
        player.current = entry

        try:
            # Re-fetch a fresh URL right before playing
            stream_url = await asyncio.get_event_loop().run_in_executor(
                None, fetch_stream_url, entry.webpage_url
            )
        except Exception as e:
            print(f"[YouTube] Failed to fetch stream URL: {e}")
            if player.text_channel:
                await player.text_channel.send(f"⚠️ Could not stream **{entry.title}**: `{e}`")
            await self._advance(guild_id)
            return

        source = discord.FFmpegOpusAudio(stream_url, **FFMPEG_OPTIONS)

        def after(error):
            if error:
                print(f"[YouTube] Playback error: {error}")
            asyncio.run_coroutine_threadsafe(self._advance(guild_id), self.bot.loop)

        vc.play(source, after=after)

        if player.text_channel:
            await player.text_channel.send(f"🎵 Now playing: **{entry.title}**")

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
            return await ctx.send(f"Could not find that song: `{e}`")

        entry = QueueEntry(
            title=info.get("title", "Unknown"),
            webpage_url=info.get("webpage_url", info.get("url")),
            thumbnail=info.get("thumbnail"),
            duration=info.get("duration"),
            uploader=info.get("uploader"),
        )

        player = self.get_player(ctx.guild.id)
        player.text_channel = ctx.channel
        player.queue.append(entry)

        if not vc.is_playing() and not vc.is_paused():
            await ctx.send(f"⏳ Loading **{entry.title}**...")
            await self._advance(ctx.guild.id)
        else:
            await ctx.send(f"📋 Added to queue: **{entry.title}** (position {len(player.queue)})")

    @commands.hybrid_command(name="next", description="Skip to the next song in the queue")
    async def next(self, ctx: commands.Context):
        vc = ctx.guild.voice_client
        if not vc or (not vc.is_playing() and not vc.is_paused()):
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
                value=f"[{player.current.title}]({player.current.webpage_url})",
                inline=False,
            )

        if player.queue:
            lines = []
            for i, entry in enumerate(list(player.queue)[:10], 1):
                lines.append(f"`{i}.` {entry.title}")
            if len(player.queue) > 10:
                lines.append(f"...and {len(player.queue) - 10} more")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="nowplaying", description="Show what's currently playing")
    async def nowplaying(self, ctx: commands.Context):
        player = self.get_player(ctx.guild.id)
        if not player.current:
            return await ctx.send("Nothing is playing.")

        entry = player.current
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**[{entry.title}]({entry.webpage_url})**",
            color=discord.Color(0x00A4E4),
        )
        if entry.thumbnail:
            embed.set_thumbnail(url=entry.thumbnail)
        if entry.duration:
            mins, secs = divmod(entry.duration, 60)
            embed.add_field(name="Duration", value=f"{mins}:{secs:02d}")
        if entry.uploader:
            embed.add_field(name="Channel", value=entry.uploader)

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
