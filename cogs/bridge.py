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


    @bridge.command(name="analytics", description="View message relay stats for your bridges")
    @app_commands.describe(bridge_id="Specific bridge ID (optional — shows all if omitted)")
    @require_perm(PermLevel.MOD)
    async def bridge_analytics(self, interaction: discord.Interaction, bridge_id: str = None):
        await interaction.response.defer(ephemeral=True)
        if bridge_id:
            bridge = await self.bot.db.get_bridge(bridge_id)
            if not bridge:
                await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
                return
            if bridge['channel_a_server_id'] != interaction.guild_id and bridge['channel_b_server_id'] != interaction.guild_id:
                await interaction.followup.send("❌ That bridge is not connected to your server.", ephemeral=True)
                return
            embed = discord.Embed(title=f"📊 Bridge Analytics — `{bridge_id[:8]}`", color=0x5865F2)
            embed.add_field(name="Channels", value=f"<#{bridge['channel_a_id']}> ↔ <#{bridge['channel_b_id']}>", inline=False)
            embed.add_field(name="Total Messages Relayed", value=f"{bridge['total_messages'] or 0:,}", inline=True)
            embed.add_field(name="Status", value="Active" if bridge['active'] and not bridge['paused'] else "Paused", inline=True)
            if bridge.get('last_message_at'):
                embed.add_field(name="Last Activity", value=str(bridge['last_message_at']), inline=True)
            embed.add_field(name="Ping Mode", value=(bridge.get('ping_mode') or 'none').title(), inline=True)
            embed.add_field(name="Link Mode", value=(bridge.get('link_mode') or 'all').title(), inline=True)
            if bridge.get('purpose'):
                embed.add_field(name="Purpose", value=bridge['purpose'], inline=False)
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
                    value=f"<#{b['channel_a_id']}> ↔ <#{b['channel_b_id']}>\n{b['total_messages'] or 0:,} msgs",
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
