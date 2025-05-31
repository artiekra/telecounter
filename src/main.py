import os
import time
import uuid
import asyncio
from telethon import TelegramClient, events
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
            await event.reply("hello new fren! you’re registered now :3")


async def main():
    await init_db(engine)
    await client.start(bot_token=bot_token)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
