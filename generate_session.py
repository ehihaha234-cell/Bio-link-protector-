import asyncio
import os
from telethon import TelegramClient
from telethon.sessions import StringSession

async def main():
    api_id = int(input("Telegram API ID: ").strip())
    api_hash = input("Telegram API Hash: ").strip()
    phone = input("Telegram phone number (+countrycode...): ").strip()

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start(phone=phone)
    session = client.session.save()
    me = await client.get_me()
    print("\nLogged in as:", me.username or me.id)
    print("\nMT_SESSION=\n" + session)
    print("\nKeep this session string secret. It can authorize the Telegram account.")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
