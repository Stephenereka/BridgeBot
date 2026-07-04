import discord
from discord import app_commands
from discord.ext import commands
import uuid
import json
from datetime import datetime, timedelta
from core.permissions import require_perm, PermLevel


class PollView(discord.ui.View):
    def __init__(self, poll_id: str, options: list[str]):
        super().__init__(timeout=None)
        self.poll_id = poll_id
        for i, opt in enumerate(options[:4]):
            label = opt[:80]
            btn = discord.ui.Button(
                label=label,
                custom_id=f"poll:{poll_id}:{i}",
                style=discord.ButtonStyle.primary,
                emoji=["1️⃣", "2️⃣", "3️⃣", "4️⃣"][i],
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, option_index: int):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            db = interaction.client.db
            poll = await db.get_poll(self.poll_id)
            if not poll or poll['status'] != 'active':
                await interaction.followup.send("❌ This poll is no longer active.", ephemeral=True)
                return
            options = json.loads(poll['options'])
            success = await db.add_poll_vote(
                str(uuid.uuid4()), self.poll_id, interaction.guild_id, interaction.user.id, option_index
            )
            if not success:
                await interaction.followup.send("❌ You've already voted in this poll.", ephemeral=True)
                return
            await interaction.followup.send(
                f"✅ Voted for **{options[option_index]}**!", ephemeral=True
            )
            # Update all poll embeds with new counts
            votes = await db.get_poll_votes(self.poll_id)
            counts = [0] * len(options)
            for v in votes:
                if v['option_index'] < len(counts):
                    counts[v['option_index']] += 1
            embed = _build_poll_embed(poll, options, counts)
            msgs = await db.get_poll_messages(self.poll_id)
            for msg_row in msgs:
                try:
                    ch = interaction.client.get_channel(msg_row['channel_id'])
                    if ch:
                        msg = await ch.fetch_message(msg_row['message_id'])
                        await msg.edit(embed=embed)
                except Exception:
                    pass
        return callback


def _build_poll_embed(poll, options, counts=None) -> discord.Embed:
    total = sum(counts) if counts else 0
    embed = discord.Embed(
        title=f"📊 {poll['question']}",
        color=0x5865F2,
    )
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    lines = []
    for i, opt in enumerate(options):
        count = counts[i] if counts else 0
        pct = int(count / total * 100) if total > 0 else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"{emojis[i]} **{opt}**\n`{bar}` {count} votes ({pct}%)")
    embed.description = "\n\n".join(lines)
    embed.set_footer(text=f"Total votes: {total} | Poll ID: {poll['id'][:8]}")
    if poll.get('ends_at'):
        embed.add_field(name="Ends", value=str(poll['ends_at']), inline=True)
    return embed


class PollsCog(commands.Cog, name="Polls"):
    def __init__(self, bot):
        self.bot = bot

    poll_group = app_commands.Group(name="poll", description="Cross-server federation polls")

    @poll_group.command(name="create", description="Create a poll across all servers in a federation")
    @app_commands.describe(
        federation_id="Federation ID to send the poll to",
        question="The poll question",
        option1="Option 1",
        option2="Option 2",
        option3="Option 3 (optional)",
        option4="Option 4 (optional)",
        duration_hours="How many hours to run the poll (1-168, default 24)",
    )
    @require_perm(PermLevel.ADMIN)
    async def poll_create(self, interaction: discord.Interaction,
                          federation_id: str, question: str,
                          option1: str, option2: str,
                          option3: str = None, option4: str = None,
                          duration_hours: int = 24):
        await interaction.response.defer(ephemeral=True)

        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return

        members = await self.bot.db.get_federation_members(federation_id)
        is_member = any(m['server_id'] == interaction.guild_id for m in members)
        if not is_member:
            await interaction.followup.send("❌ Your server is not in this federation.", ephemeral=True)
            return

        duration_hours = max(1, min(168, duration_hours))
        ends_at = (datetime.utcnow() + timedelta(hours=duration_hours)).isoformat()

        options = [o for o in [option1, option2, option3, option4] if o]
        poll_id = str(uuid.uuid4())
        await self.bot.db.create_poll(
            poll_id, federation_id, interaction.guild_id,
            interaction.user.id, question, json.dumps(options), ends_at
        )

        poll_row = {'id': poll_id, 'question': question, 'options': json.dumps(options),
                    'status': 'active', 'ends_at': ends_at}
        embed = _build_poll_embed(poll_row, options, [0] * len(options))
        view = PollView(poll_id, options)

        sent_count = 0
        for member in members:
            guild = self.bot.get_guild(member['server_id'])
            if not guild:
                continue
            targets = await self.bot.db.get_broadcast_targets(federation_id)
            target_ch = None
            for t in targets:
                if t['server_id'] == member['server_id']:
                    target_ch = self.bot.get_channel(t['channel_id'])
                    break
            if not target_ch:
                target_ch = guild.system_channel
                if not target_ch:
                    for ch in guild.text_channels:
                        if ch.permissions_for(guild.me).send_messages:
                            target_ch = ch
                            break
            if target_ch:
                try:
                    msg = await target_ch.send(embed=embed, view=view)
                    await self.bot.db.add_poll_message(str(uuid.uuid4()), poll_id, member['server_id'], target_ch.id, msg.id)
                    sent_count += 1
                except Exception:
                    pass

        await interaction.followup.send(
            f"✅ Poll `{poll_id[:8]}` created and sent to {sent_count} servers in **{fed['name']}**.",
            ephemeral=True,
        )

    @poll_group.command(name="end", description="End a poll early and announce the results")
    @app_commands.describe(poll_id="Poll ID to end")
    @require_perm(PermLevel.ADMIN)
    async def poll_end(self, interaction: discord.Interaction, poll_id: str):
        await interaction.response.defer(ephemeral=True)
        poll = await self.bot.db.get_poll(poll_id)
        if not poll:
            await interaction.followup.send("❌ Poll not found.", ephemeral=True)
            return
        if poll['creator_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ Only the server that created this poll can end it.", ephemeral=True)
            return
        await self.bot.db.close_poll(poll_id)
        options = json.loads(poll['options'])
        votes = await self.bot.db.get_poll_votes(poll_id)
        counts = [0] * len(options)
        for v in votes:
            if v['option_index'] < len(counts):
                counts[v['option_index']] += 1
        winner_idx = counts.index(max(counts)) if counts else 0
        embed = _build_poll_embed(poll, options, counts)
        embed.title = f"📊 [CLOSED] {poll['question']}"
        embed.add_field(name="🏆 Winner", value=options[winner_idx], inline=False)
        embed.color = 0x57F287
        msgs = await self.bot.db.get_poll_messages(poll_id)
        for msg_row in msgs:
            try:
                ch = self.bot.get_channel(msg_row['channel_id'])
                if ch:
                    msg = await ch.fetch_message(msg_row['message_id'])
                    await msg.edit(embed=embed, view=None)
            except Exception:
                pass
        await interaction.followup.send(f"✅ Poll `{poll_id[:8]}` ended. Winner: **{options[winner_idx]}**", ephemeral=True)

    @poll_group.command(name="results", description="View current poll results")
    @app_commands.describe(poll_id="Poll ID to check")
    async def poll_results(self, interaction: discord.Interaction, poll_id: str):
        await interaction.response.defer(ephemeral=True)
        poll = await self.bot.db.get_poll(poll_id)
        if not poll:
            await interaction.followup.send("❌ Poll not found.", ephemeral=True)
            return
        options = json.loads(poll['options'])
        votes = await self.bot.db.get_poll_votes(poll_id)
        counts = [0] * len(options)
        for v in votes:
            if v['option_index'] < len(counts):
                counts[v['option_index']] += 1
        embed = _build_poll_embed(poll, options, counts)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @poll_group.command(name="list", description="List active polls in your federations")
    @app_commands.describe(federation_id="Federation ID (optional)")
    async def poll_list(self, interaction: discord.Interaction, federation_id: str = None):
        await interaction.response.defer(ephemeral=True)
        if federation_id:
            feds = [federation_id]
        else:
            server_feds = await self.bot.db.get_federations_for_server(interaction.guild_id)
            feds = [f['id'] for f in server_feds]

        if not feds:
            await interaction.followup.send("Your server is not in any federations.", ephemeral=True)
            return

        all_polls = []
        for fid in feds:
            polls = await self.bot.db.get_active_polls_for_federation(fid)
            all_polls.extend(polls)

        if not all_polls:
            await interaction.followup.send("No active polls found.", ephemeral=True)
            return

        embed = discord.Embed(title="📊 Active Polls", color=0x5865F2)
        for p in all_polls[:10]:
            embed.add_field(
                name=f"`{p['id'][:8]}` — {p['question'][:60]}",
                value=f"Federation: `{p['federation_id'][:8]}` | Ends: {p['ends_at'] or 'No expiry'}",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(PollsCog(bot))
