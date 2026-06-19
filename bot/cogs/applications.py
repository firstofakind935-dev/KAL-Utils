import asyncio
import json
import aiosqlite
import discord
from datetime import datetime, timezone
from discord import app_commands
from discord.ext import commands

from db.database import DB_PATH

KAL_BLUE = 0x00A4E4
QUESTION_COLOR = 0x9DD9E5
ANSWER_TIMEOUT = 300

STATUS_EMOJI = {
    "pending": "⏳",
    "approved": "✅",
    "rejected": "❌",
}


def application_embed(app_row: dict) -> discord.Embed:
    answers = app_row["answers"]
    if not isinstance(answers, list):
        answers = json.loads(answers)

    emoji = STATUS_EMOJI.get(app_row["status"], "❓")
    embed = discord.Embed(title=f"Application #{app_row['id']}", color=KAL_BLUE)
    embed.add_field(name="Status", value=f"{emoji} {app_row['status'].capitalize()}", inline=True)
    embed.add_field(name="Applicant", value=app_row["user_name"], inline=True)
    embed.add_field(name="Submitted At", value=app_row["submitted_at"], inline=True)
    if app_row.get("source"):
        embed.add_field(name="Applied Via", value=app_row["source"], inline=True)

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
# Setup modals
# ---------------------------------------------------------------------------

class PanelSetupModal(discord.ui.Modal, title="Application Panel Setup"):
    panel_title = discord.ui.TextInput(
        label="Embed Title",
        placeholder="e.g. ATC24 Application",
        max_length=256,
    )
    panel_description = discord.ui.TextInput(
        label="Embed Description / Info",
        style=discord.TextStyle.paragraph,
        placeholder="Tell applicants what this panel is for...",
        max_length=2000,
    )
    button_label = discord.ui.TextInput(
        label="Button Label",
        default="Apply Now",
        max_length=80,
    )

    def __init__(self, channel: discord.TextChannel, notification: discord.TextChannel | None):
        super().__init__()
        self.channel = channel
        self.notification = notification

    async def on_submit(self, interaction: discord.Interaction):
        title = self.panel_title.value.strip()
        description = self.panel_description.value.strip()
        btn_label = self.button_label.value.strip()
        notif_id = str(self.notification.id) if self.notification else None

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """INSERT INTO application_panels
                       (guild_id, title, description, button_label, notification_channel_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (interaction.guild.id, title, description, btn_label, notif_id),
            )
            panel_id = cur.lastrowid
            await db.commit()

        embed = discord.Embed(title=title, description=description, color=KAL_BLUE)
        view = ApplicationPanelView(panel_id, btn_label)
        interaction.client.add_view(view)
        await self.channel.send(embed=embed, view=view)

        notif_mention = self.notification.mention if self.notification else "not set"
        await interaction.response.send_message(
            f"Panel **#{panel_id}** posted in {self.channel.mention}!\n"
            f"Notifications → {notif_mention}\n\n"
            f"Run `/setpanelquestions {panel_id}` to add interview questions.",
            ephemeral=True,
        )


class QuestionsModal(discord.ui.Modal, title="Set Panel Questions"):
    q1 = discord.ui.TextInput(label="Question 1", required=True, max_length=300)
    q2 = discord.ui.TextInput(label="Question 2", required=False, max_length=300, default="")
    q3 = discord.ui.TextInput(label="Question 3", required=False, max_length=300, default="")
    q4 = discord.ui.TextInput(label="Question 4", required=False, max_length=300, default="")
    q5 = discord.ui.TextInput(label="Question 5", required=False, max_length=300, default="")

    def __init__(self, panel_id: int):
        super().__init__()
        self.panel_id = panel_id

    async def on_submit(self, interaction: discord.Interaction):
        questions = [
            q.value.strip()
            for q in (self.q1, self.q2, self.q3, self.q4, self.q5)
            if q.value.strip()
        ]

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM application_questions WHERE panel_id = ?",
                (self.panel_id,),
            )
            for i, text in enumerate(questions, start=1):
                await db.execute(
                    "INSERT INTO application_questions (panel_id, question_order, question_text) VALUES (?, ?, ?)",
                    (self.panel_id, i, text),
                )
            await db.commit()

        await interaction.response.send_message(
            f"Saved **{len(questions)}** question(s) for Panel #{self.panel_id}.", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Application panel view (persistent, one per panel ID)
# ---------------------------------------------------------------------------

class ApplicationPanelView(discord.ui.View):
    def __init__(self, panel_id: int, button_label: str = "Apply Now"):
        super().__init__(timeout=None)
        self.add_item(ApplyButton(panel_id, button_label))


class ApplyButton(discord.ui.Button):
    def __init__(self, panel_id: int, label: str = "Apply Now"):
        super().__init__(
            label=label,
            custom_id=f"app:panel:{panel_id}",
            style=discord.ButtonStyle.primary,
            emoji="✈️",
        )

    async def callback(self, interaction: discord.Interaction):
        panel_id = int(self.custom_id.split(":")[-1])
        cog: "Applications" = interaction.client.cogs.get("Applications")
        if cog is None:
            return await interaction.response.send_message("Bot error — please contact an admin.", ephemeral=True)

        guild = interaction.guild
        user = interaction.user

        if user.id in cog._active_interviews:
            return await interaction.response.send_message(
                "You already have an interview in progress — check your DMs.", ephemeral=True
            )

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id FROM applications WHERE guild_id = ? AND user_id = ? AND status = 'pending'",
                (guild.id, str(user.id)),
            ) as cur:
                pending = await cur.fetchone()

            async with db.execute(
                "SELECT title, notification_channel_id FROM application_panels WHERE id = ?",
                (panel_id,),
            ) as cur:
                panel_row = await cur.fetchone()

            async with db.execute(
                "SELECT question_text FROM application_questions WHERE panel_id = ? ORDER BY question_order",
                (panel_id,),
            ) as cur:
                q_rows = await cur.fetchall()

        if pending:
            return await interaction.response.send_message(
                f"You already have a pending application (`#{pending[0]}`). "
                "Please wait for it to be reviewed before applying again.",
                ephemeral=True,
            )

        if not panel_row:
            return await interaction.response.send_message(
                "This panel no longer exists. Please contact an admin.", ephemeral=True
            )

        panel_title, notif_channel_id = panel_row
        questions = [r[0] for r in q_rows]

        if not questions:
            return await interaction.response.send_message(
                "No questions have been set up for this panel yet. Ask an admin to run `/setpanelquestions`.",
                ephemeral=True,
            )

        try:
            intro = discord.Embed(
                title="✈️ Korean Air Application",
                description=(
                    f"Welcome! I'll ask you **{len(questions)} question(s)**.\n"
                    f"Reply to each one in this DM. You have "
                    f"**{ANSWER_TIMEOUT // 60} minutes** per question.\n\n"
                    "Type `cancel` at any time to abort."
                ),
                color=KAL_BLUE,
            )
            await user.send(embed=intro)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "I couldn't DM you. Enable **Direct Messages** from server members "
                "in your privacy settings, then try again.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            "📬 Check your DMs — your application interview has started!", ephemeral=True
        )

        cog._active_interviews.add(user.id)
        try:
            await cog._run_interview(user, guild, questions, panel_title, notif_channel_id)
        finally:
            cog._active_interviews.discard(user.id)


# ---------------------------------------------------------------------------
# Review UI
# ---------------------------------------------------------------------------

class RejectReasonModal(discord.ui.Modal, title="Reject Application"):
    reason = discord.ui.TextInput(
        label="Reason for Denial",
        style=discord.TextStyle.paragraph,
        placeholder="Why is this application being rejected?",
        required=True,
        max_length=1000,
    )

    def __init__(self, app_id, user_id, user_name, cog, review_view, original_message):
        super().__init__()
        self.app_id = app_id
        self.user_id = user_id
        self.user_name = user_name
        self.cog = cog
        self.review_view = review_view
        self.original_message = original_message

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason.value.strip()
        reviewer = interaction.user.display_name

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """UPDATE applications
                   SET status='rejected', reviewed_by=?, reviewed_at=datetime('now'), review_notes=?
                   WHERE id=?""",
                (reviewer, reason, self.app_id),
            )
            await db.commit()

        try:
            applicant = await self.cog.bot.fetch_user(int(self.user_id))
            dm_embed = discord.Embed(
                title="Rejected",
                description=(
                    "Your application for the Korean24 Program has been rejected. "
                    "Please do not be disheartened. "
                    "You can always come back and apply again."
                ),
                color=0xE74C3C,
            )
            dm_embed.add_field(name="Reason For Denial", value=reason, inline=False)
            await applicant.send(embed=dm_embed)
        except Exception:
            pass

        result_embed = discord.Embed(
            title=f"Application #{self.app_id} — ❌ Rejected",
            color=0xE74C3C,
        )
        result_embed.add_field(name="Applicant", value=self.user_name, inline=True)
        result_embed.add_field(name="Reviewed By", value=reviewer, inline=True)
        result_embed.add_field(name="Reason", value=reason, inline=False)

        for item in self.review_view.children:
            item.disabled = True
        try:
            await self.original_message.edit(embed=result_embed, view=self.review_view)
        except Exception:
            pass

        await interaction.response.send_message(
            f"Application #{self.app_id} rejected.", ephemeral=True
        )


class ApplicationReviewView(discord.ui.View):
    def __init__(self, app_id, user_id, user_name, cog):
        super().__init__(timeout=None)
        self.app_id = app_id
        self.user_id = user_id
        self.user_name = user_name
        self.cog = cog

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        reviewer = interaction.user.display_name

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """UPDATE applications
                   SET status='approved', reviewed_by=?, reviewed_at=datetime('now')
                   WHERE id=?""",
                (reviewer, self.app_id),
            )
            await db.commit()

        try:
            applicant = await self.cog.bot.fetch_user(int(self.user_id))
            dm_embed = discord.Embed(
                title="Accepted",
                description=(
                    "Congratulations! Your application for the Korean24 Program has been accepted.\n\n"
                    "Please proceed to the Pilot Hub, where you'll find all the information and "
                    "resources you need to begin your journey. We look forward to seeing you in the "
                    "skies, happy flying!"
                ),
                color=0x2ECC71,
            )
            await applicant.send(embed=dm_embed)
        except Exception:
            pass

        result_embed = discord.Embed(
            title=f"Application #{self.app_id} — ✅ Approved",
            color=0x2ECC71,
        )
        result_embed.add_field(name="Applicant", value=self.user_name, inline=True)
        result_embed.add_field(name="Reviewed By", value=reviewer, inline=True)

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=result_embed, view=self)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RejectReasonModal(
            self.app_id, self.user_id, self.user_name,
            self.cog, self, interaction.message,
        )
        await interaction.response.send_modal(modal)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Applications(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active_interviews: set[int] = set()

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
                    source        TEXT,
                    reviewed_by   TEXT,
                    reviewed_at   TEXT,
                    review_notes  TEXT
                )
            """)
            try:
                await db.execute("ALTER TABLE applications ADD COLUMN source TEXT")
            except Exception:
                pass

            # Migrate old single-panel schema (guild_id PK) to multi-panel (id PK)
            try:
                await db.execute("SELECT id FROM application_panels LIMIT 1")
            except Exception:
                await db.execute("DROP TABLE IF EXISTS application_panels")
                await db.execute("DROP TABLE IF EXISTS application_questions")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS application_panels (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id                INTEGER NOT NULL,
                    title                   TEXT NOT NULL,
                    description             TEXT NOT NULL DEFAULT '',
                    button_label            TEXT NOT NULL DEFAULT 'Apply Now',
                    notification_channel_id TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS application_questions (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    panel_id       INTEGER NOT NULL,
                    question_order INTEGER NOT NULL,
                    question_text  TEXT    NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS applications_config (
                    guild_id                INTEGER PRIMARY KEY,
                    notification_channel_id TEXT
                )
            """)
            await db.commit()

            async with db.execute(
                "SELECT id, button_label FROM application_panels"
            ) as cur:
                panels = await cur.fetchall()

        for panel_id, btn_label in panels:
            self.bot.add_view(ApplicationPanelView(panel_id, btn_label))

    async def _run_interview(
        self,
        user: discord.User,
        guild: discord.Guild,
        questions: list,
        source: str = "",
        notification_channel_id: str | None = None,
    ):
        def check(m: discord.Message) -> bool:
            return m.author.id == user.id and m.guild is None

        answers = []
        for i, question in enumerate(questions, start=1):
            q_embed = discord.Embed(
                title=f"Question {i} of {len(questions)}",
                description=question,
                color=QUESTION_COLOR,
            )
            await user.send(embed=q_embed)

            try:
                reply = await self.bot.wait_for("message", check=check, timeout=ANSWER_TIMEOUT)
            except asyncio.TimeoutError:
                await user.send(embed=discord.Embed(
                    title="⏰ Application Timed Out",
                    description="You took too long to answer. Click the Apply button in the server to start over.",
                    color=0xE74C3C,
                ))
                return

            content = reply.content.strip()
            if content.lower() == "cancel":
                await user.send(embed=discord.Embed(
                    title="❌ Application Cancelled",
                    description="Your application has been cancelled and is not sent to the team for review.",
                    color=0xE74C3C,
                ))
                return

            answers.append({"question": question, "answer": content[:1000]})

        confirm_embed = discord.Embed(
            title="📋 Ready to Submit",
            description=(
                "You've answered all the questions.\n"
                "Press **Submit** to send your application, or **Cancel** to discard it."
            ),
            color=QUESTION_COLOR,
        )

        class ConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=120)
                self.choice: str | None = None

            @discord.ui.button(label="Submit", style=discord.ButtonStyle.success)
            async def submit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.choice = "submit"
                self.stop()
                await interaction.response.defer()

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
            async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.choice = "cancel"
                self.stop()
                await interaction.response.defer()

        view = ConfirmView()
        confirm_msg = await user.send(embed=confirm_embed, view=view)
        await view.wait()

        for item in view.children:
            item.disabled = True
        await confirm_msg.edit(view=view)

        if view.choice != "submit":
            await user.send(embed=discord.Embed(
                title="Cancelled",
                description="Your application has been cancelled and is not sent to the team for review.",
                color=0xE74C3C,
            ))
            return

        submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        answers_json = json.dumps(answers, ensure_ascii=False)

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """INSERT INTO applications (guild_id, user_id, user_name, submitted_at, status, answers, source)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                (guild.id, str(user.id), user.display_name, submitted_at, answers_json, source),
            )
            app_id = cursor.lastrowid
            await db.commit()

            if not notification_channel_id:
                async with db.execute(
                    "SELECT notification_channel_id FROM applications_config WHERE guild_id = ?",
                    (guild.id,),
                ) as cur:
                    row = await cur.fetchone()
                    notification_channel_id = row[0] if row else None

        await user.send(embed=discord.Embed(
            title="Submitted",
            description=(
                "Your application has been successfully submitted and is now pending review. "
                "Please allow up to 24 hours for our team to process your application.\n\n"
                "You will receive a direct message from me once a decision has been made. "
                "To help us manage applications efficiently, please do not make a ticket, "
                "DM, or contact staff members regarding the status of your application."
            ),
            color=QUESTION_COLOR,
        ))

        if notification_channel_id:
            channel = guild.get_channel(int(notification_channel_id))
            if channel:
                app_row = {
                    "id": app_id,
                    "guild_id": guild.id,
                    "user_id": str(user.id),
                    "user_name": user.display_name,
                    "submitted_at": submitted_at,
                    "status": "pending",
                    "answers": answers,
                    "source": source,
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "review_notes": None,
                }
                notify_embed = application_embed(app_row)
                notify_embed.set_author(
                    name="New Application Submitted",
                    icon_url=user.display_avatar.url,
                )
                review_view = ApplicationReviewView(app_id, str(user.id), user.display_name, self)
                try:
                    await channel.send(embed=notify_embed, view=review_view)
                except discord.Forbidden:
                    pass

    # -----------------------------------------------------------------------
    # Commands
    # -----------------------------------------------------------------------

    @commands.hybrid_command(
        name="postapplicationpanel",
        description="[Admin] Post a new application panel embed with button",
    )
    @app_commands.describe(
        channel="Channel to post the panel in",
        notification="Channel where new submissions are posted for staff review",
    )
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    @commands.guild_only()
    async def postapplicationpanel(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        notification: discord.TextChannel = None,
    ):
        if ctx.interaction is None:
            await ctx.send("Please use the slash command `/postapplicationpanel`.", ephemeral=True)
            return
        await ctx.interaction.response.send_modal(PanelSetupModal(channel, notification))

    @commands.hybrid_command(
        name="setpanelquestions",
        description="[Admin] Set interview questions for a specific panel",
    )
    @app_commands.describe(panel_id="Panel ID shown when you ran /postapplicationpanel")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    @commands.guild_only()
    async def setpanelquestions(self, ctx: commands.Context, panel_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT title FROM application_panels WHERE id = ? AND guild_id = ?",
                (panel_id, ctx.guild.id),
            ) as cur:
                row = await cur.fetchone()

        if not row:
            await ctx.send(f"Panel #{panel_id} not found in this server.", ephemeral=True)
            return

        if ctx.interaction is None:
            await ctx.send("Please use the slash command `/setpanelquestions`.", ephemeral=True)
            return

        await ctx.interaction.response.send_modal(QuestionsModal(panel_id))

    @commands.hybrid_command(
        name="listpanels",
        description="[Admin] List all application panels in this server",
    )
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    @commands.guild_only()
    async def listpanels(self, ctx: commands.Context):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id, title, button_label, notification_channel_id FROM application_panels WHERE guild_id = ?",
                (ctx.guild.id,),
            ) as cur:
                rows = await cur.fetchall()

        if not rows:
            await ctx.send(
                "No panels yet. Use `/postapplicationpanel` to create one.", ephemeral=True
            )
            return

        embed = discord.Embed(title="Application Panels", color=KAL_BLUE)
        for panel_id, title, btn_label, notif_id in rows:
            notif = f"<#{notif_id}>" if notif_id else "not set"
            embed.add_field(
                name=f"#{panel_id} — {title}",
                value=f"Button: **{btn_label}** | Notifications: {notif}\n`/setpanelquestions {panel_id}` to edit questions",
                inline=False,
            )
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="setapplicationchannel",
        description="[Admin] Set a fallback notification channel for all panels",
    )
    @app_commands.describe(channel="Channel to receive application notifications")
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def setapplicationchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO applications_config (guild_id, notification_channel_id)
                   VALUES (?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET notification_channel_id = excluded.notification_channel_id""",
                (ctx.guild.id, str(channel.id)),
            )
            await db.commit()
        await ctx.send(
            f"Fallback application notifications → {channel.mention}.", ephemeral=True
        )

    @commands.hybrid_command(
        name="myapplication",
        description="View the status of your most recent application",
    )
    @commands.guild_only()
    async def myapplication(self, ctx: commands.Context):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM applications WHERE guild_id = ? AND user_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (ctx.guild.id, str(ctx.author.id)),
            ) as cur:
                row = await cur.fetchone()

        if row is None:
            await ctx.send(
                "You haven't submitted an application yet. Click an Apply button in the applications channel.",
                ephemeral=True,
            )
            return

        embed = application_embed(dict(row))
        await ctx.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Applications(bot))
