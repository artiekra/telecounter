def format_amount(amount) -> str:
    """Format an amount with a plus sign for positive values."""
    if amount > 0:
        return f"+{amount}"
    return str(amount)