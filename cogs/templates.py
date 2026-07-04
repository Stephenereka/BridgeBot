import discord
from discord import app_commands
from discord.ext import commands
import uuid
import json
from core.permissions import require_perm, PermLevel, send_audit_log


TEMPLATE_SETTINGS = ['relay_edits', 'relay_deletes', 'relay_attachments', 'relay_embeds', 'nsfw_allowed', 'ping_mode', 'link_mode']


def _settings_summary(settings: dict) -> str:
    lines = []
    bool_fields = {'relay_edits': 'Relay Edits', 'relay_deletes': 'Relay Deletes',
                   'relay_attachments': 'Relay Attachments', 'relay_embeds': 'Relay Embeds',
                   'nsfw_allowed': 'NSFW Allowed'}
    for key, label in bool_fields.items():
        val = settings.get(key, 1 if key != 'relay_deletes' and key != 'nsfw_allowed' else 0)
        lines.append(f"{'✅' if val else '❌'} {label}")
    lines.append(f"🔔 Ping Mode: {settings.get('ping_mode', 'none').title()}")
    lines.append(f"🔗 Link Mode: {settings.get('link_mode', 'all').title()}")
    return '\n'.join(lines)


class TemplatesCog(commands.Cog, name="Templates"):
    def __init__(self, bot):
        self.bot = bot

    template_group = app_commands.Group(name="template", description="Bridge configuration templates")

    @template_group.command(name="save", description="Save a bridge's settings as a reusable template")
    @app_commands.describe(name="Template name", bridge_id="Bridge ID to save settings from")
    @require_perm(PermLevel.ADMIN)
    async def template_save(self, interaction: discord.Interaction, name: str, bridge_id: str):
        await interaction.response.defer(ephemeral=True)
        if len(name) > 50:
            await interaction.followup.send("❌ Template name must be 50 chars or fewer.", ephemeral=True)
            return
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        if bridge['channel_a_server_id'] != interaction.guild_id and bridge['channel_b_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ That bridge is not connected to your server.", ephemeral=True)
            return
        settings = {k: bridge[k] for k in TEMPLATE_SETTINGS if k in dict(bridge).keys() or bridge.get(k) is not None}
        # Handle new columns that might be None
        settings.setdefault('ping_mode', 'none')
        settings.setdefault('link_mode', 'all')
        tmpl_id = str(uuid.uuid4())
        await self.bot.db.save_template(tmpl_id, name, interaction.guild_id, json.dumps(settings))
        await interaction.followup.send(
            f"✅ Template **{name}** saved (ID: `{tmpl_id[:8]}`). Share it with `/template share {tmpl_id}` to make it public.",
            ephemeral=True,
        )

    @template_group.command(name="load", description="Apply a template's settings to a bridge")
    @app_commands.describe(template_id="Template ID", bridge_id="Bridge ID to apply settings to")
    @require_perm(PermLevel.ADMIN)
    async def template_load(self, interaction: discord.Interaction, template_id: str, bridge_id: str):
        await interaction.response.defer(ephemeral=True)
        tmpl = await self.bot.db.get_template(template_id)
        if not tmpl:
            await interaction.followup.send("❌ Template not found.", ephemeral=True)
            return
        if not tmpl['is_public'] and tmpl['creator_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ That template is private and belongs to another server.", ephemeral=True)
            return
        bridge = await self.bot.db.get_bridge(bridge_id)
        if not bridge:
            await interaction.followup.send("❌ Bridge not found.", ephemeral=True)
            return
        if bridge['channel_a_server_id'] != interaction.guild_id and bridge['channel_b_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ That bridge is not connected to your server.", ephemeral=True)
            return
        settings = json.loads(tmpl['settings'])
        for key, val in settings.items():
            try:
                await self.bot.db.update_bridge_column(bridge_id, key, val)
            except Exception:
                pass
        self.bot.relay.invalidate_bridge_cache()
        await interaction.followup.send(
            f"✅ Template **{tmpl['name']}** applied to bridge `{bridge_id[:8]}`.",
            ephemeral=True,
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'template_applied', {
            'template': tmpl['name'], 'bridge_id': bridge_id,
        })

    @template_group.command(name="list", description="Browse your templates and public templates")
    async def template_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        my_templates = await self.bot.db.get_server_templates(interaction.guild_id)
        public_templates = await self.bot.db.get_public_templates()
        embed = discord.Embed(title="🗂️ Bridge Templates", color=0x5865F2)
        if my_templates:
            lines = [f"• `{t['id'][:8]}` **{t['name']}**" + (" 🌍" if t['is_public'] else "") for t in my_templates[:5]]
            embed.add_field(name="Your Templates", value='\n'.join(lines), inline=False)
        if public_templates:
            my_ids = {t['id'] for t in my_templates}
            others = [t for t in public_templates if t['id'] not in my_ids]
            if others:
                lines = [f"• `{t['id'][:8]}` **{t['name']}**" for t in others[:5]]
                embed.add_field(name="🌍 Public Templates", value='\n'.join(lines), inline=False)
        if not my_templates and not public_templates:
            embed.description = "No templates yet. Use `/template save` to create one from any bridge."
        embed.set_footer(text="Use /template load <id> <bridge_id> to apply a template.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @template_group.command(name="info", description="View the settings in a template")
    @app_commands.describe(template_id="Template ID")
    async def template_info(self, interaction: discord.Interaction, template_id: str):
        await interaction.response.defer(ephemeral=True)
        tmpl = await self.bot.db.get_template(template_id)
        if not tmpl:
            await interaction.followup.send("❌ Template not found.", ephemeral=True)
            return
        settings = json.loads(tmpl['settings'])
        embed = discord.Embed(title=f"🗂️ Template: {tmpl['name']}", color=0x5865F2)
        embed.add_field(name="Settings", value=_settings_summary(settings), inline=False)
        embed.add_field(name="Visibility", value="🌍 Public" if tmpl['is_public'] else "🔒 Private", inline=True)
        creator = self.bot.get_guild(tmpl['creator_server_id'])
        embed.add_field(name="Created By", value=creator.name if creator else "Unknown Server", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @template_group.command(name="share", description="Make one of your templates public for other servers to use")
    @app_commands.describe(template_id="Template ID to make public")
    @require_perm(PermLevel.OWNER)
    async def template_share(self, interaction: discord.Interaction, template_id: str):
        await interaction.response.defer(ephemeral=True)
        success = await self.bot.db.make_template_public(template_id, interaction.guild_id)
        if not success:
            await interaction.followup.send("❌ Template not found or you don't own it.", ephemeral=True)
            return
        tmpl = await self.bot.db.get_template(template_id)
        await interaction.followup.send(
            f"✅ Template **{tmpl['name']}** is now public and visible to all servers.",
            ephemeral=True,
        )

    @template_group.command(name="delete", description="Delete one of your templates")
    @app_commands.describe(template_id="Template ID to delete")
    @require_perm(PermLevel.ADMIN)
    async def template_delete(self, interaction: discord.Interaction, template_id: str):
        await interaction.response.defer(ephemeral=True)
        tmpl = await self.bot.db.get_template(template_id)
        if not tmpl or tmpl['creator_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ Template not found or you don't own it.", ephemeral=True)
            return
        await self.bot.db.delete_template(template_id, interaction.guild_id)
        await interaction.followup.send(f"✅ Template **{tmpl['name']}** deleted.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(TemplatesCog(bot))
