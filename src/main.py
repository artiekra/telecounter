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
from handlers.callback import register_callback_handler
from handlers.message import register_message_handler

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


async def main():
    """Initialize the database, start listening for events."""
    await init_db(engine)
    await client.start(bot_token=bot_token)

    register_callback_handler(client, session_maker)
    register_message_handler(client, session_maker)

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
