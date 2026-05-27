import asyncio
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

# Allow imports like `from db.database import ...` and `from cogs.music import ...`
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(Path(__file__).parent.parent / ".env")

COGS = [
    "cogs.music",
    "cogs.economy",
    "cogs.moderation",
    "cogs.welcome",
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class KALBot(commands.Bot):
    async def setup_hook(self):
        from db.database import init_db
        await init_db()
        for cog in COGS:
            await self.load_extension(cog)
            print(f"  Loaded: {cog}")

    async def on_ready(self):
        print(f"\nLogged in as {self.user} (ID: {self.user.id})")
        print(f"Serving {len(self.guilds)} guild(s)\n")

    async def on_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use that command.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: `{error.param.name}`. Check `!help {ctx.command}`.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Invalid argument. Check `!help {ctx.command}`.")
        elif isinstance(error, commands.CommandNotFound):
            pass
        else:
            raise error


bot = KALBot(command_prefix="!", intents=intents)


@bot.command()
async def ping(ctx: commands.Context):
    """Check the bot's latency."""
    await ctx.send(f"Pong! Latency: **{round(bot.latency * 1000)}ms**")


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set in .env")
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
