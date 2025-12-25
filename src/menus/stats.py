import os

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import events

from database.models import User
from helpers.stats import get_balance_history, get_category_pie_charts


# [TODO: wrap matplotlib in executor for async]
async def send_menu(
    session: AsyncSession, user: User, _, event: events.NewMessage.Event
) -> None:
    """Send stats menu to the user with generated charts."""
    status_msg = await event.reply(_("stats_waiting"))

    reply_id = getattr(event, "message_id", None) or event.id

    try:
        balance_chart = await get_balance_history(session, user.id)
        pie_chart = await get_category_pie_charts(session, user.id)

        await event.client.send_file(
            event.chat_id,
            file=[balance_chart, pie_chart],
            caption=_("stats_caption"),
            reply_to=reply_id,
        )

        await status_msg.delete()

    except Exception as e:
        logger.error(e)
        await status_msg.edit(
            _("stats_generation_error").format(
                "@" + os.getenv("SUPPORT_USERNAME", "[not specified]")
            )
        )
