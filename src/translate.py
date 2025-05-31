import gettext

from sqlalchemy import select
from database.models import User
from sqlalchemy.ext.asyncio import AsyncSession

LOCALES_DIR = "locales"
DEFAULT_LANG = "en"


async def setup_translations(user_id: int, session: AsyncSession):
    """Load translations for given Telegram user."""
    result = await session.execute(
        select(User).where(User.telegram_id == user_id)
    )
    user = result.scalar_one_or_none()

    lang = user.language if user and user.language else DEFAULT_LANG

    translator = gettext.translation(
        domain="strings",
        localedir=LOCALES_DIR,
        languages=[lang],
        # fallback=True
    )

    return translator.gettext
