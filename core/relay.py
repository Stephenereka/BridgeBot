import discord
import uuid
import asyncio
import re
import time
from collections import deque

# Matches <:name:id> and <a:name:id> (custom emoji)
CUSTOM_EMOJI_RE = re.compile(r'<a?:(\w+):\d+>')
# Matches <#channel_id>
CHANNEL_MENTION_RE = re.compile(r'<#(\d+)>')
# Matches <@&role_id>
ROLE_MENTION_RE = re.compile(r'<@&\d+>')
# Matches URLs
URL_RE = re.compile(r'https?://[^\s<>"]+')

SAFE_DOMAINS = {
    'discord.gg', 'discord.com', 'discordapp.com', 'cdn.discordapp.com',
    'media.discordapp.net', 'youtube.com', 'youtu.be', 'youtu.be',
    'twitter.com', 'x.com', 'imgur.com', 'tenor.com', 'giphy.com',
    'twitch.tv', 'github.com', 'reddit.com', 'i.reddit.com',
}


def _is_safe_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ''
        return any(host == d or host.endswith('.' + d) for d in SAFE_DOMAINS)
    except Exception:
        return False


def _sanitize_content(content: str, source_guild: discord.Guild,
                       ping_mode: str = 'none', link_mode: str = 'all') -> str:
    # Always zero-width @everyone/@here
    content = content.replace('@everyone', '@​everyone').replace('@here', '@​here')

    # Role mentions
    if ping_mode == 'none':
        content = ROLE_MENTION_RE.sub('[role]', content)
    elif ping_mode == 'role':
        pass  # keep role mentions as-is
    else:  # all
        pass  # keep everything

    # Channel mentions → #name (server)
    def replace_channel(m):
        ch = source_guild.get_channel(int(m.group(1)))
        if ch:
            return f'#{ch.name} ({source_guild.name})'
        return '#unknown-channel'
    content = CHANNEL_MENTION_RE.sub(replace_channel, content)

    # Custom emoji → :name:
    content = CUSTOM_EMOJI_RE.sub(r':\1:', content)

    # Link mode
    if link_mode == 'safe':
        def replace_unsafe(m):
            return m.group(0) if _is_safe_url(m.group(0)) else '[link removed]'
        content = URL_RE.sub(replace_unsafe, content)
    elif link_mode == 'warn':
        urls = URL_RE.findall(content)
        if urls and any(not _is_safe_url(u) for u in urls):
            content = '⚠️ ' + content

    # Truncate
    if len(content) > 1990:
        content = content[:1990] + '... *(truncated)*'

    return content


class RelayEngine:
    # Rate limit: max messages per bridge per window
    RATE_LIMIT_MSGS = 15
    RATE_LIMIT_WINDOW = 10  # seconds

    def __init__(self, bot):
        self.bot = bot
        self._relayed_ids: set[int] = set()
        # Rate limiting: bridge_id -> deque of timestamps
        self._rate_state: dict[str, deque] = {}
        # Bridge cache
        self._bridge_cache: dict[int, list] = {}
        self._cache_ts: float = 0
        self._cache_lock = asyncio.Lock()

    def _mark_relayed(self, message_id: int):
        self._relayed_ids.add(message_id)
        asyncio.create_task(self._expire(message_id))

    async def _expire(self, message_id: int):
        await asyncio.sleep(60)
        self._relayed_ids.discard(message_id)

    def invalidate_bridge_cache(self):
        self._cache_ts = 0
        self._bridge_cache.clear()

    async def _get_bridges_cached(self, channel_id: int) -> list:
        now = time.monotonic()
        if now - self._cache_ts > 30:
            async with self._cache_lock:
                if now - self._cache_ts > 30:
                    all_bridges = await self.bot.db.get_all_active_bridges()
                    cache: dict[int, list] = {}
                    for b in all_bridges:
                        cache.setdefault(b['channel_a_id'], []).append(b)
                        cache.setdefault(b['channel_b_id'], []).append(b)
                    self._bridge_cache = cache
                    self._cache_ts = time.monotonic()
        return self._bridge_cache.get(channel_id, [])

    async def _check_rate_limit(self, bridge_id: str) -> bool:
        now = time.monotonic()
        q = self._rate_state.setdefault(bridge_id, deque())
        # Remove timestamps outside the window
        while q and now - q[0] > self.RATE_LIMIT_WINDOW:
            q.popleft()
        q.append(now)
        if len(q) > self.RATE_LIMIT_MSGS:
            # Rate limit exceeded — spam-pause the bridge
            await self.bot.db.update_bridge_column(bridge_id, 'spam_paused', 1)
            self.invalidate_bridge_cache()
            bridge = await self.bot.db.get_bridge(bridge_id)
            if bridge:
                await self._alert_spam_pause(bridge)
            # Auto-unpause after 60 seconds
            asyncio.create_task(self._unpause_spam(bridge_id))
            return False
        return True

    async def _unpause_spam(self, bridge_id: str):
        await asyncio.sleep(60)
        await self.bot.db.update_bridge_column(bridge_id, 'spam_paused', 0)
        self.invalidate_bridge_cache()

    async def _alert_spam_pause(self, bridge: dict):
        for sv_id in [bridge['channel_a_server_id'], bridge['channel_b_server_id']]:
            server = await self.bot.db.get_server(sv_id)
            if not server:
                continue
            ch_id = server['alert_channel_id'] or server['audit_channel_id']
            if not ch_id:
                continue
            ch = self.bot.get_channel(ch_id)
            if not ch:
                continue
            try:
                await ch.send(embed=discord.Embed(
                    title="🛑 Bridge Rate Limited",
                    description=(
                        f"Bridge `{bridge['id'][:8]}` was sending too many messages "
                        f"({self.RATE_LIMIT_MSGS}+ in {self.RATE_LIMIT_WINDOW}s) and has been "
                        f"automatically paused for 60 seconds to prevent spam.\n"
                        f"It will resume automatically."
                    ),
                    color=0xED4245,
                ))
            except Exception:
                pass

    async def relay_message(self, message: discord.Message):
        if not message.guild:
            return
        if message.id in self._relayed_ids:
            return

        bridges = await self._get_bridges_cached(message.channel.id)
        if not bridges:
            return

        for bridge in bridges:
            # Extra check: skip spam-paused bridges (cache may not reflect latest)
            if bridge.get('spam_paused'):
                continue
            if bridge.get('schedule_paused'):
                continue

            if not await self._check_rate_limit(bridge['id']):
                continue

            is_side_a = bridge['channel_a_id'] == message.channel.id
            target_ch_id = bridge['channel_b_id'] if is_side_a else bridge['channel_a_id']
            webhook_url = bridge['webhook_b_url'] if is_side_a else bridge['webhook_a_url']
            target_sv_id = bridge['channel_b_server_id'] if is_side_a else bridge['channel_a_server_id']

            if not webhook_url:
                continue

            ping_mode = bridge.get('ping_mode') or 'none'
            link_mode = bridge.get('link_mode') or 'all'

            content = _sanitize_content(message.content or '', message.guild,
                                         ping_mode=ping_mode, link_mode=link_mode)
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

            custom_name = bridge.get('webhook_display_name')
            custom_avatar = bridge.get('webhook_avatar_url')
            username = custom_name if custom_name else f"{message.author.display_name} • {message.guild.name}"
            avatar_url = custom_avatar if custom_avatar else str(message.author.display_avatar.url)

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
                await self.bot.db.increment_bridge_message_count(bridge['id'])
            else:
                await self._handle_webhook_failure(bridge, is_side_a)

    async def relay_thread_message(self, message: discord.Message):
        if not message.guild or not isinstance(message.channel, discord.Thread):
            return
        if message.id in self._relayed_ids:
            return

        tb = await self.bot.db.get_thread_bridge_by_thread(message.channel.id)
        if not tb:
            return

        is_side_a = tb['thread_a_id'] == message.channel.id
        target_thread_id = tb['thread_b_id'] if is_side_a else tb['thread_a_id']
        target_thread = self.bot.get_channel(target_thread_id)
        if not target_thread:
            return

        bridge = await self.bot.db.get_bridge(tb['bridge_id'])
        if not bridge:
            return

        ping_mode = bridge.get('ping_mode') or 'none'
        link_mode = bridge.get('link_mode') or 'all'
        content = _sanitize_content(message.content or '', message.guild, ping_mode=ping_mode, link_mode=link_mode)

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
            return

        username = f"{message.author.display_name} • {message.guild.name}"
        avatar_url = str(message.author.display_avatar.url)

        webhook_url = bridge['webhook_b_url'] if is_side_a else bridge['webhook_a_url']
        if not webhook_url:
            return

        relayed_id = await self.bot.webhook_manager.send_message(
            webhook_url=webhook_url,
            content=content,
            username=username,
            avatar_url=avatar_url,
            embeds=embeds,
            thread_id=target_thread_id,
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
                relay_ch_id=target_thread_id,
                relay_sv_id=target_thread.guild.id if hasattr(target_thread, 'guild') else 0,
            )

    async def relay_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or not after.content or before.content == after.content:
            return
        bridges = await self._get_bridges_cached(after.channel.id)
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
                    ping_mode = bridge.get('ping_mode') or 'none'
                    link_mode = bridge.get('link_mode') or 'all'
                    safe = _sanitize_content(after.content, after.guild, ping_mode=ping_mode, link_mode=link_mode)
                    await self.bot.webhook_manager.edit_message(webhook_url, r['relayed_message_id'], safe)

    async def relay_delete(self, message: discord.Message):
        if not message.guild:
            return
        bridges = await self._get_bridges_cached(message.channel.id)
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
