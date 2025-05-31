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
from translate import setup_translations

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
        _ = await setup_translations(event.sender_id, session)

        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                id=uuid.uuid4().bytes,
                telegram_id=telegram_id,
                registered_at=int(time.time()),
                language=None,
                is_banned=False,
            )
            session.add(user)
            await session.commit()

        if user.language is None:
            await send_language_selection(event)

        else:
            await event.reply(_("hey"))


async def update_user_language(event, new_language: str,
                               user: User, session):
    """Update user lang in db, notify the user."""
    user.language = new_language
    session.add(user)
    await session.commit()
    _ = await setup_translations(event.sender_id, session)

    await event.answer(_("language_set_popup").format(user.language))
    await event.edit(_("language_set_message").format(
        user.language), buttons=None)


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

        data = data.split("_")
        command = data[0]

        # update language based on callback data
        if command == "lang":
            new_language = data[1]
            await update_user_language(event, new_language, user, session)


async def main():
    """Initialize the database, start listening for events."""
    await init_db(engine)
    await client.start(bot_token=bot_token)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
