from __future__ import annotations

import argparse
from urllib.parse import urlencode

from pascal_quickstart.config import environment_from_name
from pascal_quickstart.market_data import choose_symbol, list_trades


def trades_path(symbol: str, limit: int, before_cursor: str | None) -> str:
    params = {"symbols": symbol, "limit": str(limit)}
    if before_cursor is not None:
        params["before_cursor"] = before_cursor
    return f"/api/v1/trades?{urlencode(params)}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch paginated Pascal trade history.")
    parser.add_argument("--env", default="prod", help="Pascal environment name.")
    parser.add_argument("--symbol", help="Market symbol. Defaults to the first listed market.")
    parser.add_argument("--limit", type=int, default=5, help="Trades per page, 1-500.")
    parser.add_argument("--pages", type=int, default=2, help="Maximum pages to fetch.")
    args = parser.parse_args()

    if args.pages < 1:
        parser.error("--pages must be at least 1")

    environment = environment_from_name(args.env)
    symbol = args.symbol or choose_symbol(environment)
    before_cursor: str | None = None

    print(f"Environment: {environment.name}")
    print(f"Read API: {environment.read_base_url}")
    print(f"Symbol: {symbol}")
    print()
    print("Pagination rule: response data.next_cursor becomes the next request's")
    print("before_cursor. Do not send cursor=<next_cursor>.")
    print()

    for page_number in range(1, args.pages + 1):
        print(f"Page {page_number} request:")
        print(f"GET {trades_path(symbol, args.limit, before_cursor)}")

        page = list_trades(
            environment,
            [symbol],
            limit=args.limit,
            before_cursor=before_cursor,
        )
        next_cursor = page.get("next_cursor")

        print(f"Page {page_number} returned {len(page['items'])} trade(s).")
        print(f"data.next_cursor: {next_cursor or '-'}")

        if not isinstance(next_cursor, str) or not next_cursor:
            print("No next_cursor returned; pagination is complete.")
            break
        if next_cursor == before_cursor:
            print("next_cursor did not advance; stopping to avoid repeating a page.")
            break

        before_cursor = next_cursor
        print(f"Next request will use before_cursor={before_cursor}")
        print()


if __name__ == "__main__":
    main()
