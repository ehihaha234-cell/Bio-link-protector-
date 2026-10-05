# Bio Link Protector

Fresh Telegram protection bot built with Python, python-telegram-bot 22.8 and MongoDB.

## Features
- Automatic bio link detection for group members.
- Ban users whose accessible Telegram bio contains a URL, Telegram link, or @username pattern.
- Delete the violating message when a violation is detected.
- Warn the group owner in private chat when a user is banned.
- Per-group auto-delete timer: `/autodelete <seconds>`; `/autodelete 0` disables it.
- Owner-only dashboard for statistics, active groups, broadcast and settings help.
- Broadcast a message to all active groups where the bot is still present.
- MongoDB persistence.
- Render worker deployment configuration.

## Setup
1. Create a bot with @BotFather.
2. Create a MongoDB database and obtain its connection URI.
3. Copy `.env.example` to `.env` and fill in the values.
4. Install dependencies: `pip install -r requirements.txt`
5. Run: `python bot.py`
6. Add the bot to a group as administrator with permission to delete messages and ban/restrict members.

## Auto delete
An administrator can run:

`/autodelete 60`

All regular group messages observed by the bot are queued for deletion after 60 seconds. Use `/autodelete 0` to disable.

## Owner dashboard
Only `OWNER_ID` receives the owner dashboard from `/start`. Regular users do not get owner controls.

## Bio detection note
Telegram's Bot API exposes a user's bio through `getChat` for private chats when available. For join requests, Telegram also supplies the request bio. If Telegram does not expose a bio for a particular user, the bot does not falsely ban that user. See Telegram Bot API documentation for current platform limitations.
