import uuid
import time

from telethon import events
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, Category, CategoryAlias, WalletAlias
from translate import setup_translations
from handlers.transaction import (register_transaction, create_wallet,
    create_category)
from handlers.message import COMMANDS
import menus.wallets as wallets
import menus.categories as categories


async def update_user_language(event, new_language: str,
                               user: User, session: AsyncSession,
                               command: str):
    """Update user lang in db, notify the user."""
    user.language = new_language
    session.add(user)
    await session.commit()
    _ = await setup_translations(event.sender_id, session)

    await event.answer(_("language_set_popup"))
    await event.edit(_("language_set_message"), buttons=None)

    if command == "lang":
        await event.respond(_("tutorial"))


async def universal_custom_page_input_workflow(
    session: AsyncSession,
    event,
    user: User,
    _,
    type_: str,
    msg_id: int
) -> None:
    """Ask user for a page to go to."""
    user.expectation["expect"] = {"type": "page", "data": [type_, msg_id]}
    await session.commit()

    await event.respond(_("universal_prompt_page_number"))


async def handle_command_category(session: AsyncSession, event,
                                  user: User, data: list, _) -> None:
    """Handle user pressing a button under category creation prompt msg."""
    if data[1] == "cancel":
        user.expectation["expect"] = {"type": None, "data": None}
        await session.commit()
        await event.respond(_("category_creation_cancelled"))
        return

    category_name = user.expectation["expect"]["data"]

    new_category = Category(
        id=uuid.uuid4().bytes,
        holder=user.id,
        created_at=int(time.time()),
        icon="✨",
        name=category_name
    )

    session.add(new_category)

    # delete matching aliases (same name)
    await session.execute(
        delete(CategoryAlias).where(
            CategoryAlias.holder == user.id,
            CategoryAlias.alias == category_name
        )
    )

    await session.commit()
    await session.refresh(new_category)

    await event.edit(_("category_created_successfully").format(category_name))

    user.expectation["expect"] = {"type": None, "data": None}
    await session.commit()

    current_transaction = user.expectation["transaction"]
    if len(current_transaction) > 0:
        await event.respond(_("transaction_handling_in_process").format(
            " ".join(map(str, current_transaction))
        ))
        await register_transaction(session, user, _, event, current_transaction)


async def handle_command_categoryalias(session: AsyncSession, event,
                                       user: User, data: list, _) -> None:
    """Handle user pressing a button under category alias creation msg."""
    if data[1] == "cancel":
        user.expectation["expect"] = {"type": None, "data": None}
        await session.commit()
        await event.respond(_("category_alias_creation_cancelled"))
        return

    elif data[1] == "new":
        category_name = user.expectation["expect"]["data"][0]

        new_category = Category(
            id=uuid.uuid4().bytes,
            holder=user.id,
            icon="✨",
            name=category_name
        )

        session.add(new_category)
        await session.commit()
        await session.refresh(new_category)

        await event.edit(
            _("category_created_successfully").format(category_name))

        user.expectation["expect"] = {"type": None, "data": None}
        await session.commit()

        current_transaction = user.expectation["transaction"]
        if len(current_transaction) > 0:
            # await event.respond(_("transaction_handling_in_process").format(
            #     " ".join(map(str, current_transaction))
            # ))
            await register_transaction(session, user, _, event,
                                       current_transaction)

    elif data[1] == "approve":
        alias_name = user.expectation["expect"]["data"][0]
        actual_category_id = bytes.fromhex(
            user.expectation["expect"]["data"][1])

        new_alias = CategoryAlias(
            id=uuid.uuid4().bytes,
            holder=user.id,
            category=actual_category_id,
            alias=alias_name,
        )

        session.add(new_alias)
        await session.commit()

        await event.edit(
            _("category_alias_created_successfully").format(alias_name)
        )

        user.expectation["expect"] = {"type": None, "data": None}
        await session.commit()

        current_transaction = user.expectation.get("transaction")
        if len(current_transaction) > 0:
            # await event.respond(_("transaction_handling_in_process").format(
            #     " ".join(map(str, current_transaction))
            # ))
            await register_transaction(session, user, _, event, current_transaction)


async def handle_command_walletalias(session: AsyncSession, event,
                                     user: User, data: list, _) -> None:
    """Handle user pressing a button under category alias creation msg."""
    if data[1] == "cancel":
        user.expectation["expect"] = {"type": None, "data": None}
        await session.commit()
        await event.respond(_("wallet_alias_creation_cancelled"))
        return

    elif data[1] == "new":
        name = user.expectation["expect"]["data"][0]
        await create_wallet(session, user, _, event, name)

    elif data[1] == "approve":
        alias_name = user.expectation["expect"]["data"][0]
        actual_wallet_id = bytes.fromhex(
                user.expectation["expect"]["data"][1])

        new_alias = WalletAlias(
            id=uuid.uuid4().bytes,
            holder=user.id,
            wallet=actual_wallet_id,
            alias=alias_name,
        )

        session.add(new_alias)
        await session.commit()

        await event.edit(
            _("wallet_alias_created_successfully").format(alias_name)
        )

        user.expectation["expect"] = {"type": None, "data": None}
        await session.commit()

        current_transaction = user.expectation.get("transaction")
        if len(current_transaction) > 0:
            # await event.respond(_("transaction_handling_in_process").format(
            #     " ".join(map(str, current_transaction))
            # ))
            await register_transaction(session, user, _, event, current_transaction)


async def handle_command_action(session: AsyncSession, event,
                                user: User, data: list, _) -> None:
    """Handle user pressing a button under one of the action menus."""

    if data[1][0] == "c":
        await categories.handle_action(session, event, user, data, _)

    if data[1][0] == "w":
        await wallets.handle_action(session, event, user, data, _)

    else:
        raise Exception('Got unexpected data for callback command "action"')


async def handle_command_page(session: AsyncSession, event,
                              user: User, data: list, _) -> None:
    """Handle user pressing a pagination button."""

    msg_id = int(bytes.fromhex(data[2]).decode("utf-8"))
    try:
        page = int(data[3])
    except IndexError:
        page = None
    if page:
        if data[1] == "c":
            await categories.send_menu(
                session, user, _, event, page, msg_id
            )
        elif data[1] == "w":
            await wallets.send_menu(
                session, user, _, event, page, msg_id
            )
        return
    await universal_custom_page_input_workflow(
        session, event, user, _, data[1], msg_id)


async def handle_command_export(session: AsyncSession, event,
                                user: User, data: list, _) -> None:
    """Handle user pressing an export button."""

    if data[1] == "categories":
        await categories.export(session, event, user, _)
    elif data[1] == "wallets":
        await wallets.export(session, event, user, _)
    else:
        raise Exception('Got unexpected data for callback command "export"')


def register_callback_handler(client, session_maker):

    @client.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data.decode("utf-8")

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
            if command == "lang" or command == "plang":
                user.expectation["expect"] = {"type": None, "data": None}
                user.expectation["transaction"] = []
                new_language = data[1]
                await update_user_language(event, new_language, user,
                                           session, command)

            elif command == "category":
                await handle_command_category(session, event, user, data, _)

            elif command == "wallet":
                user.expectation["expect"] = {"type": None, "data": None}
                await session.commit()
                await event.respond(_("wallet_creation_cancelled"))

            elif command == "categoryalias":
                await handle_command_categoryalias(
                    session, event, user, data, _)

            elif command == "walletalias":
                await handle_command_walletalias(
                    session, event, user, data, _)

            elif command == "add":
                user.expectation["expect"] = {"type": None, "data": None}
                user.expectation["transaction"] = []
                if data[1] == "wallet":
                    await create_wallet(session, user, _, event)
                elif data[1] == "category":
                    await create_category(session, user, _, event)

            elif command == "menu":
                user.expectation["expect"] = {"type": None, "data": None}
                user.expectation["transaction"] = []
                await COMMANDS.get(data[1])(session, user, _, event)

            elif command == "action":
                user.expectation["expect"] = {"type": None, "data": None}
                user.expectation["transaction"] = []
                await handle_command_action(session, event, user, data, _)

            elif command == "page":
                await handle_command_page(session, event, user, data, _)

            elif command == "export":
                await handle_command_export(session, event, user, data, _)

            else:
                raise Exception("Got unexpected callback query command")
