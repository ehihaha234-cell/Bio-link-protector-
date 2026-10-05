import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MONGO_URI = os.getenv("MONGO_URI", "").strip()
DB_NAME = os.getenv("DB_NAME", "bio_link_protector").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

# Bio protection
BAN_ON_LINK = os.getenv("BAN_ON_LINK", "true").lower() == "true"
CHECK_BIO_ON_JOIN = os.getenv("CHECK_BIO_ON_JOIN", "true").lower() == "true"
CHECK_BIO_ON_MESSAGE = os.getenv("CHECK_BIO_ON_MESSAGE", "true").lower() == "true"

# A conservative set of URL/link patterns. Add more patterns in protection.py if needed.

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI is missing")
if not OWNER_ID:
    raise RuntimeError("OWNER_ID is missing")
