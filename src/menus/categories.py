from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func, delete
from telethon.tl.custom import Button

from database.models import User, Category, CategoryAlias, Transaction


async def handle_expectation_edit_category(session: AsyncSession,
                                           user: User, _, event):
    """Handle edit_category expectation."""
    uuid = bytes.fromhex(user.expectation["expect"]["data"])
    raw_text = event.raw_text

    if raw_text == "":
        await event.respond(_("got_empty_message_for_category"))
        return
    if " " in raw_text or "\n" in raw_text:
        await event.respond(_("mutiple_word_category_name_error"))
        return

    # name uniqueness check
    categories = await session.execute(
        select(Category).where(Category.holder == user.id).
            where(Category.is_deleted == False).
            where(Category.name == raw_text)
    )
    categories = categories.scalars().all()
    if len(categories) != 0:
        await event.respond(_("non_unique_category_name_error"))
        return

    # delete matching aliases (same name)
    await session.execute(
        delete(CategoryAlias).where(
            CategoryAlias.holder == user.id,
            CategoryAlias.alias == raw_text
        )
    )

    category = await session.execute(
        select(Category).where(Category.id == uuid)
    )
    category = category.scalar_one_or_none()
    if category:
        category.name = raw_text
        await session.commit()
        await session.refresh(category)
        await event.respond(_("category_edited_successfully").format(raw_text))
        await send_menu(session, user, _, event)

    user.expectation["expect"] = {"type": None, "data": None}
    await session.commit()


async def handle_action(session: AsyncSession, event,
                        user: User, data: list, _) -> None:
    """Handle user pressing a button under one of the action menus."""

    if data[1][1] == "d":
        uuid = bytes.fromhex(data[2])

        category = await session.execute(
            select(Category).where(Category.id == uuid)
        )
        category = category.scalar_one_or_none()
        category.is_deleted = True
        session.add(category)

        await session.execute(
            delete(CategoryAlias).where(
                CategoryAlias.category == category.id
            )
        )

        await session.commit()

        await event.edit(_("category_deleted_succesfully"))
        await send_menu(session, user, _, event)

    else:
        raise Exception(
            'Got unexpected data for callback command "action" (categories)'
        )


async def check_ownership(session: AsyncSession, user: User,
                          _, event, uuid: bytes) -> bool:
    """Check if category belongs to User, return True if so."""
    result = await session.execute(
        select(Category).where(Category.id == uuid, Category.holder == user.id)
    )
    category = result.scalar_one_or_none()

    if category and not category.is_deleted:
        return True
    elif category and category.is_deleted:
        await event.respond(_("category_action_ownership_check_got_deleted"))
    else:
        await event.respond(_("category_action_ownership_check_failed"))


async def edit_menu(session: AsyncSession, user: User, _, event,
                    uuid: bytes) -> None:
    """Send category edit menu to the user."""
    await event.delete()

    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return

    user.expectation["expect"] = {"type": "edit_category", "data": uuid.hex()}
    await session.commit()

    buttons = [
        Button.inline(_("category_action_edit_cancel"),
                      b"menu_categories")
    ]
    await event.respond(_("edit_category_prompt"), buttons=buttons)


def format_component_transaction(transaction: Transaction, _) -> str:
    """Format a transaction for category view menu."""

    # set emoji indicator
    if transaction.sum > 0: emoji_indicator = "🟩"
    elif transaction.sum < 0: emoji_indicator = "🟥"
    else: emoji_indicator = "🟨"

    return _("category_action_view_component_transaction").format(
        emoji_indicator, transaction.sum, transaction.wallet.currency,
        transaction.wallet.name 
    )


async def view_menu(session: AsyncSession, user: User, _, event,
                    uuid: bytes) -> None:
    """Send category view menu to the user."""
    MAX_TRANSACTIONS_SHOWN = 5

    await event.delete()

    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return

    category = await session.execute(
        select(Category)
        .where(Category.id == uuid)
        .where(Category.is_deleted == False)
    )
    category = category.scalar_one_or_none()

    if category is None:
        await event.respond(_("category_action_view_not_found_error"))
        return

    # TODO: optimize to only select 5 latest
    full_transactions = await session.execute(
        select(Transaction)
        .options(
            selectinload(Transaction.category),
            selectinload(Transaction.wallet)
        )
        .where(Transaction.category_id == uuid)
    )
    full_transactions = full_transactions.scalars().all()

    transactions = full_transactions[::-1]
    if len(transactions) > MAX_TRANSACTIONS_SHOWN:
        transactions = transactions[:MAX_TRANSACTIONS_SHOWN]

    formatted_created_on = datetime.utcfromtimestamp(
        category.created_at).date().isoformat()

    buttons = [
        Button.inline(_("universal_back_button"), b"menu_categories")
    ]
    if len(transactions) == 0:
        await event.respond(_("category_action_view_no_transactions").format(
            category.icon, category.name, formatted_created_on,
            category.transaction_count
        ), buttons=buttons)
        return

    transaction_component = "\n".join(
        map(lambda x: format_component_transaction(x, _), transactions))

    if len(full_transactions) > MAX_TRANSACTIONS_SHOWN:
        not_shown_count = len(full_transactions) - MAX_TRANSACTIONS_SHOWN
        transaction_component += ("\n" +
            _("universal_component_not_shown_count").format(not_shown_count))

    await event.respond(_("category_action_view").format(
        category.icon, category.name, formatted_created_on,
        category.transaction_count, transaction_component
    ), buttons=buttons)


async def delete_menu(session: AsyncSession, user: User, _, event,
                      uuid: bytes) -> None:
    """Send category delete menu to the user."""
    await event.delete()

    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return

    name = await session.execute(
        select(Category.name)
        .where(Category.id == uuid)
    )
    name = name.scalar_one_or_none()

    buttons = [
        Button.inline(_("category_action_delete_approve"),
                      "action_cd_"+uuid.hex()),
        Button.inline(_("category_action_delete_cancel"),
                      b"menu_categories")
    ]
    await event.respond(_("delete_category_prompt").format(name),
                        buttons=buttons)


async def send_menu(session: AsyncSession, user: User, _, event) -> None:
    """Send categories menu to the user."""

    categories = await session.execute(
        select(Category).where(Category.holder == user.id).
            where(Category.is_deleted == False)
    )
    categories = categories.scalars().all()
    categories = sorted(categories,
                        key=lambda x: x.transaction_count, reverse=True)

    del_categories_count = await session.execute(
        select(func.count()).select_from(Category).where(
            Category.holder == user.id,
            Category.is_deleted == True
        )
    )
    del_categories_count = del_categories_count.scalar_one()

    if len(categories) == 0:
        buttons = [
            Button.inline(_("back_to_main_menu_button"),
                        b"menu_start")
        ]
        if del_categories_count == 0:
            await event.respond(_("menu_categories_no_categories"),
                                buttons=buttons)
        else:
            await event.respond(_("menu_categories_only_deleted").format(
                del_categories_count
            ), buttons=buttons)
        return

    category_info = [_("menu_categories_component_category_info").format(
        x.name, x.id.hex()
    ) for x in categories]

    category_info_str = "\n".join(category_info)

    content = _("menu_categories_template").format(
        category_info_str, len(categories))
    if del_categories_count != 0:
        content += _("menu_categories_component_deleted_amount").format(
                del_categories_count
            )

    buttons = [
        Button.inline(_("back_to_main_menu_button"),
                      b"menu_start")
    ]
    await event.respond(content, buttons=buttons)
