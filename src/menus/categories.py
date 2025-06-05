from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from telethon.tl.custom import Button

from database.models import User, Category, CategoryAlias


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
        await session.commit()

        await event.edit(_("category_deleted_succesfully"))

    else:
        raise Exception(
            'Got unexpected data for callback command "action" (categories)'
        )


async def check_ownership(session: AsyncSession, user: User,
                          uuid: bytes) -> bool:
    """Check if category belongs to User, return True if so."""
    result = await session.execute(
        select(Category).where(Category.id == uuid, Category.holder == user.id)
    )
    category = result.scalar_one_or_none()

    if category:
        return True

    await event.respond(_("category_action_ownership_check_failed"))


async def edit_menu(session: AsyncSession, user: User, _, event,
                    uuid: bytes) -> None:
    """Send category edit menu to the user."""
    await event.delete()

    is_owner = await check_ownership(session, user, uuid)
    if not is_owner:
        return

    user.expectation["expect"] = {"type": "edit_category", "data": uuid.hex()}
    await session.commit()

    buttons = [
        Button.inline(_("category_action_edit_cancel"),
                      b"menu_categories")
    ]
    await event.respond(_("edit_category_prompt"), buttons=buttons)


async def view_menu(session: AsyncSession, user: User, _, event,
                    uuid: bytes) -> None:
    """Send category view menu to the user."""
    await event.delete()

    is_owner = await check_ownership(session, user, uuid)
    if not is_owner:
        return

    await event.respond(f"category view, for {uuid.hex()}")


async def delete_menu(session: AsyncSession, user: User, _, event,
                      uuid: bytes) -> None:
    """Send category delete menu to the user."""
    await event.delete()

    is_owner = await check_ownership(session, user, uuid)
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
        if del_categories_count == 0:
            await event.respond(_("menu_categories_no_categories"))
        else:
            await event.respond(_("menu_categories_only_deleted").format(
                del_categories_count
            ))
        return

    category_info = [_("menu_categories_component_category_info").format(
        x.name, x.id.hex()
    ) for x in categories]

    category_info_str = "\n".join(category_info)
    if del_categories_count != 0:
        category_info_str += "\n" +\
            _("menu_categories_component_deleted_amount").format(
                del_categories_count
            )

    await event.respond(_("menu_categories_template").format(
        category_info_str, len(categories)))
