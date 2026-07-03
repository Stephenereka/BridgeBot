import discord
import uuid
import asyncio
import re


# Matches <:name:id> and <a:name:id> (custom emoji)
CUSTOM_EMOJI_RE = re.compile(r'<a?:(\w+):\d+>')
# Matches <#channel_id>
CHANNEL_MENTION_RE = re.compile(r'<#(\d+)>')
# Matches <@&role_id>
ROLE_MENTION_RE = re.compile(r'<@&\d+>')


def _sanitize_content(content: str, source_guild: discord.Guild) -> str:
    """Strip/convert mentions and emoji that don't work cross-server."""
    # @everyone and @here
    content = content.replace('@everyone', '@​everyone').replace('@here', '@​here')

    # Role mentions → strip entirely
    content = ROLE_MENTION_RE.sub('[role]', content)

    # Channel mentions → #channel-name (server)
    def replace_channel(m):
        ch = source_guild.get_channel(int(m.group(1)))
        if ch:
            return f'#{ch.name} ({source_guild.name})'
        return '#unknown-channel'
    content = CHANNEL_MENTION_RE.sub(replace_channel, content)

    # Custom emoji → :name:
    content = CUSTOM_EMOJI_RE.sub(r':\1:', content)

    # Truncate
    if len(content) > 1990:
        content = content[:1990] + '... *(truncated)*'

    return content


class RelayEngine:
    def __init__(self, bot):
        self.bot = bot
        self._relayed_ids: set[int] = set()

    def _mark_relayed(self, message_id: int):
        self._relayed_ids.add(message_id)
        asyncio.create_task(self._expire(message_id))

    async def _expire(self, message_id: int):
        await asyncio.sleep(60)
        self._relayed_ids.discard(message_id)

    async def relay_message(self, message: discord.Message):
        if not message.guild:
            return
        if message.id in self._relayed_ids:
            return

        bridges = await self.bot.db.get_bridges_for_channel(message.channel.id)
        if not bridges:
            return

        for bridge in bridges:
            is_side_a = bridge['channel_a_id'] == message.channel.id
            target_ch_id = bridge['channel_b_id'] if is_side_a else bridge['channel_a_id']
            webhook_url = bridge['webhook_b_url'] if is_side_a else bridge['webhook_a_url']
            target_sv_id = bridge['channel_b_server_id'] if is_side_a else bridge['channel_a_server_id']

            if not webhook_url:
                continue

            content = _sanitize_content(message.content or '', message.guild)
            embeds = []

            if message.attachments and bridge['relay_attachments']:
                for att in message.attachments:
                    e = discord.Embed(color=0x5865F2)
                    if att.content_type and att.content_type.startswith('image/'):
                        e.set_image(url=att.url)
                    else:
                        e.description = f"📎 [{att.filename}]({att.url})"
                    embeds.append(e)

            if message.embeds and bridge['relay_embeds']:
                embeds.extend(message.embeds[:10 - len(embeds)])

            if not content and not embeds:
                continue

            username = f"{message.author.display_name} • {message.guild.name}"
            avatar_url = str(message.author.display_avatar.url)

            relayed_id = await self.bot.webhook_manager.send_message(
                webhook_url=webhook_url,
                content=content,
                username=username,
                avatar_url=avatar_url,
                embeds=embeds,
            )

            if relayed_id:
                self._mark_relayed(relayed_id)
                await self.bot.db.save_message_map(
                    map_id=str(uuid.uuid4()),
                    bridge_id=bridge['id'],
                    orig_msg_id=message.id,
                    orig_ch_id=message.channel.id,
                    orig_sv_id=message.guild.id,
                    relay_msg_id=relayed_id,
                    relay_ch_id=target_ch_id,
                    relay_sv_id=target_sv_id,
                )
            else:
                # Webhook failed — could be deleted, trigger health check
                await self._handle_webhook_failure(bridge, is_side_a)

    async def relay_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or not after.content or before.content == after.content:
            return

        bridges = await self.bot.db.get_bridges_for_channel(after.channel.id)
        for bridge in bridges:
            if not bridge['relay_edits']:
                continue
            is_side_a = bridge['channel_a_id'] == after.channel.id
            webhook_url = bridge['webhook_b_url'] if is_side_a else bridge['webhook_a_url']
            if not webhook_url:
                continue
            relayed = await self.bot.db.get_relayed_messages(after.id)
            for r in relayed:
                if r['bridge_id'] == bridge['id']:
                    safe = _sanitize_content(after.content, after.guild)
                    await self.bot.webhook_manager.edit_message(webhook_url, r['relayed_message_id'], safe)

    async def relay_delete(self, message: discord.Message):
        if not message.guild:
            return

        bridges = await self.bot.db.get_bridges_for_channel(message.channel.id)
        for bridge in bridges:
            if not bridge['relay_deletes']:
                continue
            is_side_a = bridge['channel_a_id'] == message.channel.id
            webhook_url = bridge['webhook_b_url'] if is_side_a else bridge['webhook_a_url']
            if not webhook_url:
                continue
            relayed = await self.bot.db.get_relayed_messages(message.id)
            for r in relayed:
                if r['bridge_id'] == bridge['id']:
                    await self.bot.webhook_manager.delete_message(webhook_url, r['relayed_message_id'])

    async def _handle_webhook_failure(self, bridge, is_side_a: bool):
        """Alert the server's alert/audit channel when a webhook fails."""
        server_id = bridge['channel_a_server_id'] if is_side_a else bridge['channel_b_server_id']
        server = await self.bot.db.get_server(server_id)
        if not server:
            return
        ch_id = server['alert_channel_id'] or server['audit_channel_id']
        if not ch_id:
            return
        ch = self.bot.get_channel(ch_id)
        if not ch:
            return
        try:
            embed = discord.Embed(
                title="⚠️ Bridge Webhook Failed",
                description=(
                    f"Bridge `{bridge['id'][:8]}` failed to relay a message.\n"
                    f"The webhook may have been deleted. Use `/bridge repair {bridge['id']}` to fix it."
                ),
                color=0xFEE75C,
            )
            await ch.send(embed=embed)
        except Exception:
            pass
