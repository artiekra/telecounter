import time
from typing import Optional

from thefuzz import process
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from telethon.tl.custom import Button

from database.models import (User, Category, Wallet,
    Transaction, TransactionType)


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
    user.expectation["expect"] = {"type": "new_wallet", "data": name}
    await session.commit()

    await event.respond(_("create_new_wallet_prompt").format(name))


async def register_transaction(
    session: AsyncSession,
    user: User,
    _,
    event,
    data: list
) -> None:
    """Register transaction in the db, handle creating new category/wallet."""
    amount, category, wallet = data

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

    new_transaction = Transaction(
        holder=user.id,
        datetime=int(time.time()),
        type=TransactionType.INCOME,
        wallet_id=wallet_id,
        category_id=category_id,
        sum=amount
    )

    wallet = await session.execute(
        select(Wallet).where(Wallet.id == wallet_id)
    )
    wallet = wallet.scalar_one_or_none()

    if wallet:
        wallet.current_sum += amount
        wallet.transaction_count += 1

    session.add(new_transaction, wallet)
    await session.commit()

    category = await session.execute(
        select(Category).where(Category.id == category_id)
    )
    category = category.scalar_one_or_none()

    wallet_total = wallet.init_sum + wallet.current_sum
    await event.reply(_("transaction_registered").format(
        *map(str, [amount, category.name, wallet.name,
                   wallet_total, wallet.currency])
    ))
