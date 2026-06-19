import asyncio
import os
import sys
import threading
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(Path(__file__).parent.parent / ".env")

COGS = [
    "cogs.music",
    "cogs.economy",
    "cogs.moderation",
    "cogs.welcome",
    "cogs.events",
    "cogs.tickets",
    "cogs.youtube",
    "cogs.flightplan",
    "cogs.applications",
    "cogs.security",
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guild_scheduled_events = True


class KALBot(commands.Bot):
    async def setup_hook(self):
        from db.database import init_db
        await init_db()
        for cog in COGS:
            try:
                await self.load_extension(cog)
                print(f"  [OK] Loaded: {cog}")
            except Exception as e:
                print(f"  [ERROR] Failed to load {cog}: {e}")
        cmds = self.tree.get_commands()
        print(f"  Commands in tree: {[c.name for c in cmds]}")

    async def on_ready(self):
        print(f"\nLogged in as {self.user} (ID: {self.user.id})")
        print(f"Serving {len(self.guilds)} guild(s)")

        if getattr(self, "_synced", False):
            return
        self._synced = True

        # Remove any guild-specific command overrides — these cause duplicates
        # when Discord also has the global commands registered.
        for guild in self.guilds:
            try:
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"  Cleared guild overrides: {guild.name}")
            except Exception as e:
                print(f"  [WARN] Could not clear guild overrides for {guild.name}: {e}")

        # Sync commands globally (single source of truth)
        try:
            synced = await self.tree.sync()
            print(f"  Synced {len(synced)} commands globally")
        except Exception as e:
            print(f"  [ERROR] Global sync failed: {e}")
        print()

    async def on_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use that command.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: `{error.param.name}`. Check `/help` or `!help`.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Invalid argument. Check `/help` or `!help`.")
        elif isinstance(error, commands.CommandNotFound):
            pass
        elif isinstance(error, commands.CommandInvokeError):
            await ctx.send(f"Something went wrong: `{error.original}`")

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        msg = "You don't have permission to use that command." \
            if isinstance(error, app_commands.MissingPermissions) \
            else f"An error occurred: `{error}`"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


bot = KALBot(command_prefix="!", intents=intents)


@bot.hybrid_command(name="ping", description="Check the bot's latency")
async def ping(ctx: commands.Context):
    """Check the bot's latency."""
    await ctx.send(f"Pong! Latency: **{round(bot.latency * 1000)}ms**")


@bot.hybrid_command(name="sync", description="[Admin] Clear duplicate commands and re-sync globally")
@commands.has_permissions(administrator=True)
@app_commands.default_permissions(administrator=True)
async def sync(ctx: commands.Context):
    # Remove guild-specific overrides for every guild the bot is in
    for guild in bot.guilds:
        try:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)
        except Exception:
            pass
    # Re-sync globally as the single source of truth
    synced = await bot.tree.sync()
    await ctx.send(f"Cleared guild overrides and synced {len(synced)} commands globally.", ephemeral=True)


def _start_web(bot_instance):
    from web.app import create_app, set_bot
    set_bot(bot_instance)
    app = create_app()
    port = int(os.getenv("PORT", 8080))
    print(f"[Web] Starting staff console on port {port}")
    app.run(host="0.0.0.0", port=port, use_reloader=False)


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set in .env")
    web_thread = threading.Thread(target=_start_web, args=(bot,), daemon=True)
    web_thread.start()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
