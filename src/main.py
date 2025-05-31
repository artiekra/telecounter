import os
import time
import uuid
import asyncio
from telethon import TelegramClient, Button, events
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine

from database.connect import get_async_engine, get_session_maker
from database.init import init_db
from database.models import User

load_dotenv()

api_id = int(os.getenv("API_ID", "0"))
api_hash = os.getenv("API_HASH", "")
bot_token = os.getenv("BOT_TOKEN", "")
database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise ValueError("DATABASE_URL environment variable not set.")

engine: AsyncEngine = get_async_engine(database_url)
session_maker: async_sessionmaker = get_session_maker(engine)

client = TelegramClient("connection", api_id, api_hash)


async def send_language_selection(event: events.NewMessage.Event) -> None:
    """Send language selection msg with inline buttons."""
    buttons = [
        [Button.inline("🇬🇧 English", b"lang_en")],
        [Button.inline("🇺🇦 Українська", b"lang_uk"),
        Button.inline("🇷🇺 Русский", b"lang_ru")]
    ]

    await event.reply(
        "Welcome! Please choose your language:",
        buttons=buttons
    )


@client.on(events.NewMessage)
async def new_msg_handler(event) -> None:
    """Check if user is known, handle new message."""
    telegram_id = event.sender_id

    async with session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user:
            if user.language is None:
                await send_language_selection(event)
            else:
                await event.reply("hi))")

        else:
            new_user = User(
                id=uuid.uuid4().bytes,
                telegram_id=telegram_id,
                registered_at=int(time.time()),
                language=None,
                is_banned=False,
            )
            session.add(new_user)
            await session.commit()

            await send_language_selection(event)


@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode('utf-8')

    # get the user from DB
    telegram_id = event.sender_id
    async with session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        # TODO: is this even possible? handle this better
        if not user:
            await event.answer("User not found.")
            return

        # update language based on callback data
        if data == "lang_en":
            user.language = "en"
        elif data == "lang_uk":
            user.language = "uk"
        elif data == "lang_ru":
            user.language = "ru"

        session.add(user)
        await session.commit()

        await event.answer(f"Language set to {user.language}!")
        await event.edit(f"Language updated to {user.language}. Thank you! :3", buttons=None)


async def main():
    await init_db(engine)
    await client.start(bot_token=bot_token)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
