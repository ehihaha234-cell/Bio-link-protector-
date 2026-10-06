import asyncio
import logging
import threading
from typing import Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import (
    RPCError,
    UserAlreadyParticipantError,
    InviteHashExpiredError,
    InviteHashInvalidError,
)

from config import MT_API_ID, MT_API_HASH, MT_SESSION

logger = logging.getLogger(__name__)


class MTProtoService:
    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self.ready = False
        # MTProto runs in its own thread/event loop, while the Bot API
        # application runs in another event loop. Use a thread-safe flag
        # instead of asyncio.Event across those loops.
        self._ready_event = threading.Event()
        self._start_lock = threading.Lock()

    def _build(self):
        if not MT_API_ID or not MT_API_HASH or not MT_SESSION:
            raise RuntimeError("MT_API_ID, MT_API_HASH and MT_SESSION are required")

        self.client = TelegramClient(
            StringSession(MT_SESSION),
            MT_API_ID,
            MT_API_HASH,
            auto_reconnect=True,
        )
        return self.client

    async def start(self):
        # Do not create multiple Telethon clients if startup is triggered twice.
        with self._start_lock:
            if self.client and self.ready:
                return self.client
            self.ready = False
            self._ready_event.clear()
            client = self._build()

        try:
            await client.connect()

            if not await client.is_user_authorized():
                raise RuntimeError("MT_SESSION is invalid or not authorized")

            me = await client.get_me()
            self.ready = True
            self._ready_event.set()

            logger.info(
                "MTProto connected as @%s (%s)",
                me.username or "no_username",
                me.id,
            )
            return client
        except Exception:
            self.ready = False
            self._ready_event.clear()
            try:
                await client.disconnect()
            except Exception:
                pass
            self.client = None
            raise

    async def wait_until_ready(self, timeout: float = 45.0) -> bool:
        """Wait for the shared owner MTProto account from another thread."""
        if self.ready and self.client:
            return True

        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self.ready and self.client:
                return True
            await asyncio.sleep(0.25)
        return bool(self.ready and self.client)

    async def get_bio(self, user_entity) -> Optional[str]:
        if not self.client or not self.ready:
            logger.warning("MTProto bio lookup skipped: client not ready")
            return None

        try:
            full = await self.client(GetFullUserRequest(user_entity))
            about = getattr(full.full_user, "about", None) or ""

            entities = getattr(full.full_user, "about_entities", None) or []
            hidden_urls = []
            for ent in entities:
                url = getattr(ent, "url", None)
                if url:
                    hidden_urls.append(str(url))

            combined = about
            if hidden_urls:
                combined += " " + " ".join(hidden_urls)

            logger.info(
                "MTProto bio fetched: user=%s bio=%r",
                getattr(user_entity, "id", "?"),
                combined,
            )
            return combined
        except (RPCError, ValueError, TypeError) as exc:
            logger.warning("MTProto bio lookup failed: %s", exc)
            return None

    async def join_group_by_invite(self, invite_link: str):
        """Join a protected group using a bot-generated invite link."""
        if not await self.wait_until_ready(timeout=45):
            raise RuntimeError("MTProto client is not ready")

        link = (invite_link or "").strip()
        if not link:
            raise ValueError("Empty invite link")

        if "+" in link:
            invite_hash = link.split("+", 1)[1].split("?", 1)[0].strip("/")
        elif "/joinchat/" in link:
            invite_hash = link.split("/joinchat/", 1)[1].split("?", 1)[0].strip("/")
        else:
            raise ValueError("Unsupported invite link format")

        try:
            await self.client(ImportChatInviteRequest(invite_hash))
            logger.info("MTProto account joined group using invite link")
        except UserAlreadyParticipantError:
            logger.info("MTProto account is already a member of the group")
        except (InviteHashExpiredError, InviteHashInvalidError) as exc:
            logger.warning("MTProto invite link is invalid/expired: %s", exc)
            raise
        return True

    async def refresh_entity(self, entity):
        if not self.client or not self.ready:
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
        self._ready_event.clear()


mt = MTProtoService()
