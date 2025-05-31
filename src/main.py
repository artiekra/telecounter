import os
import time
import uuid
from telethon import TelegramClient, events
from dotenv import load_dotenv

from database.connect import get_engine, get_session
from database.init import init_db
from database.models import User
from sqlalchemy.orm import Session

load_dotenv()

api_id = int(os.getenv("API_ID", "0"))
api_hash = os.getenv("API_HASH", "")
bot_token = os.getenv("BOT_TOKEN", "")

client = TelegramClient("connection", api_id, api_hash).start(bot_token=bot_token)

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise ValueError("DATABASE_URL environment variable not set.")
engine = get_engine(database_url)
session = get_session(engine)
init_db(engine)


@client.on(events.NewMessage)
async def new_msg_handler(event) -> None:
    """Check if user is known, handle new message,"""
    telegram_id = event.sender_id

    user: User | None = session.query(User).filter_by(telegram_id=telegram_id).first()
    
    # handles existing users
    if user:
        await event.reply("hi))")

    # create new user if not found in database
    else:
        new_user = User(
            id=uuid.uuid4().bytes,
            telegram_id=telegram_id,
            registered_at=int(time.time()),
            language=None,
            is_banned=False,
        )
        session.add(new_user)
        session.commit()
        await event.reply("hello new fren! you’re registered now :3")


client.run_until_disconnected()
