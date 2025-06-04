import time
from typing import Optional

from thefuzz import process
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from telethon.tl.custom import Button

from database.models import (User, Category, Wallet,
    Transaction, TransactionType, CategoryAlias, WalletAlias)


async def find_category_by_name(
    session: AsyncSession,
    user: User,
    input_name: str,
    threshold: int = 75
) -> Optional[bytes]:
    """Find category UUID for a user by fuzzy match or alias name."""

    # check aliases for exact match
    result = await session.execute(
        select(CategoryAlias)
        .where(CategoryAlias.holder == user.id)
        .where(CategoryAlias.alias.ilike(input_name))
    )
    alias = result.scalar_one_or_none()
    if alias:
        return ("exact", alias.category)

    # get all categories
    result = await session.execute(
        select(Category).where(Category.holder == user.id)
    )
    categories = result.scalars().all()

    if not categories:
        return ("none",)

    # fuzzy match category names
    choices = {category.name: category.id for category in categories}
    match = process.extractOne(input_name, choices.keys())

    if match and match[1] >= threshold:
        if match[1] == 100:
            return ("exact", choices[match[0]])
        return ("fuzzy", choices[match[0]])

    return ("none",)


async def find_wallet_by_name(
    session: AsyncSession,
    user: User,
    input_name: str,
    threshold: int = 75
) -> Optional[bytes]:
    """Find wallet UUID for a user by alias or fuzzy name match."""

    # check aliases for exact match
    result = await session.execute(
        select(WalletAlias)
        .where(WalletAlias.holder == user.id)
        .where(WalletAlias.alias.ilike(input_name))
    )
    alias = result.scalar_one_or_none()
    if alias:
        return ("exact", alias.wallet)

    # get all wallets
    result = await session.execute(
        select(Wallet).where(Wallet.holder == user.id)
    )
    wallets = result.scalars().all()

    if not wallets:
        return ("none",)

    # fuzzy match wallet names
    choices = {wallet.name: wallet.id for wallet in wallets}
    match = process.extractOne(input_name, choices.keys())

    if match and match[1] >= threshold:
        if match[1] == 100:
            return ("exact", choices[match[0]])
        return ("fuzzy", choices[match[0]])

    return ("none",)


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
        Button.inline(_("create_prompt_approve"),
                      b"category_approve"),
        Button.inline(_("create_prompt_cancel"),
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

    buttons = [
        Button.inline(_("create_prompt_cancel"),
                      b"wallet_cancel")
    ]
    await event.respond(_("create_new_wallet_prompt").format(name),
                        buttons=buttons)


async def create_category_alias(
    session: AsyncSession,
    user: User,
    _,
    event,
    name: str,
    prediction_id
) -> None:
    """Prompt user about the correctness of fuzzy match for category name."""
    result = await session.execute(
        select(Category.name)
        .where(Category.id == prediction_id)
    )
    prediction_name = result.scalar_one_or_none()

    user.expectation["expect"] = {"type": "new_category_alias",
        "data": [name, prediction_id.hex(), prediction_name]}

    buttons = [
        Button.inline(_("create_alias_prompt_approve"),
                        b"categoryalias_approve"),
        Button.inline(_("create_alias_prompt_new"),
                        b"categoryalias_new"),
        Button.inline(_("create_alias_prompt_cancel"),
                        b"categoryalias_cancel")
    ]

    prompt = await event.respond(_("create_new_category_alias_prompt").format(
        name, prediction_name), buttons=buttons)

    user.expectation["message"] = prompt.id
    await session.commit()


async def create_wallet_alias(
    session: AsyncSession,
    user: User,
    _,
    event,
    name: str,
    prediction_id
) -> None:
    """Prompt user about the correctness of fuzzy match for wallet name."""
    result = await session.execute(
        select(Wallet.name)
        .where(Wallet.id == prediction_id)
    )
    prediction_name = result.scalar_one_or_none()

    user.expectation["expect"] = {"type": "new_wallet_alias",
        "data": [name, prediction_id.hex(), prediction_name]}

    buttons = [
        Button.inline(_("create_alias_prompt_approve"),
                        b"walletalias_approve"),
        Button.inline(_("create_alias_prompt_new"),
                        b"walletalias_new"),
        Button.inline(_("create_alias_prompt_cancel"),
                        b"walletalias_cancel")
    ]

    prompt = await event.respond(_("create_new_wallet_alias_prompt").format(
        name, prediction_name), buttons=buttons)

    user.expectation["message"] = prompt.id
    await session.commit()


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
    wallet_id = await find_wallet_by_name(session, user, wallet)

    # ask about possible typos
    if category_id[0] == "fuzzy":
        user.expectation["transaction"] = data
        await session.commit()
        await create_category_alias(session, user, _, event,
                                    category, category_id[1])
        return
    if wallet_id[0] == "fuzzy":
        user.expectation["transaction"] = data
        await session.commit()
        await create_wallet_alias(session, user, _, event,
                                  wallet, wallet_id[1])
        return

    # create category/wallet if neccesarry
    if category_id[0] == "none":
        user.expectation["transaction"] = data
        await session.commit()
        await create_category(session, user, _, event, category)
        return
    if wallet_id[0] == "none":
        user.expectation["transaction"] = data
        await session.commit()
        await create_wallet(session, user, _, event, wallet)
        return

    new_transaction = Transaction(
        holder=user.id,
        datetime=int(time.time()),
        type=TransactionType.INCOME,
        wallet_id=wallet_id[1],
        category_id=category_id[1],
        sum=amount
    )

    wallet = await session.execute(
        select(Wallet).where(Wallet.id == wallet_id[1])
    )
    wallet = wallet.scalar_one_or_none()

    if wallet:
        wallet.current_sum += amount
        wallet.transaction_count += 1

    category = await session.execute(
        select(Category).where(Category.id == category_id[1])
    )
    category = category.scalar_one_or_none()

    if category:
        category.transaction_count += 1

    session.add_all([new_transaction, wallet, category])
    await session.commit()

    wallet_total = wallet.init_sum + wallet.current_sum
    await event.reply(_("transaction_registered").format(
        *map(str, [amount, category.name, wallet.name,
                   wallet_total, wallet.currency])
    ))
