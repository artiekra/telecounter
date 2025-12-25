import datetime
import glob
import io
import os
from collections import Counter, defaultdict

import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from loguru import logger
from matplotlib.ticker import FuncFormatter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from database.models import Transaction, Wallet
from helpers.currency_converter import get_exchange_rate


def setup_plotting_style():
    """Sets global matplotlib style parameters for a modern dark theme with custom font."""
    plt.style.use("dark_background")

    # 1. Load All Static Fonts from Directory
    font_dir = "src/assets/fonts/montserrat/static"
    custom_font_family = "sans-serif"

    if os.path.exists(font_dir):
        font_files = glob.glob(os.path.join(font_dir, "*.ttf"))

        if font_files:
            for font_path in font_files:
                try:
                    fm.fontManager.addfont(font_path)
                except Exception:
                    pass

            custom_font_family = "Montserrat"
        else:
            logger.warning(f"no .ttf files found in {font_dir}")
    else:
        logger.warning(f"font directory not found at {font_dir}")

    # 2. Apply Styles
    plt.rcParams.update(
        {
            "figure.facecolor": "#121212",
            "axes.facecolor": "#121212",
            "text.color": "#E0E0E0",
            "axes.labelcolor": "#E0E0E0",
            "xtick.color": "#CCCCCC",
            "ytick.color": "#CCCCCC",
            "axes.edgecolor": "#444444",
            "grid.color": "#333333",
            "grid.linestyle": ":",
            "grid.linewidth": 0.8,
            # Font settings
            "font.family": custom_font_family,
            "font.weight": "bold",  # global bold default
            "axes.labelweight": "bold",  # axes labels bold
            "axes.titleweight": "bold",  # title bold
            "font.size": 11,
            "axes.titlesize": 16,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


setup_plotting_style()

PALETTE = [
    "#696FC7",
    "#A7AAE1",
    "#F5D3C4",
    "#F2AEBB",
    "#B5EAD7",
]


def get_text_color(hex_color):
    """Determines whether black or white text contrasts better with the background."""
    try:
        rgb = mcolors.hex2color(hex_color)
        luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        return "#000000" if luminance > 0.6 else "#FFFFFF"
    except Exception:
        return "#FFFFFF"


def safe_get_rate(base: str, target: str) -> float:
    """Wrapper to safely get rate or default to 1.0 on error."""
    try:
        if base == target:
            return 1.0
        return get_exchange_rate(base, target)
    except Exception as e:
        logger.error(f"Failed to convert {base} to {target}: {e}")
        return 1.0


# [TODO: consider this using transactions to determine the most used currency]
async def get_user_main_currency(session: AsyncSession, user_id: bytes) -> str:
    """Finds the most frequently used currency among the user's wallets."""
    stmt = select(Wallet.currency).where(
        Wallet.holder == user_id, Wallet.is_deleted == False
    )
    result = await session.execute(stmt)
    currencies = result.scalars().all()

    if not currencies:
        return "USD"  # default fallback

    return Counter(currencies).most_common(1)[0][0]


async def get_balance_history(_, session: AsyncSession, user_id: bytes) -> io.BytesIO:
    """Calculates weekly total balance history for the last year (normalized to main currency)."""
    now = datetime.datetime.now()
    one_year_ago = now - datetime.timedelta(days=365)

    # 1. Determine Target Currency
    target_currency = await get_user_main_currency(session, user_id)

    # 2. Get current total sum across all wallets, converting each to target_currency
    stmt_wallets = select(Wallet).where(
        Wallet.holder == user_id, Wallet.is_deleted == False
    )
    result_wallets = await session.execute(stmt_wallets)
    wallets = result_wallets.scalars().all()

    current_total = 0.0
    for w in wallets:
        rate = safe_get_rate(w.currency, target_currency)
        current_total += (w.init_sum + w.current_sum) * rate

    # 3. Get transactions (joined with Wallet to know source currency)
    stmt_tx = (
        select(Transaction)
        .options(joinedload(Transaction.wallet))
        .where(
            Transaction.holder == user_id,
            Transaction.datetime >= one_year_ago.timestamp(),
        )
        .order_by(Transaction.datetime.desc())
    )
    result = await session.execute(stmt_tx)
    transactions = result.scalars().all()

    history = []
    tx_idx = 0

    # 4. Back-calculate history
    # Iterate backwards week by week
    for i in range(53):
        week_date = now - datetime.timedelta(weeks=i)
        timestamp = week_date.timestamp()

        while tx_idx < len(transactions) and transactions[tx_idx].datetime > timestamp:
            tx = transactions[tx_idx]

            if tx.wallet:
                rate = safe_get_rate(tx.wallet.currency, target_currency)
                current_total -= tx.sum * rate

            tx_idx += 1

        history.append((week_date, current_total))

    history.reverse()
    dates, values = zip(*history)

    # --- Plotting ---
    fig, ax = plt.subplots(figsize=(10, 6))

    accent_color = "#696FC7"

    ax.plot(
        dates,
        values,
        linestyle="-",
        linewidth=3,
        color=accent_color,
    )

    ax.fill_between(dates, values, color=accent_color, alpha=0.15)

    # dynamically update title with currency
    # [TODO: add this to i18n]
    title_text = _("stats_chart_total_net_worth") + f" ({target_currency})"
    ax.set_title(title_text, pad=25)

    ax.grid(True, axis="y", alpha=0.3)
    ax.grid(False, axis="x")

    def localize_date(x, pos):
        """Converts matplotlib date number to localized 'Mon YY' string."""
        dt = mdates.num2date(x)
        month_name = _(f"month_{dt.month}")
        return f"{month_name} {dt.strftime('%y')}"

    ax.xaxis.set_major_formatter(FuncFormatter(localize_date))

    plt.setp(ax.get_xticklabels(), fontweight="bold")
    plt.setp(ax.get_yticklabels(), fontweight="bold")

    fig.autofmt_xdate(rotation=45)

    plt.subplots_adjust(left=0.15, right=0.90, top=0.8, bottom=0.2)

    buf = io.BytesIO()
    plt.savefig(buf, dpi=600, format="png", facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close()
    buf.name = "balance_history.png"
    return buf


async def get_category_pie_charts(
    _, session: AsyncSession, user_id: bytes
) -> io.BytesIO:
    """Generates two donut charts for income and expenses by category (normalized)."""
    one_year_ago = (datetime.datetime.now() - datetime.timedelta(days=365)).timestamp()

    # 1. Determine Target Currency
    target_currency = await get_user_main_currency(session, user_id)

    stmt = (
        select(Transaction)
        .options(
            joinedload(Transaction.category),
            joinedload(Transaction.wallet),
        )
        .where(Transaction.holder == user_id, Transaction.datetime >= one_year_ago)
    )
    result = await session.execute(stmt)
    transactions = result.scalars().all()

    income_data = defaultdict(int)
    expense_data = defaultdict(int)

    for tx in transactions:
        if tx.category and tx.wallet:
            rate = safe_get_rate(tx.wallet.currency, target_currency)
            normalized_sum = tx.sum * rate

            cat_name = tx.category.name.title()

            if normalized_sum > 0:
                income_data[cat_name] += normalized_sum
            elif normalized_sum < 0:
                expense_data[cat_name] += abs(normalized_sum)

    # --- Plotting ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 8))
    fig.suptitle(
        _("stats_chart_category_distribution")
        + f" ({target_currency})",  # [TODO: localize]
        y=0.90,
        fontsize=18,
        fontweight="bold",
    )

    def plot_donut(ax, data, title):
        if not data:
            ax.text(
                0.5,
                0.5,
                _("stats_chart_no_data"),
                ha="center",
                va="center",
                color="#777777",
                fontweight="bold",
            )
            ax.set_title(title, pad=5)
            ax.axis("off")
            return

        sorted_items = sorted(data.items(), key=lambda item: item[1], reverse=True)

        MAX_SLICES = 6
        OTHER_COLOR = "#555555"

        labels = []
        sizes = []
        colors = []

        if len(sorted_items) > MAX_SLICES:
            main_items = sorted_items[: MAX_SLICES - 1]
            tail_items = sorted_items[MAX_SLICES - 1 :]

            labels = [k for k, v in main_items]
            sizes = [v for k, v in main_items]
            colors = PALETTE[: len(main_items)]

            tail_sum = sum(v for k, v in tail_items)
            tail_names = [k for k, v in tail_items]

            if len(tail_names) == 1:
                tail_label = tail_names[0]
            elif len(tail_names) == 2:
                tail_label = f"{tail_names[0]}, {tail_names[1]}"
            else:
                tail_label = (
                    f"{tail_names[0]}, {tail_names[1]} + {len(tail_names)-2} more"
                )

            labels.append(tail_label)
            sizes.append(tail_sum)
            colors.append(OTHER_COLOR)
        else:
            labels = [k for k, v in sorted_items]
            sizes = [v for k, v in sorted_items]
            colors = PALETTE * (len(labels) // len(PALETTE) + 1)
            colors = colors[: len(labels)]

        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=None,
            autopct="%1.0f%%",
            startangle=90,
            colors=colors,
            wedgeprops=dict(width=0.4, edgecolor="#121212", linewidth=2),
            pctdistance=0.80,
        )

        for text, wedge_color in zip(autotexts, colors):
            text.set_color(get_text_color(wedge_color))
            text.set_weight("heavy")
            text.set_fontsize(10)

        ax.set_title(title, pad=5, fontsize=16, fontweight="bold")

        ax.legend(
            wedges,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.05),
            frameon=False,
            ncol=1,
            fontsize=11,
            labelspacing=0.8,
            prop={"weight": "bold"},
        )

    plot_donut(ax1, income_data, _("stats_chart_income"))
    plot_donut(ax2, expense_data, _("stats_chart_expense"))

    plt.subplots_adjust(left=0.08, right=0.92, top=0.9, bottom=0.2)

    buf = io.BytesIO()
    plt.savefig(buf, dpi=600, format="png", facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close()
    buf.name = "category_pie_charts.png"
    return buf
