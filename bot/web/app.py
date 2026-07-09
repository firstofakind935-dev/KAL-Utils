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
    APPS_PASSWORD = os.getenv("APPS_CONSOLE_PASSWORD", "apps")

    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated

    def apps_login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("apps_logged_in"):
                return redirect(url_for("apps_login"))
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

    # ── Public schedule ───────────────────────────────────────────────────────

    @app.route("/schedule")
    def schedule():
        conn = get_db()
        try:
            rows = conn.execute(
                """SELECT data, submitted_by_name FROM flight_plans
                   WHERE type = 'commercial' AND status = 'approved'
                   ORDER BY id DESC""",
            ).fetchall()
        finally:
            conn.close()

        flights = []
        for row in rows:
            try:
                data = json.loads(row["data"])
            except Exception:
                data = {}
            flights.append({
                "flight_number": data.get("flight_number", "—"),
                "route":         data.get("route", "—"),
                "aircraft":      data.get("aircraft", "—"),
                "departure_time": data.get("departure_time", "—"),
                "submitted_by_name": row["submitted_by_name"],
            })

        return render_template("schedule.html", flights=flights)

    # ── Auth routes ───────────────────────────────────────────────────────────

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

    # ── Delete action ────────────────────────────────────────────────────────

    @app.route("/plan/<int:plan_id>/delete", methods=["POST"])
    @login_required
    def plan_delete(plan_id):
        conn = get_db()
        try:
            conn.execute("DELETE FROM flight_plans WHERE id = ?", (plan_id,))
            conn.commit()
        finally:
            conn.close()

        flash(f"Flight Plan #{plan_id} has been permanently deleted.", "success")
        return redirect(url_for("dashboard"))

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

    # ════════════════════════════════════════════════════════════════════════
    # Applications section (separate password)
    # ════════════════════════════════════════════════════════════════════════

    def row_to_application(row):
        d = dict(row)
        try:
            d["answers"] = json.loads(d.get("answers") or "[]")
        except Exception:
            d["answers"] = []
        return d

    @app.route("/applications/login", methods=["GET", "POST"])
    def apps_login():
        if request.method == "POST":
            if request.form.get("password") == APPS_PASSWORD:
                session["apps_logged_in"] = True
                return redirect(url_for("applications"))
            flash("Invalid password.", "danger")
        return render_template("apps_login.html")

    @app.route("/applications/logout")
    def apps_logout():
        session.pop("apps_logged_in", None)
        return redirect(url_for("apps_login"))

    @app.route("/applications")
    @apps_login_required
    def applications():
        status = request.args.get("status", "").strip()

        query = "SELECT * FROM applications WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY id DESC"

        conn = get_db()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        apps = [row_to_application(r) for r in rows]
        return render_template("applications.html", apps=apps, filter_status=status)

    @app.route("/applications/<int:app_id>")
    @apps_login_required
    def application_detail(app_id):
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM applications WHERE id = ?", (app_id,)
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            flash("Application not found.", "warning")
            return redirect(url_for("applications"))

        return render_template("application.html", application=row_to_application(row))

    @app.route("/applications/<int:app_id>/review", methods=["POST"])
    @apps_login_required
    def application_review(app_id):
        action = request.form.get("action", "").lower()
        notes = request.form.get("notes", "").strip()

        if action not in ("approve", "reject"):
            flash("Invalid action.", "danger")
            return redirect(url_for("application_detail", app_id=app_id))

        if action == "reject" and not notes:
            flash("A reason for denial is required when rejecting an application.", "danger")
            return redirect(url_for("application_detail", app_id=app_id))

        new_status = "approved" if action == "approve" else "rejected"

        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM applications WHERE id = ?", (app_id,)
            ).fetchone()
            if row is None:
                flash("Application not found.", "warning")
                return redirect(url_for("applications"))

            application = row_to_application(row)

            conn.execute(
                """UPDATE applications
                   SET status = ?, reviewed_by = 'Staff (Web Console)',
                       reviewed_at = datetime('now'), review_notes = ?
                   WHERE id = ?""",
                (new_status, notes or None, app_id),
            )
            conn.commit()

            cfg_row = conn.execute(
                "SELECT notification_channel_id FROM applications_config WHERE guild_id = ?",
                (application.get("guild_id"),),
            ).fetchone()
            channel_id = cfg_row["notification_channel_id"] if cfg_row else None
        finally:
            conn.close()

        if _bot:
            colour = 0x2ECC71 if new_status == "approved" else 0xE74C3C
            action_word = "Approved" if new_status == "approved" else "Rejected"
            user_id = application.get("user_id")

            async def send_notifications():
                embed = discord.Embed(
                    title=f"📋 Application #{app_id} {action_word}",
                    colour=colour,
                )
                embed.add_field(
                    name="Applicant",
                    value=application.get("user_name", "—"),
                    inline=True,
                )
                embed.add_field(name="Status", value=action_word, inline=True)
                if notes:
                    embed.add_field(name="Notes", value=notes, inline=False)

                # DM the applicant
                if user_id:
                    try:
                        user = await _bot.fetch_user(int(user_id))
                        if new_status == "approved":
                            dm_embed = discord.Embed(
                                title="Accepted",
                                description=(
                                    "Congratulations! Your application for the Korean24 Program "
                                    "has been accepted.\n\n"
                                    "Please proceed to the Pilot Hub, where you'll find all the "
                                    "information and resources you need to begin your journey. "
                                    "We look forward to seeing you in the skies, happy flying!"
                                ),
                                colour=0x2ECC71,
                            )
                        else:
                            dm_embed = discord.Embed(
                                title="Rejected",
                                description=(
                                    "Your application for the Korean24 Program has been rejected. "
                                    "Please do not be disheartened. "
                                    "You can always come back and apply again."
                                ),
                                colour=0xE74C3C,
                            )
                            dm_embed.add_field(
                                name="Reason For Denial",
                                value=notes,
                                inline=False,
                            )
                        await user.send(embed=dm_embed)
                    except Exception:
                        pass

                # Post to the staff channel
                if channel_id:
                    channel = _bot.get_channel(int(channel_id))
                    if channel:
                        try:
                            await channel.send(embed=embed)
                        except Exception:
                            pass

            try:
                asyncio.run_coroutine_threadsafe(send_notifications(), _bot.loop)
            except Exception:
                pass

        flash(f"Application #{app_id} has been {new_status}.", "success")
        return redirect(url_for("application_detail", app_id=app_id))

    @app.route("/applications/<int:app_id>/delete", methods=["POST"])
    @apps_login_required
    def application_delete(app_id):
        conn = get_db()
        try:
            conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
            conn.commit()
        finally:
            conn.close()

        flash(f"Application #{app_id} has been permanently deleted.", "success")
        return redirect(url_for("applications"))

    return app
