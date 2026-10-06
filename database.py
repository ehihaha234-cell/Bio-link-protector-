from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

from config import MONGO_URI, DATABASE_NAME

_client = AsyncIOMotorClient(MONGO_URI) if MONGO_URI else None
_db = _client[DATABASE_NAME] if _client else None

class Database:
    def __init__(self):
        self.groups = _db["groups"] if _db is not None else None
        self.settings = _db["settings"] if _db is not None else None

    async def ensure_group(self, chat_id, title, chat_type):
        if self.groups is None:
            return
        now = datetime.now(timezone.utc)
        await self.groups.update_one(
            {"chat_id": chat_id},
            {"$set": {
                "title": title,
                "chat_type": chat_type,
                "active": True,
                "updated_at": now,
            }, "$setOnInsert": {"created_at": now, "delete_seconds": 0}},
            upsert=True,
        )

    async def deactivate_group(self, chat_id):
        if self.groups is None:
            return
        await self.groups.update_one({"chat_id": chat_id}, {"$set": {"active": False}})

    async def active_groups(self):
        if self.groups is None:
            return []
        return await self.groups.find({"active": True}).to_list(length=10000)

    async def set_delete_seconds(self, chat_id, seconds):
        if self.groups is None:
            return
        await self.groups.update_one(
            {"chat_id": chat_id}, {"$set": {"delete_seconds": seconds}}, upsert=True
        )

    async def get_delete_seconds(self, chat_id, default=0):
        if self.groups is None:
            return default
        doc = await self.groups.find_one({"chat_id": chat_id}, {"delete_seconds": 1})
        return int((doc or {}).get("delete_seconds", default) or 0)

    async def get_mt_session(self):
        if self.settings is None: return None
        doc = await self.settings.find_one({"_id": "mtproto_owner"})
        return (doc or {}).get("session")

    async def save_mt_session(self, session: str, phone: str = "", user_id: int = 0, username: str = ""):
        if self.settings is None:
            raise RuntimeError("MongoDB is not configured; MTProto session cannot be saved")
        await self.settings.update_one({"_id":"mtproto_owner"},{"$set":{
            "session":session,"phone":phone,"user_id":int(user_id or 0),
            "username":username or "","connected":True,
            "updated_at":datetime.now(timezone.utc)}},upsert=True)
        return True

    async def get_mt_account(self):
        if self.settings is None: return None
        return await self.settings.find_one({"_id":"mtproto_owner"})

    async def clear_mt_session(self):
        if self.settings is None: return False
        await self.settings.update_one({"_id":"mtproto_owner"},{"$set":{
            "connected":False,"session":"","phone":"","user_id":0,"username":""}},upsert=True)
        return True

    async def count_groups(self):
        if self.groups is None:
            return 0
        return await self.groups.count_documents({"active": True})

db = Database()
