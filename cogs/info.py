import discord
from discord import app_commands
from discord.ext import commands
import time

TUTORIAL_PAGES = [
    discord.Embed(
        title="🌉 BridgeBot Tutorial — Page 1 of 8: What is BridgeBot?",
        description=(
            "**BridgeBot connects Discord servers by linking channels together.**\n\n"
            "When a message is sent in a bridged channel, it is automatically relayed to the partner "
            "channel in another server — appearing with the sender's name and avatar via webhook.\n\n"
            "**What you can do with BridgeBot:**\n"
            "• 🌉 **Bridges** — Link a channel in your server to a channel in another server\n"
            "• 🏛️ **Federations** — Group multiple servers together under one alliance\n"
            "• 📊 **Polls** — Run votes that span all servers in a federation\n"
            "• 📢 **Hub Broadcasts** — Send announcements to all federation members at once\n"
            "• 🏆 **Leaderboards** — See which servers are the most active globally\n\n"
            "**Who this tutorial is for:**\n"
            "This tutorial walks through setup and usage from the perspective of a server admin. "
            "Regular members only need to know they can type in bridged channels normally — "
            "BridgeBot handles everything else automatically."
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="🌉 BridgeBot Tutorial — Page 2 of 8: First-Time Setup",
        description=(
            "**Run `/setup` first** — it shows you the recommended configuration steps.\n\n"
            "**Recommended channels to create in your server:**\n"
            "• `#bridge-admin` — Only admins can use this; run all BridgeBot commands here\n"
            "• `#bridge-logs` — BridgeBot posts audit logs here (who created/deleted what)\n\n"
            "**Connect those channels to BridgeBot:**\n"
            "```\n"
            "/config set  →  Admin Channel (restricts commands to #bridge-admin)\n"
            "/config set  →  Audit Log Channel (logs all admin actions)\n"
            "```\n"
            "**Optional — create a BridgeBot Admin role:**\n"
            "If you want non-owner staff to be able to manage bridges, create a role "
            "and set it with:\n"
            "```\n/config set  →  BridgeBot Admin Role ID\n```\n"
            "**Check your config anytime:**\n"
            "```\n/config view\n```\n"
            "⚠️ BridgeBot needs **Manage Webhooks** permission in every channel you want to bridge."
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="🌉 BridgeBot Tutorial — Page 3 of 8: Creating Your First Bridge",
        description=(
            "A bridge connects **one channel in your server** to **one channel in another server**. "
            "Both sides must have an admin approve it.\n\n"
            "**Step 1 — Get the target server's info:**\n"
            "Ask an admin of the other server for their:\n"
            "• Server ID (right-click server icon → Copy Server ID)\n"
            "• Channel ID (right-click the channel → Copy Channel ID)\n\n"
            "**Step 2 — Send the bridge request from your server:**\n"
            "```\n/bridge create\n  target_server_id: 123456789\n  target_channel_id: 987654321\n```\n"
            "This sends a notification to the other server with **Accept / Decline** buttons.\n\n"
            "**Step 3 — The other server accepts:**\n"
            "An admin there clicks **✅ Accept Bridge** and webhooks are created on both sides. "
            "The bridge goes live instantly.\n\n"
            "**Step 4 — Test it:**\n"
            "Send a message in your bridged channel. It should appear in theirs within a second.\n\n"
            "💡 Either server can delete the bridge at any time with `/bridge delete`."
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="🌉 BridgeBot Tutorial — Page 4 of 8: Managing Bridges",
        description=(
            "**View all your bridges:**\n"
            "```\n/bridge list\n```\n"
            "Each bridge has a short ID (e.g. `a1b2c3d4`). Use this ID in all bridge commands.\n\n"
            "**Pause / resume a bridge** (keeps the bridge alive but stops relaying):\n"
            "```\n/bridge pause  bridge_id: a1b2c3d4\n/bridge resume bridge_id: a1b2c3d4\n```\n"
            "**Delete a bridge permanently:**\n"
            "```\n/bridge delete bridge_id: a1b2c3d4\n```\n"
            "**Check bridge health:**\n"
            "```\n/status\n```\n"
            "If a webhook is broken (deleted from Discord), fix it with:\n"
            "```\n/bridge repair bridge_id: a1b2c3d4\n```\n"
            "**View message stats:**\n"
            "```\n/bridge analytics bridge_id: a1b2c3d4\n```\n"
            "Shows messages relayed in the last 7 days, 30 days, and all-time.\n\n"
            "**Toggle what gets relayed** (edits, deletes, attachments, embeds):\n"
            "```\n/bridge toggle bridge_id: a1b2c3d4  setting: relay_edits\n```"
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="🌉 BridgeBot Tutorial — Page 5 of 8: Bridge Customization",
        description=(
            "**Control how messages appear in the other server:**\n\n"
            "`/bridge setname` — Override the display name for all relayed messages\n"
            "`/bridge setavatar` — Override the avatar shown on relayed messages (image URL)\n"
            "`/bridge setpurpose` — Add a label so everyone knows what a bridge is for\n\n"
            "**Control mentions:**\n"
            "```\n/bridge setping bridge_id: a1b2c3d4  mode: none\n```\n"
            "• `none` — Role mentions are stripped (recommended for public bridges)\n"
            "• `role` — Role mentions pass through\n"
            "• `all` — Everything passes through\n\n"
            "**Control links:**\n"
            "```\n/bridge setlinks bridge_id: a1b2c3d4  mode: safe\n```\n"
            "• `safe` — Only known-safe domains (YouTube, Discord, GitHub, etc.) pass through\n"
            "• `warn` — Unknown links get a ⚠️ prefix\n"
            "• `all` — All links pass through\n\n"
            "**Auto-pause on a schedule** (e.g. overnight):\n"
            "```\n/bridge scheduleset bridge_id: a1b2c3d4  pause_hour: 22  resume_hour: 8\n```\n"
            "Uses UTC time. Bridge auto-pauses at 22:00 UTC and resumes at 08:00 UTC every day."
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="🌉 BridgeBot Tutorial — Page 6 of 8: Federations",
        description=(
            "A **federation** is a named alliance of multiple servers. "
            "It unlocks cross-server features like polls and hub broadcasts.\n\n"
            "**Create a federation (you become the owner):**\n"
            "```\n/federation create  name: My Alliance  description: Gaming community\n```\n"
            "**Invite another server to join:**\n"
            "```\n/federation invite  federation_id: abc123  server_id: 111222333\n```\n"
            "The invited server accepts with `/federation accept`.\n\n"
            "**List your federations:**\n"
            "```\n/federation list\n/federation info  federation_id: abc123\n/federation members  federation_id: abc123\n```\n"
            "**Make your federation discoverable** (other servers can request to join):\n"
            "```\n/federation publish  federation_id: abc123  category: gaming\n```\n"
            "Servers find you with `/federation discover` and send a join request.\n"
            "You approve/decline with `/federation review`.\n\n"
            "**Leave a federation:**\n"
            "```\n/federation leave  federation_id: abc123\n```"
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="🌉 BridgeBot Tutorial — Page 7 of 8: Advanced Features",
        description=(
            "**📊 Cross-server polls** (federation members only):\n"
            "```\n/poll create  federation_id: abc123  question: Best game?  options: Minecraft,Fortnite,Roblox\n```\n"
            "All members vote via buttons. Results update live across all servers.\n\n"
            "**📢 Hub broadcasts** (announce to all federation servers):\n"
            "```\n/hub set          → Set your server as the hub\n"
            "/hub target       → Set where broadcasts land on your server\n"
            "/hub broadcast    → Send an announcement to everyone\n```\n"
            "**📋 Bridge templates** (save and reuse bridge settings):\n"
            "```\n/template save    → Save current bridge settings as a template\n"
            "/template load    → Apply a saved template to a new bridge\n"
            "/template share   → Share your template publicly\n```\n"
            "**🔗 Referrals** (track who brought you here):\n"
            "```\n/referrals link   → Get your referral code to share\n"
            "/referrals credit → Credit the server that referred you\n"
            "/referrals stats  → See how many servers you've referred\n```\n"
            "**⭐ Reputation** — Earned automatically. The more active your bridges, "
            "the higher your score. Check the global ranking with `/leaderboard reputation`."
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="🌉 BridgeBot Tutorial — Page 8 of 8: Tips & Troubleshooting",
        description=(
            "**Common issues and fixes:**\n\n"
            "❌ **Messages not relaying**\n"
            "→ Run `/status` to check bridge health\n"
            "→ Make sure BridgeBot has **Manage Webhooks** in the bridged channel\n"
            "→ Run `/bridge repair` if a webhook is missing\n\n"
            "❌ **Bridge request not arriving in the other server**\n"
            "→ The other server needs BridgeBot added and a channel the bot can post in\n"
            "→ Ask their admin to check their `#bridge-admin` channel\n\n"
            "❌ **Bridge got auto-paused**\n"
            "→ If no messages for 14 days, bridges auto-pause. Use `/bridge resume`\n"
            "→ Bridges inactive for 37 days are permanently deleted\n\n"
            "❌ **Webhook broken / spam pause**\n"
            "→ If 15+ messages hit a bridge in 10 seconds, it spam-pauses for 60s automatically\n"
            "→ Use `/bridge repair` to fix deleted webhooks\n\n"
            "**Useful daily commands:**\n"
            "```\n"
            "/bridges          → Quick list of all your bridges\n"
            "/status           → Health check for all bridges\n"
            "/bridge analytics → Message stats per bridge\n"
            "/leaderboard server → Your server's global rank\n"
            "```\n"
            "That's everything! Use `/help` for a full command reference."
        ),
        color=0x57F287,
    ),
]


class TutorialView(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=300)
        self.page = page
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(TUTORIAL_PAGES) - 1
        self.page_label.label = f"{self.page + 1} / {len(TUTORIAL_PAGES)}"

    def _embed(self):
        e = TUTORIAL_PAGES[self.page].copy()
        e.set_footer(text="Use the buttons below to navigate • Only visible to you")
        return e

    @discord.ui.button(label="← Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="1 / 8", style=discord.ButtonStyle.primary, disabled=True)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Next →", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)


SUPPORT_SERVER = "https://discord.gg/RjrVAeB3R"

HELP_PAGES = [
    discord.Embed(
        title="🌉 BridgeBot — Overview",
        description=(
            "**Connect Discord servers with live channel bridges.**\n"
            "Messages relay instantly with real names and avatars — no bots, no copy-paste.\n\n"
            "**Quick Start**\n"
            "`/setup` — First-time setup wizard\n"
            "`/bridge create` — Request a channel bridge with another server\n"
            "`/federation create` — Group servers into an alliance\n"
            "`/tutorial` — Full interactive guide (Admin only)\n\n"
            "**Utility**\n"
            "`/bridges` — List all bridges on this server\n"
            "`/status` — Bridge health check\n"
            "`/ping` — Check bot latency\n"
            "`/stats` — Global BridgeBot statistics\n"
            "`/report` — Report a user from a bridged server"
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="🌉 Bridge Commands",
        description=(
            "**Create & Manage**\n"
            "`/bridge create` — Request a channel bridge\n"
            "`/bridge forum` — Bridge two forum channels\n"
            "`/bridge list` — List all your bridges\n"
            "`/bridge delete` — Remove a bridge permanently\n"
            "`/bridge pause` — Pause relaying (keeps bridge alive)\n"
            "`/bridge resume` — Resume a paused bridge\n"
            "`/bridge repair` — Fix broken webhooks\n"
            "`/bridge analytics` — Stats: 7d / 30d / all-time\n"
            "`/bridge toggle` — Toggle edits, deletes, embeds, attachments\n"
            "`/bridge suggest` — Suggest a bridge (any member)\n\n"
            "**Customization**\n"
            "`/bridge setname` — Custom display name for relayed messages\n"
            "`/bridge setavatar` — Custom avatar URL for relayed messages\n"
            "`/bridge setpurpose` — Label what a bridge is for\n"
            "`/bridge setping` — Control mention passthrough (`none` / `role` / `all`)\n"
            "`/bridge setlinks` — Link filtering (`safe` / `warn` / `all`)\n"
            "`/bridge scheduleset` — Auto-pause between hours (UTC)\n"
            "`/bridge scheduleclear` — Remove auto-pause schedule"
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="🏛️ Federation Commands",
        description=(
            "**Setup**\n"
            "`/federation create` — Create a federation (you become owner)\n"
            "`/federation invite` — Invite another server\n"
            "`/federation accept` — Accept an invite\n"
            "`/federation decline` — Decline an invite\n"
            "`/federation leave` — Leave a federation\n\n"
            "**Browse**\n"
            "`/federation list` — List federations you're in\n"
            "`/federation info` — Details about a federation\n"
            "`/federation members` — See all member servers\n\n"
            "**Public Directory**\n"
            "`/federation publish` — List your federation publicly\n"
            "`/federation unpublish` — Remove from public directory\n"
            "`/federation discover` — Browse public federations\n"
            "`/federation request` — Send a join request\n"
            "`/federation review` — Approve / decline join requests\n\n"
            "**Owner Only**\n"
            "`/federation delete` — Disband federation\n"
            "`/federation kick` — Remove a server\n"
            "`/federation transfer` — Transfer ownership"
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="📊 Polls, Hub & Templates",
        description=(
            "**Cross-Server Polls** *(federation members only)*\n"
            "`/poll create` — Create a vote across all federation servers\n"
            "`/poll end` — Close a poll early\n"
            "`/poll results` — See current results\n"
            "`/poll list` — List active polls\n\n"
            "**Hub Broadcasts** *(send announcements to all federation servers)*\n"
            "`/hub set` — Set your server as the federation hub\n"
            "`/hub broadcast` — Send an announcement to all servers\n"
            "`/hub target` — Set where incoming broadcasts land\n\n"
            "**Bridge Templates** *(save & reuse bridge settings)*\n"
            "`/template save` — Save a bridge's settings as a template\n"
            "`/template load` — Apply a saved template to a bridge\n"
            "`/template list` — View your saved templates\n"
            "`/template share` — Share a template publicly"
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="⚙️ Setup & Configuration",
        description=(
            "**Initial Setup**\n"
            "`/setup` — Step-by-step first-time setup wizard\n"
            "`/config view` — View all current settings\n"
            "`/config set` — Change a setting (admin channel, audit log, role, etc.)\n\n"
            "**Access Control**\n"
            "`/blacklist add` — Block a server from bridging with you\n"
            "`/blacklist remove` — Unblock a server\n"
            "`/blacklist list` — View blocked servers\n"
            "`/rolesync add` — Sync a role across bridged servers\n"
            "`/rolesync remove` — Remove a role sync\n"
            "`/rolesync list` — View active role syncs\n"
            "`/rolesync toggle` — Enable/disable role sync\n\n"
            "**Data & Alerts**\n"
            "`/export` — Export config as JSON backup\n"
            "`/config import` — Restore config from a JSON file\n"
            "`/bridgealert` — Set channel for bridge alerts\n"
            "`/digest on` / `off` — Weekly activity digest\n"
            "`/webhook rotate` — Rotate all webhook URLs"
        ),
        color=0x5865F2,
    ),
    discord.Embed(
        title="🚫 Moderation & Safety",
        description=(
            "**Ban Relay** *(requires a federation)*\n"
            "`/banrelay enable` — Enable ban relay for a federation\n"
            "  • `mode: automatic` — fires on every ban\n"
            "  • `mode: manual only` — only fires when you use `/banrelay ban`\n"
            "  • `auto_ban: True` — auto-bans user in all federated servers\n"
            "`/banrelay ban` — Manually relay a ban with a custom reason\n"
            "  *(use this when another bot did the ban and the reason is missing)*\n"
            "`/banrelay disable` — Disable ban relay\n"
            "`/banrelay status` — Check relay mode per federation\n"
            "`/banrelay exclude` — Exclude a user from being relayed\n\n"
            "**Reports**\n"
            "`/report` — Report a user from a bridged server to your mods"
        ),
        color=0xED4245,
    ),
    discord.Embed(
        title="🏆 Leaderboards, Stats & Referrals",
        description=(
            "**Leaderboards**\n"
            "`/leaderboard bridges` — Servers with the most bridges\n"
            "`/leaderboard messages` — Servers with the most messages relayed\n"
            "`/leaderboard federations` — Largest federations\n"
            "`/leaderboard activity` — Most active bridges\n"
            "`/leaderboard reputation` — Server reputation scores & tiers\n"
            "`/leaderboard server` — Your server's rank and reputation badge\n\n"
            "**Reputation Tiers** *(earned automatically)*\n"
            "🥉 Newcomer → 🥈 Connector → 🥇 Bridge Builder\n"
            "💎 Network Leader → 👑 Network Champion\n\n"
            "**Referrals**\n"
            "`/referrals link` — Get your server's referral code\n"
            "`/referrals credit` — Credit a server that referred you\n"
            "`/referrals stats` — See how many servers you've brought in"
        ),
        color=0xFEE75C,
    ),
]

HELP_CATEGORY_LABELS = [
    "🌉 Overview",
    "🌉 Bridges",
    "🏛️ Federations",
    "📊 Polls & Hub",
    "⚙️ Config",
    "🚫 Moderation",
    "🏆 Leaderboards",
]


class HelpSelect(discord.ui.Select):
    def __init__(self, view_ref):
        options = [
            discord.SelectOption(label=label, value=str(i))
            for i, label in enumerate(HELP_CATEGORY_LABELS)
        ]
        super().__init__(placeholder="Jump to a category...", options=options, row=0)
        self._view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        self._view_ref.page = int(self.values[0])
        self._view_ref._update_buttons()
        await interaction.response.edit_message(embed=self._view_ref._embed(), view=self._view_ref)


class HelpView(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=300)
        self.page = page
        self.add_item(HelpSelect(self))
        self.add_item(discord.ui.Button(
            label="💬 Support Server",
            style=discord.ButtonStyle.link,
            url=SUPPORT_SERVER,
            row=1,
        ))
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(HELP_PAGES) - 1
        self.page_label.label = f"{self.page + 1} / {len(HELP_PAGES)}"

    def _embed(self):
        e = HELP_PAGES[self.page].copy()
        e.set_footer(text=f"BridgeBot • {HELP_CATEGORY_LABELS[self.page]} • Use /tutorial for the full setup guide")
        return e

    @discord.ui.button(label="← Prev", style=discord.ButtonStyle.secondary, row=2)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="1 / 7", style=discord.ButtonStyle.primary, disabled=True, row=2)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Next →", style=discord.ButtonStyle.secondary, row=2)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)


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

        embed = discord.Embed(
            title="📊 BridgeBot Stats",
            description=f"Global statistics across all servers using BridgeBot.",
            color=0x5865F2,
        )
        embed.add_field(name="🌍 Connected Servers", value=f"`{s['servers']:,}`", inline=True)
        embed.add_field(name="✅ Active Servers", value=f"`{s.get('active_servers', 0):,}`", inline=True)
        embed.add_field(name="🌉 Active Bridges", value=f"`{s['bridges']:,}`", inline=True)
        embed.add_field(name="💬 Messages Relayed", value=f"`{s['messages_relayed']:,}`", inline=True)
        embed.add_field(name="🏛️ Federations", value=f"`{s['federations']:,}`", inline=True)
        embed.add_field(name="⭐ Reputation Score", value=f"`{s.get('total_reputation', 0):,.0f}` pts", inline=True)
        embed.add_field(name="⏱️ Uptime", value=f"`{uptime_str}`", inline=True)
        embed.add_field(name="📶 Latency", value=f"`{round(self.bot.latency * 1000)}ms`", inline=True)
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

    @app_commands.command(name="help", description="Browse all BridgeBot commands by category")
    async def help(self, interaction: discord.Interaction):
        view = HelpView(page=0)
        await interaction.response.send_message(embed=view._embed(), view=view, ephemeral=True)

    @app_commands.command(name="tutorial", description="Interactive step-by-step guide to setting up and using BridgeBot (Admin only)")
    async def tutorial(self, interaction: discord.Interaction):
        from core.permissions import get_perm_level, PermLevel
        level = await get_perm_level(interaction)
        if level < PermLevel.ADMIN:
            await interaction.response.send_message("❌ The tutorial is for admins only.", ephemeral=True)
            return
        view = TutorialView(page=0)
        await interaction.response.send_message(embed=view._embed(), view=view, ephemeral=True)

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
