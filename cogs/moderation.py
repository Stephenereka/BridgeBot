import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import uuid
from core.permissions import require_perm, PermLevel, send_audit_log


class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot):
        self.bot = bot

    banrelay = app_commands.Group(name="banrelay", description="Manage cross-server ban relay")

    @banrelay.command(name="enable", description="Enable ban relay for a federation")
    @app_commands.describe(
        federation_id="Federation ID to enable ban relay for",
        auto_ban="Automatically ban the user in all federated servers (default: alert only)",
        mode="automatic = fires on every ban; manual = only fires when you run /banrelay ban",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="automatic", value="automatic"),
        app_commands.Choice(name="manual only", value="manual"),
    ])
    @require_perm(PermLevel.ADMIN)
    async def banrelay_enable(
        self,
        interaction: discord.Interaction,
        federation_id: str,
        auto_ban: bool = False,
        mode: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return

        manual_only = mode is not None and mode.value == "manual"
        await self.bot.db.set_ban_relay(
            federation_id, interaction.guild_id,
            enabled=True, auto_ban=auto_ban, manual_only=manual_only,
        )

        relay_mode = "manual only" if manual_only else "automatic"
        ban_mode = "auto-ban" if auto_ban else "alert only"
        await interaction.followup.send(
            f"✅ Ban relay enabled for **{fed['name']}**.\n"
            f"• Relay mode: **{relay_mode}**\n"
            f"• Ban action: **{ban_mode}**\n\n"
            f"{'Bans will relay automatically when they happen.' if not manual_only else 'Use `/banrelay ban` to relay bans manually.'}",
            ephemeral=True,
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'banrelay_enabled', {
            'federation': fed['name'], 'relay_mode': relay_mode, 'ban_mode': ban_mode,
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

    @banrelay.command(name="ban", description="Manually relay a ban to all federated servers")
    @app_commands.describe(
        federation_id="Federation ID to relay the ban through",
        user_id="ID of the user that was banned",
        reason="Reason for the ban (required — use this when another bot did the ban)",
    )
    @require_perm(PermLevel.ADMIN)
    async def banrelay_ban(
        self,
        interaction: discord.Interaction,
        federation_id: str,
        user_id: str,
        reason: str,
    ):
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

        config = await self.bot.db.get_ban_relay_config(federation_id, interaction.guild_id)
        if not config or not config['enabled']:
            await interaction.followup.send(
                "❌ Ban relay is not enabled for this federation in your server. Run `/banrelay enable` first.",
                ephemeral=True,
            )
            return

        try:
            user = await self.bot.fetch_user(uid)
        except discord.NotFound:
            await interaction.followup.send("❌ User not found — check the ID.", ephemeral=True)
            return
        except Exception:
            await interaction.followup.send("❌ Could not fetch user.", ephemeral=True)
            return

        await self.bot.db.save_ban_relay(str(uuid.uuid4()), federation_id, uid, interaction.guild_id, reason)
        relayed_to = await self._fire_relay(
            user=user,
            banned_guild=interaction.guild,
            fed=fed,
            reason=reason,
            source_server_id=interaction.guild_id,
            manual=True,
            relayed_by=interaction.user,
        )

        await interaction.followup.send(
            f"✅ Ban for **{user}** (`{uid}`) relayed to **{relayed_to}** server(s) in **{fed['name']}**.\n"
            f"Reason: {reason}",
            ephemeral=True,
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'banrelay_manual', {
            'user': str(user), 'user_id': uid, 'federation': fed['name'], 'reason': reason,
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
                relay_mode = "Manual only" if config.get('manual_only') else "Automatic"
                ban_action = "🤖 Auto-ban" if config['auto_ban'] else "🔔 Alert only"
                status = f"✅ Enabled — {relay_mode} | {ban_action}"
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

    async def _fire_relay(self, user, banned_guild, fed, reason, source_server_id, manual=False, relayed_by=None):
        """Send ban relay alerts to all member servers in a federation. Returns count of servers notified."""
        members = await self.bot.db.get_federation_members(fed['id'])
        relayed_to = 0

        for member in members:
            if member['server_id'] == source_server_id:
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
            embed.add_field(name="Banned in", value=banned_guild.name, inline=True)
            embed.add_field(name="Federation", value=fed['name'], inline=True)
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)
            if manual and relayed_by:
                embed.add_field(name="Relayed by", value=f"{relayed_by} (manual)", inline=False)

            if target_config['auto_ban']:
                try:
                    await target_guild.ban(user, reason=f"Ban relay from {banned_guild.name} via BridgeBot ({fed['name']})")
                    embed.add_field(name="Action Taken", value="✅ User auto-banned in this server", inline=False)
                except discord.Forbidden:
                    embed.add_field(name="Action Failed", value="❌ Missing permission to ban", inline=False)
                except Exception:
                    pass

            if alert_ch:
                try:
                    await alert_ch.send(embed=embed)
                    relayed_to += 1
                except Exception:
                    pass

        return relayed_to

    async def handle_ban(self, guild: discord.Guild, user: discord.User):
        """Called from main.py on_member_ban — relays ban to federated servers."""
        # Small delay to let Discord populate audit log for native/other-bot bans
        await asyncio.sleep(1.5)

        feds = await self.bot.db.get_federations_for_server(guild.id)
        for fed in feds:
            config = await self.bot.db.get_ban_relay_config(fed['id'], guild.id)
            if not config or not config['enabled']:
                continue
            # Skip if this federation is set to manual-only
            if config.get('manual_only'):
                continue

            is_excluded = await self.bot.db.is_ban_relay_excluded(fed['id'], guild.id, user.id)
            if is_excluded:
                continue

            # Try to get reason from Discord audit log
            reason = None
            try:
                ban_entry = await guild.fetch_ban(user)
                reason = ban_entry.reason
            except Exception:
                pass

            await self.bot.db.save_ban_relay(str(uuid.uuid4()), fed['id'], user.id, guild.id, reason)
            await self._fire_relay(
                user=user,
                banned_guild=guild,
                fed=fed,
                reason=reason,
                source_server_id=guild.id,
                manual=False,
            )

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
