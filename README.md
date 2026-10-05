# Bio Link Protector — Bot API + MTProto

This bot uses the Telegram Bot API for moderation and a dedicated MTProto user account for reading Telegram profile bios.

## Protection flow

1. Add the **bot** to a group and make it an administrator with permission to ban/restrict users and delete messages.
2. Add the **MTProto user account** to every protected group. The MTProto account is required because the Bot API does not expose arbitrary group members' profile bios.
3. When a user joins or sends a group message, the MTProto account reads that user's current profile bio.
4. If the bio contains a Telegram/web link or `@username`, the bot bans the user and sends a warning to the group administrators.
5. If the bio is clean, nothing is changed.
6. Auto-delete and owner broadcast/group statistics continue through the Bot API.

## MTProto setup

Create Telegram API credentials at `my.telegram.org` and get:

- `MT_API_ID`
- `MT_API_HASH`

Generate the session locally:

```text
pip install Telethon==1.45.0
python generate_session.py
```

Enter the MTProto account's phone number, login code and 2FA password if requested. Copy the printed `MT_SESSION` value into Render.

**Use a dedicated Telegram account for the MTProto connection. Never publish the session string.** Anyone who gets it can access that Telegram account.

## Render Free Web Service

Build command:

```text
pip install -r requirements.txt
```

Start command:

```text
python bot.py
```

Health endpoint:

```text
/health
```

Required environment variables:

```text
BOT_TOKEN
OWNER_ID
MONGO_URI
DATABASE_NAME
DEFAULT_DELETE_SECONDS
MAX_DELETE_SECONDS
MT_API_ID
MT_API_HASH
MT_SESSION
```

Only one instance may poll with the same `BOT_TOKEN`. If another copy is running, Telegram will return `409 Conflict`.
