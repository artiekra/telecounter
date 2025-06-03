import uuid
import time

from telethon import events
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, Category
from translate import setup_translations
from handlers.transaction import register_transaction


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


async def handle_command_category(session: AsyncSession, event,
                                  user: User, data: list, _) -> None:
    """Handle user pressing a button under category creation prompt msg."""
    if data[1] == "cancel":
        user.expectation["expect"] = {"type": None, "data": None}
        await session.commit()
        await event.respond(_("category_creation_cancelled"))
        return

    new_category = Category(
        id=uuid.uuid4().bytes,
        holder=user.id,
        icon="✨",
        name=user.expectation["expect"]["data"]
    )

    session.add(new_category)
    await session.commit()
    await session.refresh(new_category)

    await event.edit(_("category_created_successfully"))

    user.expectation["expect"] = {"type": None, "data": None}
    await session.commit()

    current_transaction = user.expectation["transaction"]
    if current_transaction is not None:
        await event.respond(_("transaction_handling_in_process").format(
            " ".join(map(str, current_transaction))
        ))
        await register_transaction(session, user, _, event, current_transaction)


def register_callback_handler(client, session_maker):

    @client.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data.decode('utf-8')

        # get the user from DB
        telegram_id = event.sender_id
        async with session_maker() as session:
            _ = await setup_translations(telegram_id, session)
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

            elif command == "category":
                await handle_command_category(session, event, user, data, _)

            else:
                raise Error("Got unexpected callback query command")
