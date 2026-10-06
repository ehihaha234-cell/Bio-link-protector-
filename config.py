import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
MONGO_URI = os.getenv("MONGO_URI", "").strip()

# Backward-compatible database selection.
# Older Bio Link Protector builds used DB_NAME. Newer builds used
# DATABASE_NAME. Prefer DB_NAME when it exists so replacing the code does
# not silently switch to a new empty MongoDB database.
DB_NAME = os.getenv("DB_NAME", "").strip()
DATABASE_NAME = DB_NAME or os.getenv("DATABASE_NAME", "bio_link_protector").strip()

DEFAULT_DELETE_SECONDS = int(os.getenv("DEFAULT_DELETE_SECONDS", "0") or 0)
MAX_DELETE_SECONDS = int(os.getenv("MAX_DELETE_SECONDS", "86400") or 86400)

MT_API_ID = int(os.getenv("MT_API_ID", "0") or 0)
MT_API_HASH = os.getenv("MT_API_HASH", "").strip()
MT_SESSION = os.getenv("MT_SESSION", "").strip()
