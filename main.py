import discord
from discord.ext import commands, tasks
from config import Config
from core.database import Database
from core.relay import RelayEngine
from core.webhook_manager import WebhookManager
import asyncio


DEFAULT_PREFIX = '!bb '


def _get_prefix(bot, message):
    prefix = DEFAULT_PREFIX
    if message.guild:
        prefix = bot.guild_prefixes.get(message.guild.id, DEFAULT_PREFIX)
    return commands.when_mentioned_or(prefix)(bot, message)


class BridgeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        super().__init__(
            command_prefix=_get_prefix,
            intents=intents,
            application_id=Config.APPLICATION_ID,
            help_command=None,
        )

        self.guild_prefixes = {}
        self.db = Database()
        self.relay = RelayEngine(self)
        self.webhook_manager = WebhookManager(self)

    async def setup_hook(self):
        await self.db.init()
        for row in await self.db.get_all_server_prefixes():
            self.guild_prefixes[row['id']] = row['prefix']

        cogs = [
            'cogs.bridge',
            'cogs.federation',
            'cogs.info',
            'cogs.setup_cog',
            'cogs.moderation',
            'cogs.leaderboard',
            'cogs.polls',
            'cogs.hub',
            'cogs.templates',
        ]
        for cog in cogs:
            await self.load_extension(cog)
            print(f'  Loaded {cog}')

        synced = await self.tree.sync()
        print(f'  Synced {len(synced)} slash commands')

        self.webhook_health_check.start()
        self.purge_old_data.start()
        self.inactive_bridge_check.start()
        self.anniversary_check.start()
        self.weekly_digest.start()

    async def on_ready(self):
        print(f'\n🌉 BridgeBot online as {self.user} (ID: {self.user.id})')
        print(f'   Serving {len(self.guilds)} servers\n')
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="bridges connect | /help",
            )
        )
        await self._send_restart_notices()

    async def _send_restart_notices(self):
        """Notify bridged channels that the bot restarted and messages may have been missed."""
        try:
            bridges = await self.db.get_all_active_bridges()
            notified = set()
            for bridge in bridges:
                for ch_id in [bridge['channel_a_id'], bridge['channel_b_id']]:
                    if ch_id in notified:
                        continue
                    notified.add(ch_id)
                    ch = self.get_channel(ch_id)
                    if ch:
                        try:
                            msg = await ch.send(
                                embed=discord.Embed(
                                    description="🌉 BridgeBot reconnected. Messages sent during downtime may not have been relayed.",
                                    color=0xFEE75C,
                                )
                            )
                            await asyncio.sleep(8)
                            await msg.delete()
                        except Exception:
                            pass
        except Exception:
            pass

    @tasks.loop(minutes=10)
    async def webhook_health_check(self):
        """Every 10 minutes, verify all webhooks are still alive."""
        try:
            bridges = await self.db.get_all_active_bridges()
            for bridge in bridges:
                for side, webhook_url, server_id, ch_id in [
                    ('a', bridge['webhook_a_url'], bridge['channel_a_server_id'], bridge['channel_a_id']),
                    ('b', bridge['webhook_b_url'], bridge['channel_b_server_id'], bridge['channel_b_id']),
                ]:
                    if not webhook_url:
                        continue
                    ch = self.get_channel(ch_id)
                    if not ch:
                        continue
                    # Try to recreate webhook if it's gone
                    ok = await self.webhook_manager.verify_webhook(webhook_url)
                    if not ok:
                        new_url = await self.webhook_manager.create_webhook(ch)
                        if new_url:
                            if side == 'a':
                                await self.db.update_bridge_webhooks(bridge['id'], webhook_a_url=new_url)
                            else:
                                await self.db.update_bridge_webhooks(bridge['id'], webhook_b_url=new_url)
                        else:
                            # Alert the server
                            server = await self.db.get_server(server_id)
                            if server:
                                alert_ch_id = server['alert_channel_id'] or server['audit_channel_id']
                                if alert_ch_id:
                                    alert_ch = self.get_channel(alert_ch_id)
                                    if alert_ch:
                                        try:
                                            await alert_ch.send(embed=discord.Embed(
                                                title="⚠️ Bridge Webhook Missing",
                                                description=(
                                                    f"Bridge `{bridge['id'][:8]}` has a broken webhook in <#{ch_id}>.\n"
                                                    f"BridgeBot needs **Manage Webhooks** permission in that channel.\n"
                                                    f"Use `/bridge repair {bridge['id']}` once permissions are restored."
                                                ),
                                                color=0xED4245,
                                            ))
                                        except Exception:
                                            pass
        except Exception as e:
            print(f'Health check error: {e}')

    @webhook_health_check.before_loop
    async def before_health_check(self):
        await self.wait_until_ready()

    @tasks.loop(hours=24)
    async def purge_old_data(self):
        try:
            await self.db.purge_old_message_map(days=30)
        except Exception as e:
            print(f'Purge error: {e}')

    @purge_old_data.before_loop
    async def before_purge(self):
        await self.wait_until_ready()

    @tasks.loop(hours=24)
    async def inactive_bridge_check(self):
        try:
            inactive = await self.db.get_inactive_bridges()
            for bridge in inactive:
                days = bridge['days_inactive']
                ch_a = self.get_channel(bridge['channel_a_id'])
                ch_b = self.get_channel(bridge['channel_b_id'])
                guild_a = self.get_guild(bridge['channel_a_server_id'])
                guild_b = self.get_guild(bridge['channel_b_server_id'])

                if days >= 37:
                    for ch in [ch_a, ch_b]:
                        if ch:
                            try:
                                await ch.send(embed=discord.Embed(
                                    title="🗑️ Bridge Removed",
                                    description="This bridge has been inactive for 37 days and was automatically removed.",
                                    color=0xED4245,
                                ))
                            except Exception:
                                pass
                    await self.db.delete_bridge(bridge['id'])
                elif days >= 30:
                    for ch in [ch_a, ch_b]:
                        if ch:
                            try:
                                await ch.send(embed=discord.Embed(
                                    title="⚠️ Bridge Expiring in 7 Days",
                                    description="This bridge has been inactive for 30 days and will be permanently deleted in 7 days unless a message is sent.",
                                    color=0xED4245,
                                ))
                            except Exception:
                                pass
                elif days >= 14:
                    if not bridge['paused']:
                        await self.db.update_bridge_column(bridge['id'], 'paused', 1)
                        self.relay.invalidate_bridge_cache()
                        for ch in [ch_a, ch_b]:
                            if ch:
                                try:
                                    await ch.send(embed=discord.Embed(
                                        title="⏸️ Bridge Auto-Paused",
                                        description="This bridge was inactive for 14 days and has been automatically paused. An admin can resume it with `/bridge resume`.",
                                        color=0xFEE75C,
                                    ))
                                except Exception:
                                    pass
                elif days >= 7:
                    for ch in [ch_a, ch_b]:
                        if ch:
                            try:
                                await ch.send(embed=discord.Embed(
                                    title="💤 Quiet Bridge",
                                    description="This bridge has been inactive for 7 days. It will be auto-paused in 7 more days if no messages are sent.",
                                    color=0x5865F2,
                                ))
                            except Exception:
                                pass
        except Exception as e:
            print(f'Inactive bridge check error: {e}')

    @inactive_bridge_check.before_loop
    async def before_inactive_check(self):
        await self.wait_until_ready()

    @tasks.loop(hours=24)
    async def anniversary_check(self):
        try:
            bridges = await self.db.get_anniversary_bridges()
            for bridge in bridges:
                guild_a = self.get_guild(bridge['channel_a_server_id'])
                guild_b = self.get_guild(bridge['channel_b_server_id'])
                ch_a = self.get_channel(bridge['channel_a_id'])
                ch_b = self.get_channel(bridge['channel_b_id'])
                msg_count = bridge['total_messages'] or 0
                a_name = guild_a.name if guild_a else 'a server'
                b_name = guild_b.name if guild_b else 'a server'
                embed = discord.Embed(
                    title="🌉 Bridge Anniversary!",
                    description=(
                        f"🎉 **One month of bridging between {a_name} and {b_name}!**\n"
                        f"{msg_count:,} messages have been shared across this bridge. Keep it up!"
                    ),
                    color=0x57F287,
                )
                for ch in [ch_a, ch_b]:
                    if ch:
                        try:
                            await ch.send(embed=embed)
                        except Exception:
                            pass
        except Exception as e:
            print(f'Anniversary check error: {e}')

    @anniversary_check.before_loop
    async def before_anniversary(self):
        await self.wait_until_ready()

    @tasks.loop(hours=168)
    async def weekly_digest(self):
        try:
            for guild in self.guilds:
                server = await self.db.get_server(guild.id)
                if not server or not server['digest_enabled'] or not server['digest_channel_id']:
                    continue
                stats = await self.db.get_server_weekly_stats(guild.id)
                if not stats or stats.get('total_messages', 0) == 0:
                    continue
                ch = self.get_channel(server['digest_channel_id'])
                if not ch:
                    continue
                embed = discord.Embed(title="📊 Weekly Bridge Digest", color=0x5865F2)
                embed.add_field(name="Messages Relayed", value=f"{stats['total_messages']:,}", inline=True)
                embed.add_field(name="Active Bridges", value=str(stats['active_bridges']), inline=True)
                if stats.get('top_bridges'):
                    lines = []
                    for i, b in enumerate(stats['top_bridges'][:3]):
                        lines.append(f"**{i+1}.** <#{b['channel_id']}> — {b['messages']:,} msgs")
                    embed.add_field(name="Top Bridges This Week", value='\n'.join(lines), inline=False)
                embed.set_footer(text="Use /digest off to disable.")
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass
        except Exception as e:
            print(f'Weekly digest error: {e}')

    @weekly_digest.before_loop
    async def before_weekly_digest(self):
        await self.wait_until_ready()

    async def on_guild_join(self, guild: discord.Guild):
        await self.db.upsert_server(guild)
        ch = guild.system_channel
        if ch:
            embed = discord.Embed(
                title="🌉 Thanks for adding BridgeBot!",
                description=(
                    "Bridge channels between Discord servers and build federations.\n\n"
                    "**Get started:**\n"
                    "• `/setup` — Configure the bot\n"
                    "• `/bridge create` — Create your first bridge\n"
                    "• `/help` — See all commands\n"
                    "• `/leaderboard bridges` — See top servers"
                ),
                color=0x5865F2,
            )
            try:
                await ch.send(embed=embed)
            except Exception:
                pass

    async def on_guild_remove(self, guild: discord.Guild):
        await self.db.mark_server_kicked(guild.id)
        print(f'  Left server: {guild.name} ({guild.id})')

    async def on_thread_create(self, thread: discord.Thread):
        if not thread.parent_id:
            return
        try:
            bridges = await self.relay._get_bridges_cached(thread.parent_id)
            for bridge in bridges:
                if not bridge['active'] or bridge['paused']:
                    continue
                is_side_a = bridge['channel_a_id'] == thread.parent_id
                other_ch_id = bridge['channel_b_id'] if is_side_a else bridge['channel_a_id']
                other_ch = self.get_channel(other_ch_id)
                if not other_ch:
                    continue
                try:
                    other_thread = await other_ch.create_thread(
                        name=thread.name,
                        type=thread.type if thread.type != discord.ChannelType.news_thread else discord.ChannelType.public_thread,
                        reason="BridgeBot thread mirror",
                    )
                    await self.db.add_thread_bridge(
                        str(__import__('uuid').uuid4()),
                        bridge['id'],
                        thread.id,
                        thread.guild.id,
                        other_thread.id,
                        other_ch.guild.id,
                    )
                    await other_thread.send(embed=discord.Embed(
                        description=f"🔗 This thread is bridged from **{thread.guild.name}**",
                        color=0x5865F2,
                    ))
                except Exception as e:
                    print(f'Thread bridge create error: {e}')
        except Exception as e:
            print(f'on_thread_create error: {e}')

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.webhook_id:
            return
        if isinstance(message.channel, discord.Thread):
            await self.relay.relay_thread_message(message)
        else:
            await self.relay.relay_message(message)
        await self.process_commands(message)

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.bot or after.webhook_id:
            return
        await self.relay.relay_edit(before, after)

    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or message.webhook_id:
            return
        await self.relay.relay_delete(message)

    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        mod_cog = self.cogs.get('Moderation')
        if mod_cog:
            await mod_cog.handle_ban(guild, user)

    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        mod_cog = self.cogs.get('Moderation')
        if mod_cog:
            await mod_cog.handle_unban(guild, user)

    async def on_member_join(self, member: discord.Member):
        """Apply cross-server role sync when a user joins."""
        try:
            mappings = await self.db.get_role_mappings_for_target(member.guild.id)
            for mapping in mappings:
                source_guild = self.get_guild(mapping['source_server_id'])
                if not source_guild:
                    continue
                source_member = source_guild.get_member(member.id)
                if not source_member:
                    continue
                has_role = any(r.id == mapping['source_role_id'] for r in source_member.roles)
                if has_role:
                    target_role = member.guild.get_role(mapping['target_role_id'])
                    if target_role:
                        try:
                            await member.add_roles(target_role, reason="BridgeBot cross-server role sync")
                        except Exception:
                            pass
        except Exception:
            pass

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        msg = "An unexpected error occurred. Please try again."
        if isinstance(error, discord.app_commands.CommandOnCooldown):
            msg = f"Slow down! Try again in `{error.retry_after:.1f}s`."
        elif isinstance(error, discord.app_commands.MissingPermissions):
            msg = "You don't have permission to use this command."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
        except Exception:
            pass
        print(f'Command error: {error}')


def main():
    bot = BridgeBot()
    bot.run(Config.TOKEN, log_handler=None)


if __name__ == '__main__':
    main()
