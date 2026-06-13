import asyncio
import json
import aiosqlite
import discord
from datetime import datetime, timezone
from discord import app_commands
from discord.ext import commands

from db.database import DB_PATH

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KAL_BLUE = 0x00A4E4
QUESTION_COLOR = 0x9DD9E5

STATUS_EMOJI = {
    "pending": "⏳",
    "approved": "✅",
    "rejected": "❌",
}

# (dm_text, plain_text) — dm_text may contain Discord markdown, plain_text is
# what gets stored and shown in embeds / the web console.
QUESTIONS = [
    ("What is your roblox username?",
     "What is your roblox username?"),
    ("Do you have the ATC24 Role on the ATC24 Server?",
     "Do you have the ATC24 Role on the ATC24 Server?"),
    ("Do you promise to only use Korean Air to log flights?",
     "Do you promise to only use Korean Air to log flights?"),
    ("Will you log flights __**outside**__ of ATC24?",
     "Will you log flights outside of ATC24?"),
    ("How many PTFS Minutes do you have?",
     "How many PTFS Minutes do you have?"),
]

ANSWER_TIMEOUT = 300  # seconds the applicant has to answer each question


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def application_embed(app_row: dict) -> discord.Embed:
    """Build a discord.Embed for an application from a DB row dict."""
    answers = app_row["answers"]
    if not isinstance(answers, list):
        answers = json.loads(answers)

    emoji = STATUS_EMOJI.get(app_row["status"], "❓")

    embed = discord.Embed(
        title=f"Application #{app_row['id']}",
        color=KAL_BLUE,
    )
    embed.add_field(name="Status", value=f"{emoji} {app_row['status'].capitalize()}", inline=True)
    embed.add_field(name="Applicant", value=app_row["user_name"], inline=True)
    embed.add_field(name="Submitted At", value=app_row["submitted_at"], inline=True)

    for i, qa in enumerate(answers, start=1):
        embed.add_field(
            name=f"Q{i}. {qa['question']}",
            value=(qa["answer"] or "—")[:1024],
            inline=False,
        )

    if app_row.get("reviewed_by"):
        embed.add_field(name="Reviewed By", value=app_row["reviewed_by"], inline=True)
    if app_row.get("reviewed_at"):
        embed.add_field(name="Reviewed At", value=app_row["reviewed_at"], inline=True)
    if app_row.get("review_notes"):
        embed.add_field(name="Review Notes", value=app_row["review_notes"], inline=False)

    embed.set_footer(text=f"Application ID: {app_row['id']}")
    return embed


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Applications(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active_interviews: set[int] = set()

    # -----------------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------------

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id      INTEGER NOT NULL,
                    user_id       TEXT    NOT NULL,
                    user_name     TEXT    NOT NULL,
                    submitted_at  TEXT    NOT NULL,
                    status        TEXT    NOT NULL DEFAULT 'pending',
                    answers       TEXT    NOT NULL,
                    reviewed_by   TEXT,
                    reviewed_at   TEXT,
                    review_notes  TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS applications_config (
                    guild_id                 INTEGER PRIMARY KEY,
                    notification_channel_id  TEXT
                )
            """)
            await db.commit()

    # -----------------------------------------------------------------------
    # Commands
    # -----------------------------------------------------------------------

    @commands.hybrid_command(
        name="apply",
        description="Apply to Korean Air — the bot will interview you in your DMs",
    )
    @commands.guild_only()
    async def apply(self, ctx: commands.Context):
        """Start the application interview in the user's DMs."""
        user = ctx.author

        if user.id in self._active_interviews:
            await ctx.send(
                "You already have an application interview in progress — check your DMs.",
                ephemeral=True,
            )
            return

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id FROM applications WHERE guild_id = ? AND user_id = ? AND status = 'pending'",
                (ctx.guild.id, str(user.id)),
            ) as cur:
                pending = await cur.fetchone()

        if pending:
            await ctx.send(
                f"You already have a pending application (`#{pending[0]}`). "
                "Please wait for it to be reviewed before applying again.",
                ephemeral=True,
            )
            return

        # Open the DM channel first so we can fail fast if DMs are closed
        try:
            intro = discord.Embed(
                title="✈️ Korean Air Application",
                description=(
                    f"Welcome! I'll ask you **{len(QUESTIONS)} questions**.\n"
                    f"Reply to each one in this DM. You have "
                    f"**{ANSWER_TIMEOUT // 60} minutes** per question.\n"
                    "Type `cancel` at any time to abort."
                ),
                color=KAL_BLUE,
            )
            await user.send(embed=intro)
        except discord.Forbidden:
            await ctx.send(
                "I couldn't DM you. Please enable **Direct Messages** from server "
                "members in your privacy settings, then run `/apply` again.",
                ephemeral=True,
            )
            return

        await ctx.send("📬 Check your DMs — your application interview has started!", ephemeral=True)

        self._active_interviews.add(user.id)
        try:
            await self._run_interview(user, ctx.guild)
        finally:
            self._active_interviews.discard(user.id)

    async def _run_interview(self, user: discord.User, guild: discord.Guild):
        """Ask each question in DM, collect answers, then store and notify."""

        def check(m: discord.Message) -> bool:
            return m.author.id == user.id and m.guild is None

        answers = []
        for i, (dm_text, plain_text) in enumerate(QUESTIONS, start=1):
            q_embed = discord.Embed(
                title=f"Question {i}",
                description=dm_text,
                color=QUESTION_COLOR,
            )
            await user.send(embed=q_embed)
            try:
                reply = await self.bot.wait_for("message", check=check, timeout=ANSWER_TIMEOUT)
            except asyncio.TimeoutError:
                timeout_embed = discord.Embed(
                    title="⏰ Application Timed Out",
                    description="You took too long to answer. Run `/apply` in the server to start over.",
                    color=0xE74C3C,
                )
                await user.send(embed=timeout_embed)
                return

            content = reply.content.strip()
            if content.lower() == "cancel":
                cancel_embed = discord.Embed(
                    title="❌ Application Cancelled",
                    description="Run `/apply` in the server to start over.",
                    color=0xE74C3C,
                )
                await user.send(embed=cancel_embed)
                return

            answers.append({"question": plain_text, "answer": content[:1000]})

        submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        answers_json = json.dumps(answers, ensure_ascii=False)

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """
                INSERT INTO applications
                    (guild_id, user_id, user_name, submitted_at, status, answers)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (guild.id, str(user.id), user.display_name, submitted_at, answers_json),
            )
            app_id = cursor.lastrowid
            await db.commit()

            async with db.execute(
                "SELECT notification_channel_id FROM applications_config WHERE guild_id = ?",
                (guild.id,),
            ) as cur:
                row = await cur.fetchone()
                notification_channel_id = row[0] if row else None

        app_row = {
            "id": app_id,
            "guild_id": guild.id,
            "user_id": str(user.id),
            "user_name": user.display_name,
            "submitted_at": submitted_at,
            "status": "pending",
            "answers": answers,
            "reviewed_by": None,
            "reviewed_at": None,
            "review_notes": None,
        }

        confirm = application_embed(app_row)
        confirm.title = f"✅ Application #{app_id} Submitted"
        confirm.description = "Your application is **pending review**. You'll receive a DM when a decision is made."
        await user.send(embed=confirm)

        if notification_channel_id:
            channel = guild.get_channel(int(notification_channel_id))
            if channel:
                notify_embed = application_embed(app_row)
                notify_embed.set_author(
                    name="New Application Submitted",
                    icon_url=user.display_avatar.url,
                )
                try:
                    await channel.send(embed=notify_embed)
                except discord.Forbidden:
                    pass

    @commands.hybrid_command(
        name="myapplication",
        description="View the status of your most recent application",
    )
    @commands.guild_only()
    async def myapplication(self, ctx: commands.Context):
        """Show the caller's most recent application (ephemeral)."""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM applications
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (ctx.guild.id, str(ctx.author.id)),
            ) as cur:
                row = await cur.fetchone()

        if row is None:
            await ctx.send("You haven't submitted an application yet. Use `/apply` to start.", ephemeral=True)
            return

        embed = application_embed(dict(row))
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="setapplicationchannel",
        description="[Admin] Set the channel where applications are posted",
    )
    @app_commands.describe(channel="The text channel to receive application notifications")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def setapplicationchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Save the notification channel for application submissions and decisions."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO applications_config (guild_id, notification_channel_id)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET notification_channel_id = excluded.notification_channel_id
                """,
                (ctx.guild.id, str(channel.id)),
            )
            await db.commit()

        await ctx.send(
            f"Application notifications will now be posted to {channel.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Applications(bot))
