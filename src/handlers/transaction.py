from typing import Optional

from thefuzz import process
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import User, Category, Wallet


async def find_category_by_name(
    session: AsyncSession,
    telegram_id: int,
    input_name: str,
    threshold: int = 80
) -> Optional[bytes]:
    """Find category UUID for a user by fuzzy name match using Telegram ID."""
    
    # get the user by telegram ID
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if not user:  # TODO: maybe throw some different kind of error?
        return None

    # get all their categories
    result = await session.execute(
        select(Category).where(Category.holder == user.id)
    )
    categories = result.scalars().all()

    if not categories:
        return None

    # prepare name → uuid mapping
    choices = {category.name: category.id for category in categories}

    # fuzzy match
    match, score = process.extractOne(input_name, choices.keys())

    if score >= threshold:
        return choices[match]
    return None


# TODO: for cleaner code, combine this func with find_category_by_name?
async def find_wallet_by_name(
    session: AsyncSession,
    telegram_id: int,
    input_name: str,
    threshold: int = 80
) -> Optional[bytes]:
    """Find wallet UUID for a user by fuzzy name match using Telegram ID."""
    
    # get the user by telegram ID
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if not user:  # TODO: maybe throw some different kind of error?
        return None

    # get all their wallets
    result = await session.execute(
        select(Wallet).where(Wallet.holder == user.id)
    )
    wallets = result.scalars().all()

    if not wallets:
        return None

    # prepare name → uuid mapping
    choices = {wallet.name: wallet.id for wallet in wallets}

    # fuzzy match
    match, score = process.extractOne(input_name, choices.keys())

    if score >= threshold:
        return choices[match]
    return None


async def register_transaction(
    session: AsyncSession,
    user: User,
    _,
    event,
    data: list
) -> None:
    """Register transaction in the db, handle creating new category/wallet."""
    sum, category, wallet = data

    category_id = await find_category_by_name(
        session, event.sender_id, category)
    if category_id is None:
        await event.reply("no category found")

    wallet_id = await find_wallet_by_name(
        session, event.sender_id, wallet)
    if wallet_id is None:
        await event.reply("no wallet found")

    await event.reply(" ".join(map(str, [sum, category_id, wallet_id])))
