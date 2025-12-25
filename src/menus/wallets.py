import csv
import json
import math
import os
from datetime import datetime, timezone
from io import BytesIO, StringIO

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from telethon.tl.custom import Button

from database.models import Transaction, User, Wallet, WalletAlias
from helpers.amount_formatter import format_amount

with open("src/assets/currency_codes.json", "r", encoding="utf-7") as f:
    currency_data = json.load(f)
    ALLOWED_CURRENCIES = set(currency_data.get("currency_codes", []))


async def handle_expectation_edit_wallet(session: AsyncSession, user: User, _, event):
    """Handle edit_wallet expectation."""
    uuid = bytes.fromhex(user.expectation["expect"]["data"])
    raw_text = event.raw_text

    if raw_text == "":
        await event.respond(_("got_empty_message_for_wallet"))
        return

    parts = raw_text.split()
    currency = parts[0] if len(parts) > 0 else "eur"
    init_sum = parts[1] if len(parts) > 1 else "0"
    name = parts[2] if len(parts) > 2 else None

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
        select(Wallet)
        .where(Wallet.holder == user.id)
        .where(Wallet.is_deleted is False)
        .where(Wallet.name == name.lower())
        .where(Wallet.id != uuid)
    )
    wallets = wallets.scalars().all()
    if len(wallets) != 0:
        await event.respond(_("non_unique_wallet_name_error"))
        return

    # delete matching aliases (same name)
    await session.execute(
        delete(WalletAlias).where(
            WalletAlias.holder == user.id, WalletAlias.alias == name.lower()
        )
    )

    # delete all aliases belonging to this wallet
    await session.execute(delete(WalletAlias).where(WalletAlias.wallet == uuid))

    wallet = await session.execute(select(Wallet).where(Wallet.id == uuid))
    wallet = wallet.scalar_one_or_none()
    if wallet:
        wallet.name = name
        wallet.currency = currency
        wallet.init_sum = init_sum
        await session.commit()
        await session.refresh(wallet)
        await event.respond(
            _("wallet_edited_successfully").format(
                name, currency, format_amount(init_sum)
            )
        )
        await send_menu(session, user, _, event)

    user.expectation["expect"] = {"type": None, "data": None}
    await session.commit()


async def export(session: AsyncSession, event, user: User, _):
    """Handle export callback - send back user wallets as csv."""
    await event.respond(_("export_started"))

    result = await session.execute(select(Wallet).where(Wallet.holder == user.id))
    wallets = result.scalars().all()

    # prepare csv in memory
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(
        [
            "created_at",
            "name",
            "currency",
            "init_sum",
            "current_sum",
            "transaction_count",
            "is_deleted",
        ]
    )

    for wallet in wallets:

        created_at = datetime.utcfromtimestamp(wallet.created_at).isoformat()
        is_deleted = "false" if not wallet.is_deleted else "true"

        writer.writerow(
            [
                created_at,
                wallet.name,
                wallet.currency,
                wallet.init_sum,
                wallet.current_sum,
                wallet.transaction_count,
                is_deleted,
            ]
        )

    # convert to bytes for sending
    csv_bytes = BytesIO(csv_buffer.getvalue().encode("utf-8"))

    today = datetime.utcnow().strftime("%Y-%m-%d")
    csv_bytes.name = f"export_wallets_{today}.csv"

    await event.respond(_("export_wallets_caption"), file=csv_bytes)


async def handle_action(
    session: AsyncSession, event, user: User, data: list, _
) -> None:
    """Handle user pressing a button under one of the action menus."""

    if data[1][1] == "d":
        uuid = bytes.fromhex(data[2])

        wallet = await session.execute(select(Wallet).where(Wallet.id == uuid))
        wallet = wallet.scalar_one_or_none()
        wallet.is_deleted = True
        session.add(wallet)

        await session.execute(
            delete(WalletAlias).where(WalletAlias.wallet == wallet.id)
        )

        await session.commit()

        await event.edit(_("wallet_deleted_succesfully"))
        await send_menu(session, user, _, event)

    else:
        raise Exception('Got unexpected data for callback command "action" (wallets)')


async def check_ownership(
    session: AsyncSession, user: User, _, event, uuid: bytes
) -> bool:
    """Check if wallet belongs to User, return True if so."""
    result = await session.execute(
        select(Wallet).where(Wallet.id == uuid, Wallet.holder == user.id)
    )
    wallet = result.scalar_one_or_none()

    if wallet and not wallet.is_deleted:
        return True
    elif wallet and wallet.is_deleted:
        await event.respond(_("wallet_action_ownership_check_got_deleted"))
    else:
        await event.respond(_("wallet_action_ownership_check_failed"))

    return False


async def edit_menu(session: AsyncSession, user: User, _, event, uuid: bytes) -> None:
    """Send wallet edit menu to the user."""
    await event.delete()

    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return

    user.expectation["expect"] = {"type": "edit_wallet", "data": uuid.hex()}
    await session.commit()

    buttons = [Button.inline(_("wallet_action_edit_cancel"), b"menu_wallets")]
    await event.respond(_("edit_wallet_prompt"), buttons=buttons)


def format_component_transaction(transaction: Transaction, _) -> str:
    """Format a transaction for wallet view menu."""

    # set emoji indicator
    if transaction.sum > 0:
        emoji_indicator = "🟩"
    elif transaction.sum < 0:
        emoji_indicator = "🟥"
    else:
        emoji_indicator = "🟨"

    return _("wallet_action_view_component_transaction").format(
        emoji_indicator,
        format_amount(transaction.sum),
        transaction.wallet.currency,
        transaction.category.name,
    )


async def view_menu(session: AsyncSession, user: User, _, event, uuid: bytes) -> None:
    """Send wallet view menu to the user."""
    MAX_TRANSACTIONS_SHOWN = 5
    MAX_ALIASES_SHOWN = 5

    await event.delete()

    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return

    wallet = await session.execute(
        select(Wallet).where(Wallet.id == uuid).where(Wallet.is_deleted == False)
    )
    wallet = wallet.scalar_one_or_none()

    if wallet is None:
        await event.respond(_("wallet_action_view_not_found_error"))
        return

    # TODO: optimize to only select 5 latest
    full_transactions = await session.execute(
        select(Transaction)
        .options(selectinload(Transaction.category))
        .where(Transaction.wallet_id == uuid)
        .order_by(Transaction.datetime.desc())
    )
    full_transactions = full_transactions.scalars().all()

    transactions = full_transactions
    if len(transactions) > MAX_TRANSACTIONS_SHOWN:
        transactions = transactions[:MAX_TRANSACTIONS_SHOWN]

    formatted_created_on = datetime.fromtimestamp(
        wallet.created_at, tz=timezone.utc
    ).strftime("%Y-%m-%d, %H:%M UTC")

    buttons = [Button.inline(_("universal_back_button"), b"menu_wallets")]
    if len(transactions) == 0:
        await event.respond(
            _("wallet_action_view_no_transactions").format(
                wallet.icon,
                wallet.name,
                formatted_created_on,
                wallet.currency,
                wallet.init_sum,
            ),
            buttons=buttons,
        )
        return

    transaction_component = "\n".join(
        map(lambda x: format_component_transaction(x, _), transactions)
    )

    if len(full_transactions) > MAX_TRANSACTIONS_SHOWN:
        not_shown_count = len(full_transactions) - MAX_TRANSACTIONS_SHOWN
        transaction_component += "\n" + _("universal_component_not_shown_count").format(
            not_shown_count
        )

    content = _("wallet_action_view").format(
        wallet.icon,
        wallet.name,
        formatted_created_on,
        wallet.currency,
        wallet.init_sum,
        wallet.transaction_count,
        transaction_component,
    )

    # TODO: optimize to only select 5 latest
    full_aliases = await session.execute(
        select(WalletAlias).where(WalletAlias.wallet == uuid)
    )
    full_aliases = full_aliases.scalars().all()

    aliases = full_aliases[::-1]
    if len(aliases) > MAX_ALIASES_SHOWN:
        aliases = aliases[:MAX_ALIASES_SHOWN]

    if len(aliases) > 0:
        content += "\n\n" + _("wallet_action_view_component_aliases").format(
            ", ".join([f"`{x.alias}`" for x in aliases])
        )
        if len(full_aliases) > MAX_ALIASES_SHOWN:
            content += " " + _("universal_component_not_shown_count").format(
                len(full_aliases) - MAX_ALIASES_SHOWN
            )

    await event.respond(content, buttons=buttons)


async def delete_menu(session: AsyncSession, user: User, _, event, uuid: bytes) -> None:
    """Send wallet delete menu to the user."""
    await event.delete()

    is_owner = await check_ownership(session, user, _, event, uuid)
    if not is_owner:
        return

    name = await session.execute(select(Wallet.name).where(Wallet.id == uuid))
    name = name.scalar_one_or_none()

    buttons = [
        Button.inline(_("wallet_action_delete_approve"), "action_wd_" + uuid.hex()),
        Button.inline(_("wallet_action_delete_cancel"), b"menu_wallets"),
    ]
    await event.respond(_("delete_wallet_prompt").format(name), buttons=buttons)


async def send_menu(
    session: AsyncSession,
    user: User,
    _,
    event,
    page: int = 1,
    original_msg: int | None = None,
) -> None:
    """Send wallets menu to the user."""
    WALLETS_PER_PAGE = 20

    # TODO: include pagination into a query
    wallets = await session.execute(
        select(Wallet).where(Wallet.holder == user.id).where(Wallet.is_deleted == False)
    )
    wallets = wallets.scalars().all()
    wallets = sorted(wallets, key=lambda x: x.transaction_count, reverse=True)

    wallets_count = len(wallets)

    del_wallets_count = await session.execute(
        select(func.count())
        .select_from(Wallet)
        .where(Wallet.holder == user.id, Wallet.is_deleted == True)
    )
    del_wallets_count = del_wallets_count.scalar_one()

    if len(wallets) == 0:
        buttons = [Button.inline(_("back_to_main_menu_button"), b"menu_start")]
        if del_wallets_count == 0:
            await event.respond(_("menu_wallets_no_wallets"), buttons=buttons)
        else:
            await event.respond(
                _("menu_wallets_only_deleted").format(del_wallets_count),
                buttons=buttons,
            )
        return

    page_count = math.ceil(len(wallets) / WALLETS_PER_PAGE)

    if page < 1:
        page = 1
    if page > page_count:
        page = page_count

    wallets = wallets[(page - 1) * WALLETS_PER_PAGE : page * WALLETS_PER_PAGE]

    wallet_info = [
        _("menu_wallets_component_wallet_info").format(
            os.getenv("BOT_USERNAME"),
            x.name,
            format_amount(x.init_sum + x.current_sum),
            x.currency,
            x.id.hex(),
        )
        for x in wallets
    ]

    wallet_info_str = "\n".join(wallet_info)

    content = _("menu_wallets_template").format(wallet_info_str, wallets_count)
    if del_wallets_count != 0:
        content += _("menu_wallets_component_deleted_amount").format(del_wallets_count)

    # get the id of newly sent message, and then add buttons according to that

    pagination_buttons = []

    if page_count > 1:
        pagination_buttons = [
            Button.inline("◀️", b"none"),
            Button.inline(f"{page} / {page_count}", b"none"),
            Button.inline("▶️", b"none"),
        ]

    buttons = [
        pagination_buttons,
        [
            Button.inline(_("export_button"), b"export_wallets"),
            Button.inline(_("back_to_main_menu_button"), b"menu_start"),
        ],
    ]
    if original_msg is None:
        message = await event.respond(content, buttons=buttons)
    else:
        message = await event.client.edit_message(
            entity=event.chat_id, message=original_msg, text=content, buttons=buttons
        )

    pagination_buttons = []

    if page_count > 1:
        msg_id = str(message.id).encode("utf-8").hex()
        back_button_data = "page_w_" + msg_id + "_" + str(page - 1)
        main_button_data = "page_w_" + msg_id
        forward_button_data = "page_w_" + msg_id + "_" + str(page + 1)
        pagination_buttons = [
            Button.inline("◀️", back_button_data),
            Button.inline(f"{page} / {page_count}", main_button_data),
            Button.inline("▶️", forward_button_data),
        ]

    buttons = [
        pagination_buttons,
        [
            Button.inline(_("export_button"), b"export_wallets"),
            Button.inline(_("back_to_main_menu_button"), b"menu_start"),
        ],
    ]
    await message.edit(content, buttons=buttons)
