from datetime import datetime, timezone
import asyncio
from pymongo import MongoClient, ReturnDocument

from config import MONGO_URI, DATABASE_NAME

# Use synchronous PyMongo underneath asyncio.to_thread().
# This avoids Motor's event-loop affinity problems when the bot and the
# Telethon MTProto client run on different asyncio loops/threads.
_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000) if MONGO_URI else None
_db = _client[DATABASE_NAME] if _client is not None else None

class Database:
    def __init__(self):
        self.groups = _db["groups"] if _db is not None else None
        self.settings = _db["settings"] if _db is not None else None
        self.users = _db["users"] if _db is not None else None
        self.warning_counts = _db["warning_counts"] if _db is not None else None

    async def _call(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def ensure_group(self, chat_id, title, chat_type):
        if self.groups is None:
            return
        now = datetime.now(timezone.utc)
        await self._call(
            self.groups.update_one,
            {"chat_id": chat_id},
            {"$set": {"title": title, "chat_type": chat_type, "active": True, "updated_at": now},
             "$setOnInsert": {"created_at": now, "delete_seconds": 0, "paused": False, "detect_on_join": True, "message_action": "ban", "delete_after_warning": True, "punishment": "mute", "warning_limit": 3}},
            upsert=True,
        )

    async def get_group(self, chat_id):
        if self.groups is None:
            return None
        return await self._call(self.groups.find_one, {"chat_id": chat_id})

    async def set_group_paused(self, chat_id, paused):
        if self.groups is None:
            return
        await self._call(self.groups.update_one, {"chat_id": chat_id}, {"$set": {"paused": bool(paused)}})

    async def is_group_paused(self, chat_id):
        if self.groups is None:
            return False
        doc = await self._call(self.groups.find_one, {"chat_id": chat_id}, {"paused": 1})
        return bool((doc or {}).get("paused", False))

    async def deactivate_group(self, chat_id):
        if self.groups is None:
            return
        await self._call(self.groups.update_one, {"chat_id": chat_id}, {"$set": {"active": False}})

    async def active_groups(self):
        if self.groups is None:
            return []
        return await self._call(lambda: list(self.groups.find({"active": True}).limit(10000)))

    async def set_delete_seconds(self, chat_id, seconds):
        if self.groups is None:
            return
        await self._call(
            self.groups.update_one,
            {"chat_id": chat_id},
            {"$set": {"delete_seconds": seconds}},
            upsert=True,
        )

    async def get_delete_seconds(self, chat_id, default=0):
        if self.groups is None:
            return default
        doc = await self._call(self.groups.find_one, {"chat_id": chat_id}, {"delete_seconds": 1})
        return int((doc or {}).get("delete_seconds", default) or 0)

    async def get_mt_session(self):
        if self.settings is None:
            return None
        doc = await self._call(self.settings.find_one, {"_id": "mtproto_owner"})
        return (doc or {}).get("session")

    async def save_mt_session(self, session: str, phone: str = "", user_id: int = 0, username: str = ""):
        if self.settings is None:
            raise RuntimeError("MongoDB is not configured; MTProto session cannot be saved")
        await self._call(
            self.settings.update_one,
            {"_id": "mtproto_owner"},
            {"$set": {
                "session": session,
                "phone": phone,
                "user_id": int(user_id or 0),
                "username": username or "",
                "connected": True,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return True

    async def get_mt_account(self):
        if self.settings is None:
            return None
        return await self._call(self.settings.find_one, {"_id": "mtproto_owner"})

    async def clear_mt_session(self):
        if self.settings is None:
            return False
        await self._call(
            self.settings.update_one,
            {"_id": "mtproto_owner"},
            {"$set": {"connected": False, "session": "", "phone": "", "user_id": 0, "username": ""}},
            upsert=True,
        )
        return True


    async def get_protection_settings(self, chat_id):
        if self.groups is None:
            return {"detect_on_join": True, "message_action": "ban", "delete_after_warning": True, "punishment": "mute", "warning_limit": 3}
        doc = await self._call(self.groups.find_one, {"chat_id": int(chat_id)}, {
            "detect_on_join": 1, "message_action": 1, "delete_after_warning": 1, "punishment": 1, "warning_limit": 1
        })
        return {
            "detect_on_join": bool((doc or {}).get("detect_on_join", True)),
            "message_action": (doc or {}).get("message_action", "ban"),
            "delete_after_warning": bool((doc or {}).get("delete_after_warning", True)),
            "punishment": (doc or {}).get("punishment", "mute"),
            "warning_limit": max(1, int((doc or {}).get("warning_limit", 3) or 3)),
        }

    async def update_protection_setting(self, chat_id, key, value):
        if self.groups is None:
            return
        allowed = {"detect_on_join", "message_action", "delete_after_warning", "punishment", "warning_limit"}
        if key not in allowed:
            raise ValueError("Invalid protection setting")
        await self._call(self.groups.update_one, {"chat_id": int(chat_id)}, {"$set": {key: value}}, upsert=True)

    async def increment_warning(self, chat_id, user_id):
        if self.warning_counts is None:
            return 1
        doc = await self._call(
            self.warning_counts.find_one_and_update,
            {"chat_id": int(chat_id), "user_id": int(user_id)},
            {"$inc": {"count": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
        # Return the incremented document directly: one MongoDB round-trip
        # instead of update + second find. This keeps warning responses fast.
        return int((doc or {}).get("count", 1) or 1)

    async def get_warning_count(self, chat_id, user_id):
        if self.warning_counts is None:
            return 0
        doc = await self._call(self.warning_counts.find_one, {"chat_id": int(chat_id), "user_id": int(user_id)})
        return int((doc or {}).get("count", 0) or 0)

    async def count_groups(self):
        if self.groups is None:
            return 0
        return await self._call(self.groups.count_documents, {"active": True})

    async def increment_stat(self, key, amount=1):
        if self.settings is None:
            return
        await self._call(
            self.settings.update_one,
            {"_id": "statistics"},
            {"$inc": {key: int(amount)}},
            upsert=True,
        )

    async def get_statistics(self):
        groups = await self.count_groups()
        doc = {} if self.settings is None else await self._call(self.settings.find_one, {"_id": "statistics"})
        users_started = 0
        if self.users is not None:
            users_started = await self._call(self.users.count_documents, {})
        return {
            "groups": groups,
            "users_started": int(users_started),
            "users_banned": int((doc or {}).get("users_banned", 0) or 0),
        }

    async def record_user_start(self, user_id):
        if self.users is None:
            return
        await self._call(
            self.users.update_one,
            {"_id": int(user_id)},
            {"$set": {"last_started_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    async def record_user_banned(self, user_id, chat_id=None):
        if self.settings is None:
            return
        await self.increment_stat("users_banned", 1)

    async def ping(self):
        if self._client_is_missing():
            return False
        try:
            await self._call(_client.admin.command, "ping")
            return True
        except Exception:
            return False

    def _client_is_missing(self):
        return _client is None

db = Database()
