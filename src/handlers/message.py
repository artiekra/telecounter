import time
import uuid

from telethon import events
from telethon.tl.custom import Button
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from translate import setup_translations
from handlers.transaction import register_transaction


async def send_language_selection(event: events.NewMessage.Event) -> None:
    """Send language selection msg with inline buttons."""
    buttons = [
        [Button.inline("🇬🇧 English", b"lang_en")],
        [Button.inline("🇺🇦 Українська", b"lang_uk"),
         Button.inline("🇷🇺 Русский", b"lang_ru")]
    ]

    await event.reply(
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
        await event.respond(_("got_empty_message"))
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
                )
                session.add(user)
                await session.commit()

            if user.language is None:
                await send_language_selection(event)
            else:
                if event.raw_text.startswith("/"):
                    await handle_command(session, user, _, event)
                else:
                    await handle_transaction(session, user, _, event)
