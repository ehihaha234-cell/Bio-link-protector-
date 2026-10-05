from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

from config import MONGO_URI, DB_NAME

client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=8000)
db = client[DB_NAME]
groups = db.groups
messages = db.messages
stats = db.stats


def now():
    return datetime.now(timezone.utc)


async def init_db():
    await groups.create_index("chat_id", unique=True)
    await messages.create_index("delete_at")
    await messages.create_index([("chat_id", 1), ("message_id", 1)], unique=True)
    await stats.create_index("key", unique=True)


async def upsert_group(chat_id: int, title: str, added_by: Optional[int] = None):
    await groups.update_one(
        {"chat_id": chat_id},
        {
            "$set": {"title": title, "active": True, "updated_at": now()},
            "$setOnInsert": {
                "chat_id": chat_id,
                "auto_delete_seconds": 0,
                "created_at": now(),
                "added_by": added_by,
            },
        },
        upsert=True,
    )


async def mark_group_inactive(chat_id: int):
    await groups.update_one({"chat_id": chat_id}, {"$set": {"active": False, "updated_at": now()}})


async def get_group(chat_id: int):
    return await groups.find_one({"chat_id": chat_id})


async def set_auto_delete(chat_id: int, seconds: int):
    await groups.update_one(
        {"chat_id": chat_id},
        {"$set": {"auto_delete_seconds": seconds, "updated_at": now()}},
        upsert=True,
    )


async def queue_message(chat_id: int, message_id: int, delete_at: datetime):
    await messages.update_one(
        {"chat_id": chat_id, "message_id": message_id},
        {"$set": {"delete_at": delete_at}},
        upsert=True,
    )


async def get_due_messages(limit: int = 100):
    return await messages.find({"delete_at": {"$lte": now()}}).limit(limit).to_list(length=limit)


async def remove_queued_message(doc_id):
    await messages.delete_one({"_id": doc_id})


async def increment_stat(key: str, amount: int = 1):
    await stats.update_one({"key": key}, {"$inc": {"value": amount}}, upsert=True)


async def get_stat(key: str) -> int:
    doc = await stats.find_one({"key": key})
    return int(doc.get("value", 0)) if doc else 0


async def list_active_groups():
    return await groups.find({"active": True}).sort("title", 1).to_list(length=None)


async def count_groups(active_only: bool = True) -> int:
    return await groups.count_documents({"active": True} if active_only else {})
