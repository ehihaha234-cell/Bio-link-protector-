# Bio Link Protector

Fresh Telegram group protection bot.

## Current features

- Automatic group registration when the bot becomes a member/admin.
- Owner-only `/start`, `/broadcast`, `/stats`, and `/groups`.
- Automatic message deletion timer per group (database setting ready).
- Protection engine with link detection and ban handling when bio data is available.
- Admin warning after a successful protection action.
- MongoDB storage.
- Render Worker deployment.

## Environment variables

```env
BOT_TOKEN=
OWNER_ID=
MONGO_URI=
DATABASE_NAME=bio_link_protector
DEFAULT_DELETE_SECONDS=0
MAX_DELETE_SECONDS=86400
```

## Telegram permissions

Make the bot an administrator in each protected group with:
- Ban users
- Delete messages

## Important Bot API limitation

A Telegram bot cannot arbitrarily retrieve every group member's profile bio by user ID. This project does not pretend otherwise. Bio is only checked when the Telegram update/context actually exposes the bio. A separate MTProto user-account architecture would be required for broader profile inspection and is intentionally not enabled in this Bot-API-only build.
