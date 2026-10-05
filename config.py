import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
MONGO_URI = os.getenv("MONGO_URI", "").strip()
DATABASE_NAME = os.getenv("DATABASE_NAME", "bio_link_protector").strip()

# Default auto-delete duration for group messages.
DEFAULT_DELETE_SECONDS = int(os.getenv("DEFAULT_DELETE_SECONDS", "0") or 0)
MAX_DELETE_SECONDS = int(os.getenv("MAX_DELETE_SECONDS", "86400") or 86400)

# MTProto user account used only to read Telegram profile bios.
MT_API_ID = int(os.getenv("MT_API_ID", "0") or 0)
MT_API_HASH = os.getenv("MT_API_HASH", "").strip()
MT_SESSION = os.getenv("MT_SESSION", "").strip()
