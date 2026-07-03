import discord
from enum import IntEnum
from functools import wraps


class PermLevel(IntEnum):
    MEMBER = 1
    MOD = 2
    ADMIN = 3
    OWNER = 4


async def get_perm_level(interaction: discord.Interaction) -> PermLevel:
    guild = interaction.guild
    user = interaction.user

    if not guild:
        return PermLevel.MEMBER

    if guild.owner_id == user.id:
        return PermLevel.OWNER

    member = guild.get_member(user.id) or await guild.fetch_member(user.id)

    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return PermLevel.ADMIN

    bot_admin_role = discord.utils.get(guild.roles, name="BridgeBot Admin")
    if bot_admin_role and bot_admin_role in member.roles:
        return PermLevel.ADMIN

    if member.guild_permissions.manage_messages:
        return PermLevel.MOD

    bot_mod_role = discord.utils.get(guild.roles, name="BridgeBot Mod")
    if bot_mod_role and bot_mod_role in member.roles:
        return PermLevel.MOD

    return PermLevel.MEMBER


def require_perm(level: PermLevel):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            user_level = await get_perm_level(interaction)

            if user_level < level:
                labels = {
                    PermLevel.MOD: "**BridgeBot Mod** or higher",
                    PermLevel.ADMIN: "**Server Admin** (Manage Server) or higher",
                    PermLevel.OWNER: "**Server Owner**",
                }
                await interaction.response.send_message(
                    f"❌ You need {labels.get(level, 'higher permissions')} to use this command.",
                    ephemeral=True
                )
                return

            # Enforce admin channel restriction for admin+ commands
            if level >= PermLevel.ADMIN and user_level < PermLevel.OWNER:
                server = await self.bot.db.get_server(interaction.guild_id)
                if server and server['admin_channel_id']:
                    if interaction.channel_id != server['admin_channel_id']:
                        await interaction.response.send_message(
                            f"❌ Admin commands can only be used in <#{server['admin_channel_id']}>.",
                            ephemeral=True
                        )
                        return

            return await func(self, interaction, *args, **kwargs)
        return wrapper
    return decorator


async def send_audit_log(bot, guild_id: int, actor: discord.Member, action: str, details: dict, success: bool = True):
    import uuid, json
    server = await bot.db.get_server(guild_id)
    if not server:
        return

    await bot.db.log_action(str(uuid.uuid4()), guild_id, actor.id, action, details, success)

    if server['audit_channel_id']:
        channel = bot.get_channel(server['audit_channel_id'])
        if channel:
            color = discord.Color.green() if success else discord.Color.red()
            embed = discord.Embed(
                title=f"🔍 Audit — `{action}`",
                color=color,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Actor", value=f"{actor.mention} (`{actor.id}`)", inline=True)
            embed.add_field(name="Status", value="✅ Success" if success else "❌ Failed", inline=True)
            if details:
                for k, v in details.items():
                    embed.add_field(name=k.replace('_', ' ').title(), value=str(v), inline=False)
            embed.set_footer(text="BridgeBot Audit Log")
            try:
                await channel.send(embed=embed)
            except Exception:
                pass
