import os
import json
import sqlite3
import asyncio
from functools import wraps

import discord
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
)

from db.database import DB_PATH

_bot = None


def set_bot(bot):
    global _bot
    _bot = bot


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("WEB_SECRET_KEY", "kal-dev-secret")

    CONSOLE_PASSWORD = os.getenv("WEB_CONSOLE_PASSWORD", "admin")

    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated

    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def build_summary(plan_type, data):
        try:
            if plan_type == "commercial":
                flight = data.get("flight_number", "")
                route = data.get("route", "")
                return f"{flight} {route}".strip() or "—"
            elif plan_type == "training":
                trainee = data.get("trainee", "???")
                trainer = data.get("trainer", "???")
                return f"{trainee} / {trainer}"
            elif plan_type == "evaluation":
                examinee = data.get("examinee", "???")
                examiner = data.get("examiner", "???")
                return f"{examinee} / {examiner}"
        except Exception:
            pass
        return "—"

    def row_to_plan(row):
        d = dict(row)
        try:
            data = json.loads(d.get("data") or "{}")
        except Exception:
            data = {}
        d["data"] = data
        d["summary"] = build_summary(d.get("type", ""), data)
        return d

    # ── Auth routes ──────────────────────────────────────────────────────────

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if request.form.get("password") == CONSOLE_PASSWORD:
                session["logged_in"] = True
                return redirect(url_for("dashboard"))
            flash("Invalid password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ── Dashboard ─────────────────────────────────────────────────────────────

    @app.route("/")
    @login_required
    def dashboard():
        plan_type = request.args.get("type", "").strip()
        status = request.args.get("status", "").strip()

        query = "SELECT * FROM flight_plans WHERE 1=1"
        params = []

        if plan_type:
            query += " AND type = ?"
            params.append(plan_type)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY id DESC"

        conn = get_db()
        try:
            cur = conn.execute(query, params)
            rows = cur.fetchall()
        finally:
            conn.close()

        plans = [row_to_plan(r) for r in rows]
        return render_template(
            "dashboard.html",
            plans=plans,
            filter_type=plan_type,
            filter_status=status,
        )

    # ── Plan detail ───────────────────────────────────────────────────────────

    @app.route("/plan/<int:plan_id>")
    @login_required
    def plan_detail(plan_id):
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM flight_plans WHERE id = ?", (plan_id,)
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            flash("Plan not found.", "warning")
            return redirect(url_for("dashboard"))

        plan = row_to_plan(row)
        return render_template("plan.html", plan=plan)

    # ── Review action ─────────────────────────────────────────────────────────

    @app.route("/plan/<int:plan_id>/review", methods=["POST"])
    @login_required
    def plan_review(plan_id):
        action = request.form.get("action", "").lower()
        notes = request.form.get("notes", "").strip()

        if action not in ("approve", "reject"):
            flash("Invalid action.", "danger")
            return redirect(url_for("plan_detail", plan_id=plan_id))

        new_status = "approved" if action == "approve" else "rejected"

        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM flight_plans WHERE id = ?", (plan_id,)
            ).fetchone()
            if row is None:
                flash("Plan not found.", "warning")
                return redirect(url_for("dashboard"))

            plan = row_to_plan(row)

            conn.execute(
                """UPDATE flight_plans
                   SET status = ?, reviewed_by = 'Staff (Web Console)',
                       reviewed_at = datetime('now'), review_notes = ?
                   WHERE id = ?""",
                (new_status, notes or None, plan_id),
            )
            conn.commit()

            # Look up notification channel for this guild
            guild_id = plan.get("guild_id")
            cfg_row = conn.execute(
                "SELECT notification_channel_id FROM flightplan_config WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()
            channel_id = cfg_row["notification_channel_id"] if cfg_row else None
        finally:
            conn.close()

        # Send Discord notification asynchronously
        if _bot and channel_id:
            colour = 0x2ECC71 if new_status == "approved" else 0xE74C3C
            status_label = new_status.capitalize()
            action_word = "Approved" if new_status == "approved" else "Rejected"

            async def send_notification():
                channel = _bot.get_channel(int(channel_id))
                if channel is None:
                    return
                embed = discord.Embed(
                    title=f"✈️ Flight Plan #{plan_id} {action_word}",
                    colour=colour,
                )
                embed.add_field(
                    name="Plan Type",
                    value=plan.get("type", "—").capitalize(),
                    inline=True,
                )
                embed.add_field(
                    name="Submitted By",
                    value=plan.get("submitted_by_name", "—"),
                    inline=True,
                )
                embed.add_field(
                    name="Status",
                    value=status_label,
                    inline=True,
                )
                if notes:
                    embed.add_field(name="Notes", value=notes, inline=False)
                await channel.send(embed=embed)

            try:
                asyncio.run_coroutine_threadsafe(
                    send_notification(), _bot.loop
                )
            except Exception:
                pass

        flash(f"Plan #{plan_id} has been {new_status}.", "success")
        return redirect(url_for("plan_detail", plan_id=plan_id))

    return app
