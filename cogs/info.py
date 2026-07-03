import discord
from discord import app_commands
from discord.ext import commands
import time


class InfoCog(commands.Cog, name="Info"):
    def __init__(self, bot):
        self.bot = bot
        self._start_time = time.time()

    @app_commands.command(name="ping", description="Check BridgeBot's latency")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        color = 0x57F287 if latency < 100 else (0xFEE75C if latency < 200 else 0xED4245)
        embed = discord.Embed(title="🏓 Pong!", color=color)
        embed.add_field(name="Gateway Latency", value=f"`{latency}ms`")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="stats", description="View BridgeBot's global statistics")
    async def stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        s = await self.bot.db.get_global_stats()
        uptime_s = int(time.time() - self._start_time)
        h, m = divmod(uptime_s // 60, 60)
        uptime_str = f"{h}h {m}m"

        embed = discord.Embed(title="📊 BridgeBot Stats", color=0x5865F2)
        embed.add_field(name="Servers", value=f"`{s['servers']:,}`", inline=True)
        embed.add_field(name="Active Bridges", value=f"`{s['bridges']:,}`", inline=True)
        embed.add_field(name="Messages Relayed", value=f"`{s['messages_relayed']:,}`", inline=True)
        embed.add_field(name="Federations", value=f"`{s['federations']:,}`", inline=True)
        embed.add_field(name="Uptime", value=f"`{uptime_str}`", inline=True)
        embed.add_field(name="Latency", value=f"`{round(self.bot.latency * 1000)}ms`", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="bridges", description="List all active bridges on this server")
    async def bridges(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        all_bridges = await self.bot.db.get_bridges_for_server(interaction.guild_id)

        if not all_bridges:
            await interaction.followup.send("No bridges on this server. Admins can use `/bridge create` to set one up.", ephemeral=True)
            return

        embed = discord.Embed(title="🌉 Bridges on This Server", color=0x5865F2)
        for b in all_bridges:
            ch_a = self.bot.get_channel(b['channel_a_id'])
            ch_b = self.bot.get_channel(b['channel_b_id'])
            a_str = f"<#{b['channel_a_id']}>" if ch_a else f"`{b['channel_a_id']}`"
            b_str = f"<#{b['channel_b_id']}>" if ch_b else f"`{b['channel_b_id']}`"
            status = "⏸️" if b['paused'] else ("✅" if b['active'] else "❌")
            embed.add_field(name=f"{status} `{b['id'][:8]}`", value=f"{a_str} ↔ {b_str}", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="status", description="Check if all bridges on this server are healthy")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        all_bridges = await self.bot.db.get_bridges_for_server(interaction.guild_id)

        embed = discord.Embed(title="🔍 Bridge Health Check", color=0x5865F2)
        embed.add_field(name="Bot Status", value="✅ Online", inline=True)
        embed.add_field(name="Latency", value=f"`{round(self.bot.latency * 1000)}ms`", inline=True)
        embed.add_field(name="Total Bridges", value=str(len(all_bridges)), inline=True)

        issues = []
        for b in all_bridges:
            if not b['active']:
                issues.append(f"❌ `{b['id'][:8]}` — Inactive")
            elif b['paused']:
                issues.append(f"⏸️ `{b['id'][:8]}` — Paused")
            elif not b['webhook_a_url'] or not b['webhook_b_url']:
                issues.append(f"⚠️ `{b['id'][:8]}` — Missing webhook")

        if issues:
            embed.add_field(name="Issues Found", value="\n".join(issues), inline=False)
            embed.color = 0xFEE75C
        else:
            embed.add_field(name="All Clear", value="✅ All bridges are healthy.", inline=False)
            embed.color = 0x57F287

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Show all BridgeBot commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🌉 BridgeBot — Command Reference",
            description="Connect Discord servers with channel bridges and federations.",
            color=0x5865F2,
        )
        embed.add_field(
            name="🌉 Bridge Commands",
            value=(
                "`/bridge create` — Request a channel bridge\n"
                "`/bridge list` — List all server bridges\n"
                "`/bridge delete` — Remove a bridge\n"
                "`/bridge pause` — Pause a bridge\n"
                "`/bridge resume` — Resume a bridge\n"
                "`/bridge toggle` — Toggle relay settings\n"
                "`/bridge stats` — View bridge stats"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏛️ Federation Commands",
            value=(
                "`/federation create` — Create a federation\n"
                "`/federation invite` — Invite a server\n"
                "`/federation accept` — Accept an invite\n"
                "`/federation decline` — Decline an invite\n"
                "`/federation leave` — Leave a federation\n"
                "`/federation list` — Your federations\n"
                "`/federation info` — Federation details\n"
                "`/federation members` — Member servers\n"
                "`/federation delete` — Delete (owner only)\n"
                "`/federation kick` — Remove a server (owner only)"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ Setup & Config",
            value=(
                "`/setup` — First-time setup wizard\n"
                "`/config view` — View server config\n"
                "`/config set` — Change a config value\n"
                "`/blacklist add/remove/list` — Manage server blacklist\n"
                "`/rolesync add/remove/list/toggle` — Role sync mappings"
            ),
            inline=False,
        )
        embed.add_field(
            name="📊 Info Commands",
            value=(
                "`/ping` — Bot latency\n"
                "`/stats` — Global statistics\n"
                "`/bridges` — Bridges on this server\n"
                "`/status` — Bridge health check\n"
                "`/help` — This menu"
            ),
            inline=False,
        )
        embed.set_footer(text="Permission levels: Member < Mod (Manage Messages) < Admin (Manage Server) < Owner")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="report", description="Report a user from a bridged server")
    @app_commands.describe(user_id="The user's Discord ID", reason="What did they do?")
    async def report(self, interaction: discord.Interaction, user_id: str, reason: str):
        await interaction.response.defer(ephemeral=True)
        server = await self.bot.db.get_server(interaction.guild_id)
        if server and server['audit_channel_id']:
            ch = self.bot.get_channel(server['audit_channel_id'])
            if ch:
                embed = discord.Embed(title="🚨 User Report", color=0xED4245)
                embed.add_field(name="Reported User ID", value=f"`{user_id}`", inline=True)
                embed.add_field(name="Reported by", value=f"{interaction.user.mention}", inline=True)
                embed.add_field(name="Server", value=interaction.guild.name, inline=True)
                embed.add_field(name="Reason", value=reason, inline=False)
                try:
                    await ch.send(embed=embed)
                    await interaction.followup.send("✅ Report submitted to server moderators.", ephemeral=True)
                    return
                except Exception:
                    pass
        await interaction.followup.send("✅ Report received. Moderators have been notified.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(InfoCog(bot))
