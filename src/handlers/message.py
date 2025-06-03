import time
import uuid

from telethon import events
from telethon.tl.custom import Button
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, Wallet
from translate import setup_translations
from handlers.transaction import register_transaction, create_category


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


# TODO: on /start, send some info about balances, some overview..
async def handle_command_start(session: AsyncSession, user: User,
                               _, event) -> None:
    """Handle /start command"""
    await event.respond(_("command_start"))


async def handle_command_help(session: AsyncSession, user: User,
                               _, event) -> None:
    """Handle /help command"""
    await event.respond(_("command_help"))


# TODO: put support username into config, make it optional
async def handle_unknown_command(session: AsyncSession, user: User,
                                 _, event) -> None:
    """Handle unknown commands"""
    command = event.raw_text.split()[0]

    await event.respond(_("unknown_command").format(
        command, "@support"
    ))


COMMANDS = {"start": handle_command_start, "help": handle_command_help}

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
    await session.commit()
    await session.refresh(new_wallet)

    await event.respond(_("wallet_created_successfully"))

    user.expectation["expect"] = {"type": None, "data": None}
    await session.commit()

    current_transaction = user.expectation["transaction"]
    if current_transaction is not None:
        # await event.respond(_("transaction_handling_in_process").format(
        #     " ".join(map(str, current_transaction))
        # ))
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
    init_sum = parts[1] if len(parts) > 1 else None
    name = parts[2] if len(parts) > 2 else user.expectation["expect"]["data"]

    data = [name, currency, init_sum]

    await register_new_wallet(session, event, user, data, _)


async def handle_expectation(session: AsyncSession, user: User, _, event):
    """Handle bot flow if data is expected from user."""
    expect = user.expectation["expect"]
    raw_text = event.raw_text

    if expect["type"] == "new_category":
        if raw_text == "":
            await event.respond(_("got_empty_message_for_category"))
            return
        if " " in raw_text or "\n" in raw_text:
            await event.respond(_("mutiple_word_category_name_error"))
            return
        await create_category(session, user, _, event, raw_text)

    elif expect["type"] == "new_wallet":
        await handle_expectation_new_wallet(session, user, _, event)

    else:
        raise Error("Got unexpected expectation type")


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
                        "expect": {"type": None, "data": None}}
                )
                session.add(user)
                await session.commit()

            if user.language is None:
                await send_language_selection(event)
                return

            if event.raw_text.startswith("/"):
                user.expectation["expect"] = {"type": None, "data": None}
                await session.commit()
                await handle_command(session, user, _, event)
                return

            if user.expectation["expect"]["type"] is None:
                await handle_transaction(session, user, _, event)
                return

            await handle_expectation(session, user, _, event)
