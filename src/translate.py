import gettext
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User

LOCALES_DIR = "locales"
DEFAULT_LANG = "en"


async def setup_translations(user_id: int, session: AsyncSession):
    """Load translations for given Telegram user."""
    result = await session.execute(select(User).where(User.telegram_id == user_id))
    user = result.scalar_one_or_none()

    lang = user.language if user and user.language else DEFAULT_LANG

    mo_path = os.path.join(LOCALES_DIR, f"{lang}.mo")
    try:
        with open(mo_path, "rb") as mo_file:
            translator = gettext.GNUTranslations(mo_file).gettext
    except FileNotFoundError:
        translator = lambda s: s  # fallback: return original string

    return translator
