from __future__ import annotations

import argparse
from typing import Any

from pascal_quickstart.config import environment_from_name
from pascal_quickstart.market_data import (
    best_bid_ask,
    get_books,
    get_server_time,
    list_markets,
)


def market_label(market: dict[str, Any]) -> str:
    symbol = market["symbol"]
    attrs = market["display_attributes"]
    event = attrs.get("event_description", "")
    market_description = attrs.get("market_description", "")
    if event or market_description:
        return f"{symbol} - {event} / {market_description}"
    return str(symbol)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch read-only Pascal market context.")
    parser.add_argument("--env", default="prod", help="Pascal environment name.")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    environment = environment_from_name(args.env)
    server_time = get_server_time(environment)
    markets = list_markets(environment)
    selected = markets[: max(1, args.limit)]
    symbols = [market["symbol"] for market in selected]
    books = get_books(environment, symbols)

    print(f"Environment: {environment.name}")
    print(f"Read API: {environment.read_base_url}")
    print(f"Server time: {server_time.get('server_time_ms')}")
    print()
    print(f"First {len(selected)} market(s):")
    for market in selected:
        symbol = market["symbol"]
        book = books.get(symbol, {})
        bid, ask = best_bid_ask(book)
        print(f"- {market_label(market)}")
        print(f"  mark={market.get('mark_price')} open_interest={market.get('open_interest')}")
        print(f"  best_bid={bid or '-'} best_ask={ask or '-'}")


if __name__ == "__main__":
    main()
