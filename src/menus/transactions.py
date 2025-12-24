import calendar
import csv
import math
import os
from datetime import date, datetime, timezone
from io import BytesIO, StringIO

from dateutil import parser
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from telethon.tl.custom import Button

from database.models import Transaction, User
from handlers.transaction import register_transaction


def parse_time(s: str) -> float | None:
    """Parse flexible UTC date/time string and return Unix timestamp."""
    s = s.strip()
    try:
        dt = parser.parse(s, dayfirst=True, fuzzy=False)
    except parser.ParserError:
        return None

    if dt.date() == datetime.now().date() and all(x not in s for x in ["-", ".", "/"]):
        dt = datetime.combine(date.today(), dt.time())

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt.timestamp()


def get_month_name(_, month_index: int) -> str:
    """Return the translated month string"""
    # this list is here so xgettext can find the strings
    # we don't actually need to use it in the logic
    _unused = [
        _("month_1"),
        _("month_2"),
        _("month_3"),
        _("month_4"),
        _("month_5"),
        _("month_6"),
        _("month_7"),
        _("month_8"),
        _("month_9"),
        _("month_10"),
        _("month_11"),
        _("month_12"),
    ]

    return _(f"month_{month_index}")


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


async def handle_expectation_edit_transaction(
    session: AsyncSession, user: User, _, event
):
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
        session,
        user,
        _,
        event,
        [sum_val, category, wallet],
        True,
        custom_datetime=saved_datetime,
    )

    if result:
        await delete_transaction(session, uuid)


async def handle_expectation_reschedule_transaction(
    session: AsyncSession, user: User, _, event
):
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
        update(Transaction).where(Transaction.id == uuid).values(datetime=new_timestamp)
    )
    await session.commit()

    buttons = [Button.inline(_("universal_back_button"), b"menu_transactions")]
    await event.reply(
        _("transaction_rescheduled").format(*map(str, [new_timestamp_formatted])),
        buttons=buttons,
    )


async def export(session: AsyncSession, event, user: User, _):
    await event.respond(_("export_started"))

    result = await session.execute(
        select(Transaction)
        .where(Transaction.holder == user.id)
        .options(selectinload(Transaction.wallet), selectinload(Transaction.category))
    )
    transactions = result.scalars().all()

    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["created_at", "wallet", "category", "sum", "currency"])

    for transaction in transactions:
        created_at = datetime.utcfromtimestamp(transaction.datetime).isoformat()
        writer.writerow(
            [
                created_at,
                transaction.wallet.name,
                transaction.category.name,
                transaction.sum,
                transaction.wallet.currency,
            ]
        )

    csv_bytes = BytesIO(csv_buffer.getvalue().encode("utf-8"))
    today = datetime.utcnow().strftime("%Y-%m-%d")
    csv_bytes.name = f"export_transactions_{today}.csv"

    await event.respond(_("export_transactions_caption"), file=csv_bytes)


async def handle_action(
    session: AsyncSession, event, user: User, data: list, _
) -> None:
    """Handle user pressing a button under one of the action menus."""

    if data[1][1] == "d":
        uuid = bytes.fromhex(data[2])

        # fetch transaction first to get the date for menu context
        stmt = select(Transaction).where(Transaction.id == uuid)
        res = await session.execute(stmt)
        txn = res.scalar_one_or_none()

        saved_year = None
        saved_month = None
        if txn:
            dt = datetime.fromtimestamp(txn.datetime, tz=timezone.utc)
            saved_year = dt.year
            saved_month = dt.month

        await delete_transaction(session, uuid)

        await event.edit(_("transaction_deleted_succesfully"))

        # return to the specific year/month view
        await send_menu(session, user, _, event, year=saved_year, month=saved_month)

    else:
        raise Exception(
            'Got unexpected data for callback command "action" (transactions)'
        )


async def check_ownership(
    session: AsyncSession, user: User, _, event, uuid: bytes
) -> bool:
    result = await session.execute(
        select(Transaction).where(Transaction.id == uuid, Transaction.holder == user.id)
    )
    transaction = result.scalar_one_or_none()

    if transaction:
        return True
    else:
        await event.respond(_("transaction_action_ownership_check_failed"))
        return False


async def view_menu(session: AsyncSession, user: User, _, event, uuid: bytes) -> None:
    await event.delete()

    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return

    transaction = await session.execute(
        select(Transaction)
        .where(Transaction.id == uuid)
        .options(selectinload(Transaction.wallet), selectinload(Transaction.category))
    )
    transaction = transaction.scalar_one_or_none()

    if transaction is None:
        await event.respond(_("transaction_action_view_not_found_error"))
        return

    formatted_datetime = datetime.fromtimestamp(
        transaction.datetime, tz=timezone.utc
    ).strftime("%Y-%m-%d, %H:%M UTC")

    if transaction.sum > 0:
        emoji_indicator = "🟩"
    elif transaction.sum < 0:
        emoji_indicator = "🟥"
    else:
        emoji_indicator = "🟨"

    buttons = [Button.inline(_("universal_back_button"), b"menu_transactions")]
    await event.respond(
        _("transaction_action_view").format(
            os.getenv("BOT_USERNAME"),
            emoji_indicator,
            transaction.sum,
            transaction.wallet.currency,
            formatted_datetime,
            transaction.wallet.name,
            transaction.category.name,
            transaction.wallet.id.hex(),
            transaction.category.id.hex(),
        ),
        buttons=buttons,
    )
    return


async def edit_menu(session: AsyncSession, user: User, _, event, uuid: bytes) -> None:
    await event.delete()
    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return
    user.expectation["expect"] = {"type": "edit_transaction", "data": uuid.hex()}
    await session.commit()
    buttons = [Button.inline(_("transaction_action_edit_cancel"), b"menu_transactions")]
    await event.respond(_("edit_transaction_prompt"), buttons=buttons)


async def reschedule_menu(
    session: AsyncSession, user: User, _, event, uuid: bytes
) -> None:
    await event.delete()
    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return
    user.expectation["expect"] = {"type": "reschedule_transaction", "data": uuid.hex()}
    await session.commit()
    buttons = [
        Button.inline(_("transaction_action_reschedule_cancel"), b"menu_transactions")
    ]
    await event.respond(_("reschedule_transaction_prompt"), buttons=buttons)


async def delete_menu(session: AsyncSession, user: User, _, event, uuid: bytes) -> None:
    await event.delete()
    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return
    buttons = [
        Button.inline(
            _("transaction_action_delete_approve"), "action_td_" + uuid.hex()
        ),
        Button.inline(_("transaction_action_delete_cancel"), b"menu_transactions"),
    ]
    await event.respond(_("delete_transaction_prompt"), buttons=buttons)


async def _render_year_selection(event, years, _):
    """Render the year selection menu."""
    buttons = []
    row = []
    for year in years:
        row.append(Button.inline(str(year), f"menu_transactions_{year}".encode()))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([Button.inline(_("back_to_main_menu_button"), b"menu_start")])
    await event.edit(_("menu_transactions_select_year"), buttons=buttons)


async def _render_month_selection(event, year, months, _, has_multiple_years=False):
    """Render the month selection menu."""
    buttons = []
    row = []
    for month in months:
        month_name = get_month_name(_, month)
        row.append(
            Button.inline(month_name, f"menu_transactions_{year}_{month}".encode())
        )
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    if has_multiple_years:
        back_data = b"menu_transactions"
    else:
        back_data = b"menu_start"

    buttons.append([Button.inline(_("universal_back_button"), back_data)])
    await event.edit(_("menu_transactions_select_month").format(year), buttons=buttons)


async def send_menu(
    session: AsyncSession,
    user: User,
    _,
    event,
    page: int = 1,
    original_msg: int | None = None,
    year: int | None = None,
    month: int | None = None,
) -> None:
    """Send transactions menu with Year > Month > List hierarchy."""

    # 1. Fetch timestamps for hierarchy
    stmt = select(Transaction.datetime).where(Transaction.holder == user.id)
    result = await session.execute(stmt)
    timestamps = result.scalars().all()

    if not timestamps:
        buttons = [Button.inline(_("back_to_main_menu_button"), b"menu_start")]
        await event.respond(_("menu_transactions_no_transactions"), buttons=buttons)
        return

    # Build structure: {2023: {1, 2}, 2024: {5, 6}}
    structure = {}
    for ts in timestamps:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        y, m = dt.year, dt.month
        if y not in structure:
            structure[y] = set()
        structure[y].add(m)

    sorted_years = sorted(structure.keys(), reverse=True)
    has_multiple_years = len(sorted_years) > 1

    # 2. Logic: Resolve Year
    if year is None:
        if has_multiple_years:
            if hasattr(event, "edit"):
                await _render_year_selection(event, sorted_years, _)
            else:
                msg = await event.respond("...")
                await _render_year_selection(msg, sorted_years, _)
            return
        else:
            year = sorted_years[0]

    # 3. Logic: Resolve Month
    available_months = sorted(list(structure.get(year, [])), reverse=True)
    has_multiple_months = len(available_months) > 1

    if month is None:
        if has_multiple_months:
            target = event if hasattr(event, "edit") else (await event.respond("..."))
            await _render_month_selection(
                target, year, available_months, _, has_multiple_years
            )
            return
        else:
            if available_months:
                month = available_months[0]
            else:
                month = 1

    # 4. Render Transactions List
    TRANSACTIONS_PER_PAGE = 14

    start_date = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end_date = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end_date = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    start_ts = start_date.timestamp()
    end_ts = end_date.timestamp()

    transactions_query = await session.execute(
        select(Transaction)
        .where(
            and_(
                Transaction.holder == user.id,
                Transaction.datetime >= start_ts,
                Transaction.datetime < end_ts,
            )
        )
        .options(selectinload(Transaction.wallet), selectinload(Transaction.category))
        .order_by(Transaction.datetime.desc())
    )
    transactions = transactions_query.scalars().all()
    transactions_count = len(transactions)

    page_count = math.ceil(len(transactions) / TRANSACTIONS_PER_PAGE)
    if page < 1:
        page = 1
    if page > page_count:
        page = page_count

    visible_transactions = transactions[
        (page - 1) * TRANSACTIONS_PER_PAGE : page * TRANSACTIONS_PER_PAGE
    ]

    transaction_info = []
    for transaction in visible_transactions:
        if transaction.sum > 0:
            emoji_indicator = "🟩"
        elif transaction.sum < 0:
            emoji_indicator = "🟥"
        else:
            emoji_indicator = "🟨"

        new = _("menu_transactions_component_transaction_info").format(
            os.getenv("BOT_USERNAME"),
            emoji_indicator,
            transaction.sum,
            transaction.wallet.currency,
            transaction.category.name,
            transaction.wallet.name,
            transaction.id.hex(),
            transaction.category.id.hex(),
            transaction.wallet.id.hex(),
        )
        transaction_info.append(new)

    transaction_info_str = "\n".join(transaction_info)

    month_name = get_month_name(_, month)
    header = f"📅 **{month_name} {year}**\n\n"  # [TODO: move into a localized string]
    content = header + _("menu_transactions_template").format(
        transaction_info_str, transactions_count
    )

    if has_multiple_months:
        back_data = f"menu_transactions_{year}".encode()
    elif has_multiple_years:
        back_data = b"menu_transactions"
    else:
        back_data = b"menu_start"

    pagination_buttons = []

    buttons = [
        [],
        [
            Button.inline(_("export_button"), b"export_transactions"),
            Button.inline(_("universal_back_button"), back_data),
        ],
    ]

    if original_msg is None:
        if hasattr(event, "edit"):
            message = await event.edit(content, buttons=buttons)
        else:
            message = await event.respond(content, buttons=buttons)
    else:
        message = await event.client.edit_message(
            entity=event.chat_id, message=original_msg, text=content, buttons=buttons
        )

    if page_count > 1:
        msg_id = str(message.id).encode("utf-8").hex()
        # embed Year and Month in the callback data so context is preserved
        # new format: page_t_MSGID_PAGE_YEAR_MONTH
        # middle button uses 'beam' keyword instead of page number to trigger input
        base_data = f"page_t_{msg_id}"

        back_p = f"{base_data}_{page - 1}_{year}_{month}"
        main_p = f"{base_data}_beam_{year}_{month}"
        next_p = f"{base_data}_{page + 1}_{year}_{month}"

        pagination_buttons = [
            Button.inline("◀️", back_p.encode()),
            Button.inline(f"{page} / {page_count}", main_p.encode()),
            Button.inline("▶️", next_p.encode()),
        ]
        buttons[0] = pagination_buttons
        await message.edit(content, buttons=buttons)
