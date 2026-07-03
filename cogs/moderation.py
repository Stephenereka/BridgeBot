import discord
from discord import app_commands
from discord.ext import commands
import uuid
from core.permissions import require_perm, PermLevel, send_audit_log


class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot):
        self.bot = bot

    banrelay = app_commands.Group(name="banrelay", description="Manage cross-server ban relay")

    @banrelay.command(name="enable", description="Enable ban relay for a federation — bans are shared across all member servers")
    @app_commands.describe(
        federation_id="Federation ID to enable ban relay for",
        auto_ban="If True, automatically ban the user. If False, just send an alert.",
    )
    @require_perm(PermLevel.ADMIN)
    async def banrelay_enable(self, interaction: discord.Interaction, federation_id: str, auto_ban: bool = False):
        await interaction.response.defer(ephemeral=True)
        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return
        await self.bot.db.set_ban_relay(federation_id, interaction.guild_id, enabled=True, auto_ban=auto_ban)
        mode = "auto-ban" if auto_ban else "alert only"
        await interaction.followup.send(
            f"✅ Ban relay enabled for **{fed['name']}** (`{mode}` mode).\n"
            f"Bans in this server will be reported to all federated servers.",
            ephemeral=True,
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'banrelay_enabled', {
            'federation': fed['name'], 'mode': mode,
        })

    @banrelay.command(name="disable", description="Disable ban relay for a federation")
    @app_commands.describe(federation_id="Federation ID to disable ban relay for")
    @require_perm(PermLevel.ADMIN)
    async def banrelay_disable(self, interaction: discord.Interaction, federation_id: str):
        await interaction.response.defer(ephemeral=True)
        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return
        await self.bot.db.set_ban_relay(federation_id, interaction.guild_id, enabled=False)
        await interaction.followup.send(f"✅ Ban relay disabled for **{fed['name']}**.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'banrelay_disabled', {
            'federation': fed['name'],
        })

    @banrelay.command(name="status", description="Check ban relay status for all federations this server is in")
    @require_perm(PermLevel.MOD)
    async def banrelay_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        feds = await self.bot.db.get_federations_for_server(interaction.guild_id)
        if not feds:
            await interaction.followup.send("This server is not in any federations.", ephemeral=True)
            return

        embed = discord.Embed(title="🔨 Ban Relay Status", color=0x5865F2)
        for f in feds:
            config = await self.bot.db.get_ban_relay_config(f['id'], interaction.guild_id)
            if config and config['enabled']:
                mode = "🤖 Auto-ban" if config['auto_ban'] else "🔔 Alert only"
                status = f"✅ Enabled — {mode}"
            else:
                status = "❌ Disabled"
            embed.add_field(name=f['name'], value=status, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @banrelay.command(name="exclude", description="Exclude a user from ban relay — their bans won't be shared")
    @app_commands.describe(
        federation_id="Federation ID",
        user_id="User ID to exclude from ban relay",
    )
    @require_perm(PermLevel.ADMIN)
    async def banrelay_exclude(self, interaction: discord.Interaction, federation_id: str, user_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.followup.send("❌ Invalid user ID.", ephemeral=True)
            return
        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return
        await self.bot.db.add_ban_relay_exclusion(str(uuid.uuid4()), federation_id, interaction.guild_id, uid, interaction.user.id)
        await interaction.followup.send(f"✅ User `{user_id}` excluded from ban relay in **{fed['name']}**.", ephemeral=True)

    async def handle_ban(self, guild: discord.Guild, user: discord.User):
        """Called from main.py on_member_ban — relays ban to federated servers."""
        feds = await self.bot.db.get_federations_for_server(guild.id)
        for fed in feds:
            config = await self.bot.db.get_ban_relay_config(fed['id'], guild.id)
            if not config or not config['enabled']:
                continue

            is_excluded = await self.bot.db.is_ban_relay_excluded(fed['id'], guild.id, user.id)
            if is_excluded:
                continue

            await self.bot.db.save_ban_relay(str(uuid.uuid4()), fed['id'], user.id, guild.id)
            members = await self.bot.db.get_federation_members(fed['id'])

            for member in members:
                if member['server_id'] == guild.id:
                    continue
                target_guild = self.bot.get_guild(member['server_id'])
                if not target_guild:
                    continue

                target_config = await self.bot.db.get_ban_relay_config(fed['id'], member['server_id'])
                if not target_config or not target_config['enabled']:
                    continue

                target_server = await self.bot.db.get_server(member['server_id'])
                alert_ch = None
                if target_server and target_server['alert_channel_id']:
                    alert_ch = self.bot.get_channel(target_server['alert_channel_id'])
                elif target_server and target_server['audit_channel_id']:
                    alert_ch = self.bot.get_channel(target_server['audit_channel_id'])

                embed = discord.Embed(
                    title="🔨 Ban Relay Alert",
                    description=f"A user was banned in a federated server.",
                    color=0xED4245,
                )
                embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
                embed.add_field(name="Banned in", value=guild.name, inline=True)
                embed.add_field(name="Federation", value=fed['name'], inline=True)

                try:
                    ban_entry = await guild.fetch_ban(user)
                    if ban_entry.reason:
                        embed.add_field(name="Reason", value=ban_entry.reason, inline=False)
                except Exception:
                    pass

                if target_config['auto_ban']:
                    try:
                        await target_guild.ban(user, reason=f"Ban relay from {guild.name} via BridgeBot ({fed['name']} federation)")
                        embed.add_field(name="Action Taken", value="✅ User auto-banned in this server", inline=False)
                    except discord.Forbidden:
                        embed.add_field(name="Action Failed", value="❌ Missing permission to ban", inline=False)
                    except Exception:
                        pass

                if alert_ch:
                    try:
                        await alert_ch.send(embed=embed)
                    except Exception:
                        pass

    async def handle_unban(self, guild: discord.Guild, user: discord.User):
        """Called from main.py on_member_unban — relays unban to federated servers."""
        feds = await self.bot.db.get_federations_for_server(guild.id)
        for fed in feds:
            config = await self.bot.db.get_ban_relay_config(fed['id'], guild.id)
            if not config or not config['enabled']:
                continue

            await self.bot.db.mark_ban_relay_unbanned(fed['id'], user.id, guild.id)
            members = await self.bot.db.get_federation_members(fed['id'])

            for member in members:
                if member['server_id'] == guild.id:
                    continue
                target_guild = self.bot.get_guild(member['server_id'])
                if not target_guild:
                    continue

                target_config = await self.bot.db.get_ban_relay_config(fed['id'], member['server_id'])
                if not target_config or not target_config['enabled'] or not target_config['auto_ban']:
                    continue

                target_server = await self.bot.db.get_server(member['server_id'])
                alert_ch = None
                if target_server and target_server['alert_channel_id']:
                    alert_ch = self.bot.get_channel(target_server['alert_channel_id'])
                elif target_server and target_server['audit_channel_id']:
                    alert_ch = self.bot.get_channel(target_server['audit_channel_id'])

                try:
                    await target_guild.unban(user, reason=f"Unban relay from {guild.name} via BridgeBot")
                    if alert_ch:
                        embed = discord.Embed(
                            title="✅ Unban Relay",
                            description=f"**{user}** was unbanned in **{guild.name}** and has been unbanned here too.",
                            color=0x57F287,
                        )
                        embed.add_field(name="Federation", value=fed['name'], inline=True)
                        await alert_ch.send(embed=embed)
                except Exception:
                    pass


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
