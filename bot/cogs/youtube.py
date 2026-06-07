import asyncio
import os
from collections import deque
from pathlib import Path

import discord
import imageio_ffmpeg
import yt_dlp
from discord import app_commands
from discord.ext import commands

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
COOKIES_PATH = "/tmp/yt_cookies.txt"

def _setup_cookies() -> str | None:
    """Write cookies to a fixed temp path. Returns path if cookies exist, else None."""
    env_cookies = os.getenv("YOUTUBE_COOKIES")
    if env_cookies:
        with open(COOKIES_PATH, "w") as f:
            f.write(env_cookies)
        return COOKIES_PATH
    local = Path(__file__).resolve().parent.parent.parent / "cookies.txt"
    if local.exists():
        return str(local)
    return None

def _make_ytdl_opts(cookies_path: str | None) -> dict:
    opts = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch",
        "source_address": "0.0.0.0",
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "check_formats": False,
    }
    if cookies_path:
        opts["cookiefile"] = cookies_path
    return opts

FFMPEG_OPTIONS = {
    "executable": FFMPEG_EXE,
    "before_options": "-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -af aresample=48000",
}


def fetch_info(query: str, opts: dict) -> dict:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return info


def fetch_stream_url(webpage_url: str, opts: dict) -> str:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(webpage_url, download=False)
        if "entries" in info:
            info = info["entries"][0]
        formats = info.get("formats", [])
        # Prefer audio-only formats sorted by quality
        audio = [f for f in formats if f.get("vcodec") == "none" and f.get("url")]
        if audio:
            return audio[-1]["url"]
        # Fall back to any format with a direct URL
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
        cookies_path = _setup_cookies()
        self.ytdl_opts = _make_ytdl_opts(cookies_path)
        print(f"[YouTube] Cookies: {'loaded from ' + cookies_path if cookies_path else 'NOT found — YouTube may block playback'}")

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
            # Disconnect after 5 minutes of inactivity
            for _ in range(60):
                await asyncio.sleep(5)
                if player.queue or (vc.is_playing() or vc.is_paused()):
                    return  # new song was added, let it handle advancing
            if vc.is_connected() and not vc.is_playing():
                await vc.disconnect()
            return

        entry = player.queue.popleft()
        player.current = entry

        try:
            # Re-fetch a fresh URL right before playing
            stream_url = await asyncio.get_running_loop().run_in_executor(
                None, fetch_stream_url, entry.webpage_url, self.ytdl_opts
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

    @commands.hybrid_command(name="ytcheck", description="Check YouTube cookie status")
    @commands.has_permissions(administrator=True)
    async def ytcheck(self, ctx: commands.Context):
        cookie_file = self.ytdl_opts.get("cookiefile")
        if cookie_file and Path(cookie_file).exists():
            size = Path(cookie_file).stat().st_size
            await ctx.send(f"✅ Cookies loaded from `{cookie_file}` ({size} bytes)", ephemeral=True)
        else:
            env_set = bool(os.getenv("YOUTUBE_COOKIES"))
            await ctx.send(
                f"❌ No cookies file found.\n"
                f"`YOUTUBE_COOKIES` env var: {'set but file missing' if env_set else 'not set'}\n"
                f"Local cookies.txt: {'not found' if not Path(COOKIES_PATH).exists() else 'found'}",
                ephemeral=True,
            )

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
            info = await asyncio.get_running_loop().run_in_executor(None, fetch_info, query, self.ytdl_opts)
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
