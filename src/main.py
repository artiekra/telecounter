import asyncio
import os

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from telethon import TelegramClient

from database.connect import get_async_engine, get_session_maker
from database.init import init_db
from handlers.callback import register_callback_handler
from handlers.message import register_message_handler

load_dotenv()

logger.opt(colors=True)

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")

engine: AsyncEngine = get_async_engine(DATABASE_URL)
session_maker: async_sessionmaker = get_session_maker(engine)

client = TelegramClient("connection", API_ID, API_HASH)


async def main():
    """Initialize the database, start listening for events."""
    logger.info("Initializing database...")
    await init_db(engine)
    logger.success("Database initialized.")

    logger.info("Starting Telegram client...")
    await client.start(bot_token=BOT_TOKEN)
    logger.success("Telegram client started.")

    register_callback_handler(client, session_maker)
    register_message_handler(client, session_maker)

    await client.run_until_disconnected()
    logger.info("Telegram client disconnected.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
