from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

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
    price_to_micro_dollars,
    signed_cancel_order_request,
    signed_place_order_request,
)

Handler = Callable[[argparse.ArgumentParser, argparse.Namespace], None]
Side = Literal["BID", "ASK"]
TimeInForce = Literal["GTC", "GTT", "IOC"]
OrderType = Literal["LIMIT", "MARKET"]
HistoryKind = Literal["all", "fills", "transfers", "position-resolutions"]
MAX_ORDER_BATCH_SIZE = 50
MAX_CANCEL_BATCH_SIZE = 50
MAX_CLIENT_ORDER_ID = (1 << 64) - 2
MAX_U64 = (1 << 64) - 1
ORDER_SPEC_FIELDS = {
    "allow_missing_replace",
    "client_order_id",
    "expires_ts_ms",
    "post_only",
    "price",
    "reduce_only",
    "replace_client_order_id",
    "side",
    "size",
    "symbol",
    "tif",
    "type",
}


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
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    try:
        config = load_config(args.env, require_keys=False)
        markets = list_markets(config.environment)
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


def submit_orders(
    config: PascalConfig,
    requests: list[dict[str, Any]],
    *,
    send: bool,
    dry_run_message: str,
) -> None:
    body = requests
    print("Request JSON:")
    print(pretty_json(body))
    if not send:
        print()
        print(dry_run_message)
        return
    response = post_json(f"{config.environment.write_base_url}/api/v1/orders", body)
    print()
    print("Response JSON:")
    print(pretty_json(response))


def submit_order(config: PascalConfig, request: dict[str, Any], *, send: bool) -> None:
    submit_orders(
        config,
        [request],
        send=send,
        dry_run_message="Dry run only. Re-run with --send to post this order.",
    )


def submit_cancels(
    config: PascalConfig,
    requests: list[dict[str, Any]],
    *,
    send: bool,
    dry_run_message: str,
) -> None:
    body = requests
    print("Request JSON:")
    print(pretty_json(body))
    if not send:
        print()
        print(dry_run_message)
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


def format_micro_price(micro_price: int) -> str:
    return f"{micro_price // 1_000_000}.{micro_price % 1_000_000:06d}"


def order_field(index: int, name: str) -> str:
    return f"orders[{index}].{name}"


def read_order_specs(source: str) -> list[dict[str, Any]]:
    if source == "-":
        text = sys.stdin.read()
    elif source.lstrip().startswith("["):
        text = source
    else:
        try:
            text = Path(source).read_text()
        except OSError as exc:
            raise ValueError(f"Could not read order JSON from {source!r}: {exc}") from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Order input must be valid JSON: {exc}") from exc

    if not isinstance(raw, list):
        raise ValueError("Order input must be a JSON array.")
    if not raw:
        raise ValueError("Order input must contain at least one order.")
    if len(raw) > MAX_ORDER_BATCH_SIZE:
        raise ValueError(f"Order input may contain at most {MAX_ORDER_BATCH_SIZE} orders.")

    specs: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"orders[{index}] must be a JSON object.")
        specs.append(item)
    return specs


def require_string(spec: dict[str, Any], index: int, name: str) -> str:
    value = spec.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{order_field(index, name)} must be a non-empty string.")
    return value


def choice_field(
    spec: dict[str, Any],
    index: int,
    name: str,
    choices: tuple[str, ...],
    default: str | None = None,
) -> str:
    value = spec.get(name, default)
    if value is None:
        raise ValueError(f"{order_field(index, name)} must be one of: {', '.join(choices)}.")
    if not isinstance(value, str):
        raise ValueError(f"{order_field(index, name)} must be one of: {', '.join(choices)}.")
    normalized = value.upper()
    if normalized not in choices:
        raise ValueError(f"{order_field(index, name)} must be one of: {', '.join(choices)}.")
    return normalized


def bool_field(spec: dict[str, Any], index: int, name: str, *, default: bool = False) -> bool:
    value = spec.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{order_field(index, name)} must be true or false.")
    return value


def int_field(
    spec: dict[str, Any],
    index: int,
    name: str,
    *,
    required: bool,
    default: int | None = None,
    minimum: int = 0,
    maximum: int = MAX_U64,
) -> int | None:
    value = spec.get(name, default)
    if value is None:
        if required:
            raise ValueError(f"{order_field(index, name)} is required.")
        return None
    if isinstance(value, bool):
        raise ValueError(f"{order_field(index, name)} must be an integer.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isdecimal():
        parsed = int(value)
    else:
        raise ValueError(f"{order_field(index, name)} must be an integer.")
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{order_field(index, name)} must be between {minimum} and {maximum}.")
    return parsed


def price_field(spec: dict[str, Any], index: int) -> str | None:
    value = spec.get("price")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise ValueError(f"{order_field(index, 'price')} must be a decimal string.")
    try:
        micro_price = price_to_micro_dollars(str(value))
    except ValueError as exc:
        raise ValueError(f"{order_field(index, 'price')}: {exc}") from exc
    return format_micro_price(micro_price)


def signed_order_requests_from_specs(
    config: PascalConfig,
    specs: list[dict[str, Any]],
    *,
    base_client_order_id: int | None = None,
    client_ts_ms: int | None = None,
    recv_window_ms: int = 5000,
) -> list[dict[str, Any]]:
    if len(specs) > MAX_ORDER_BATCH_SIZE:
        raise ValueError(f"Order input may contain at most {MAX_ORDER_BATCH_SIZE} orders.")
    auth_ts_ms = client_ts_ms if client_ts_ms is not None else now_ms()
    generated_client_order_id = (
        base_client_order_id if base_client_order_id is not None else auth_ts_ms
    )
    requests: list[dict[str, Any]] = []
    seen_client_order_ids: set[int] = set()

    for index, spec in enumerate(specs):
        unknown_fields = sorted(set(spec) - ORDER_SPEC_FIELDS)
        if unknown_fields:
            joined = ", ".join(unknown_fields)
            raise ValueError(f"orders[{index}] has unsupported field(s): {joined}.")

        order_type = cast(
            OrderType, choice_field(spec, index, "type", ("LIMIT", "MARKET"), "LIMIT")
        )
        side = cast(Side, choice_field(spec, index, "side", ("BID", "ASK")))
        tif_default = "IOC" if order_type == "MARKET" else "GTC"
        tif = cast(
            TimeInForce, choice_field(spec, index, "tif", ("GTC", "GTT", "IOC"), tif_default)
        )
        if order_type == "MARKET" and tif != "IOC":
            raise ValueError(f"{order_field(index, 'tif')} must be IOC for MARKET orders.")

        default_client_id = generated_client_order_id + index
        if spec.get("client_order_id") is None:
            if default_client_id < 0 or default_client_id > MAX_CLIENT_ORDER_ID:
                raise ValueError(
                    f"generated {order_field(index, 'client_order_id')} must be between "
                    f"0 and {MAX_CLIENT_ORDER_ID}."
                )
            client_id = default_client_id
        else:
            client_id = int_field(
                spec,
                index,
                "client_order_id",
                required=True,
                maximum=MAX_CLIENT_ORDER_ID,
            )
            if client_id is None:
                raise ValueError(f"{order_field(index, 'client_order_id')} is required.")
        if client_id in seen_client_order_ids:
            raise ValueError(f"Duplicate client_order_id in batch: {client_id}.")
        seen_client_order_ids.add(client_id)

        replace_client_order_id = int_field(
            spec,
            index,
            "replace_client_order_id",
            required=False,
            maximum=MAX_CLIENT_ORDER_ID,
        )
        expires_ts_ms = int_field(spec, index, "expires_ts_ms", required=False)
        size = int_field(spec, index, "size", required=True, minimum=1)
        if size is None:
            raise ValueError(f"{order_field(index, 'size')} is required.")
        post_only = bool_field(spec, index, "post_only")
        reduce_only = bool_field(spec, index, "reduce_only")
        allow_missing_replace = bool_field(spec, index, "allow_missing_replace")
        if allow_missing_replace and replace_client_order_id is None:
            raise ValueError(
                f"{order_field(index, 'allow_missing_replace')} requires "
                f"{order_field(index, 'replace_client_order_id')}."
            )

        price = price_field(spec, index)
        if price is None:
            if order_type != "MARKET":
                raise ValueError(f"{order_field(index, 'price')} is required for LIMIT orders.")
            price = market_price(side, None)

        requests.append(
            signed_place_order_request(
                deployment_id=config.environment.deployment_id,
                owner_public_key=config.owner_public_key,
                trading_private_key=config.trading_private_key,
                client_order_id=client_id,
                replace_client_order_id=replace_client_order_id,
                symbol=require_string(spec, index, "symbol"),
                side=side,
                price=price,
                size=size,
                tif=tif,
                expires_ts_ms=expires_ts_ms,
                post_only=post_only,
                reduce_only=reduce_only,
                allow_missing_replace=allow_missing_replace,
                order_type=order_type,
                client_ts_ms=auth_ts_ms,
                recv_window_ms=recv_window_ms,
            )
        )

    return requests


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


def handle_batch_orders(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    config = load_trading_config(parser, args)
    try:
        specs = read_order_specs(args.orders_json)
        requests = signed_order_requests_from_specs(
            config,
            specs,
            base_client_order_id=args.base_client_order_id,
            recv_window_ms=args.recv_window_ms,
        )
    except (KeyParseError, ValueError) as exc:
        parser.error(str(exc))
    submit_orders(
        config,
        requests,
        send=args.send,
        dry_run_message="Dry run only. Re-run with --send to post this order batch.",
    )


def parse_id_values(
    values: list[list[str]] | None,
    *,
    name: str,
    maximum: int,
) -> list[int]:
    ids: list[int] = []
    for group in values or []:
        for raw_value in group:
            for item in raw_value.split(","):
                value = item.strip()
                if not value:
                    continue
                if not value.isdecimal():
                    raise ValueError(f"{name} must contain unsigned integer ids.")
                parsed = int(value)
                if parsed > maximum:
                    raise ValueError(f"{name} ids must be between 0 and {maximum}.")
                ids.append(parsed)
    return ids


def signed_cancel_requests_from_ids(
    config: PascalConfig,
    *,
    client_order_ids: list[int],
    order_ids: list[int],
    recv_window_ms: int = 5000,
) -> list[dict[str, Any]]:
    total = len(client_order_ids) + len(order_ids)
    if total == 0:
        raise ValueError("Provide at least one --client-order-id or --order-id.")
    if total > MAX_CANCEL_BATCH_SIZE:
        raise ValueError(f"Cancel batches may contain at most {MAX_CANCEL_BATCH_SIZE} ids.")
    if len(set(client_order_ids)) != len(client_order_ids):
        raise ValueError("Duplicate --client-order-id value in cancel batch.")
    if len(set(order_ids)) != len(order_ids):
        raise ValueError("Duplicate --order-id value in cancel batch.")

    auth_ts_ms = now_ms()
    requests: list[dict[str, Any]] = []
    for client_order_id_value in client_order_ids:
        requests.append(
            signed_cancel_order_request(
                deployment_id=config.environment.deployment_id,
                owner_public_key=config.owner_public_key,
                trading_private_key=config.trading_private_key,
                client_order_id=client_order_id_value,
                client_ts_ms=auth_ts_ms,
                recv_window_ms=recv_window_ms,
            )
        )
    for order_id_value in order_ids:
        requests.append(
            signed_cancel_order_request(
                deployment_id=config.environment.deployment_id,
                owner_public_key=config.owner_public_key,
                trading_private_key=config.trading_private_key,
                order_id=order_id_value,
                client_ts_ms=auth_ts_ms,
                recv_window_ms=recv_window_ms,
            )
        )
    return requests


def handle_cancel_order(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    config = load_trading_config(parser, args)
    try:
        requests = signed_cancel_requests_from_ids(
            config,
            client_order_ids=parse_id_values(
                args.client_order_id,
                name="--client-order-id",
                maximum=MAX_CLIENT_ORDER_ID,
            ),
            order_ids=parse_id_values(args.order_id, name="--order-id", maximum=MAX_U64),
            recv_window_ms=args.recv_window_ms,
        )
    except (KeyParseError, ValueError) as exc:
        parser.error(str(exc))
    submit_cancels(
        config,
        requests,
        send=args.send,
        dry_run_message="Dry run only. Re-run with --send to post this cancel batch.",
    )


def build_markets_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "markets",
        "List active Pascal markets.",
        [
            "cli markets",
            "cli markets --limit 10",
            "cli markets --query senate --limit 20",
            "cli markets --limit 5 --json",
        ],
    )
    add_env(parser)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum markets to print. Omit to print all live markets.",
    )
    parser.add_argument("--query", help="Filter by symbol, event, or market text.")
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


def build_batch_orders_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "batch-orders",
        "Build and optionally send signed orders from an unsigned JSON array.",
        [
            "cli batch-orders orders.json",
            "cli batch-orders - < orders.json",
            'cli batch-orders \'[{"symbol":"ME_SEN_2026.REP","side":"BID",'
            '"price":"0.450000","size":1}]\'',
            "cli batch-orders orders.json --base-client-order-id 1783261000000 --send",
        ],
    )
    add_env(parser)
    parser.add_argument("--send", action="store_true", help="Actually post the write request.")
    parser.add_argument(
        "--recv-window-ms",
        type=int,
        default=5000,
        help="Request receive window used for every order signature.",
    )
    parser.add_argument(
        "--base-client-order-id",
        type=int,
        help="First generated client_order_id. Defaults to the current millisecond timestamp.",
    )
    parser.add_argument(
        "orders_json",
        help="Unsigned JSON array, path to a JSON file, or '-' to read the array from stdin.",
    )
    return parser


def build_cancel_order_parser() -> argparse.ArgumentParser:
    parser = command_parser(
        "cancel-order",
        "Build and optionally send one or more signed order cancels.",
        [
            "cli cancel-order --client-order-id 1783261000000",
            "cli cancel-order --client-order-id 1783261000000 1783261000001",
            "cli cancel-order --client-order-id 1783261000000,1783261000001",
            "cli cancel-order --order-id 185499743",
            "cli cancel-order --client-order-id 1783261000000 --send",
        ],
    )
    add_env(parser)
    parser.add_argument("--send", action="store_true", help="Actually post the write request.")
    parser.add_argument(
        "--client-order-id",
        action="append",
        nargs="+",
        metavar="ID",
        help=(
            "Cancel by client-assigned order id. May be repeated, comma-delimited, "
            "or followed by multiple ids."
        ),
    )
    parser.add_argument(
        "--order-id",
        action="append",
        nargs="+",
        metavar="ID",
        help=(
            "Cancel by exchange-assigned order id. May be repeated, comma-delimited, "
            "or followed by multiple ids."
        ),
    )
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
    "batch-orders": Command(
        "Dry-run or send a JSON array of orders.",
        build_batch_orders_parser,
        handle_batch_orders,
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
