import discord
from discord import app_commands
from discord.ext import commands
from core.permissions import require_perm, PermLevel


class ReferralsCog(commands.Cog, name="Referrals"):
    def __init__(self, bot):
        self.bot = bot

    referrals_group = app_commands.Group(name="referrals", description="Track server referrals")

    @referrals_group.command(name="link", description="Get your server's referral code to share with other servers")
    async def referrals_link(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔗 Your Referral Code",
            description=(
                f"Share your server ID with other Discord communities to track referrals.\n\n"
                f"**Your referral code:** `{interaction.guild_id}`\n\n"
                f"When another server adds BridgeBot, they can run:\n"
                f"`/referrals credit {interaction.guild_id}`\n"
                f"to credit your server for referring them."
            ),
            color=0x5865F2,
        )
        embed.set_footer(text="Referrals are tracked per server. One credit per referred server.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @referrals_group.command(name="credit", description="Credit another server for referring yours to BridgeBot")
    @app_commands.describe(referrer_server_id="The server ID that told you about BridgeBot")
    @require_perm(PermLevel.ADMIN)
    async def referrals_credit(self, interaction: discord.Interaction, referrer_server_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            ref_sv_id = int(referrer_server_id)
        except ValueError:
            await interaction.followup.send("❌ Invalid server ID.", ephemeral=True)
            return
        if ref_sv_id == interaction.guild_id:
            await interaction.followup.send("❌ You cannot credit your own server.", ephemeral=True)
            return
        success = await self.bot.db.credit_referral(ref_sv_id, interaction.guild_id)
        if not success:
            await interaction.followup.send("❌ Your server has already credited a referrer. Only one referral credit is allowed.", ephemeral=True)
            return
        referrer_guild = self.bot.get_guild(ref_sv_id)
        referrer_name = referrer_guild.name if referrer_guild else f"Server `{referrer_server_id}`"
        await interaction.followup.send(
            f"✅ **{referrer_name}** has been credited for referring your server to BridgeBot! Thank you for recognizing them.",
            ephemeral=True,
        )
        # Notify the referrer
        if referrer_guild:
            server_data = await self.bot.db.get_server(ref_sv_id)
            notify_ch_id = server_data['admin_channel_id'] or server_data['audit_channel_id'] if server_data else None
            notify_ch = self.bot.get_channel(notify_ch_id) if notify_ch_id else referrer_guild.system_channel
            if notify_ch:
                count = await self.bot.db.get_referral_count(ref_sv_id)
                try:
                    await notify_ch.send(embed=discord.Embed(
                        title="🎉 New Referral!",
                        description=(
                            f"**{interaction.guild.name}** credited your server for referring them to BridgeBot!\n"
                            f"You now have **{count}** total referral(s)."
                        ),
                        color=0x57F287,
                    ))
                except Exception:
                    pass

    @referrals_group.command(name="stats", description="View your server's referral statistics")
    async def referrals_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        referrals = await self.bot.db.get_referrals(interaction.guild_id)
        count = len(referrals)
        embed = discord.Embed(
            title=f"🔗 Referral Stats — {interaction.guild.name}",
            color=0x5865F2,
        )
        embed.add_field(name="Total Referrals", value=f"`{count}`", inline=True)
        embed.add_field(name="Your Referral Code", value=f"`{interaction.guild_id}`", inline=True)
        if referrals:
            lines = []
            for r in referrals[:10]:
                name = r.get('referred_name') or f"Server `{r['referred_server_id']}`"
                lines.append(f"• {name}")
            embed.add_field(name="Referred Servers", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Referred Servers", value="None yet. Share your referral code!", inline=False)
        embed.set_footer(text="Share /referrals link with other servers to grow your referral count.")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ReferralsCog(bot))
