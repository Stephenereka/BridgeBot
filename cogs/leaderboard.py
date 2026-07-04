import discord
from discord import app_commands
from discord.ext import commands


MEDALS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


class LeaderboardCog(commands.Cog, name="Leaderboard"):
    def __init__(self, bot):
        self.bot = bot

    lb = app_commands.Group(name="leaderboard", description="Global and server leaderboards")

    @lb.command(name="bridges", description="Top 10 servers with the most active bridges globally")
    async def lb_bridges(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await self.bot.db.leaderboard_bridges()

        embed = discord.Embed(
            title="🌉 Top 10 — Most Bridges",
            description="Servers with the most active channel bridges.",
            color=0x5865F2,
        )
        if not rows:
            embed.description = "No bridges yet. Be the first!"
        else:
            lines = []
            for i, row in enumerate(rows[:10]):
                guild = self.bot.get_guild(row['server_id'])
                name = guild.name if guild else row['server_name']
                lines.append(f"{MEDALS[i]} **{name}** — `{row['bridge_count']}` bridges")
            embed.description = "\n".join(lines)

        embed.set_footer(text="Create bridges with /bridge create to climb the leaderboard!")
        await interaction.followup.send(embed=embed)

    @lb.command(name="messages", description="Top 10 servers by total messages relayed globally")
    async def lb_messages(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await self.bot.db.leaderboard_messages()

        embed = discord.Embed(
            title="💬 Top 10 — Most Messages Relayed",
            description="Servers that have relayed the most messages across bridges.",
            color=0x5865F2,
        )
        if not rows:
            embed.description = "No messages relayed yet!"
        else:
            lines = []
            for i, row in enumerate(rows[:10]):
                guild = self.bot.get_guild(row['server_id'])
                name = guild.name if guild else row['server_name']
                lines.append(f"{MEDALS[i]} **{name}** — `{row['msg_count']:,}` messages")
            embed.description = "\n".join(lines)

        embed.set_footer(text="More bridges = more messages = higher rank!")
        await interaction.followup.send(embed=embed)

    @lb.command(name="federations", description="Top 10 federations by number of member servers")
    async def lb_federations(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await self.bot.db.leaderboard_federations()

        embed = discord.Embed(
            title="🏛️ Top 10 — Largest Federations",
            description="Federations with the most member servers.",
            color=0x5865F2,
        )
        if not rows:
            embed.description = "No federations yet. Create one with `/federation create`!"
        else:
            lines = []
            for i, row in enumerate(rows[:10]):
                lines.append(f"{MEDALS[i]} **{row['name']}** — `{row['member_count']}` servers")
            embed.description = "\n".join(lines)

        embed.set_footer(text="Grow your federation with /federation invite!")
        await interaction.followup.send(embed=embed)

    @lb.command(name="activity", description="Top 10 most active bridges by messages relayed")
    async def lb_activity(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await self.bot.db.leaderboard_bridge_activity()

        embed = discord.Embed(
            title="⚡ Top 10 — Most Active Bridges",
            description="The busiest channel bridges on the network.",
            color=0x5865F2,
        )
        if not rows:
            embed.description = "No bridge activity yet!"
        else:
            lines = []
            for i, row in enumerate(rows[:10]):
                ch_a = self.bot.get_channel(row['channel_a_id'])
                ch_b = self.bot.get_channel(row['channel_b_id'])
                a_str = f"#{ch_a.name}" if ch_a else f"ch:{row['channel_a_id']}"
                b_str = f"#{ch_b.name}" if ch_b else f"ch:{row['channel_b_id']}"
                lines.append(f"{MEDALS[i]} **{a_str} ↔ {b_str}** — `{row['msg_count']:,}` messages")
            embed.description = "\n".join(lines)

        await interaction.followup.send(embed=embed)

    @lb.command(name="reputation", description="Top 10 servers by reputation score")
    async def lb_reputation(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await self.bot.db.leaderboard_reputation()
        embed = discord.Embed(
            title="⭐ Top 10 — Server Reputation",
            description="Servers ranked by reputation score (based on bridges, messages, federations, and longevity).",
            color=0x5865F2,
        )
        if not rows:
            embed.description = "No reputation scores yet — scores update daily!"
        else:
            lines = []
            for i, row in enumerate(rows[:10]):
                guild = self.bot.get_guild(row['id'])
                name = guild.name if guild else row['name']
                badge = self.bot.db.get_reputation_badge(row['reputation_score'])
                lines.append(f"{MEDALS[i]} **{name}** — {badge} `{row['reputation_score']:.0f} pts`")
            embed.description = "\n".join(lines)
        embed.set_footer(text="Scores update daily. Earn points through active bridges, messages, and federations.")
        await interaction.followup.send(embed=embed)

    @lb.command(name="server", description="See how this server ranks on the global leaderboard")
    async def lb_server(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        bridge_rank = await self.bot.db.server_bridge_rank(interaction.guild_id)
        msg_rank = await self.bot.db.server_message_rank(interaction.guild_id)
        bridge_count = await self.bot.db.server_bridge_count(interaction.guild_id)
        msg_count = await self.bot.db.server_message_count(interaction.guild_id)
        fed_count = len(await self.bot.db.get_federations_for_server(interaction.guild_id))
        server_data = await self.bot.db.get_server(interaction.guild_id)
        rep_score = server_data['reputation_score'] if server_data else 0
        rep_badge = self.bot.db.get_reputation_badge(rep_score)
        rep_rank = await self.bot.db.get_server_reputation_rank(interaction.guild_id)

        embed = discord.Embed(
            title=f"📊 {interaction.guild.name} — Global Rank",
            color=0x5865F2,
        )
        embed.add_field(
            name="🌉 Bridges",
            value=f"`{bridge_count}` bridges\nRank: **#{bridge_rank}** globally",
            inline=True,
        )
        embed.add_field(
            name="💬 Messages Relayed",
            value=f"`{msg_count:,}` messages\nRank: **#{msg_rank}** globally",
            inline=True,
        )
        embed.add_field(
            name="🏛️ Federations",
            value=f"Member of `{fed_count}` federation(s)",
            inline=True,
        )
        embed.add_field(
            name="⭐ Reputation",
            value=f"{rep_badge}\n`{rep_score:.0f} pts` — Rank **#{rep_rank}** globally",
            inline=True,
        )
        embed.set_footer(text="Use /bridge create to climb the leaderboard!")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(LeaderboardCog(bot))
