import asyncio
import logging
import os
from typing import Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import RPCError

from config import MT_API_ID, MT_API_HASH, MT_SESSION

logger = logging.getLogger(__name__)

class MTProtoService:
    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self.ready = False

    def _build(self):
        if not MT_API_ID or not MT_API_HASH or not MT_SESSION:
            raise RuntimeError("MT_API_ID, MT_API_HASH and MT_SESSION are required")
        self.client = TelegramClient(
            StringSession(MT_SESSION), MT_API_ID, MT_API_HASH,
            auto_reconnect=True,
        )
        return self.client

    async def start(self):
        client = self._build()
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("MT_SESSION is invalid or not authorized")
        me = await client.get_me()
        await client.get_dialogs(limit=None)
        self.ready = True
        logger.info("MTProto connected as @%s (%s)", me.username or "no_username", me.id)
        return client

    async def get_bio(self, user_entity) -> Optional[str]:
        if not self.client or not self.ready:
            logger.warning("MTProto bio lookup skipped: client not ready")
            return None
        try:
            full = await self.client(GetFullUserRequest(user_entity))
            about = getattr(full.full_user, "about", None) or ""

            # Telegram can store a clickable URL as an entity even when the
            # visible bio text does not contain the URL. Include those URLs
            # in the text checked by the protector.
            entities = getattr(full.full_user, "about_entities", None) or []
            hidden_urls = []
            for ent in entities:
                url = getattr(ent, "url", None)
                if url:
                    hidden_urls.append(str(url))

            combined = about
            if hidden_urls:
                combined += " " + " ".join(hidden_urls)

            logger.info("MTProto bio fetched: user=%s bio=%r", getattr(user_entity, "id", "?"), combined)
            return combined
        except (RPCError, ValueError, TypeError) as exc:
            logger.warning("MTProto bio lookup failed: %s", exc)
            return None

    async def refresh_entity(self, entity):
        if not self.client:
            return None
        try:
            return await self.client.get_entity(entity)
        except Exception as exc:
            logger.warning("MTProto entity lookup failed: %s", exc)
            return None

    async def stop(self):
        if self.client:
            await self.client.disconnect()
            self.ready = False

mt = MTProtoService()
