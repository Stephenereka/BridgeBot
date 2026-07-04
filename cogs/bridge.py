import discord
from discord import app_commands
from discord.ext import commands
import uuid
from core.permissions import require_perm, PermLevel, get_perm_level, send_audit_log


class BridgeConsentView(discord.ui.View):
    def __init__(self, bot, bridge_id: str, pending: dict):
        super().__init__(timeout=86400)
        self.bot = bot
        self.bridge_id = bridge_id
        self.pending = pending

    @discord.ui.button(label="✅ Accept Bridge", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        level = await get_perm_level(interaction)
        if level < PermLevel.ADMIN:
            await interaction.response.send_message("❌ Only admins can accept bridge requests.", ephemeral=True)
            return

        data = self.pending.get(self.bridge_id)
        if not data:
            await interaction.response.send_message("❌ This bridge request has expired.", ephemeral=True)
            return

        await interaction.response.defer()

        guild_a = self.bot.get_guild(data['server_a_id'])
        guild_b = interaction.guild
        if guild_a:
            await self.bot.db.upsert_server(guild_a)
        await self.bot.db.upsert_server(guild_b)

        channel_a = self.bot.get_channel(data['channel_a_id'])
        channel_b = self.bot.get_channel(data['channel_b_id'])

        webhook_a_url = await self.bot.webhook_manager.create_webhook(channel_a) if channel_a else None
        webhook_b_url = await self.bot.webhook_manager.create_webhook(channel_b) if channel_b else None

        if not webhook_a_url or not webhook_b_url:
            await interaction.followup.send(
                "❌ Failed to create webhooks. Make sure BridgeBot has **Manage Webhooks** permission in both channels."
            )
            return

        full_id = str(uuid.uuid4())
        await self.bot.db.create_bridge(
            bridge_id=full_id,
            channel_a_id=data['channel_a_id'],
            server_a_id=data['server_a_id'],
            channel_b_id=data['channel_b_id'],
            server_b_id=data['server_b_id'],
            created_by=data['created_by'],
        )
        await self.bot.db.update_bridge_webhooks(full_id, webhook_a_url, webhook_b_url)
        self.pending.pop(self.bridge_id, None)

        audit_details = {
            'bridge_id': full_id[:8],
            'server_a': guild_a.name if guild_a else str(data['server_a_id']),
            'channel_a': f'#{channel_a.name}' if channel_a else str(data['channel_a_id']),
            'server_b': guild_b.name,
            'channel_b': f'#{channel_b.name}' if channel_b else str(data['channel_b_id']),
            'accepted_by': str(interaction.user),
        }
        # Log to both servers' audit channels
        await send_audit_log(self.bot, guild_b.id, interaction.user, 'bridge_accepted', audit_details)
        if guild_a:
            await send_audit_log(self.bot, guild_a.id, interaction.user, 'bridge_accepted', audit_details)

        embed = discord.Embed(
            title="🌉 Bridge Active!",
            description=(
                f"**#{channel_a.name if channel_a else '?'}** ({guild_a.name if guild_a else '?'}) "
                f"↔ **#{channel_b.name if channel_b else '?'}** ({guild_b.name})"
            ),
            color=0x57F287,
        )
        embed.set_footer(text=f"Bridge ID: {full_id[:8]}")
        await interaction.followup.send(embed=embed)

        if channel_a:
            try:
                await channel_a.send(embed=discord.Embed(
                    title="🌉 Bridge Accepted!",
                    description=(
                        f"Your bridge to **{guild_b.name}** is now live!\n"
                        f"This channel ↔ **#{channel_b.name if channel_b else '?'}**"
                    ),
                    color=0x57F287,
                ))
            except Exception:
                pass
        self.stop()

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        level = await get_perm_level(interaction)
        if level < PermLevel.ADMIN:
            await interaction.response.send_message("❌ Only admins can decline bridge requests.", ephemeral=True)
            return

        data = self.pending.pop(self.bridge_id, None)
        await interaction.response.send_message("Bridge request declined.")

        if data:
            guild_a = self.bot.get_guild(data['server_a_id'])
            audit_details = {
                'request_id': self.bridge_id,
                'server_a': guild_a.name if guild_a else str(data['server_a_id']),
                'channel_a': str(data['channel_a_id']),
                'channel_b': str(data['channel_b_id']),
                'declined_by': str(interaction.user),
            }
            # Log to both servers' audit channels
            await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_declined', audit_details)
            if guild_a:
                await send_audit_log(self.bot, guild_a.id, interaction.user, 'bridge_declined', audit_details)

            channel_a = self.bot.get_channel(data['channel_a_id'])
            if channel_a:
                guild_b = self.bot.get_guild(data['server_b_id'])
                try:
                    await channel_a.send(embed=discord.Embed(
                        title="❌ Bridge Declined",
                        description=f"Your bridge request to **{guild_b.name if guild_b else 'the target server'}** was declined.",
                        color=0xED4245,
                    ))
                except Exception:
                    pass
        self.stop()


class BridgeCog(commands.Cog, name="Bridge"):
    def __init__(self, bot):
        self.bot = bot
        self._pending: dict = {}  # short_id -> bridge data

    bridge = app_commands.Group(name="bridge", description="Manage channel bridges")

    @bridge.command(name="create", description="Request a bridge between this channel and a channel in another server")
    @app_commands.describe(
        target_server_id="Target server ID (right-click server → Copy ID)",
        target_channel_id="Target channel ID (right-click channel → Copy ID)",
    )
    @require_perm(PermLevel.ADMIN)
    async def bridge_create(self, interaction: discord.Interaction, target_server_id: str, target_channel_id: str):
        await interaction.response.defer(ephemeral=True)

        try:
            t_sv = int(target_server_id)
            t_ch = int(target_channel_id)
        except ValueError:
            await interaction.followup.send("❌ IDs must be numbers. Enable Developer Mode and right-click to copy IDs.", ephemeral=True)
            return

        await self.bot.db.upsert_server(interaction.guild)

        if await self.bot.db.is_blacklisted(interaction.guild_id, t_sv):
            await interaction.followup.send("❌ One of the servers has blacklisted the other.", ephemeral=True)
            return

        target_guild = self.bot.get_guild(t_sv)
        if not target_guild:
            await interaction.followup.send("❌ I'm not in that server or the ID is wrong.", ephemeral=True)
            return

        target_channel = target_guild.get_channel(t_ch)
        if not target_channel:
            await interaction.followup.send("❌ Can't find that channel in the target server.", ephemeral=True)
            return

        src = interaction.channel
        if hasattr(src, 'nsfw') and hasattr(target_channel, 'nsfw'):
            if src.nsfw != target_channel.nsfw:
                await interaction.followup.send(
                    "❌ Cannot bridge NSFW ↔ non-NSFW channels (Discord ToS). Both must match.",
                    ephemeral=True,
                )
                return

        # Check for duplicate bridge
        existing = await self.bot.db.get_bridges_for_channel(interaction.channel_id)
        for b in existing:
            if b['channel_b_id'] == t_ch or b['channel_a_id'] == t_ch:
                await interaction.followup.send("❌ A bridge between these channels already exists.", ephemeral=True)
                return

        short_id = str(uuid.uuid4())[:8]
        self._pending[short_id] = {
            'channel_a_id': interaction.channel_id,
            'server_a_id': interaction.guild_id,
            'channel_b_id': t_ch,
            'server_b_id': t_sv,
            'created_by': interaction.user.id,
        }

        # Find a channel to send the consent request in the target server
        consent_ch = target_guild.system_channel
        if not consent_ch:
            for ch in target_guild.text_channels:
                perms = ch.permissions_for(target_guild.me)
                if perms.send_messages and perms.embed_links:
                    consent_ch = ch
                    break

        if not consent_ch:
            await interaction.followup.send("❌ I can't send messages in the target server. Check my permissions there.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🌉 Bridge Request",
            description=(
                f"**{interaction.guild.name}** wants to bridge channels with this server.\n\n"
                f"**Their channel:** #{src.name}\n"
                f"**Your channel:** #{target_channel.name}"
            ),
            color=0x5865F2,
        )
        embed.add_field(name="Requested by", value=str(interaction.user), inline=True)
        embed.add_field(name="Their Server", value=interaction.guild.name, inline=True)
        embed.set_footer(text=f"Bridge ID: {short_id} • Expires in 24 hours • Only admins can accept")

        view = BridgeConsentView(self.bot, short_id, self._pending)
        try:
            await consent_ch.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.followup.send("❌ Couldn't send consent message in target server.", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ Bridge request sent to **{target_guild.name}**! Waiting for their admin to accept.\n`Request ID: {short_id}`",
            ephemeral=True,
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_request_sent', {
            'target_server': target_guild.name,
            'target_channel': f'#{target_channel.name}',
            'request_id': short_id,
        })

    @bridge.command(name="list", description="List all bridges on this server")
    async def bridge_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bridges = await self.bot.db.get_bridges_for_server(interaction.guild_id)

        if not bridges:
            await interaction.followup.send("No bridges found. Use `/bridge create` to set one up.", ephemeral=True)
            return

        embed = discord.Embed(title="🌉 Server Bridges", color=0x5865F2)
        for b in bridges:
            ch_a = self.bot.get_channel(b['channel_a_id'])
            ch_b = self.bot.get_channel(b['channel_b_id'])
            a_str = f"<#{b['channel_a_id']}>" if ch_a else f"Unknown (`{b['channel_a_id']}`)"
            b_str = f"<#{b['channel_b_id']}>" if ch_b else f"Unknown (`{b['channel_b_id']}`)"

            if b['paused']:
                status = "⏸️ Paused"
            elif b['active']:
                status = "✅ Active"
            else:
                status = "❌ Inactive"

            embed.add_field(
                name=f"`{b['id'][:8]}` — {status}",
                value=f"{a_str} ↔ {b_str}",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bridge.command(name="delete", description="Remove a bridge permanently")
    @app_commands.describe(bridge_id="Bridge ID from /bridge list (first 8 characters)")
    @require_perm(PermLevel.ADMIN)
    async def bridge_delete(self, interaction: discord.Interaction, bridge_id: str):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        if bridge['channel_a_server_id'] != interaction.guild_id and bridge['channel_b_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ You can only delete bridges that involve your server.", ephemeral=True)
            return

        if bridge['webhook_a_url']:
            await self.bot.webhook_manager.delete_webhook_by_url(bridge['webhook_a_url'])
        if bridge['webhook_b_url']:
            await self.bot.webhook_manager.delete_webhook_by_url(bridge['webhook_b_url'])

        await self.bot.db.delete_bridge(bridge_id)
        self.bot.relay.invalidate_bridge_cache()
        await interaction.followup.send(f"✅ Bridge `{bridge_id}` removed.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_deleted', {'bridge_id': bridge_id})

    @bridge.command(name="pause", description="Temporarily pause a bridge without deleting it")
    @app_commands.describe(bridge_id="Bridge ID from /bridge list")
    @require_perm(PermLevel.ADMIN)
    async def bridge_pause(self, interaction: discord.Interaction, bridge_id: str):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        if bridge['paused']:
            await interaction.followup.send("⏸️ Already paused. Use `/bridge resume` to unpause.", ephemeral=True)
            return
        await self.bot.db.set_bridge_paused(bridge_id, True)
        await interaction.followup.send(f"⏸️ Bridge `{bridge_id}` paused.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_paused', {'bridge_id': bridge_id})

    @bridge.command(name="resume", description="Resume a paused bridge")
    @app_commands.describe(bridge_id="Bridge ID from /bridge list")
    @require_perm(PermLevel.ADMIN)
    async def bridge_resume(self, interaction: discord.Interaction, bridge_id: str):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        if not bridge['paused']:
            await interaction.followup.send("▶️ Bridge is already active.", ephemeral=True)
            return
        await self.bot.db.set_bridge_paused(bridge_id, False)
        await interaction.followup.send(f"▶️ Bridge `{bridge_id}` resumed.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_resumed', {'bridge_id': bridge_id})

    @bridge.command(name="toggle", description="Toggle a relay setting on a bridge")
    @app_commands.describe(bridge_id="Bridge ID", setting="Which setting to flip")
    @app_commands.choices(setting=[
        app_commands.Choice(name="Relay Edits", value="relay_edits"),
        app_commands.Choice(name="Relay Deletes", value="relay_deletes"),
        app_commands.Choice(name="Relay Attachments", value="relay_attachments"),
        app_commands.Choice(name="Relay Embeds", value="relay_embeds"),
        app_commands.Choice(name="Allow NSFW", value="nsfw_allowed"),
    ])
    @require_perm(PermLevel.ADMIN)
    async def bridge_toggle(self, interaction: discord.Interaction, bridge_id: str, setting: str):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        await self.bot.db.toggle_bridge_setting(bridge_id, setting)
        bridge = await self.bot.db.get_bridge(bridge_id)
        state = "✅ ON" if bridge[setting] else "❌ OFF"
        label = setting.replace('_', ' ').title()
        await interaction.followup.send(f"**{label}** is now **{state}** for bridge `{bridge_id}`.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_toggle', {
            'bridge_id': bridge_id, 'setting': setting, 'new_value': state,
        })

    @bridge.command(name="stats", description="View stats and settings for a bridge")
    @app_commands.describe(bridge_id="Bridge ID from /bridge list")
    @require_perm(PermLevel.ADMIN)
    async def bridge_stats(self, interaction: discord.Interaction, bridge_id: str):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return

        count = await self.bot.db.get_bridge_message_count(bridge_id)
        ch_a = self.bot.get_channel(bridge['channel_a_id'])
        ch_b = self.bot.get_channel(bridge['channel_b_id'])

        embed = discord.Embed(title=f"📊 Bridge `{bridge_id[:8]}`", color=0x5865F2)
        embed.add_field(name="Channels", value=f"<#{bridge['channel_a_id']}> ↔ <#{bridge['channel_b_id']}>", inline=False)
        embed.add_field(name="Messages Relayed", value=f"`{count:,}`", inline=True)
        embed.add_field(name="Status", value="⏸️ Paused" if bridge['paused'] else ("✅ Active" if bridge['active'] else "❌ Inactive"), inline=True)
        embed.add_field(name="Relay Edits", value="✅" if bridge['relay_edits'] else "❌", inline=True)
        embed.add_field(name="Relay Deletes", value="✅" if bridge['relay_deletes'] else "❌", inline=True)
        embed.add_field(name="Relay Attachments", value="✅" if bridge['relay_attachments'] else "❌", inline=True)
        embed.add_field(name="Relay Embeds", value="✅" if bridge['relay_embeds'] else "❌", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


    @bridge.command(name="analytics", description="View detailed message relay stats for a bridge")
    @app_commands.describe(bridge_id="Specific bridge ID (shows all bridges if omitted)")
    @require_perm(PermLevel.MOD)
    async def bridge_analytics(self, interaction: discord.Interaction, bridge_id: str = None):
        await interaction.response.defer(ephemeral=True)
        if bridge_id:
            bridge = await self.bot.db.get_bridge_analytics_detailed(bridge_id)
            if not bridge:
                await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
                return
            if bridge['channel_a_server_id'] != interaction.guild_id and bridge['channel_b_server_id'] != interaction.guild_id:
                await interaction.followup.send("❌ That bridge is not connected to your server.", ephemeral=True)
                return
            embed = discord.Embed(title=f"📊 Bridge Analytics — `{bridge_id[:8]}`", color=0x5865F2)
            embed.add_field(name="Channels", value=f"<#{bridge['channel_a_id']}> ↔ <#{bridge['channel_b_id']}>", inline=False)
            status = "✅ Active" if bridge['active'] and not bridge['paused'] else "⏸️ Paused"
            embed.add_field(name="Status", value=status, inline=True)
            embed.add_field(name="Last 7 Days", value=f"{bridge.get('messages_7d', 0):,} msgs", inline=True)
            embed.add_field(name="Last 30 Days", value=f"{bridge.get('messages_30d', 0):,} msgs", inline=True)
            embed.add_field(name="All-Time Total", value=f"{bridge.get('total_messages') or 0:,} msgs", inline=True)
            embed.add_field(name="Ping Mode", value=(bridge.get('ping_mode') or 'none').title(), inline=True)
            embed.add_field(name="Link Mode", value=(bridge.get('link_mode') or 'all').title(), inline=True)
            if bridge.get('webhook_display_name'):
                embed.add_field(name="Custom Name", value=bridge['webhook_display_name'], inline=True)
            if bridge.get('purpose'):
                embed.add_field(name="Purpose", value=bridge['purpose'], inline=False)
            if bridge.get('last_message_at'):
                embed.add_field(name="Last Message", value=str(bridge['last_message_at'])[:16], inline=True)
            embed.add_field(name="Created", value=str(bridge.get('created_at', ''))[:16], inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            bridges = await self.bot.db.get_bridges_for_server(interaction.guild_id)
            if not bridges:
                await interaction.followup.send("No bridges found for this server.", ephemeral=True)
                return
            embed = discord.Embed(title="📊 Bridge Analytics — All Bridges", color=0x5865F2)
            for b in bridges[:10]:
                status = "✅" if b['active'] and not b['paused'] else "⏸️"
                embed.add_field(
                    name=f"{status} `{b['id'][:8]}`",
                    value=f"<#{b['channel_a_id']}> ↔ <#{b['channel_b_id']}>\n{b.get('total_messages') or 0:,} msgs total",
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @bridge.command(name="setping", description="Set how mentions are handled for a bridge")
    @app_commands.describe(
        bridge_id="Bridge ID from /bridge list",
        mode="none=strip mentions, role=allow role pings, all=allow everything"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="none — strip all mentions (default, safest)", value="none"),
        app_commands.Choice(name="role — allow role pings but block @everyone", value="role"),
        app_commands.Choice(name="all — allow all mentions (trusted bridges only)", value="all"),
    ])
    @require_perm(PermLevel.ADMIN)
    async def bridge_setping(self, interaction: discord.Interaction, bridge_id: str, mode: str):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        if bridge['channel_a_server_id'] != interaction.guild_id and bridge['channel_b_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ That bridge is not connected to your server.", ephemeral=True)
            return
        await self.bot.db.update_bridge_column(bridge_id, 'ping_mode', mode)
        self.bot.relay.invalidate_bridge_cache()
        await interaction.followup.send(f"✅ Ping mode for bridge `{bridge_id[:8]}` set to **{mode}**.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_setping', {'bridge_id': bridge_id, 'mode': mode})

    @bridge.command(name="setlinks", description="Set how links are handled for a bridge")
    @app_commands.describe(
        bridge_id="Bridge ID from /bridge list",
        mode="safe=known sites only, warn=flag unknowns, all=allow everything"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="safe — only YouTube, Discord CDN, and known safe sites", value="safe"),
        app_commands.Choice(name="warn — allow all links but flag unknown ones with ⚠️", value="warn"),
        app_commands.Choice(name="all — allow all links (default)", value="all"),
    ])
    @require_perm(PermLevel.ADMIN)
    async def bridge_setlinks(self, interaction: discord.Interaction, bridge_id: str, mode: str):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        if bridge['channel_a_server_id'] != interaction.guild_id and bridge['channel_b_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ That bridge is not connected to your server.", ephemeral=True)
            return
        await self.bot.db.update_bridge_column(bridge_id, 'link_mode', mode)
        self.bot.relay.invalidate_bridge_cache()
        await interaction.followup.send(f"✅ Link mode for bridge `{bridge_id[:8]}` set to **{mode}**.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_setlinks', {'bridge_id': bridge_id, 'mode': mode})

    @bridge.command(name="setpurpose", description="Set a description/purpose for a bridge (shown in analytics)")
    @app_commands.describe(bridge_id="Bridge ID", purpose="What this bridge is for (max 200 chars)")
    @require_perm(PermLevel.ADMIN)
    async def bridge_setpurpose(self, interaction: discord.Interaction, bridge_id: str, purpose: str):
        await interaction.response.defer(ephemeral=True)
        if len(purpose) > 200:
            await interaction.followup.send("❌ Purpose must be 200 characters or fewer.", ephemeral=True)
            return
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        if bridge['channel_a_server_id'] != interaction.guild_id and bridge['channel_b_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ That bridge is not connected to your server.", ephemeral=True)
            return
        await self.bot.db.update_bridge_column(bridge_id, 'purpose', purpose)
        await interaction.followup.send(f"✅ Purpose for bridge `{bridge_id[:8]}` updated.", ephemeral=True)

    @bridge.command(name="setname", description="Set a custom display name for relayed messages on this bridge")
    @app_commands.describe(bridge_id="Bridge ID from /bridge list", name="Custom name (leave empty to reset to default)")
    @require_perm(PermLevel.ADMIN)
    async def bridge_setname(self, interaction: discord.Interaction, bridge_id: str, name: str = None):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        if bridge['channel_a_server_id'] != interaction.guild_id and bridge['channel_b_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ That bridge is not connected to your server.", ephemeral=True)
            return
        if name and len(name) > 80:
            await interaction.followup.send("❌ Name must be 80 characters or fewer.", ephemeral=True)
            return
        await self.bot.db.update_bridge_column(bridge_id, 'webhook_display_name', name)
        self.bot.relay.invalidate_bridge_cache()
        if name:
            await interaction.followup.send(f"✅ Relayed messages on bridge `{bridge_id[:8]}` will now show as **{name}**.", ephemeral=True)
        else:
            await interaction.followup.send(f"✅ Custom name cleared. Bridge `{bridge_id[:8]}` will use default display names.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_setname', {'bridge_id': bridge_id, 'name': name})

    @bridge.command(name="setavatar", description="Set a custom avatar for relayed messages on this bridge")
    @app_commands.describe(bridge_id="Bridge ID from /bridge list", url="Image URL (leave empty to reset to default)")
    @require_perm(PermLevel.ADMIN)
    async def bridge_setavatar(self, interaction: discord.Interaction, bridge_id: str, url: str = None):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        if bridge['channel_a_server_id'] != interaction.guild_id and bridge['channel_b_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ That bridge is not connected to your server.", ephemeral=True)
            return
        if url and not (url.startswith('http://') or url.startswith('https://')):
            await interaction.followup.send("❌ Please provide a valid image URL starting with http:// or https://", ephemeral=True)
            return
        await self.bot.db.update_bridge_column(bridge_id, 'webhook_avatar_url', url)
        self.bot.relay.invalidate_bridge_cache()
        if url:
            await interaction.followup.send(f"✅ Custom avatar set for bridge `{bridge_id[:8]}`.", ephemeral=True)
        else:
            await interaction.followup.send(f"✅ Custom avatar cleared for bridge `{bridge_id[:8]}`.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_setavatar', {'bridge_id': bridge_id})

    @bridge.command(name="forum", description="Bridge a forum channel with a forum channel in another server")
    @app_commands.describe(
        local_forum="Your forum channel",
        target_server_id="Target server ID",
        target_forum_id="Target forum channel ID in the other server"
    )
    @require_perm(PermLevel.ADMIN)
    async def bridge_forum(self, interaction: discord.Interaction, local_forum: discord.ForumChannel,
                           target_server_id: str, target_forum_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            t_sv = int(target_server_id)
            t_ch = int(target_forum_id)
        except ValueError:
            await interaction.followup.send("❌ Invalid server or channel ID.", ephemeral=True)
            return
        target_guild = self.bot.get_guild(t_sv)
        if not target_guild:
            await interaction.followup.send("❌ I'm not in that server.", ephemeral=True)
            return
        target_forum = self.bot.get_channel(t_ch)
        if not target_forum or not isinstance(target_forum, discord.ForumChannel):
            await interaction.followup.send("❌ Target channel not found or is not a forum channel.", ephemeral=True)
            return
        if await self.bot.db.is_blacklisted(interaction.guild_id, t_sv):
            await interaction.followup.send("❌ Your server has blacklisted that server (or vice versa).", ephemeral=True)
            return
        bridge_id = str(uuid.uuid4())
        await self.bot.db.create_bridge(
            bridge_id=bridge_id,
            channel_a_id=local_forum.id,
            server_a_id=interaction.guild_id,
            channel_b_id=t_ch,
            server_b_id=t_sv,
            created_by=interaction.user.id,
        )
        await self.bot.db.update_bridge_column(bridge_id, 'channel_type', 'forum')
        self.bot.relay.invalidate_bridge_cache()
        embed = discord.Embed(
            title="📁 Forum Bridge Created",
            description=(
                f"Forum posts created in **{local_forum.name}** will be automatically mirrored to "
                f"**{target_forum.name}** in **{target_guild.name}**, and vice versa."
            ),
            color=0x57F287,
        )
        embed.add_field(name="Bridge ID", value=f"`{bridge_id[:8]}`", inline=False)
        embed.set_footer(text="New forum posts will be bridged automatically. Existing posts are not affected.")
        await interaction.followup.send(embed=embed, ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'forum_bridge_created', {
            'bridge_id': bridge_id[:8], 'local_forum': local_forum.name, 'target_guild': target_guild.name,
        })

    @bridge.command(name="scheduleset", description="Auto-pause a bridge during certain hours each day")
    @app_commands.describe(
        bridge_id="Bridge ID",
        pause_hour="UTC hour to pause (0-23)",
        resume_hour="UTC hour to resume (0-23)",
        days="Days to apply schedule: comma-separated 0-6 (0=Mon, 6=Sun). Leave empty for all days."
    )
    @require_perm(PermLevel.ADMIN)
    async def bridge_scheduleset(self, interaction: discord.Interaction, bridge_id: str,
                                  pause_hour: int, resume_hour: int, days: str = None):
        await interaction.response.defer(ephemeral=True)
        if not (0 <= pause_hour <= 23 and 0 <= resume_hour <= 23):
            await interaction.followup.send("❌ Hours must be between 0 and 23 (UTC).", ephemeral=True)
            return
        if pause_hour == resume_hour:
            await interaction.followup.send("❌ Pause and resume hours cannot be the same.", ephemeral=True)
            return
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        if bridge['channel_a_server_id'] != interaction.guild_id and bridge['channel_b_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ That bridge is not connected to your server.", ephemeral=True)
            return
        if days:
            try:
                day_nums = [int(d.strip()) for d in days.split(',')]
                if any(d < 0 or d > 6 for d in day_nums):
                    raise ValueError
                days_clean = ','.join(str(d) for d in day_nums)
            except ValueError:
                await interaction.followup.send("❌ Days must be comma-separated numbers 0-6 (0=Mon, 6=Sun).", ephemeral=True)
                return
        else:
            days_clean = None
        await self.bot.db.update_bridge_column(bridge_id, 'schedule_pause_hour', pause_hour)
        await self.bot.db.update_bridge_column(bridge_id, 'schedule_resume_hour', resume_hour)
        await self.bot.db.update_bridge_column(bridge_id, 'schedule_days', days_clean)
        self.bot.relay.invalidate_bridge_cache()
        days_str = f" on days {days_clean}" if days_clean else " daily"
        await interaction.followup.send(
            f"✅ Bridge `{bridge_id[:8]}` will auto-pause at **{pause_hour:02d}:00 UTC** "
            f"and resume at **{resume_hour:02d}:00 UTC**{days_str}.",
            ephemeral=True,
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_schedule_set', {
            'bridge_id': bridge_id, 'pause_hour': pause_hour, 'resume_hour': resume_hour, 'days': days_clean,
        })

    @bridge.command(name="scheduleclear", description="Remove the schedule from a bridge (always on)")
    @app_commands.describe(bridge_id="Bridge ID to remove schedule from")
    @require_perm(PermLevel.ADMIN)
    async def bridge_scheduleclear(self, interaction: discord.Interaction, bridge_id: str):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        await self.bot.db.update_bridge_column(bridge_id, 'schedule_pause_hour', None)
        await self.bot.db.update_bridge_column(bridge_id, 'schedule_resume_hour', None)
        await self.bot.db.update_bridge_column(bridge_id, 'schedule_days', None)
        await self.bot.db.update_bridge_column(bridge_id, 'schedule_paused', 0)
        self.bot.relay.invalidate_bridge_cache()
        await interaction.followup.send(f"✅ Schedule cleared for bridge `{bridge_id[:8]}`. Bridge is now always active.", ephemeral=True)

    @bridge.command(name="suggest", description="Suggest that your server bridges with another server")
    @app_commands.describe(
        server_id="ID of the server you want to bridge with",
        message="Why should your server bridge with them? (optional)"
    )
    async def bridge_suggest(self, interaction: discord.Interaction, server_id: str, message: str = None):
        await interaction.response.defer(ephemeral=True)
        try:
            t_sv_id = int(server_id)
        except ValueError:
            await interaction.followup.send("❌ Invalid server ID.", ephemeral=True)
            return
        if t_sv_id == interaction.guild_id:
            await interaction.followup.send("❌ You can't suggest bridging with your own server.", ephemeral=True)
            return
        target_guild = self.bot.get_guild(t_sv_id)
        sugg_id = str(uuid.uuid4())
        await self.bot.db.create_bridge_suggestion(
            sugg_id, interaction.guild_id, interaction.user.id, t_sv_id, message
        )
        server = await self.bot.db.get_server(interaction.guild_id)
        notify_ch_id = server['admin_channel_id'] or server['audit_channel_id'] if server else None
        notify_ch = self.bot.get_channel(notify_ch_id) if notify_ch_id else interaction.channel
        if notify_ch:
            target_name = target_guild.name if target_guild else f"Server `{server_id}`"
            embed = discord.Embed(
                title="💡 Bridge Suggestion",
                description=f"**{interaction.user}** suggests bridging with **{target_name}**.",
                color=0x5865F2,
            )
            if message:
                embed.add_field(name="Their Reason", value=message[:500], inline=False)
            embed.add_field(
                name="How to Act on This",
                value=f"If you agree, use `/bridge create` to send a bridge request to them.\nTarget server ID: `{server_id}`",
                inline=False,
            )
            embed.set_footer(text=f"Suggested by {interaction.user} | {interaction.user.id}")
            try:
                await notify_ch.send(embed=embed)
            except Exception:
                pass
        await interaction.followup.send(
            f"✅ Your suggestion has been forwarded to **your server's admins**. "
            f"They can review it and decide whether to create a bridge.",
            ephemeral=True,
        )

    @bridge.command(name="repair", description="Recreate broken webhooks for a bridge")
    @app_commands.describe(bridge_id="Bridge ID from /bridge list")
    @require_perm(PermLevel.ADMIN)
    async def bridge_repair(self, interaction: discord.Interaction, bridge_id: str):
        await interaction.response.defer(ephemeral=True)
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return

        repaired = []
        failed = []

        for side, ch_id, url_field in [
            ('A', bridge['channel_a_id'], 'webhook_a_url'),
            ('B', bridge['channel_b_id'], 'webhook_b_url'),
        ]:
            ch = self.bot.get_channel(ch_id)
            if not ch:
                failed.append(f"Side {side}: channel not found")
                continue
            ok = await self.bot.webhook_manager.verify_webhook(bridge[url_field] or '')
            if not ok or not bridge[url_field]:
                new_url = await self.bot.webhook_manager.create_webhook(ch)
                if new_url:
                    kwargs = {f'webhook_{side.lower()}_url': new_url}
                    await self.bot.db.update_bridge_webhooks(bridge_id, **kwargs)
                    repaired.append(f"Side {side} ({ch.name})")
                else:
                    failed.append(f"Side {side}: missing Manage Webhooks permission in #{ch.name}")
            else:
                repaired.append(f"Side {side} ({ch.name}) — already healthy")

        lines = []
        if repaired:
            lines.append("✅ **Repaired:**\n" + "\n".join(f"  • {r}" for r in repaired))
        if failed:
            lines.append("❌ **Failed:**\n" + "\n".join(f"  • {f}" for f in failed))

        await interaction.followup.send("\n".join(lines) or "Nothing to repair.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'bridge_repaired', {'bridge_id': bridge_id})


async def setup(bot):
    await bot.add_cog(BridgeCog(bot))
