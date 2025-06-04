from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User


async def send_menu(session: AsyncSession, user: User, _, event) -> None:
    """Send categories menu to the user"""
    await event.reply("hai categories")
