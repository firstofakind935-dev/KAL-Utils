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
            await self.load_extension(cog)
            print(f"  Loaded: {cog}")
        await self.tree.sync()
        print("  Synced slash commands")

    async def on_ready(self):
        print(f"\nLogged in as {self.user} (ID: {self.user.id})")
        print(f"Serving {len(self.guilds)} guild(s)\n")

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


@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def sync(ctx: commands.Context):
    """Clear guild command overrides (fixes duplicates) and re-sync globally."""
    # Wipe guild-specific overrides that cause double commands
    bot.tree.clear_commands(guild=ctx.guild)
    await bot.tree.sync(guild=ctx.guild)
    # Push fresh global list
    synced = await bot.tree.sync()
    await ctx.send(f"Cleared guild overrides and synced {len(synced)} commands globally!")


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
