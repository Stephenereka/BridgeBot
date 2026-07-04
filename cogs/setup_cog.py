import discord
from discord import app_commands
from discord.ext import commands
import uuid
from core.permissions import require_perm, PermLevel, send_audit_log


class SetupCog(commands.Cog, name="Setup"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="First-time BridgeBot setup wizard (Server Owner only)")
    @require_perm(PermLevel.OWNER)
    async def setup(self, interaction: discord.Interaction):
        await self.bot.db.upsert_server(interaction.guild)
        embed = discord.Embed(
            title="🌉 BridgeBot Setup",
            description=(
                "Welcome! Let's configure BridgeBot for your server.\n\n"
                "**Recommended setup:**\n"
                "1. Create a `#bridge-admin` channel (admin commands only)\n"
                "2. Create a `#bridge-audit` channel (logs all admin actions)\n"
                "3. Run `/config set admin_channel <channel_id>` to restrict commands\n"
                "4. Run `/config set audit_channel <channel_id>` to enable audit logs\n"
                "5. Create a `BridgeBot Admin` role for non-owner admins (optional)\n\n"
                "Then use `/bridge create` to set up your first bridge!"
            ),
            color=0x5865F2,
        )
        embed.add_field(
            name="Required Bot Permissions",
            value="✅ Send Messages\n✅ Embed Links\n✅ Manage Webhooks\n✅ Read Message History",
            inline=False,
        )
        embed.set_footer(text="Use /help to see all commands.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    config_group = app_commands.Group(name="config", description="View and update server configuration")

    @config_group.command(name="view", description="View current BridgeBot configuration for this server")
    @require_perm(PermLevel.ADMIN)
    async def config_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.upsert_server(interaction.guild)
        server = await self.bot.db.get_server(interaction.guild_id)

        embed = discord.Embed(title="⚙️ Server Configuration", color=0x5865F2)
        embed.add_field(
            name="Admin Channel",
            value=f"<#{server['admin_channel_id']}>" if server['admin_channel_id'] else "Not set (commands work anywhere)",
            inline=False,
        )
        embed.add_field(
            name="Audit Log Channel",
            value=f"<#{server['audit_channel_id']}>" if server['audit_channel_id'] else "Not set (no audit logs)",
            inline=False,
        )
        embed.add_field(
            name="BridgeBot Admin Role",
            value=f"<@&{server['admin_role_id']}>" if server['admin_role_id'] else "Not set (use Discord permissions)",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config_group.command(name="set", description="Update a configuration value")
    @app_commands.describe(
        key="Which setting to update",
        value="The channel or role ID to set (or 'none' to clear)",
    )
    @app_commands.choices(key=[
        app_commands.Choice(name="Admin Channel (restricts admin commands)", value="admin_channel_id"),
        app_commands.Choice(name="Audit Log Channel", value="audit_channel_id"),
        app_commands.Choice(name="BridgeBot Admin Role ID", value="admin_role_id"),
    ])
    @require_perm(PermLevel.OWNER)
    async def config_set(self, interaction: discord.Interaction, key: str, value: str):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.upsert_server(interaction.guild)

        if value.lower() == 'none':
            await self.bot.db.update_server_config(interaction.guild_id, key, None)
            await interaction.followup.send(f"✅ `{key}` cleared.", ephemeral=True)
            return

        try:
            int_val = int(value)
        except ValueError:
            await interaction.followup.send("❌ Value must be a numeric ID or 'none' to clear.", ephemeral=True)
            return

        await self.bot.db.update_server_config(interaction.guild_id, key, int_val)
        label = key.replace('_', ' ').title()
        await interaction.followup.send(f"✅ **{label}** set to `{int_val}`.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'config_update', {
            'key': key, 'new_value': int_val,
        })

    blacklist_group = app_commands.Group(name="blacklist", description="Manage your server blacklist")

    @blacklist_group.command(name="add", description="Block a server from ever bridging with yours")
    @app_commands.describe(server_id="Server ID to blacklist")
    @require_perm(PermLevel.ADMIN)
    async def bl_add(self, interaction: discord.Interaction, server_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            sv_id = int(server_id)
        except ValueError:
            await interaction.followup.send("❌ Invalid server ID.", ephemeral=True)
            return
        await self.bot.db.add_blacklist(str(uuid.uuid4()), interaction.guild_id, sv_id)
        guild = self.bot.get_guild(sv_id)
        name = guild.name if guild else f"`{server_id}`"
        await interaction.followup.send(f"🚫 **{name}** has been blacklisted. They cannot bridge with your server.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'blacklist_add', {'blocked_server': server_id})

    @blacklist_group.command(name="remove", description="Remove a server from your blacklist")
    @app_commands.describe(server_id="Server ID to unblacklist")
    @require_perm(PermLevel.ADMIN)
    async def bl_remove(self, interaction: discord.Interaction, server_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            sv_id = int(server_id)
        except ValueError:
            await interaction.followup.send("❌ Invalid server ID.", ephemeral=True)
            return
        await self.bot.db.remove_blacklist(interaction.guild_id, sv_id)
        await interaction.followup.send(f"✅ Server `{server_id}` removed from blacklist.", ephemeral=True)

    @blacklist_group.command(name="list", description="View your server blacklist")
    @require_perm(PermLevel.ADMIN)
    async def bl_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bl = await self.bot.db.get_blacklist(interaction.guild_id)
        if not bl:
            await interaction.followup.send("Your blacklist is empty.", ephemeral=True)
            return
        embed = discord.Embed(title="🚫 Blacklisted Servers", color=0xED4245)
        for entry in bl:
            guild = self.bot.get_guild(entry['blocked_server_id'])
            name = guild.name if guild else f"Unknown Server"
            embed.add_field(name=name, value=f"ID: `{entry['blocked_server_id']}`", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    rolesync_group = app_commands.Group(name="rolesync", description="Manage cross-server role sync")

    @rolesync_group.command(name="add", description="Map a role from this server to a role in another server")
    @app_commands.describe(
        federation_id="Federation ID these servers share",
        source_role="Role in THIS server to sync from",
        target_server_id="Target server ID",
        target_role_id="Role ID in the target server to grant",
    )
    @require_perm(PermLevel.ADMIN)
    async def rs_add(self, interaction: discord.Interaction, federation_id: str, source_role: discord.Role,
                     target_server_id: str, target_role_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            t_sv = int(target_server_id)
            t_role = int(target_role_id)
        except ValueError:
            await interaction.followup.send("❌ Invalid server or role ID.", ephemeral=True)
            return

        map_id = str(uuid.uuid4())
        await self.bot.db.add_role_mapping(map_id, federation_id, interaction.guild_id, source_role.id, t_sv, t_role)
        await interaction.followup.send(
            f"✅ Role sync added: **{source_role.name}** here → role `{t_role}` in server `{t_sv}`.",
            ephemeral=True,
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'rolesync_add', {
            'source_role': source_role.name, 'target_server': t_sv, 'target_role': t_role,
        })

    @rolesync_group.command(name="remove", description="Remove a role sync mapping")
    @app_commands.describe(mapping_id="Mapping ID from /rolesync list")
    @require_perm(PermLevel.ADMIN)
    async def rs_remove(self, interaction: discord.Interaction, mapping_id: str):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.delete_role_mapping(mapping_id)
        await interaction.followup.send(f"✅ Role mapping `{mapping_id}` removed.", ephemeral=True)

    @rolesync_group.command(name="list", description="List all role sync mappings for this server")
    @require_perm(PermLevel.MOD)
    async def rs_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        mappings = await self.bot.db.get_role_mappings(interaction.guild_id)
        if not mappings:
            await interaction.followup.send("No role sync mappings configured.", ephemeral=True)
            return
        embed = discord.Embed(title="🔄 Role Sync Mappings", color=0x5865F2)
        for m in mappings:
            role = interaction.guild.get_role(m['source_role_id'])
            status = "✅" if m['active'] else "❌"
            embed.add_field(
                name=f"{status} `{m['id'][:8]}`",
                value=f"<@&{m['source_role_id']}> → role `{m['target_role_id']}` in `{m['target_server_id']}`",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @rolesync_group.command(name="toggle", description="Enable or disable a role sync mapping")
    @app_commands.describe(mapping_id="Mapping ID from /rolesync list")
    @require_perm(PermLevel.ADMIN)
    async def rs_toggle(self, interaction: discord.Interaction, mapping_id: str):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.toggle_role_mapping(mapping_id)
        await interaction.followup.send(f"✅ Role mapping `{mapping_id}` toggled.", ephemeral=True)


    @app_commands.command(name="bridgealert", description="Set the channel where bridge error alerts are posted")
    @app_commands.describe(channel="Channel to send bridge alerts to")
    @require_perm(PermLevel.ADMIN)
    async def bridgealert(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.upsert_server(interaction.guild)
        await self.bot.db.update_server_config(interaction.guild_id, 'alert_channel_id', channel.id)
        await interaction.followup.send(
            f"✅ Bridge alerts will now be sent to {channel.mention}.", ephemeral=True
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'alert_channel_set', {
            'channel': channel.name,
        })

    @app_commands.command(name="digest", description="Enable or disable weekly bridge summary for this server")
    @app_commands.describe(
        action="Turn weekly digest on or off",
        channel="Channel to send digests to (required when turning on)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="on — enable weekly digest", value="on"),
        app_commands.Choice(name="off — disable weekly digest", value="off"),
    ])
    @require_perm(PermLevel.ADMIN)
    async def digest(self, interaction: discord.Interaction, action: str, channel: discord.TextChannel = None):
        if action == "on" and not channel:
            await interaction.response.send_message("❌ You must specify a channel when enabling the digest.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.upsert_server(interaction.guild)
        if action == "on":
            await self.bot.db.update_server_config(interaction.guild_id, 'digest_enabled', 1)
            await self.bot.db.update_server_config(interaction.guild_id, 'digest_channel_id', channel.id)
            await interaction.followup.send(f"✅ Weekly digest enabled. Stats will be sent to {channel.mention} every week.", ephemeral=True)
        else:
            await self.bot.db.update_server_config(interaction.guild_id, 'digest_enabled', 0)
            await interaction.followup.send("✅ Weekly digest disabled.", ephemeral=True)

    @app_commands.command(name="setprefix", description="Change BridgeBot's legacy text-command prefix for this server (bot owner only)")
    @app_commands.describe(prefix="New prefix, e.g. !bb or ? (default is \"!bb \")")
    async def setprefix(self, interaction: discord.Interaction, prefix: str):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Bot owner only.", ephemeral=True)
            return
        if len(prefix) > 10:
            await interaction.response.send_message("Prefix must be 10 characters or fewer.", ephemeral=True)
            return
        await self.bot.db.upsert_server(interaction.guild)
        await self.bot.db.update_server_config(interaction.guild_id, 'prefix', prefix)
        self.bot.guild_prefixes[interaction.guild_id] = prefix
        await interaction.response.send_message(f"Prefix updated to `{prefix}` for this server.", ephemeral=True)

    @app_commands.command(name="export", description="Export this server's BridgeBot config as JSON")
    @require_perm(PermLevel.ADMIN)
    async def export(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        import json, io
        data = await self.bot.db.get_server_config_export(interaction.guild_id)
        # Remove sensitive webhook URLs
        for b in data.get('bridges', []):
            b.pop('webhook_a_url', None)
            b.pop('webhook_b_url', None)
        json_str = json.dumps(data, indent=2, default=str)
        file = discord.File(fp=io.BytesIO(json_str.encode()), filename=f"bridgebot_config_{interaction.guild_id}.json")
        await interaction.followup.send("Here is your server config export:", file=file, ephemeral=True)

    webhook_group = app_commands.Group(name="webhook", description="Webhook management")

    @webhook_group.command(name="rotate", description="Regenerate webhook URLs for a bridge (security refresh)")
    @app_commands.describe(bridge_id="Bridge ID from /bridge list")
    @require_perm(PermLevel.ADMIN)
    async def webhook_rotate(self, interaction: discord.Interaction, bridge_id: str):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return

        results = []
        for side, ch_id, old_url_key in [
            ('A', bridge['channel_a_id'], 'webhook_a_url'),
            ('B', bridge['channel_b_id'], 'webhook_b_url'),
        ]:
            ch = self.bot.get_channel(ch_id)
            if not ch:
                results.append(f"Side {side}: channel not accessible")
                continue
            if bridge[old_url_key]:
                await self.bot.webhook_manager.delete_webhook_by_url(bridge[old_url_key])
            new_url = await self.bot.webhook_manager.create_webhook(ch)
            if new_url:
                kwargs = {f'webhook_{side.lower()}_url': new_url}
                await self.bot.db.update_bridge_webhooks(bridge_id, **kwargs)
                results.append(f"Side {side} ({ch.name}): ✅ rotated")
            else:
                results.append(f"Side {side} ({ch.name}): ❌ failed (check Manage Webhooks permission)")

        await interaction.followup.send("\n".join(results), ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'webhook_rotated', {'bridge_id': bridge_id})


async def setup(bot):
    await bot.add_cog(SetupCog(bot))
