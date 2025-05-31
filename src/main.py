import os
from telethon import TelegramClient, events
from dotenv import load_dotenv

from database.connect import get_engine
from database.init import init_db

load_dotenv()

api_id = int(os.getenv("API_ID", "0"))
api_hash = os.getenv("API_HASH", "")
bot_token = os.getenv("BOT_TOKEN", "")

client = TelegramClient("connection", api_id, api_hash).start(bot_token=bot_token)

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise ValueError("DATABASE_URL environment variable not set.")
db_engine = get_engine(database_url)
init_db(db_engine)


@client.on(events.NewMessage)
async def new_msg_handler(event) -> None:
    """Reply to every new message with 'hi))'."""
    await event.reply("hi))")


client.run_until_disconnected()
