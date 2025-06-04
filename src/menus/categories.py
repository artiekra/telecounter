from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import User, Category


async def send_menu(session: AsyncSession, user: User, _, event) -> None:
    """Send categories menu to the user"""

    categories = await session.execute(
        select(Category).where(Category.holder == user.id)
    )
    categories = categories.scalars().all()

    await event.reply(" ".join(map(str, categories)))
