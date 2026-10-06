import asyncio, logging, threading
from typing import Optional
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import RPCError, UserAlreadyParticipantError, InviteHashExpiredError, InviteHashInvalidError, SessionPasswordNeededError
from config import MT_API_ID, MT_API_HASH, MT_SESSION
from database import db
logger=logging.getLogger(__name__)

class MTProtoService:
    def __init__(self):
        self.client=None; self.ready=False; self.loop=None
        self._lock=threading.Lock(); self.message_handler=None; self.chat_action_handler=None
        self._handlers_attached=False; self._login_phone=""; self._phone_code_hash=""

    def set_handlers(self, message_handler, chat_action_handler):
        self.message_handler=message_handler; self.chat_action_handler=chat_action_handler
        if self.client and self.ready: self._attach_handlers()

    def _attach_handlers(self):
        if not self.client or self._handlers_attached: return
        if self.message_handler: self.client.add_event_handler(self.message_handler, events.NewMessage())
        if self.chat_action_handler: self.client.add_event_handler(self.chat_action_handler, events.ChatAction())
        self._handlers_attached=True

    def _new_client(self, session=""):
        if not MT_API_ID or not MT_API_HASH: raise RuntimeError("MT_API_ID and MT_API_HASH are required")
        return TelegramClient(StringSession(session or ""),MT_API_ID,MT_API_HASH,auto_reconnect=True)

    async def _connect(self, session):
        client=self._new_client(session); await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect(); raise RuntimeError("Saved MTProto session is not authorized")
        me=await client.get_me(); self.client=client; self.ready=True; self._handlers_attached=False
        self._attach_handlers(); logger.info("MTProto connected as @%s (%s)",me.username or "no_username",me.id)
        return client

    async def start(self):
        self.loop=asyncio.get_running_loop()
        session=MT_SESSION or await db.get_mt_session()
        if not session: raise RuntimeError("Owner MTProto account is not connected")
        with self._lock:
            if self.client and self.ready: return self.client
            self.ready=False
        return await self._connect(session)

    def run(self,coro):
        if not self.loop or not self.loop.is_running(): raise RuntimeError("MTProto loop not running")
        return asyncio.run_coroutine_threadsafe(coro,self.loop)

    async def _run_on_mt_loop(self,coro):
        current=asyncio.get_running_loop()
        if self.loop and self.loop.is_running() and self.loop is not current:
            return await asyncio.wrap_future(self.run(coro))
        return await coro

    async def login_send_code(self,phone):
        async def op():
            if self.client:
                try: await self.client.disconnect()
                except: pass
            self.client=self._new_client(""); await self.client.connect()
            sent=await self.client.send_code_request(phone)
            self._login_phone=phone; self._phone_code_hash=sent.phone_code_hash
            return True
        return await self._run_on_mt_loop(op())

    async def login_code(self,code):
        async def op():
            try:
                me=await self.client.sign_in(phone=self._login_phone,code=code,phone_code_hash=self._phone_code_hash)
                return me,False
            except SessionPasswordNeededError:
                return None,True
        return await self._run_on_mt_loop(op())

    async def login_password(self,password):
        async def op(): return await self.client.sign_in(password=password)
        return await self._run_on_mt_loop(op())

    async def finish_login(self,phone,me):
        async def op():
            session=self.client.session.save()
            await db.save_mt_session(session,phone,int(me.id),me.username or "")
            self.ready=True; self._handlers_attached=False; self._attach_handlers()
            return session
        return await self._run_on_mt_loop(op())

    async def logout(self):
        async def op():
            if self.client:
                try: await self.client.log_out()
                except: pass
                try: await self.client.disconnect()
                except: pass
            self.client=None; self.ready=False; self._handlers_attached=False
            await db.clear_mt_session()
        return await self._run_on_mt_loop(op())

    async def wait_until_ready(self,timeout=45):
        if self.ready and self.client: return True
        deadline=asyncio.get_running_loop().time()+timeout
        while asyncio.get_running_loop().time()<deadline:
            if self.ready and self.client:return True
            await asyncio.sleep(.25)
        return bool(self.ready and self.client)

    async def get_bio(self,user_entity):
        if not self.client or not self.ready:return None
        try:
            full=await self.client(GetFullUserRequest(user_entity)); about=getattr(full.full_user,"about",None) or ""
            entities=getattr(full.full_user,"about_entities",None) or []
            urls=[str(getattr(e,"url")) for e in entities if getattr(e,"url",None)]
            return about+((" "+" ".join(urls)) if urls else "")
        except (RPCError,ValueError,TypeError) as e:
            logger.warning("MTProto bio lookup failed: %s",e); return None

    async def join_group_by_invite(self,invite_link):
        if not await self.wait_until_ready(45): raise RuntimeError("MTProto client is not ready")
        link=(invite_link or "").strip()
        if "+" in link: h=link.split("+",1)[1].split("?",1)[0].strip("/")
        elif "/joinchat/" in link: h=link.split("/joinchat/",1)[1].split("?",1)[0].strip("/")
        else: raise ValueError("Unsupported invite link format")
        try: await self.client(ImportChatInviteRequest(h))
        except UserAlreadyParticipantError: pass
        except (InviteHashExpiredError,InviteHashInvalidError): raise
        return True

    async def refresh_entity(self,entity):
        if not self.client or not self.ready:return None
        try:return await self.client.get_entity(entity)
        except Exception:return None

    async def stop(self):
        if self.client: await self.client.disconnect()
        self.client=None; self.ready=False

mt=MTProtoService()
