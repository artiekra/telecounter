from telethon import events
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from translate import setup_translations


async def update_user_language(event, new_language: str,
                               user: User, session: AsyncSession):
    """Update user lang in db, notify the user."""
    user.language = new_language
    session.add(user)
    await session.commit()
    _ = await setup_translations(event.sender_id, session)

    await event.answer(_("language_set_popup").format(user.language))
    await event.edit(_("language_set_message").format(
        user.language), buttons=None)
    await event.respond(_("tutorial"))


def register_callback_handler(client, session_maker):

    @client.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data.decode('utf-8')

        # get the user from DB
        telegram_id = event.sender_id
        async with session_maker() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()

            # TODO: is this even possible? handle this better
            if not user:
                await event.answer("User not found.")
                return

            data = data.split("_")
            command = data[0]

            # update language based on callback data
            if command == "lang":
                new_language = data[1]
                await update_user_language(event, new_language, user, session)
