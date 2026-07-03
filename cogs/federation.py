import discord
from discord import app_commands
from discord.ext import commands
import uuid
from core.permissions import require_perm, PermLevel, send_audit_log


class FederationCog(commands.Cog, name="Federation"):
    def __init__(self, bot):
        self.bot = bot

    fed = app_commands.Group(name="federation", description="Manage server federations")

    @fed.command(name="create", description="Create a new named federation for your server")
    @app_commands.describe(name="Federation name (max 50 characters)", description="Short description of the federation")
    @require_perm(PermLevel.ADMIN)
    async def fed_create(self, interaction: discord.Interaction, name: str, description: str = None):
        await interaction.response.defer(ephemeral=True)

        if len(name) > 50:
            await interaction.followup.send("❌ Federation name must be 50 characters or fewer.", ephemeral=True)
            return

        await self.bot.db.upsert_server(interaction.guild)
        fed_id = str(uuid.uuid4())
        await self.bot.db.create_federation(fed_id, name, interaction.guild_id, description)

        embed = discord.Embed(
            title="🏛️ Federation Created",
            description=f"**{name}** is ready. Invite other servers with `/federation invite`.",
            color=0x5865F2,
        )
        embed.add_field(name="Federation ID", value=f"`{fed_id}`", inline=False)
        if description:
            embed.add_field(name="Description", value=description, inline=False)
        embed.set_footer(text="Share the Federation ID with servers you want to invite.")
        await interaction.followup.send(embed=embed, ephemeral=True)

        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'federation_created', {
            'federation_id': fed_id, 'name': name,
        })

    @fed.command(name="invite", description="Invite another server to join your federation")
    @app_commands.describe(
        federation_id="Your federation ID",
        server_id="Server ID to invite",
    )
    @require_perm(PermLevel.ADMIN)
    async def fed_invite(self, interaction: discord.Interaction, federation_id: str, server_id: str):
        await interaction.response.defer(ephemeral=True)

        try:
            t_sv_id = int(server_id)
        except ValueError:
            await interaction.followup.send("❌ Server ID must be a number.", ephemeral=True)
            return

        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return
        if fed['owner_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ Only the federation owner can invite servers.", ephemeral=True)
            return

        target_guild = self.bot.get_guild(t_sv_id)
        if not target_guild:
            await interaction.followup.send("❌ I'm not in that server.", ephemeral=True)
            return

        mem_id = str(uuid.uuid4())
        await self.bot.db.invite_to_federation(mem_id, federation_id, t_sv_id, interaction.user.id)

        # Notify target server
        notify_ch = target_guild.system_channel
        if not notify_ch:
            for ch in target_guild.text_channels:
                if ch.permissions_for(target_guild.me).send_messages:
                    notify_ch = ch
                    break

        if notify_ch:
            embed = discord.Embed(
                title="🏛️ Federation Invitation",
                description=(
                    f"**{interaction.guild.name}** has invited this server to join the "
                    f"**{fed['name']}** federation.\n\n"
                    f"Use `/federation accept {federation_id}` to join, or `/federation decline {federation_id}` to decline."
                ),
                color=0x5865F2,
            )
            embed.set_footer(text=f"Federation ID: {federation_id}")
            try:
                await notify_ch.send(embed=embed)
            except Exception:
                pass

        await interaction.followup.send(
            f"✅ Invitation sent to **{target_guild.name}**!", ephemeral=True
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'federation_invite_sent', {
            'federation_id': federation_id, 'target_server': target_guild.name,
        })

    @fed.command(name="accept", description="Accept a pending federation invitation")
    @app_commands.describe(federation_id="The Federation ID from the invitation message")
    @require_perm(PermLevel.ADMIN)
    async def fed_accept(self, interaction: discord.Interaction, federation_id: str):
        await interaction.response.defer(ephemeral=True)

        invites = await self.bot.db.get_pending_invites(interaction.guild_id)
        matching = [i for i in invites if i['federation_id'] == federation_id]
        if not matching:
            await interaction.followup.send("❌ No pending invitation found for that federation.", ephemeral=True)
            return

        await self.bot.db.upsert_server(interaction.guild)
        await self.bot.db.update_federation_status(federation_id, interaction.guild_id, 'active', interaction.user.id)

        fed = await self.bot.db.get_federation(federation_id)
        await interaction.followup.send(
            f"✅ Joined **{fed['name']}** federation!", ephemeral=True
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'federation_joined', {
            'federation_id': federation_id, 'federation_name': fed['name'],
        })

    @fed.command(name="decline", description="Decline a federation invitation")
    @app_commands.describe(federation_id="The Federation ID to decline")
    @require_perm(PermLevel.ADMIN)
    async def fed_decline(self, interaction: discord.Interaction, federation_id: str):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.update_federation_status(federation_id, interaction.guild_id, 'declined')
        await interaction.followup.send("Federation invitation declined.", ephemeral=True)

    @fed.command(name="leave", description="Leave a federation your server is in")
    @app_commands.describe(federation_id="Federation ID to leave")
    @require_perm(PermLevel.ADMIN)
    async def fed_leave(self, interaction: discord.Interaction, federation_id: str):
        await interaction.response.defer(ephemeral=True)

        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return
        if fed['owner_server_id'] == interaction.guild_id:
            await interaction.followup.send(
                "❌ You own this federation. Use `/federation delete` to delete it, or `/federation transfer` to hand it off first.",
                ephemeral=True,
            )
            return

        await self.bot.db.update_federation_status(federation_id, interaction.guild_id, 'left')
        await interaction.followup.send(f"✅ Left **{fed['name']}** federation.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'federation_left', {
            'federation_id': federation_id, 'federation_name': fed['name'],
        })

    @fed.command(name="list", description="List all federations this server belongs to")
    async def fed_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        feds = await self.bot.db.get_federations_for_server(interaction.guild_id)

        if not feds:
            await interaction.followup.send("This server is not in any federations yet.", ephemeral=True)
            return

        embed = discord.Embed(title="🏛️ Your Federations", color=0x5865F2)
        for f in feds:
            owner = self.bot.get_guild(f['owner_server_id'])
            owner_str = owner.name if owner else f"Server `{f['owner_server_id']}`"
            embed.add_field(
                name=f['name'],
                value=f"**ID:** `{f['id']}`\nOwner: {owner_str}" + (f"\n{f['description']}" if f['description'] else ""),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @fed.command(name="info", description="Get details about a federation")
    @app_commands.describe(federation_id="Federation ID")
    async def fed_info(self, interaction: discord.Interaction, federation_id: str):
        await interaction.response.defer(ephemeral=True)
        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return

        members = await self.bot.db.get_federation_members(federation_id)
        owner = self.bot.get_guild(fed['owner_server_id'])

        embed = discord.Embed(
            title=f"🏛️ {fed['name']}",
            description=fed['description'] or "No description.",
            color=0x5865F2,
        )
        embed.add_field(name="Federation ID", value=f"`{federation_id}`", inline=False)
        embed.add_field(name="Owner", value=owner.name if owner else f"`{fed['owner_server_id']}`", inline=True)
        embed.add_field(name="Members", value=str(len(members)), inline=True)
        embed.add_field(name="Created", value=f"<t:{int(discord.utils.utcnow().timestamp())}:R>", inline=True)

        member_list = "\n".join(f"• {m['server_name']}" for m in members[:10])
        if member_list:
            embed.add_field(name="Member Servers", value=member_list, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @fed.command(name="members", description="List all servers in a federation")
    @app_commands.describe(federation_id="Federation ID")
    async def fed_members(self, interaction: discord.Interaction, federation_id: str):
        await interaction.response.defer(ephemeral=True)
        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return

        members = await self.bot.db.get_federation_members(federation_id)
        if not members:
            await interaction.followup.send("No active members in this federation.", ephemeral=True)
            return

        embed = discord.Embed(title=f"🏛️ {fed['name']} — Members", color=0x5865F2)
        for m in members:
            guild = self.bot.get_guild(m['server_id'])
            line = guild.name if guild else m['server_name']
            embed.add_field(name=line, value=f"ID: `{m['server_id']}`", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @fed.command(name="delete", description="Delete a federation you own (owner only)")
    @app_commands.describe(federation_id="Federation ID to delete")
    @require_perm(PermLevel.OWNER)
    async def fed_delete(self, interaction: discord.Interaction, federation_id: str):
        await interaction.response.defer(ephemeral=True)
        fed = await self.bot.db.get_federation(federation_id)
        if not fed:
            await interaction.followup.send("❌ Federation not found.", ephemeral=True)
            return
        if fed['owner_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ Only the federation owner server can delete it.", ephemeral=True)
            return

        await self.bot.db.delete_federation(federation_id)
        await interaction.followup.send(f"✅ Federation **{fed['name']}** deleted.", ephemeral=True)
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'federation_deleted', {
            'federation_id': federation_id, 'name': fed['name'],
        })

    @fed.command(name="kick", description="Remove a server from your federation (owner only)")
    @app_commands.describe(federation_id="Federation ID", server_id="Server ID to remove")
    @require_perm(PermLevel.OWNER)
    async def fed_kick(self, interaction: discord.Interaction, federation_id: str, server_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            t_sv = int(server_id)
        except ValueError:
            await interaction.followup.send("❌ Invalid server ID.", ephemeral=True)
            return

        fed = await self.bot.db.get_federation(federation_id)
        if not fed or fed['owner_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ Federation not found or you don't own it.", ephemeral=True)
            return
        if t_sv == interaction.guild_id:
            await interaction.followup.send("❌ You can't kick your own server.", ephemeral=True)
            return

        await self.bot.db.update_federation_status(federation_id, t_sv, 'banned')
        kicked = self.bot.get_guild(t_sv)
        await interaction.followup.send(
            f"✅ **{kicked.name if kicked else server_id}** removed from the federation.", ephemeral=True
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'federation_kick', {
            'federation_id': federation_id, 'kicked_server': server_id,
        })


    @fed.command(name="transfer", description="Transfer federation ownership to another server (owner only)")
    @app_commands.describe(federation_id="Federation ID", server_id="Server ID of the new owner")
    @require_perm(PermLevel.OWNER)
    async def fed_transfer(self, interaction: discord.Interaction, federation_id: str, server_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            t_sv = int(server_id)
        except ValueError:
            await interaction.followup.send("❌ Invalid server ID.", ephemeral=True)
            return
        fed = await self.bot.db.get_federation(federation_id)
        if not fed or fed['owner_server_id'] != interaction.guild_id:
            await interaction.followup.send("❌ Federation not found or you don't own it.", ephemeral=True)
            return
        members = await self.bot.db.get_federation_members(federation_id)
        if not any(m['server_id'] == t_sv for m in members):
            await interaction.followup.send("❌ That server is not a member of this federation.", ephemeral=True)
            return
        await self.bot.db.transfer_federation(federation_id, t_sv)
        new_guild = self.bot.get_guild(t_sv)
        await interaction.followup.send(
            f"✅ **{fed['name']}** ownership transferred to **{new_guild.name if new_guild else server_id}**.",
            ephemeral=True,
        )
        await send_audit_log(self.bot, interaction.guild_id, interaction.user, 'federation_transferred', {
            'federation_id': federation_id, 'new_owner': server_id,
        })


async def setup(bot):
    await bot.add_cog(FederationCog(bot))
