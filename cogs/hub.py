import discord
from discord import app_commands
from discord.ext import commands
import uuid
from core.permissions import require_perm, PermLevel, send_audit_log


class HubCog(commands.Cog, name="Hub"):
    def __init__(self, bot):
        self.bot = bot

    hub_group = app_commands.Group(name="hub", description="Federation hub broadcasting")

    @hub_group.command(name="set", description="Set this server as the hub for a federation you own")
    @app_commands.describe(
        federation_id="Federation ID you own",
        channel="Channel to use as the hub broadcast channel"
    )
    @require_perm(PermLevel.OWNER)
    async def hub_set(self, interaction: discord.Interaction, federation_id: str, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return
        if fed['owner_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ Only the federation owner server can set the hub.", ephemeral=True)
            return
        await self.bot.db.set_hub_channel(federation_id, interaction.guild_id, channel.id)
        await interaction.followup.send(
            f"✅ **{fed['name']}** hub set to {channel.mention}. Use `/hub broadcast` to send announcements to all members.",
            ephemeral=True,
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'hub_set', {
            'federation_id': federation_id, 'channel': channel.name,
        })

    @hub_group.command(name="broadcast", description="Broadcast a message to all servers in a federation")
    @app_commands.describe(
        federation_id="Federation ID",
        message="Message to broadcast to all member servers"
    )
    @require_perm(PermLevel.ADMIN)
    async def hub_broadcast(self, interaction: discord.Interaction, federation_id: str, message: str):
        await interaction.response.defer(ephemeral=True)
        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return

        hub = await self.bot.db.get_hub_channel(federation_id)
        if not hub or hub['server_id'] != interaction.guild_id:
            await interaction.followup.send(
                "❌ Your server is not the hub for this federation. Use `/hub set` first.", ephemeral=True
            )
            return

        members = await self.bot.db.get_federation_members(federation_id)
        embed = discord.Embed(
            title=f"📢 Announcement from {interaction.guild.name}",
            description=message[:2000],
            color=0x5865F2,
        )
        embed.set_footer(text=f"Via {fed['name']} federation hub | From: {interaction.user}")

        sent = 0
        for member in members:
            if member['server_id'] == interaction.guild_id:
                continue
            targets = await self.bot.db.get_broadcast_targets(federation_id)
            ch = None
            for t in targets:
                if t['server_id'] == member['server_id']:
                    ch = self.bot.get_channel(t['channel_id'])
                    break
            if not ch:
                guild = self.bot.get_guild(member['server_id'])
                if guild:
                    ch = guild.system_channel
                    if not ch:
                        for tc in guild.text_channels:
                            if tc.permissions_for(guild.me).send_messages:
                                ch = tc
                                break
            if ch:
                try:
                    await ch.send(embed=embed)
                    sent += 1
                except Exception:
                    pass

        await interaction.followup.send(f"✅ Broadcast sent to {sent} servers.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'hub_broadcast', {
            'federation_id': federation_id, 'recipients': sent,
        })

    @hub_group.command(name="target", description="Set which channel receives hub broadcasts for your server")
    @app_commands.describe(
        federation_id="Federation ID you're a member of",
        channel="Channel to receive hub broadcasts"
    )
    @require_perm(PermLevel.ADMIN)
    async def hub_target(self, interaction: discord.Interaction, federation_id: str, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return
        members = await self.bot.db.get_federation_members(federation_id)
        if not any(m['server_id'] == interaction.guild_id for m in members):
            await interaction.followup.send("❌ Your server is not a member of this federation.", ephemeral=True)
            return
        await self.bot.db.set_broadcast_target(str(uuid.uuid4()), federation_id, interaction.guild_id, channel.id)
        await interaction.followup.send(
            f"✅ Hub broadcasts from **{fed['name']}** will be delivered to {channel.mention}.",
            ephemeral=True,
        )

    @hub_group.command(name="status", description="View hub configuration for a federation")
    @app_commands.describe(federation_id="Federation ID")
    async def hub_status(self, interaction: discord.Interaction, federation_id: str):
        await interaction.response.defer(ephemeral=True)
        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return
        hub = await self.bot.db.get_hub_channel(federation_id)
        targets = await self.bot.db.get_broadcast_targets(federation_id)
        embed = discord.Embed(title=f"📡 Hub — {fed['name']}", color=0x5865F2)
        if hub:
            hub_guild = self.bot.get_guild(hub['server_id'])
            embed.add_field(
                name="Hub Server",
                value=f"{hub_guild.name if hub_guild else hub['server_id']} → <#{hub['channel_id']}>",
                inline=False,
            )
        else:
            embed.add_field(name="Hub Server", value="Not configured — use `/hub set`", inline=False)
        if targets:
            lines = []
            for t in targets:
                g = self.bot.get_guild(t['server_id'])
                lines.append(f"• {g.name if g else t['server_id']} → <#{t['channel_id']}>")
            embed.add_field(name="Broadcast Targets", value='\n'.join(lines[:10]), inline=False)
        else:
            embed.add_field(name="Broadcast Targets", value="None set — members use `/hub target`", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(HubCog(bot))
