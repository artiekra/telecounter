import json
import os
import time

import requests

CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "cache.json")
BASE_CURRENCY = "USD"


def get_exchange_rate(base_currency: str, target_currency: str) -> float:
    """Get the exchange rate from base_currency to target_currency."""
    cache_data = None
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cache_data = json.load(f)
            if time.time() - cache_data.get("timestamp", 0) < 86400:  # 24 hours
                rates = cache_data["rates"]
                if (
                    BASE_CURRENCY in rates
                    and base_currency in rates
                    and target_currency in rates
                ):
                    # calculate rate: target / base
                    return rates[target_currency] / rates[base_currency]
        except (json.JSONDecodeError, KeyError):
            cache_data = None  # reset on error

    try:
        url = f"https://api.exchangerate-api.com/v4/latest/{BASE_CURRENCY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        rates = data["rates"]

        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        cache_data = {
            "base": BASE_CURRENCY,
            "rates": rates,
            "timestamp": time.time(),
        }
        with open(CACHE_FILE, "w") as f:
            json.dump(cache_data, f)

        if base_currency in rates and target_currency in rates:
            return rates[target_currency] / rates[base_currency]
        else:
            raise ValueError(
                f"One or both currencies '{base_currency}' or '{target_currency}' not supported by the API"
            )

    except requests.RequestException as e:
        if (
            cache_data
            and BASE_CURRENCY in cache_data["rates"]
            and base_currency in cache_data["rates"]
            and target_currency in cache_data["rates"]
        ):
            return (
                cache_data["rates"][target_currency]
                / cache_data["rates"][base_currency]
            )
        raise ValueError(
            f"Unable to fetch exchange rates: {str(e)}. Cache unavailable or expired."
        )

    except Exception as e:
        raise ValueError(f"Error retrieving exchange rate: {str(e)}")
