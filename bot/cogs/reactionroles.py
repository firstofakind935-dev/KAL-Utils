import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from db.database import DB_PATH


class ReactionRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reaction_roles (
                    guild_id   INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    emoji      TEXT NOT NULL,
                    role_id    INTEGER NOT NULL,
                    PRIMARY KEY (message_id, emoji)
                )
            """)
            await db.commit()

    async def _get_role_id(self, guild_id: int, message_id: int, emoji: str) -> int | None:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT role_id FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
                (guild_id, message_id, emoji),
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row else None

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        emoji_str = str(payload.emoji)
        role_id = await self._get_role_id(payload.guild_id, payload.message_id, emoji_str)
        if role_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(role_id)
        member = guild.get_member(payload.user_id)
        if role and member:
            try:
                await member.add_roles(role, reason="Reaction role")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        emoji_str = str(payload.emoji)
        role_id = await self._get_role_id(payload.guild_id, payload.message_id, emoji_str)
        if role_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(role_id)
        member = guild.get_member(payload.user_id)
        if role and member:
            try:
                await member.remove_roles(role, reason="Reaction role removed")
            except discord.HTTPException:
                pass

    @commands.hybrid_command(name="reactionrole", description="Add a reaction role mapping to a message")
    @app_commands.describe(
        message_id="The ID of the message to attach the reaction role to",
        emoji="The emoji that triggers the role assignment",
        role="The role to assign when the emoji is reacted",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def reactionrole(
        self,
        ctx: commands.Context,
        message_id: str,
        emoji: str,
        role: discord.Role,
    ):
        try:
            msg_id = int(message_id)
        except ValueError:
            return await ctx.send("Invalid message ID.", ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO reaction_roles (guild_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?)
                   ON CONFLICT(message_id, emoji) DO UPDATE SET role_id = excluded.role_id""",
                (ctx.guild.id, msg_id, emoji, role.id),
            )
            await db.commit()
        await ctx.send(f"Reaction role added: {emoji} → {role.mention} on message `{msg_id}`.")

    @commands.hybrid_command(name="removereactionrole", description="Remove a reaction role mapping from a message")
    @app_commands.describe(
        message_id="The ID of the message to remove the reaction role from",
        emoji="The emoji to remove",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def removereactionrole(self, ctx: commands.Context, message_id: str, emoji: str):
        try:
            msg_id = int(message_id)
        except ValueError:
            return await ctx.send("Invalid message ID.", ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
                (ctx.guild.id, msg_id, emoji),
            )
            await db.commit()
        await ctx.send(f"Removed reaction role mapping for {emoji} on message `{msg_id}`.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRoles(bot))
