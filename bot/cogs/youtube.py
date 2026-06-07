import asyncio
import base64
import os
import re
from collections import deque
from pathlib import Path

import aiohttp
import discord
import imageio_ffmpeg
import yt_dlp
from discord import app_commands
from discord.ext import commands

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
COOKIES_PATH = "/tmp/yt_cookies.txt"

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://piped-api.garudalinux.org",
    "https://api.piped.projectsegfau.lt",
]

FFMPEG_OPTIONS = {
    "executable": FFMPEG_EXE,
    "before_options": "-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -af aresample=48000",
}


def _setup_cookies() -> str | None:
    env_b64 = os.getenv("YOUTUBE_COOKIES_B64")
    if env_b64:
        try:
            content = base64.b64decode(env_b64).decode("utf-8")
            with open(COOKIES_PATH, "w") as f:
                f.write(content)
            return COOKIES_PATH
        except Exception as e:
            print(f"[YouTube] Failed to decode YOUTUBE_COOKIES_B64: {e}")
    env_cookies = os.getenv("YOUTUBE_COOKIES")
    if env_cookies:
        content = env_cookies.replace("\\n", "\n").replace("\\t", "\t")
        with open(COOKIES_PATH, "w") as f:
            f.write(content)
        return COOKIES_PATH
    local = Path(__file__).resolve().parent.parent.parent / "cookies.txt"
    return str(local) if local.exists() else None


def _extract_video_id(url: str) -> str | None:
    for pattern in [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
    ]:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


async def _piped_get(session: aiohttp.ClientSession, path: str) -> dict:
    """Try each Piped instance until one responds."""
    for base in PIPED_INSTANCES:
        try:
            async with session.get(f"{base}{path}", timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return await r.json()
        except Exception:
            continue
    raise RuntimeError("All Piped instances failed")


async def piped_search(query: str) -> dict:
    """Search Piped and return first video result as a QueueEntry-compatible dict."""
    async with aiohttp.ClientSession() as session:
        data = await _piped_get(session, f"/search?q={aiohttp.helpers.quote(query)}&filter=videos")
    items = [i for i in data.get("items", []) if i.get("type") == "stream"]
    if not items:
        raise ValueError("No results found")
    item = items[0]
    video_id = _extract_video_id(item.get("url", "")) or item.get("url", "").split("=")[-1]
    return {
        "id": video_id,
        "title": item.get("title", "Unknown"),
        "thumbnail": item.get("thumbnail"),
        "duration": item.get("duration"),
        "uploader": item.get("uploaderName"),
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
    }


async def piped_stream_url(video_id: str) -> str:
    """Get the best audio stream URL from Piped."""
    async with aiohttp.ClientSession() as session:
        data = await _piped_get(session, f"/streams/{video_id}")
    streams = data.get("audioStreams", [])
    if not streams:
        raise ValueError("No audio streams from Piped")
    best = sorted(streams, key=lambda x: x.get("bitrate", 0), reverse=True)[0]
    return best["url"]


def ytdl_search_info(query: str, opts: dict) -> dict:
    """Use yt-dlp only for metadata lookup (no stream extraction)."""
    with yt_dlp.YoutubeDL({**opts, "skip_download": True}) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return info


class QueueEntry:
    def __init__(self, title: str, webpage_url: str, video_id: str,
                 thumbnail: str = None, duration: int = None, uploader: str = None):
        self.title = title
        self.webpage_url = webpage_url
        self.video_id = video_id
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
        cookies_path = _setup_cookies()
        self.ytdl_opts = {
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch",
            "skip_download": True,
            "extract_flat": True,
        }
        if cookies_path:
            self.ytdl_opts["cookiefile"] = cookies_path
        status = f"loaded from {cookies_path}" if cookies_path else "not found"
        print(f"[YouTube] Cookies: {status}")

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
            for _ in range(60):
                await asyncio.sleep(5)
                if player.queue or vc.is_playing() or vc.is_paused():
                    return
            if vc.is_connected() and not vc.is_playing():
                await vc.disconnect()
            return

        entry = player.queue.popleft()
        player.current = entry

        try:
            stream_url = await piped_stream_url(entry.video_id)
        except Exception as e:
            print(f"[YouTube] Piped failed for {entry.title}: {e}")
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

    @commands.hybrid_command(name="ytcheck", description="Check YouTube cookie/Piped status")
    @commands.has_permissions(administrator=True)
    async def ytcheck(self, ctx: commands.Context):
        cookie_file = self.ytdl_opts.get("cookiefile")
        cookie_status = f"✅ `{cookie_file}` ({Path(cookie_file).stat().st_size} bytes)" \
            if cookie_file and Path(cookie_file).exists() else "❌ Not loaded"
        try:
            async with aiohttp.ClientSession() as session:
                data = await _piped_get(session, "/search?q=test&filter=videos")
            piped_status = "✅ Reachable"
        except Exception as e:
            piped_status = f"❌ {e}"
        await ctx.send(f"**Cookies:** {cookie_status}\n**Piped API:** {piped_status}", ephemeral=True)

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

        # Check if it's a URL or a search query
        video_id = _extract_video_id(query)

        try:
            if video_id:
                # Direct URL — fetch metadata from Piped
                async with aiohttp.ClientSession() as session:
                    data = await _piped_get(session, f"/streams/{video_id}")
                info = {
                    "id": video_id,
                    "title": data.get("title", "Unknown"),
                    "thumbnail": data.get("thumbnailUrl"),
                    "duration": data.get("duration"),
                    "uploader": data.get("uploader"),
                    "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
                }
            else:
                # Search query — use Piped search
                info = await piped_search(query)
        except Exception as e:
            return await ctx.send(f"Could not find that song: `{e}`")

        entry = QueueEntry(
            title=info.get("title", "Unknown"),
            webpage_url=info.get("webpage_url", ""),
            video_id=info.get("id", ""),
            thumbnail=info.get("thumbnail") or info.get("thumbnailUrl"),
            duration=info.get("duration"),
            uploader=info.get("uploader") or info.get("uploaderName"),
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
            lines = [f"`{i}.` {e.title}" for i, e in enumerate(list(player.queue)[:10], 1)]
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
