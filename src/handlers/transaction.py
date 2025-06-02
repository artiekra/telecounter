from typing import Optional

from thefuzz import process
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from telethon.tl.custom import Button

from database.models import User, Category, Wallet


async def find_category_by_name(
    session: AsyncSession,
    user: User,
    input_name: str,
    threshold: int = 80
) -> Optional[bytes]:
    """Fuzzy search for a category UUID for a given user by name."""
    result = await session.execute(
        select(Category).where(Category.holder == user.id)
    )
    categories = result.scalars().all()

    if not categories:
        return None

    choices = {category.name: category.id for category in categories}
    match = process.extractOne(input_name, choices.keys())

    if match and match[1] >= threshold:
        return choices[match[0]]
    return None


async def find_wallet_by_name(
    session: AsyncSession,
    user: User,
    input_name: str,
    threshold: int = 80
) -> Optional[bytes]:
    """Fuzzy search for a wallet UUID for a given user by name."""
    result = await session.execute(
        select(Wallet).where(Wallet.holder == user.id)
    )
    wallets = result.scalars().all()

    if not wallets:
        return None

    choices = {wallet.name: wallet.id for wallet in wallets}
    match = process.extractOne(input_name, choices.keys())

    if match and match[1] >= threshold:
        return choices[match[0]]
    return None


async def create_category(
    session: AsyncSession,
    user: User,
    _,
    event,
    name: str
) -> None:
    """Prompt user for creation of a new category."""
    user.expectation["expect"] = {"type": "new_category", "data": name}
    await session.commit()

    buttons = [
        Button.inline(_("create_new_category_prompt_approve"),
                      b"category_approve"),
        Button.inline(_("create_new_category_prompt_cancel"),
                      b"category_cancel")
    ]
    await event.respond(_("create_new_category_prompt").format(name),
                        buttons=buttons)


async def create_wallet(
    session: AsyncSession,
    user: User,
    _,
    event,
    name: str
) -> None:
    """Prompt user for creation of a new wallet."""

    await event.reply("creating new wallet..")


async def register_transaction(
    session: AsyncSession,
    user: User,
    _,
    event,
    data: list
) -> None:
    """Register transaction in the db, handle creating new category/wallet."""
    sum, category, wallet = data

    category_id = await find_category_by_name(session, user, category)
    if category_id is None:
        user.expectation["transaction"] = data
        await session.commit()
        await create_category(session, user, _, event, category)
        return

    wallet_id = await find_wallet_by_name(session, user, wallet)
    if wallet_id is None:
        user.expectation["transaction"] = data
        await session.commit()
        await create_wallet(session, user, _, event, wallet)
        return

    await event.reply(" ".join(map(str, [sum, category_id, wallet_id])))
