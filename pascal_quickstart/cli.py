from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pascal_quickstart.config import PascalConfig, PascalEnvironment, load_config
from pascal_quickstart.crypto import KeyParseError
from pascal_quickstart.http import PascalHTTPError, post_json, pretty_json
from pascal_quickstart.market_data import (
    best_bid_ask,
    choose_symbol,
    get_account_history,
    get_account_state,
    get_books,
    get_deposit_address,
    list_account_fills,
    list_account_transfers,
    list_markets,
    list_position_resolutions,
)
from pascal_quickstart.signing import (
    now_ms,
    signed_cancel_order_request,
    signed_place_order_request,
)

Handler = Callable[[argparse.ArgumentParser, argparse.Namespace], None]
Side = Literal["BID", "ASK"]
HistoryKind = Literal["all", "fills", "transfers", "position-resolutions"]


@dataclass(frozen=True)
class Command:
    summary: str
    build_parser: Callable[[], argparse.ArgumentParser]
    handler: Handler
    requires_args: bool = False


def command_parser(command: str, summary: str, examples: list[str]) -> argparse.ArgumentParser:
    epilog = "Examples:\n" + "\n".join(f"  {example}" for example in examples)
    return argparse.ArgumentParser(
        prog=f"cli {command}",
        description=summary,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def add_env(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env", default="prod", help="Pascal environment name.")


def add_owner(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--owner",
        help="Owner wallet public key. Defaults to PASCAL_OWNER_PUBLIC_KEY from .env.",
    )


def add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print full JSON data.")


def add_pagination(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=50, help="Maximum items to fetch.")
    parser.add_argument("--before-cursor", help="Fetch items older than this next_cursor.")
    parser.add_argument("--at-or-before-seq", help="Start at or before this sequence number.")


def add_order_common(parser: argparse.ArgumentParser) -> None:
    add_env(parser)
    parser.add_argument("--send", action="store_true", help="Actually post the write request.")
    parser.add_argument("--symbol", help="Market symbol. Defaults to the first listed market.")
    parser.add_argument("--side", default="BID", choices=["BID", "ASK"])
    parser.add_argument("--size", type=int, default=1)
    parser.add_argument(
        "--client-order-id",
        type=int,
        help="Client order id. Defaults to the current millisecond timestamp.",
    )
    parser.add_argument("--reduce-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--recv-window-ms", type=int, default=5000)


def load_read_account(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> tuple[PascalEnvironment, str]:
    try:
        config = load_config(args.env, require_keys=False)
    except ValueError as exc:
        parser.error(str(exc))
    owner = (args.owner or config.owner_public_key).strip()
    if not owner:
        parser.error("Pass --owner or set PASCAL_OWNER_PUBLIC_KEY in .env.")
    return config.environment, owner


def load_trading_config(parser: argparse.ArgumentParser, args: argparse.Namespace) -> PascalConfig:
    try:
        return load_config(args.env)
    except ValueError as exc:
        parser.error(str(exc))


def market_label(market: dict[str, Any]) -> str:
    attrs = market.get("display_attributes", {})
    event = attrs.get("event_description", "") if isinstance(attrs, dict) else ""
    description = attrs.get("market_description", "") if isinstance(attrs, dict) else ""
    if event or description:
        return f"{event} / {description}".strip(" /")
    return "-"


def compact_json(value: Any) -> str:
    return pretty_json(value)


def string_value(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def print_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> None:
    if not rows:
        print("- none")
        return

    widths = [
        max(len(header), *(len(string_value(row.get(key))) for row in rows))
        for header, key in columns
    ]
    print(
        "  ".join(header.ljust(width) for (header, _), width in zip(columns, widths, strict=True))
    )
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print(
            "  ".join(
                string_value(row.get(key)).ljust(width)
                for (_, key), width in zip(columns, widths, strict=True)
            )
        )


def print_main_help() -> None:
    print("Pascal quickstart CLI")
    print()
    print("Usage:")
    print("  cli <command> [arguments]")
    print()
    print("Run `cli <command> --help` to see that command's arguments and examples.")
    print()
    print("Commands:")
    width = max(len(name) for name in COMMANDS)
    for name, command in COMMANDS.items():
        print(f"  {name:<{width}}  {command.summary}")


def parse_symbols(values: list[str] | None) -> list[str]:
    symbols: list[str] = []
    for value in values or []:
        symbols.extend(symbol.strip() for symbol in value.split(",") if symbol.strip())
    return symbols


def page_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items", [])
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def best_level(book: dict[str, Any], side: str) -> tuple[str | None, str | None]:
    levels = book.get(side)
    if not isinstance(levels, list) or not levels:
        return None, None
    first = levels[0]
    if not isinstance(first, list | tuple) or len(first) < 2:
        return None, None
    price = first[0] if isinstance(first[0], str) else None
    size = first[1] if isinstance(first[1], str) else None
    return price, size


def handle_markets(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        config = load_config(args.env, require_keys=False)
        markets = list_markets(config.environment, strict=args.strict)
    except ValueError as exc:
        parser.error(str(exc))
    if args.query:
        query = args.query.lower()
        markets = [
            market
            for market in markets
            if query in str(market.get("symbol", "")).lower()
            or query in market_label(market).lower()
        ]
    if args.limit is not None:
        markets = markets[: args.limit]
    if args.json:
        print(compact_json(markets))
        return
    print(f"Environment: {config.environment.name}")
    print(f"Markets: {len(markets)}")
    for market in markets:
        print(
            f"- {market.get('symbol')} mark={market.get('mark_price', '-')} "
            f"oi={market.get('open_interest', '-')} {market_label(market)}"
        )


def handle_book(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        config = load_config(args.env, require_keys=False)
    except ValueError as exc:
        parser.error(str(exc))

    symbols = parse_symbols(args.symbols) + parse_symbols(args.symbol)
    if not symbols:
        parser.error("Provide one or more symbols.")
    if len(symbols) > 50:
        parser.error("Book lookup supports at most 50 symbols.")

    books = get_books(config.environment, symbols)
    if args.json:
        print(compact_json(books))
        return
    print(f"Environment: {config.environment.name}")
    for symbol in symbols:
        book = books.get(symbol, {})
        if not isinstance(book, dict):
            print(f"{symbol}: no book returned")
            continue
        best_bid, best_ask = best_bid_ask(book)
        _, bid_size = best_level(book, "bids")
        _, ask_size = best_level(book, "asks")
        print(
            f"{symbol}: best_bid={best_bid or '-'} bid_size={bid_size or '-'} "
            f"best_ask={best_ask or '-'} ask_size={ask_size or '-'}"
        )


def handle_orders(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    environment, owner = load_read_account(parser, args)
    state = get_account_state(environment, owner)
    raw_orders = state.get("orders", [])
    orders = (
        [order for order in raw_orders if isinstance(order, dict)]
        if isinstance(raw_orders, list)
        else []
    )
    if args.symbol:
        orders = [order for order in orders if order.get("symbol") == args.symbol]
    if args.json:
        print(compact_json(orders))
        return
    print(f"Environment: {environment.name}")
    print(f"Owner: {owner}")
    print(f"Open orders: {len(orders)}")
    for order in orders:
        print(
            f"- id={order.get('id', '-')} client_id={order.get('client_order_id', '-')} "
            f"{order.get('symbol', '-')} {order.get('side', '-')} "
            f"price={order.get('price', '-')} remaining={order.get('size_remaining', '-')}"
        )


def handle_positions(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    environment, owner = load_read_account(parser, args)
    state = get_account_state(environment, owner)
    raw_positions = state.get("positions", [])
    positions = (
        [position for position in raw_positions if isinstance(position, dict)]
        if isinstance(raw_positions, list)
        else []
    )
    if args.symbol:
        positions = [position for position in positions if position.get("symbol") == args.symbol]
    if args.json:
        print(compact_json(positions))
        return
    print(f"Environment: {environment.name}")
    print(f"Owner: {owner}")
    print(f"Positions: {len(positions)}")
    for position in positions:
        print(
            f"- {position.get('symbol', '-')} size={position.get('size', '-')} "
            f"mark={position.get('mark_price', '-')} "
            f"avg_entry={position.get('average_entry_price', '-')} "
            f"realized={position.get('realized_pnl_usd', '-')} "
            f"unrealized={position.get('unrealized_pnl_usd', '-')}"
        )


def handle_deposit_address(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    environment, owner = load_read_account(parser, args)
    data = get_deposit_address(environment, owner)
    print(compact_json(data))


def fetch_history_page(
    kind: HistoryKind,
    environment: PascalEnvironment,
    owner: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    symbols = parse_symbols(args.symbol)
    if kind == "fills":
        return list_account_fills(
            environment,
            owner,
            symbols=symbols,
            limit=args.limit,
            before_cursor=args.before_cursor,
            at_or_before_seq=args.at_or_before_seq,
        )
    if kind == "transfers":
        return list_account_transfers(
            environment,
            owner,
            limit=args.limit,
            before_cursor=args.before_cursor,
            at_or_before_seq=args.at_or_before_seq,
        )
    return list_position_resolutions(
        environment,
        owner,
        limit=args.limit,
        before_cursor=args.before_cursor,
        at_or_before_seq=args.at_or_before_seq,
    )


def print_history_rows(kind: HistoryKind, data: dict[str, Any]) -> None:
    items = page_items(data)
    print(f"{kind}: {len(items)}")
    if kind == "fills":
        print_table(
            items,
            [
                ("time_ms", "trade_ts_ms"),
                ("seq", "seq"),
                ("symbol", "symbol"),
                ("side", "side"),
                ("price", "fill_price"),
                ("size", "fill_size"),
                ("liq", "liquidity"),
                ("fee", "fee_usd"),
                ("realized", "realized_pnl_usd"),
                ("client_id", "client_order_id"),
            ],
        )
    elif kind == "transfers":
        print_table(
            items,
            [
                ("time_ms", "transfer_ts_ms"),
                ("seq", "seq"),
                ("type", "type"),
                ("status", "status"),
                ("net", "net_usd"),
                ("fee", "fee_usd"),
                ("collateral", "collateral_change_usd"),
            ],
        )
    else:
        print_table(
            items,
            [
                ("time_ms", "position_resolution_ts_ms"),
                ("seq", "seq"),
                ("symbol", "symbol"),
                ("resolution", "resolution"),
                ("size", "size"),
                ("realized", "realized_pnl_usd"),
                ("collateral", "collateral_change_usd"),
            ],
        )
    next_cursor = data.get("next_cursor")
    if next_cursor:
        print(f"next_cursor={next_cursor}")


def handle_history(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    environment, owner = load_read_account(parser, args)
    if args.kind == "all":
        data = {
            kind: fetch_history_page(kind, environment, owner, args)
            for kind in ("fills", "transfers", "position-resolutions")
        }
        if args.json:
            print(compact_json(data))
            return
        print(f"Environment: {environment.name}")
        print(f"Owner: {owner}")
        for index, kind in enumerate(("fills", "transfers", "position-resolutions")):
            if index:
                print()
            print_history_rows(kind, data[kind])
        return

    data = fetch_history_page(args.kind, environment, owner, args)
    if args.json:
        print(compact_json(data))
        return
    print(f"Environment: {environment.name}")
    print(f"Owner: {owner}")
    print_history_rows(args.kind, data)


def latest_point(points: Any) -> tuple[str, str]:
    if not isinstance(points, list) or not points:
        return "-", "-"
    point = points[-1]
    if not isinstance(point, list | tuple) or len(point) < 2:
        return "-", "-"
    return string_value(point[0]), string_value(point[1])


def handle_pnl(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    environment, owner = load_read_account(parser, args)
    data = get_account_history(environment, owner)
    if args.json:
        print(compact_json(data))
        return

    rows: list[dict[str, Any]] = []
    for item in page_items(data):
        series = item.get("data", {})
        if not isinstance(series, dict):
            series = {}
        account_points = series.get("account_value_history", [])
        pnl_points = series.get("pnl_history", [])
        account_time, account_value = latest_point(account_points)
        pnl_time, pnl_value = latest_point(pnl_points)
        rows.append(
            {
                "timeframe": item.get("timeframe"),
                "account_time_ms": account_time,
                "account_value": account_value,
                "pnl_time_ms": pnl_time,
                "pnl": pnl_value,
                "account_points": len(account_points) if isinstance(account_points, list) else 0,
                "pnl_points": len(pnl_points) if isinstance(pnl_points, list) else 0,
            }
        )

    print(f"Environment: {environment.name}")
    print(f"Owner: {owner}")
    print_table(
        rows,
        [
            ("timeframe", "timeframe"),
            ("account_time_ms", "account_time_ms"),
            ("account_value", "account_value"),
            ("pnl_time_ms", "pnl_time_ms"),
            ("pnl", "pnl"),
            ("acct_pts", "account_points"),
            ("pnl_pts", "pnl_points"),
        ],
    )


def submit_order(config: PascalConfig, request: dict[str, Any], *, send: bool) -> None:
    body = [request]
    print("Request JSON:")
    print(pretty_json(body))
    if not send:
        print()
        print("Dry run only. Re-run with --send to post this order.")
        return
    response = post_json(f"{config.environment.write_base_url}/api/v1/orders", body)
    print()
    print("Response JSON:")
    print(pretty_json(response))


def submit_cancel(config: PascalConfig, request: dict[str, Any], *, send: bool) -> None:
    body = [request]
    print("Request JSON:")
    print(pretty_json(body))
    if not send:
        print()
        print("Dry run only. Re-run with --send to post this cancel.")
        return
    response = post_json(f"{config.environment.write_base_url}/api/v1/cancels", body)
    print()
    print("Response JSON:")
    print(pretty_json(response))


def resolve_order_symbol(config: PascalConfig, symbol: str | None) -> str:
    return symbol or choose_symbol(config.environment)


def client_order_id(value: int | None) -> int:
    return value if value is not None else now_ms()


def handle_limit_order(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    config = load_trading_config(parser, args)
    try:
        request = signed_place_order_request(
            deployment_id=config.environment.deployment_id,
            owner_public_key=config.owner_public_key,
            trading_private_key=config.trading_private_key,
            client_order_id=client_order_id(args.client_order_id),
            replace_client_order_id=args.replace_client_order_id,
            symbol=resolve_order_symbol(config, args.symbol),
            side=args.side,
            price=args.price,
            size=args.size,
            tif=args.tif,
            expires_ts_ms=args.expires_ts_ms,
            post_only=args.post_only,
            reduce_only=args.reduce_only,
            recv_window_ms=args.recv_window_ms,
        )
    except (KeyParseError, ValueError) as exc:
        parser.error(str(exc))
    submit_order(config, request, send=args.send)


def market_price(side: Side, explicit_price: str | None) -> str:
    if explicit_price is not None:
        return explicit_price
    return "1.000000" if side == "BID" else "0.010000"


def handle_market_order(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    config = load_trading_config(parser, args)
    try:
        request = signed_place_order_request(
            deployment_id=config.environment.deployment_id,
            owner_public_key=config.owner_public_key,
            trading_private_key=config.trading_private_key,
            client_order_id=client_order_id(args.client_order_id),
            symbol=resolve_order_symbol(config, args.symbol),
            side=args.side,
            price=market_price(args.side, args.price),
            size=args.size,
            tif="IOC",
            post_only=False,
            reduce_only=args.reduce_only,
            order_type="MARKET",
            recv_window_ms=args.recv_window_ms,
        )
    except (KeyParseError, ValueError) as exc:
        parser.error(str(exc))
    submit_order(config, request, send=args.send)


def handle_cancel_order(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if (args.client_order_id is None) == (args.order_id is None):
        parser.error("Provide exactly one of --client-order-id or --order-id.")

    config = load_trading_config(parser, args)
    try:
        request = signed_cancel_order_request(
            deployment_id=config.environment.deployment_id,
            owner_public_key=config.owner_public_key,
            trading_private_key=config.trading_private_key,
            client_order_id=args.client_order_id,
            order_id=args.order_id,
            recv_window_ms=args.recv_window_ms,
        )
    except (KeyParseError, ValueError) as exc:
        parser.error(str(exc))
    submit_cancel(config, request, send=args.send)


def build_markets_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "markets",
        "List active Pascal markets.",
        [
            "cli markets --limit 10",
            "cli markets --query senate --limit 20",
            "cli markets --limit 5 --json",
        ],
    )
    add_env(parser)
    parser.add_argument("--limit", type=int, default=20, help="Maximum markets to print.")
    parser.add_argument("--query", help="Filter by symbol, event, or market text.")
    parser.add_argument("--strict", action=argparse.BooleanOptionalAction, default=True)
    add_json(parser)
    return parser


def build_book_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "book",
        "Get top-of-book prices for one or more markets.",
        [
            "cli book ME_SEN_2026.REP",
            "cli book ME_SEN_2026.REP AI_BEST_MODEL_26JUL31.GOOGLE",
            "cli book --symbol ME_SEN_2026.REP --json",
        ],
    )
    add_env(parser)
    parser.add_argument("symbols", nargs="*", help="Market symbols to fetch.")
    parser.add_argument(
        "--symbol",
        action="append",
        help="Market symbol to fetch. May be repeated or comma-delimited.",
    )
    add_json(parser)
    return parser


def build_orders_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "orders",
        "List open orders for an owner account.",
        [
            "cli orders --owner <owner-wallet-public-key>",
            "cli orders --symbol ME_SEN_2026.REP",
            "cli orders --json",
        ],
    )
    add_env(parser)
    add_owner(parser)
    parser.add_argument("--symbol", help="Only show orders for this market symbol.")
    add_json(parser)
    return parser


def build_positions_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "positions",
        "List open positions for an owner account.",
        [
            "cli positions --owner <owner-wallet-public-key>",
            "cli positions --symbol ME_SEN_2026.REP",
            "cli positions --json",
        ],
    )
    add_env(parser)
    add_owner(parser)
    parser.add_argument("--symbol", help="Only show this market position.")
    add_json(parser)
    return parser


def build_deposit_address_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "deposit-address",
        "Get the registered deposit address for an owner account.",
        [
            "cli deposit-address --owner <owner-wallet-public-key>",
            "cli deposit-address --env prod",
        ],
    )
    add_env(parser)
    add_owner(parser)
    return parser


def build_history_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "history",
        "Get account fills, transfers, and position-resolution history.",
        [
            "cli history",
            "cli history --kind fills --symbol ME_SEN_2026.REP --limit 25",
            "cli history --kind transfers --before-cursor <next_cursor> --json",
            "cli history --kind position-resolutions --limit 25",
        ],
    )
    add_env(parser)
    add_owner(parser)
    parser.add_argument(
        "--kind",
        default="all",
        choices=["all", "fills", "transfers", "position-resolutions"],
    )
    parser.add_argument(
        "--symbol",
        action="append",
        help="Market symbol filter for fills. May be repeated or comma-delimited.",
    )
    add_pagination(parser)
    add_json(parser)
    return parser


def build_pnl_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "pnl",
        "Get account value and PnL time series.",
        [
            "cli pnl",
            "cli pnl --json",
            "cli pnl --owner <owner-wallet-public-key>",
        ],
    )
    add_env(parser)
    add_owner(parser)
    add_json(parser)
    return parser


def build_limit_order_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "limit-order",
        "Build and optionally send a signed limit order.",
        [
            "cli limit-order --symbol ME_SEN_2026.REP --side BID --price 0.450000 --size 1",
            "cli limit-order --symbol ME_SEN_2026.REP --side ASK "
            "--price 0.550000 --size 1 --post-only",
            "cli limit-order --symbol ME_SEN_2026.REP --side BID --price 0.450000 --size 1 --send",
        ],
    )
    add_order_common(parser)
    parser.add_argument(
        "--price", default="0.010000", help="Limit price as a decimal string, 6 d.p."
    )
    parser.add_argument("--replace-client-order-id", type=int)
    parser.add_argument("--tif", default="GTC", choices=["GTC", "GTT", "IOC"])
    parser.add_argument("--expires-ts-ms", type=int)
    parser.add_argument("--post-only", action=argparse.BooleanOptionalAction, default=False)
    return parser


def build_market_order_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "market-order",
        "Build and optionally send a signed IOC market order.",
        [
            "cli market-order --symbol ME_SEN_2026.REP --side BID --size 1",
            "cli market-order --symbol ME_SEN_2026.REP --side ASK --size 1 --price 0.010000",
            "cli market-order --symbol ME_SEN_2026.REP --side BID --size 1 --send",
        ],
    )
    add_order_common(parser)
    parser.add_argument(
        "--price",
        help="Optional protection price. Defaults to 1.000000 for BID and 0.010000 for ASK.",
    )
    return parser


def build_cancel_order_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "cancel-order",
        "Build and optionally send a signed order cancel.",
        [
            "cli cancel-order --client-order-id 1783261000000",
            "cli cancel-order --order-id 185499743",
            "cli cancel-order --client-order-id 1783261000000 --send",
        ],
    )
    add_env(parser)
    parser.add_argument("--send", action="store_true", help="Actually post the write request.")
    parser.add_argument("--client-order-id", type=int, help="Cancel by client-assigned order id.")
    parser.add_argument("--order-id", type=int, help="Cancel by exchange-assigned order id.")
    parser.add_argument("--recv-window-ms", type=int, default=5000)
    return parser


COMMANDS: dict[str, Command] = {
    "markets": Command("List markets.", build_markets_parser, handle_markets),
    "book": Command("Get top-of-book prices.", build_book_parser, handle_book, requires_args=True),
    "orders": Command("List open orders.", build_orders_parser, handle_orders),
    "positions": Command("List open positions.", build_positions_parser, handle_positions),
    "deposit-address": Command(
        "Get an account deposit address.", build_deposit_address_parser, handle_deposit_address
    ),
    "history": Command("Get account event history.", build_history_parser, handle_history),
    "pnl": Command("Get account value and PnL history.", build_pnl_parser, handle_pnl),
    "limit-order": Command(
        "Dry-run or send a limit order.",
        build_limit_order_parser,
        handle_limit_order,
        requires_args=True,
    ),
    "market-order": Command(
        "Dry-run or send a market order.",
        build_market_order_parser,
        handle_market_order,
        requires_args=True,
    ),
    "cancel-order": Command(
        "Dry-run or send an order cancel.",
        build_cancel_order_parser,
        handle_cancel_order,
        requires_args=True,
    ),
}


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print_main_help()
        return

    command_name = args[0]
    command = COMMANDS.get(command_name)
    if command is None:
        known = ", ".join(COMMANDS)
        raise SystemExit(f"Unknown command {command_name!r}. Known commands: {known}")

    parser = command.build_parser()
    if len(args) == 1 and command.requires_args:
        parser.print_help()
        return

    parsed = parser.parse_args(args[1:])
    try:
        command.handler(parser, parsed)
    except PascalHTTPError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
