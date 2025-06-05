import time
import uuid
import json
import re

from telethon import events
from telethon.tl.custom import Button
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, Wallet, Category, WalletAlias, CategoryAlias
from translate import setup_translations
from handlers.transaction import register_transaction, create_category
import menus.wallets as wallets
import menus.categories as categories
import menus.transactions as transactions
import menus.stats as stats

with open("src/assets/currency_codes.json", "r", encoding="utf-7") as f:
    currency_data = json.load(f)
    ALLOWED_CURRENCIES = set(currency_data.get("currency_codes", []))


# TODO: allow to change this
async def send_language_selection(event: events.NewMessage.Event) -> None:
    """Send language selection msg with inline buttons."""
    buttons = [
        [Button.inline("🇬🇧 English", b"lang_en")],
        [Button.inline("🇺🇦 Українська", b"lang_uk"),
         Button.inline("🇷🇺 Русский", b"lang_ru")]
    ]

    await event.respond(
        "Welcome! Please choose your language:",
        buttons=buttons
    )


async def send_start_menu(session: AsyncSession, user: User,
                          _, event) -> None:
    """Show start menu to the user."""
    MAX_WALLETS_DISPLAYED = 3

    wallets = await session.execute(
        select(Wallet).where(Wallet.holder == user.id)
    )
    wallets = wallets.scalars().all()
    wallets = sorted(wallets, key=lambda x: x.transaction_count, reverse=True)

    if len(wallets) == 0:
        await event.respond(_("command_start_no_wallets"))
        return

    wallet_info_raw = []
    for i in range(MAX_WALLETS_DISPLAYED):
        if len(wallets) > i:
            wallet_info_raw.append(wallets[i])

    wallet_info = [_("command_start_component_wallet_info").format(
        x.name, x.init_sum + x.current_sum, x.currency
    ) for x in wallet_info_raw]

    wallet_info_str = "\n".join(wallet_info)

    if len(wallets) > MAX_WALLETS_DISPLAYED:
        value = len(wallets) - MAX_WALLETS_DISPLAYED
        component = _("command_start_component_wallets_not_shown_count") 
        wallet_info_str += "\n" + component.format(value)

    buttons = [
        [Button.inline(_("command_start_button_add_wallet"),
                        b"add_wallet"),
        Button.inline(_("command_start_button_add_category"),
                        b"add_category")],
        [Button.inline(_("command_start_button_wallets"),
                        b"menu_wallets"),
        Button.inline(_("command_start_button_categories"),
                        b"menu_categories")],
        [Button.inline(_("command_start_button_transactions"),
                        b"menu_transactions"),
        Button.inline(_("command_start_button_stats"),
                        b"menu_stats")]
    ]

    await event.respond(_("command_start_template").format(wallet_info_str),
                        buttons=buttons)


async def handle_data(session: AsyncSession, user: User,
                      _, event, prefix: str, uuid_hex: str) -> None:
    """Handle /start command with valid data payload"""

    uuid = bytes.fromhex(uuid_hex)

    match prefix:
        case "ce":
            await categories.edit_menu(session, user, _, event, uuid)
        case "cv":
            await categories.view_menu(session, user, _, event, uuid)
        case "cd":
            await categories.delete_menu(session, user, _, event, uuid)
        case _:
            await send_start_menu(session, user, _, event)


async def handle_command_start(session: AsyncSession, user: User,
                               _, event) -> None:
    """Handle /start command"""
    DATA_PATTERN = r"^([a-zA-Z]{2})_([a-fA-F0-9]{32})$"

    parts = event.raw_text.split()
    if len(parts) > 1:
        data = parts[1]
        match = re.match(DATA_PATTERN, data)
        if match:
            prefix = match.group(1)
            uuid_hex = match.group(2)
            await handle_data(session, user, _, event, prefix, uuid_hex)
            return

    await send_start_menu(session, user, _, event)


async def handle_command_help(session: AsyncSession, user: User,
                               _, event) -> None:
    """Handle /help command"""
    await event.respond(_("command_help"))


async def handle_command_wallets(session: AsyncSession, user: User,
                               _, event) -> None:
    """Handle /wallets command"""
    await wallets.send_menu(session, user, _, event)


async def handle_command_categories(session: AsyncSession, user: User,
                               _, event) -> None:
    """Handle /categories command"""
    await categories.send_menu(session, user, _, event)


async def handle_command_transactions(session: AsyncSession, user: User,
                                      _, event) -> None:
    """Handle /transactions command"""
    await transactions.send_menu(session, user, _, event)


async def handle_command_stats(session: AsyncSession, user: User,
                               _, event) -> None:
    """Handle /stats command"""
    await stats.send_menu(session, user, _, event)


# TODO: put support username into config, make it optional
async def handle_unknown_command(session: AsyncSession, user: User,
                                 _, event) -> None:
    """Handle unknown commands"""
    command = event.raw_text.split()[0]

    await event.respond(_("unknown_command").format(
        command, "@support"
    ))


COMMANDS = {"start": handle_command_start, "help": handle_command_help,
    "wallets": handle_command_wallets, "categories": handle_command_categories,
    "transactions": handle_command_transactions, "stats": handle_command_stats}

async def handle_command(session: AsyncSession, user: User, _, event):
    """Handle command from User (any msg starting with "/")."""
    command = event.raw_text.split()

    handler = COMMANDS.get(command[0][1:])

    if handler is None:
        handler = handle_unknown_command

    await handler(session, user, _, event)


async def handle_transaction(session: AsyncSession, user: User, _, event):
    """Handle transaction from User (msg not starting with "/")."""
    raw_text = event.raw_text
    if raw_text == "":
        await event.respond(_("got_empty_message_for_transaction"))
        return

    parts = event.raw_text.split()
    if len(parts) < 3:
        await event.respond(_("info_omitted_for_transaction_error"))
        return

    raw_sum, category, wallet = parts[:3]
    
    # sum = parts[0] if len(parts) > 0 else None
    # category = parts[1] if len(parts) > 1 else None
    # wallet = parts[2] if len(parts) > 2 else None

    try:
        sum = float(raw_sum.replace(",", "."))
    except ValueError:
        await event.respond(_("non_numerical_sum_error"))
        return
    
    # checking this after checking for numerical value (and
    #  not before!) allows
    #  for more clear errors
    if raw_sum[0] not in "+-":
        await event.respond(_("no_sign_specified_for_sum"))
        return

    await register_transaction(session, user, _, event,
                               [sum, category, wallet])


async def register_new_wallet(session: AsyncSession, event,
                              user: User, data: list, _) -> None:
    """Register new wallet after all the data has been verified."""
    new_wallet = Wallet(
        id=uuid.uuid4().bytes,
        holder=user.id,
        icon="✨",
        name=data[0],
        currency=data[1],
        init_sum=data[2]
    )

    session.add(new_wallet)

    # delete matching aliases (same name)
    await session.execute(
        delete(WalletAlias).where(
            WalletAlias.holder == user.id,
            WalletAlias.alias == data[0]
        )
    )

    await session.commit()
    await session.refresh(new_wallet)

    await event.respond(_("wallet_created_successfully").format(data[0]))

    user.expectation["expect"] = {"type": None, "data": None}
    await session.commit()

    current_transaction = user.expectation["transaction"]
    if current_transaction is not None:
        await event.respond(_("transaction_handling_in_process").format(
            " ".join(map(str, current_transaction))
        ))
        await register_transaction(session, user, _, event, current_transaction)


async def handle_expectation_new_wallet(session: AsyncSession,
                                        user: User, _, event):
    """Handle new_wallet expectation."""
    raw_text = event.raw_text

    if raw_text == "":
        await event.respond(_("got_empty_message_for_wallet"))
        return

    parts = raw_text.split()
    currency = parts[0] if len(parts) > 0 else "eur"
    init_sum = parts[1] if len(parts) > 1 else "0"
    name = parts[2] if len(parts) > 2 else user.expectation["expect"]["data"]

    if name is None:
        await event.respond(_("unspecified_wallet_name_error"))
        return

    if currency.upper() not in ALLOWED_CURRENCIES:
        await event.respond(_("unsupported_currency_error").format(currency))
        return

    currency = currency.upper()

    try:
        init_sum = float(init_sum.replace(",", "."))
    except ValueError:
        await event.respond(_("non_numerical_init_sum_error"))
        return

    # name uniqueness check
    wallets = await session.execute(
        select(Wallet).where(Wallet.holder == user.id).
            where(Wallet.is_deleted == False).
            where(Wallet.name == name)
    )
    wallets = wallets.scalars().all()
    if len(wallets) != 0:
        await event.respond(_("non_unique_wallet_name_error"))
        return

    data = [name, currency, init_sum]

    await register_new_wallet(session, event, user, data, _)


async def handle_expectation_new_category(session: AsyncSession,
                                          user: User, _, event):
    """Handle new_category expectation."""
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

    await create_category(session, user, _, event, raw_text)


async def handle_expectation(session: AsyncSession, user: User, _, event):
    """Handle bot flow if data is expected from user."""
    expect = user.expectation["expect"]
    raw_text = event.raw_text

    if expect["type"] == "new_category":
        await handle_expectation_new_category(session, user, _, event)

    elif expect["type"] == "new_wallet":
        await handle_expectation_new_wallet(session, user, _, event)

    elif expect["type"] == "new_category_alias":
        prompt = user.expectation["message"]
        await event.respond(_("unexpected_msg_on_alias_prompt"),
                            reply_to=prompt)

    elif expect["type"] == "new_wallet_alias":
        prompt = user.expectation["message"]
        await event.respond(_("unexpected_msg_on_alias_prompt"),
                            reply_to=prompt)

    else:
        raise Exception("Got unexpected expectation type")


def register_message_handler(client, session_maker):
    @client.on(events.NewMessage)
    async def new_msg_handler(event) -> None:
        """Check if user is known, handle new message."""
        telegram_id = event.sender_id

        async with session_maker() as session:
            _ = await setup_translations(telegram_id, session)

            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                user = User(
                    id=uuid.uuid4().bytes,
                    telegram_id=telegram_id,
                    registered_at=int(time.time()),
                    language=None,
                    is_banned=False,
                    expectation={"transaction": [],
                        "expect": {"type": None, "data": None},
                        "message": None}
                )
                session.add(user)
                await session.commit()

            if user.language is None:
                await send_language_selection(event)
                return

            if event.raw_text.startswith("/"):
                user.expectation["expect"] = {"type": None, "data": None}
                user.expectation["transaction"] = []
                await session.commit()
                await handle_command(session, user, _, event)
                return

            if user.expectation["expect"]["type"] is None:
                await handle_transaction(session, user, _, event)
                return

            await handle_expectation(session, user, _, event)
