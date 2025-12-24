import os
import csv
import math
from io import StringIO, BytesIO
from datetime import datetime, date, timezone
from dateutil import parser

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func, delete, update, desc
from telethon.tl.custom import Button

from database.models import User, Transaction, Wallet, Category
from handlers.transaction import register_transaction


def parse_time(s: str) -> float|None:
    """Parse flexible UTC date/time string and return Unix timestamp."""
    s = s.strip()
    try:
        dt = parser.parse(s, dayfirst=True, fuzzy=False)
    except parser.ParserError:
        return None
    
    # if its just a time (no date part), use today
    if dt.date() == datetime.now().date() and all(x not in s for x in ['-', '.', '/']):
        dt = datetime.combine(date.today(), dt.time())
    
    # ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    
    return dt.timestamp()


async def delete_transaction(session, uuid):
    """Deletes a transaction by UUID and adjusts Wallet data"""

    stmt = (
        select(Transaction)
        .where(Transaction.id == uuid)
        .options(selectinload(Transaction.wallet))
    )
    txn_result = await session.execute(stmt)
    old_transaction = txn_result.scalar_one_or_none()

    if old_transaction and old_transaction.wallet:
        old_transaction.wallet.current_sum -= old_transaction.sum
        old_transaction.wallet.transaction_count -= 1
        
        await session.delete(old_transaction)

    await session.commit()


async def handle_expectation_edit_transaction(session: AsyncSession,
                                              user: User, _, event):
    """Handle edit_transaction expectation."""
    uuid = bytes.fromhex(user.expectation["expect"]["data"])
    raw_text = event.raw_text

    if raw_text == "":
        await event.respond(_("got_empty_message_for_transaction"))
        return

    old_txn_result = await session.execute(
        select(Transaction).where(Transaction.id == uuid)
    )
    old_transaction = old_txn_result.scalar_one_or_none()

    if not old_transaction:
        await event.respond(_("transaction_action_view_not_found_error"))
        return
    
    saved_datetime = old_transaction.datetime

    parts = event.raw_text.split()
    if len(parts) < 3:
        await event.respond(_("info_omitted_for_transaction_error"))
        return

    raw_sum, category, wallet = parts[:3]
    
    try:
        sum_val = float(raw_sum.replace(",", "."))
    except ValueError:
        await event.respond(_("non_numerical_sum_error"))
        return
    
    if raw_sum[0] not in "+-":
        await event.respond(_("no_sign_specified_for_sum"))
        return

    result = await register_transaction(
        session, user, _, event,
        [sum_val, category, wallet], 
        True,
        custom_datetime=saved_datetime 
    )

    if result:
        await delete_transaction(session, uuid)


async def handle_expectation_reschedule_transaction(session: AsyncSession,
                                                    user: User, _, event):
    """Handle reschedule_transaction expectation."""
    uuid = bytes.fromhex(user.expectation["expect"]["data"])
    raw_text = event.raw_text

    if raw_text == "":
        await event.respond(_("got_empty_message_for_transaction_time"))
        return

    new_timestamp = parse_time(raw_text)
    if new_timestamp is None:
        await event.respond(_("could_not_parse_transaction_time"))
        return

    new_timestamp_formatted = datetime.fromtimestamp(
        new_timestamp, tz=timezone.utc
    ).strftime("%Y-%m-%d, %H:%M UTC")

    await session.execute(
        update(Transaction).
        where(Transaction.id == uuid).
        values(datetime=new_timestamp)
    )
    await session.commit()

    buttons = [
        Button.inline(_("universal_back_button"), b"menu_transactions")
    ]
    await event.reply(_("transaction_rescheduled").format(
        *map(str, [new_timestamp_formatted])
    ), buttons=buttons)


async def export(session: AsyncSession, event, user: User, _ ):
    """Handle export callback - send back user transactions as csv."""
    await event.respond(_("export_started"))

    result = await session.execute(
        select(Transaction).where(Transaction.holder == user.id)
        .options(
            selectinload(Transaction.wallet),
            selectinload(Transaction.category)
        )
    )
    transactions = result.scalars().all()

    # prepare csv in memory
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["created_at", "wallet", "category", "sum", "currency"])

    for transaction in transactions:

        created_at = datetime.utcfromtimestamp(transaction.datetime).isoformat()

        writer.writerow([
            created_at,
            transaction.wallet.name,
            transaction.category.name,
            transaction.sum,
            transaction.wallet.currency
        ])

    # convert to bytes for sending
    csv_bytes = BytesIO(csv_buffer.getvalue().encode("utf-8"))

    today = datetime.utcnow().strftime("%Y-%m-%d")
    csv_bytes.name = f"export_transactions_{today}.csv"

    await event.respond(_("export_transactions_caption"), file=csv_bytes)


async def handle_action(session: AsyncSession, event,
                        user: User, data: list, _) -> None:
    """Handle user pressing a button under one of the action menus."""

    if data[1][1] == "d":
        uuid = bytes.fromhex(data[2])

        await delete_transaction(session, uuid)

        await event.edit(_("transaction_deleted_succesfully"))
        await send_menu(session, user, _, event)

    else:
        raise Exception(
            'Got unexpected data for callback command "action" (transactions)'
        )


async def check_ownership(session: AsyncSession, user: User,
                          _, event, uuid: bytes) -> bool:
    """Check if transaction belongs to User, return True if so."""
    result = await session.execute(
        select(Transaction).where(Transaction.id == uuid,
                                  Transaction.holder == user.id)
    )
    transaction = result.scalar_one_or_none()

    if transaction:
        return True
    else:
        await event.respond(_("transaction_action_ownership_check_failed"))


async def view_menu(session: AsyncSession, user: User, _, event,
                    uuid: bytes) -> None:
    """Send transaction view menu to the user."""
    await event.delete()

    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return

    transaction = await session.execute(
        select(Transaction)
        .where(Transaction.id == uuid)
        .options(
            selectinload(Transaction.wallet),
            selectinload(Transaction.category)
        )
    )
    transaction = transaction.scalar_one_or_none()

    if transaction is None:
        await event.respond(_("transaction_action_view_not_found_error"))
        return

    formatted_datetime = datetime.fromtimestamp(
        transaction.datetime, tz=timezone.utc
    ).strftime("%Y-%m-%d, %H:%M UTC")

    # set emoji indicator
    if transaction.sum > 0: emoji_indicator = "🟩"
    elif transaction.sum < 0: emoji_indicator = "🟥"
    else: emoji_indicator = "🟨"

    buttons = [
        Button.inline(_("universal_back_button"), b"menu_transactions")
    ]
    await event.respond(_("transaction_action_view").format(
        os.getenv("BOT_USERNAME"),
        emoji_indicator, transaction.sum, transaction.wallet.currency,
        formatted_datetime, transaction.wallet.name, transaction.category.name,
        transaction.wallet.id.hex(), transaction.category.id.hex()
    ), buttons=buttons)
    return


async def edit_menu(session: AsyncSession, user: User, _, event,
                    uuid: bytes) -> None:
    """Send transaction edit menu to the user."""
    await event.delete()

    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return

    user.expectation["expect"] = {"type": "edit_transaction", "data": uuid.hex()}
    await session.commit()

    buttons = [
        Button.inline(_("transaction_action_edit_cancel"),
                      b"menu_transactions")
    ]
    await event.respond(_("edit_transaction_prompt"), buttons=buttons)


async def reschedule_menu(session: AsyncSession, user: User, _, event,
                          uuid: bytes) -> None:
    """Send transaction rescheduling menu to the user."""
    await event.delete()

    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return

    user.expectation["expect"] = {"type": "reschedule_transaction",
                                  "data": uuid.hex()}
    await session.commit()

    buttons = [
        Button.inline(_("transaction_action_reschedule_cancel"),
                      b"menu_transactions")
    ]
    await event.respond(_("reschedule_transaction_prompt"), buttons=buttons)


async def delete_menu(session: AsyncSession, user: User, _, event,
                      uuid: bytes) -> None:
    """Send transaction delete menu to the user."""
    await event.delete()

    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return

    buttons = [
        Button.inline(_("transaction_action_delete_approve"),
                      "action_td_"+uuid.hex()),
        Button.inline(_("transaction_action_delete_cancel"),
                      b"menu_transactions")
    ]
    await event.respond(_("delete_transaction_prompt"),
                        buttons=buttons)


async def send_menu(session: AsyncSession, user: User, _,
                    event, page: int = 1, original_msg: int = None) -> None:
    """Send transactions menu to the user."""
    TRANSACTIONS_PER_PAGE = 14

    # TODO: include pagination into a query
    transactions = await session.execute(
        select(Transaction).where(Transaction.holder == user.id)
        .options(
            selectinload(Transaction.wallet),
            selectinload(Transaction.category)
        )
        .order_by(Transaction.datetime.desc())
    )
    transactions = transactions.scalars().all()

    transactions_count = len(transactions)

    if len(transactions) == 0:
        buttons = [
            Button.inline(_("back_to_main_menu_button"),
                        b"menu_start")
        ]
        await event.respond(_("menu_transactions_no_transactions"),
                            buttons=buttons)
        return

    page_count = math.ceil(len(transactions) / TRANSACTIONS_PER_PAGE)

    if page < 1: page = 1
    if page > page_count: page = page_count

    transactions = transactions[
        (page-1)*TRANSACTIONS_PER_PAGE:page*TRANSACTIONS_PER_PAGE
    ]

    transaction_info = []
    for transaction in transactions:

        # set emoji indicator
        if transaction.sum > 0: emoji_indicator = "🟩"
        elif transaction.sum < 0: emoji_indicator = "🟥"
        else: emoji_indicator = "🟨"

        new = _("menu_transactions_component_transaction_info").format(
            os.getenv("BOT_USERNAME"),
            emoji_indicator, transaction.sum, transaction.wallet.currency,
            transaction.category.name, transaction.wallet.name,
            transaction.id.hex(), transaction.category.id.hex(),
            transaction.wallet.id.hex()
        )
        transaction_info.append(new)

    transaction_info_str = "\n".join(transaction_info)

    content = _("menu_transactions_template").format(
        transaction_info_str, transactions_count)

    # get the id of newly sent message, and then add buttons according to that

    pagination_buttons = []

    if page_count > 1:
        pagination_buttons = [Button.inline("◀️", b"none"),
            Button.inline(f"{page} / {page_count}", b"none"),
            Button.inline("▶️", b"none")]

    buttons = [
        pagination_buttons,
        [Button.inline(_("export_button"), b"export_transactions"),
         Button.inline(_("back_to_main_menu_button"), b"menu_start")]
    ]
    if original_msg is None:
        message = await event.respond(content, buttons=buttons)
    else:
        message = await event.client.edit_message(
            entity=event.chat_id,
            message=original_msg,
            text=content,
            buttons=buttons
        )

    pagination_buttons = []

    if page_count > 1:
        msg_id = str(message.id).encode("utf-8").hex()
        back_button_data = "page_t_" + msg_id + "_" + str(page-1)
        main_button_data = "page_t_" + msg_id
        forward_button_data = "page_t_" + msg_id + "_" + str(page+1)
        pagination_buttons = [Button.inline("◀️", back_button_data),
            Button.inline(f"{page} / {page_count}", main_button_data),
            Button.inline("▶️", forward_button_data)]

    buttons = [
        pagination_buttons,
        [Button.inline(_("export_button"), b"export_transactions"),
         Button.inline(_("back_to_main_menu_button"), b"menu_start")]
    ]
    await message.edit(content, buttons=buttons)
