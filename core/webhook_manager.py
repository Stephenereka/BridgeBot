import discord
import aiohttp
import asyncio
from typing import Optional

WEBHOOK_NAME = "BridgeBot Relay"


class WebhookManager:
    def __init__(self, bot):
        self.bot = bot

    async def create_webhook(self, channel: discord.TextChannel) -> Optional[str]:
        try:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if wh.name == WEBHOOK_NAME and wh.user and wh.user.id == self.bot.user.id:
                    return wh.url
            webhook = await channel.create_webhook(name=WEBHOOK_NAME, reason="BridgeBot channel bridge")
            return webhook.url
        except discord.Forbidden:
            return None
        except Exception:
            return None

    async def delete_webhook_by_url(self, url: str):
        try:
            async with aiohttp.ClientSession() as session:
                wh = discord.Webhook.from_url(url, session=session)
                await wh.delete(reason="BridgeBot bridge removed")
        except Exception:
            pass

    async def send_message(
        self,
        webhook_url: str,
        content: str,
        username: str,
        avatar_url: str,
        embeds: list = None,
    ) -> Optional[int]:
        safe = (
            content
            .replace('@everyone', '@​everyone')
            .replace('@here', '@​here')
        )
        if len(safe) > 1997:
            safe = safe[:1997] + '...'

        async with aiohttp.ClientSession() as session:
            wh = discord.Webhook.from_url(webhook_url, session=session)
            try:
                msg = await wh.send(
                    content=safe or None,
                    username=username[:80],
                    avatar_url=avatar_url,
                    embeds=embeds or [],
                    wait=True,
                )
                return msg.id
            except discord.NotFound:
                return None
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = float(getattr(e.response, 'headers', {}).get('Retry-After', 1))
                    await asyncio.sleep(retry_after)
                    return await self.send_message(webhook_url, content, username, avatar_url, embeds)
                return None
            except Exception:
                return None

    async def edit_message(self, webhook_url: str, message_id: int, new_content: str) -> bool:
        safe = (
            new_content
            .replace('@everyone', '@​everyone')
            .replace('@here', '@​here')
        )
        if len(safe) > 1997:
            safe = safe[:1997] + '...'
        async with aiohttp.ClientSession() as session:
            wh = discord.Webhook.from_url(webhook_url, session=session)
            try:
                await wh.edit_message(message_id, content=safe)
                return True
            except Exception:
                return False

    async def delete_message(self, webhook_url: str, message_id: int) -> bool:
        async with aiohttp.ClientSession() as session:
            wh = discord.Webhook.from_url(webhook_url, session=session)
            try:
                await wh.delete_message(message_id)
                return True
            except Exception:
                return False
