from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import User, Category


async def edit_menu(session: AsyncSession, user: User, _, event,
                    uuid: bytes) -> None:
    """Send category edit menu to the user."""
    await event.delete()

    await event.respond(f"category edit, for {uuid.hex()}")


async def view_menu(session: AsyncSession, user: User, _, event,
                    uuid: bytes) -> None:
    """Send category view menu to the user."""
    await event.delete()

    await event.respond(f"category view, for {uuid.hex()}")


async def delete_menu(session: AsyncSession, user: User, _, event,
                    uuid: bytes) -> None:
    """Send category delete menu to the user."""
    await event.delete()

    await event.respond(f"category delete, for {uuid.hex()}")


async def send_menu(session: AsyncSession, user: User, _, event) -> None:
    """Send categories menu to the user."""

    categories = await session.execute(
        select(Category).where(Category.holder == user.id)
    )
    categories = categories.scalars().all()
    categories = sorted(categories,
                        key=lambda x: x.transaction_count, reverse=True)

    if len(categories) == 0:
        await event.respond(_("menu_categories_no_categories"))
        return

    category_info = [_("menu_categories_component_category_info").format(
        x.name, x.id.hex()
    ) for x in categories]

    category_info_str = "\n".join(category_info)

    await event.respond(_("menu_categories_template").format(
        category_info_str, len(categories)))
