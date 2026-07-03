import discord
from discord.ext import commands
from config import Config
from core.database import Database
from core.relay import RelayEngine
from core.webhook_manager import WebhookManager


class BridgeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        super().__init__(
            command_prefix='!bb ',
            intents=intents,
            application_id=Config.APPLICATION_ID,
            help_command=None,
        )

        self.db = Database()
        self.relay = RelayEngine(self)
        self.webhook_manager = WebhookManager(self)

    async def setup_hook(self):
        await self.db.init()

        cogs = [
            'cogs.bridge',
            'cogs.federation',
            'cogs.info',
            'cogs.setup_cog',
        ]
        for cog in cogs:
            await self.load_extension(cog)
            print(f'  Loaded {cog}')

        synced = await self.tree.sync()
        print(f'  Synced {len(synced)} slash commands')

    async def on_ready(self):
        print(f'\n🌉 BridgeBot online as {self.user} (ID: {self.user.id})')
        print(f'   Serving {len(self.guilds)} servers\n')
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="bridges connect | /help",
            )
        )

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
                    "• `/help` — See all commands"
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

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.webhook_id:
            return
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
