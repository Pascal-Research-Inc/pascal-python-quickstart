from __future__ import annotations

from decimal import Decimal
from typing import Any

from pascal_quickstart.config import PascalEnvironment
from pascal_quickstart.http import get_json, unwrap_envelope


def get_server_time(environment: PascalEnvironment) -> dict[str, Any]:
    data = unwrap_envelope(
        get_json(f"{environment.read_base_url}/api/v1/time"), context="server time"
    )
    if not isinstance(data, dict):
        raise TypeError("server time response data must be an object")
    return data


def list_markets(environment: PascalEnvironment, *, strict: bool = True) -> list[dict[str, Any]]:
    response = get_json(
        f"{environment.read_base_url}/api/v1/markets",
        {"strict": "true" if strict else "false"},
    )
    data = unwrap_envelope(response, context="markets")
    if not isinstance(data, list):
        raise TypeError("markets response data must be an array")
    return [item for item in data if isinstance(item, dict)]


def get_books(environment: PascalEnvironment, symbols: list[str]) -> dict[str, Any]:
    if not symbols:
        return {}
    response = get_json(
        f"{environment.read_base_url}/api/v1/books",
        {"symbols": ",".join(symbols[:50])},
    )
    data = unwrap_envelope(response, context="books")
    if not isinstance(data, dict):
        raise TypeError("books response data must be an object")
    books = data.get("books")
    if not isinstance(books, dict):
        raise TypeError("books response missing books object")
    return books


def list_trades(
    environment: PascalEnvironment,
    symbols: list[str],
    *,
    limit: int = 100,
    before_cursor: str | None = None,
    at_or_before_seq: int | str | None = None,
) -> dict[str, Any]:
    """Fetch one page of public trade history.

    For older pages, pass the prior page's ``next_cursor`` back as
    ``before_cursor``. There is no ``cursor`` query parameter for this endpoint.
    """

    if not symbols:
        raise ValueError("symbols must contain at least one market symbol")
    if len(symbols) > 30:
        raise ValueError("trades supports at most 30 market symbols")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if before_cursor is not None and at_or_before_seq is not None:
        raise ValueError("Pass at most one of before_cursor or at_or_before_seq")

    params = {
        "symbols": ",".join(symbols),
        "limit": str(limit),
    }
    if before_cursor is not None:
        params["before_cursor"] = before_cursor
    if at_or_before_seq is not None:
        params["at_or_before_seq"] = str(at_or_before_seq)

    data = unwrap_envelope(
        get_json(f"{environment.read_base_url}/api/v1/trades", params),
        context="trades",
    )
    if not isinstance(data, dict):
        raise TypeError("trades response data must be an object")
    if not isinstance(data.get("items"), list):
        raise TypeError("trades response missing items array")
    return data


def get_account_state(environment: PascalEnvironment, owner_public_key: str) -> dict[str, Any]:
    data = unwrap_envelope(
        get_json(f"{environment.read_base_url}/api/v1/accounts/{owner_public_key}"),
        context="account state",
    )
    if not isinstance(data, dict):
        raise TypeError("account state response data must be an object")
    return data


def get_trading_keys(environment: PascalEnvironment, owner_public_key: str) -> list[dict[str, Any]]:
    data = unwrap_envelope(
        get_json(f"{environment.read_base_url}/api/v1/accounts/{owner_public_key}/trading-keys"),
        context="trading keys",
    )
    if not isinstance(data, list):
        raise TypeError("trading keys response data must be an array")
    return [item for item in data if isinstance(item, dict)]


def choose_symbol(environment: PascalEnvironment) -> str:
    markets = list_markets(environment)
    if not markets:
        raise RuntimeError(f"No markets returned by {environment.read_base_url}")
    symbol = markets[0].get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise RuntimeError("First market response did not include a symbol")
    return symbol


def best_bid_ask(book: dict[str, Any]) -> tuple[str | None, str | None]:
    bids = book.get("bids")
    asks = book.get("asks")
    best_bid = bids[0][0] if isinstance(bids, list) and bids else None
    best_ask = asks[0][0] if isinstance(asks, list) and asks else None
    return (
        best_bid if isinstance(best_bid, str) else None,
        best_ask if isinstance(best_ask, str) else None,
    )


def decimal_six(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.000001')):.6f}"
