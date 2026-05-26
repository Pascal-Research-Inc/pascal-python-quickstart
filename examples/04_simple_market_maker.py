"""A tiny example market maker on Pascal.

Usage:
    uv run python examples/04_simple_market_maker.py
    uv run python examples/04_simple_market_maker.py --send

By default the script picks the first market, then quotes three bid and ask
levels sized 1/3/5 contracts at 1c/2c/3c from the BBO while keeping inventory
within --max-position. If one side has no BBO, the bot does not quote that side.

Ctrl+C cancels the bot's open orders.
"""

from __future__ import annotations

import argparse
import time

from simple_market_maker_helpers import (
    LEVEL_SIZES,
    Order,
    Quote,
    Side,
    Slot,
    account_parts,
    all_slots,
    flatten_orders,
    format_reconcile_row,
    group_bot_orders,
    order_id,
    price_for_level,
    print_heartbeat,
    seed_next_ids,
    sign_cancel,
    sign_place,
    take_next_id,
)

from pascal_quickstart.config import PascalConfig, load_config
from pascal_quickstart.http import post_json, pretty_json
from pascal_quickstart.market_data import (
    best_bid_ask,
    get_account_state,
    get_books,
    list_markets,
)


def desired_quotes(
    *,
    best_bid: str | None,
    best_ask: str | None,
    position_size: int,
    max_position: int,
) -> tuple[dict[Slot, Quote], dict[Slot, str]]:
    """Create the quote ladder allowed by the current BBO and position."""

    desired: dict[Slot, Quote] = {}
    skipped: dict[Slot, str] = {}
    side_inputs: tuple[tuple[Side, str | None, int], ...] = (
        ("BID", best_bid, max(0, max_position - position_size)),
        ("ASK", best_ask, max(0, max_position + position_size)),
    )

    for side, best_price, capacity in side_inputs:
        quoted_size = 0
        previous_price: str | None = None
        for level, size in enumerate(LEVEL_SIZES):
            slot = (side, level)
            if best_price is None:
                skipped[slot] = "no_best_bid" if side == "BID" else "no_best_ask"
                continue
            price = price_for_level(best_price, side=side, level=level)
            if price == previous_price:
                skipped[slot] = "duplicate_price"
            elif quoted_size + size > capacity:
                skipped[slot] = "position_bound"
            else:
                desired[slot] = Quote(side, level, price, size)
                quoted_size += size
            previous_price = price

    return desired, skipped


def reconcile(
    open_orders: list[Order],
    desired: dict[Slot, Quote],
    skipped: dict[Slot, str],
    *,
    config: PascalConfig,
    symbol: str,
    base_client_order_id: int,
    next_ids: dict[Slot, int],
    recv_window_ms: int,
) -> tuple[list[Order], list[Order], list[str], list[Order]]:
    """Turn current state plus desired quotes into one order batch and one cancel batch."""

    grouped = group_bot_orders(
        open_orders, symbol=symbol, base_client_order_id=base_client_order_id
    )
    order_body: list[Order] = []
    cancel_body: list[Order] = []
    rows: list[str] = []

    for side, level in all_slots():
        slot = (side, level)
        current = grouped[slot][-1] if grouped[slot] else None

        # Keep at most one open order per side/level slot.
        for duplicate in grouped[slot][:-1]:
            cancel_body.append(sign_cancel(config, duplicate, recv_window_ms))
            rows.append(
                format_reconcile_row(
                    side, level, desired.get(slot), duplicate, "CANCEL", "duplicate_slot"
                )
            )

        quote = desired.get(slot)
        if quote is None:
            # Stop quoting this slot when there is no BBO, a duplicate edge price,
            # or quoting the level would exceed the max-position bound.
            reason = skipped.get(slot, "not_desired")
            if current is not None:
                cancel_body.append(sign_cancel(config, current, recv_window_ms))
                rows.append(format_reconcile_row(side, level, None, current, "CANCEL", reason))
            else:
                rows.append(format_reconcile_row(side, level, None, None, "SKIP", reason))
            continue

        if current is None:
            # A missing quote can mean startup or a fill. In both cases place
            # with a fresh client id instead of trying to replace a missing order.
            order_body.append(
                sign_place(
                    config,
                    symbol=symbol,
                    quote=quote,
                    client_order_id=take_next_id(next_ids, side, level),
                    replace_client_order_id=None,
                    recv_window_ms=recv_window_ms,
                )
            )
            rows.append(format_reconcile_row(side, level, quote, None, "PLACE", "missing"))
            continue

        price_matches = current.get("price") == quote.price
        size_matches = current.get("size_remaining") == str(quote.size)
        if price_matches and size_matches:
            rows.append(format_reconcile_row(side, level, quote, current, "KEEP", "current"))
            continue

        reason = "price_changed" if not price_matches else "size_changed"
        if not price_matches and not size_matches:
            reason = "price_and_size_changed"
        order_body.append(
            sign_place(
                config,
                symbol=symbol,
                quote=quote,
                client_order_id=take_next_id(next_ids, side, level),
                replace_client_order_id=order_id(current),
                recv_window_ms=recv_window_ms,
            )
        )
        rows.append(format_reconcile_row(side, level, quote, current, "REPLACE", reason))

    return order_body, cancel_body, rows, flatten_orders(grouped)


def submit_batch(
    label: str, url: str, body: list[Order], *, send: bool, print_request: bool = True
) -> bool:
    """Print exact write JSON, optionally POST it, and return whether it failed."""

    if not body:
        return False
    if not send and not print_request:
        return False

    print(f"{label} request JSON:")
    print(pretty_json(body))
    if not send:
        print(f"{label}: {len(body)} prepared, 0 sent (dry run).")
        return False

    response = post_json(url, body)
    print(f"{label} response JSON:")
    print(pretty_json(response))
    envelopes = response if isinstance(response, list) else []
    errors = [
        envelope
        for envelope in envelopes
        if isinstance(envelope, dict) and envelope.get("status") == "error"
    ]
    successes = sum(
        1
        for envelope in envelopes
        if isinstance(envelope, dict) and envelope.get("status") == "success"
    )
    print(f"{label}: {len(body)} submitted, {successes} success, {len(errors)} error")
    for index, envelope in enumerate(envelopes):
        if not isinstance(envelope, dict) or envelope.get("status") != "error":
            continue
        data = envelope.get("data", {})
        code = data.get("code", "-") if isinstance(data, dict) else "-"
        message = data.get("message", "-") if isinstance(data, dict) else "-"
        print(f"- request_index={index} code={code} message={message}")
    return bool(errors) or not isinstance(response, list)


def sync_once(
    *,
    config: PascalConfig,
    symbol: str,
    base_client_order_id: int,
    next_ids: dict[Slot, int],
    max_position: int,
    recv_window_ms: int,
    send: bool,
    iteration: int,
    previous_position_size: int | None,
    last_debug: float,
    debug_seconds: float,
) -> tuple[int, float]:
    """Fetch account/book state, reconcile quotes, then submit cancel/order batches."""

    # One account-state call gives us open orders and positions.
    account_state = get_account_state(config.environment, config.owner_public_key)
    open_orders, position, position_size = account_parts(account_state, symbol)

    book = get_books(config.environment, [symbol]).get(symbol, {})
    best_bid, best_ask = best_bid_ask(book) if isinstance(book, dict) else (None, None)
    desired, skipped = desired_quotes(
        best_bid=best_bid,
        best_ask=best_ask,
        position_size=position_size,
        max_position=max_position,
    )
    order_body, cancel_body, rows, bot_orders = reconcile(
        open_orders,
        desired,
        skipped,
        config=config,
        symbol=symbol,
        base_client_order_id=base_client_order_id,
        next_ids=next_ids,
        recv_window_ms=recv_window_ms,
    )

    position_changed = previous_position_size is None or position_size != previous_position_size
    pending_count = len(order_body) + len(cancel_body)
    now = time.monotonic()
    should_print_debug = now - last_debug > debug_seconds
    should_print_reconcile = position_changed or (send and pending_count > 0) or should_print_debug

    if position_changed:
        old = "-" if previous_position_size is None else str(previous_position_size)
        print(f"Position changed: {old} -> {position_size}")
        print(pretty_json(position or {"symbol": symbol, "size": "0"}))

    if should_print_reconcile:
        print(
            f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] loop={iteration} symbol={symbol} "
            f"bbo={best_bid or '-'}/{best_ask or '-'} position={position_size}/{max_position} "
            f"bot_orders={len(bot_orders)} actions={pending_count}"
        )
        print("Reconcile:")
        print("side lvl desired_px size current_id current_px current_size action   reason")
        for row in rows:
            print(row)

    cancel_failed = submit_batch(
        "Cancel",
        f"{config.environment.write_base_url}/api/v1/cancels",
        cancel_body,
        send=send,
        print_request=should_print_reconcile,
    )
    order_failed = submit_batch(
        "Order",
        f"{config.environment.write_base_url}/api/v1/orders",
        order_body,
        send=send,
        print_request=should_print_reconcile,
    )
    if cancel_failed or order_failed:
        print("Write batch contained an error; next loop will refresh account state.")

    if should_print_debug:
        print_heartbeat(
            best_bid,
            best_ask,
            position_size,
            bot_orders,
            len(desired),
            pending_count,
        )
        last_debug = now
    return position_size, last_debug


def cancel_open_bot_orders(
    *,
    config: PascalConfig,
    symbol: str,
    base_client_order_id: int,
    recv_window_ms: int,
    send: bool,
) -> None:
    """Fetch open orders, cancel this bot's orders, and confirm cleanup."""

    account_state = get_account_state(config.environment, config.owner_public_key)
    open_orders, _, _ = account_parts(account_state, symbol)
    grouped = group_bot_orders(
        open_orders, symbol=symbol, base_client_order_id=base_client_order_id
    )
    body = [sign_cancel(config, order, recv_window_ms) for order in flatten_orders(grouped)]
    print(f"cleanup: found {len(body)} open bot order(s).")
    failed = submit_batch(
        "Cleanup cancel",
        f"{config.environment.write_base_url}/api/v1/cancels",
        body,
        send=send,
    )
    if failed:
        print("cleanup: cancel batch had errors; inspect response JSON above.")
    if send:
        account_state = get_account_state(config.environment, config.owner_public_key)
        open_orders, _, _ = account_parts(account_state, symbol)
        grouped = group_bot_orders(
            open_orders, symbol=symbol, base_client_order_id=base_client_order_id
        )
        print(f"cleanup: final open bot order count={len(flatten_orders(grouped))}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small Pascal post-only market maker.")
    parser.add_argument("--env", default="prod", help="Pascal environment name.")
    parser.add_argument("--send", action="store_true", help="Actually post write requests.")
    parser.add_argument("--symbol", help="Market symbol. Defaults to the first listed market.")
    parser.add_argument("--max-position", type=int, default=10)
    parser.add_argument("--base-client-order-id", type=int, default=10_000)
    parser.add_argument("--recv-window-ms", type=int, default=5000)
    parser.add_argument("--debug-seconds", type=float, default=5.0)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--iterations", type=int, help="Stop after this many loop iterations.")
    args = parser.parse_args()

    config = load_config(args.env)
    markets = list_markets(config.environment)
    if not markets:
        raise RuntimeError(f"No markets returned by {config.environment.read_base_url}")
    symbol = args.symbol or str(markets[0]["symbol"])

    account_state = get_account_state(config.environment, config.owner_public_key)
    open_orders, _, _ = account_parts(account_state, symbol)
    next_ids = seed_next_ids(
        open_orders, symbol=symbol, base_client_order_id=args.base_client_order_id
    )

    print(f"Symbol: {symbol}")
    print(f"Environment: {config.environment.name}")
    print(f"Max position: +/-{args.max_position}")
    if not args.send:
        print("Dry run only. Requests will be printed but not posted.")

    previous_position_size: int | None = None
    last_debug = 0.0
    iteration = 0
    try:
        while True:
            iteration += 1
            try:
                previous_position_size, last_debug = sync_once(
                    config=config,
                    symbol=symbol,
                    base_client_order_id=args.base_client_order_id,
                    next_ids=next_ids,
                    max_position=args.max_position,
                    recv_window_ms=args.recv_window_ms,
                    send=args.send,
                    iteration=iteration,
                    previous_position_size=previous_position_size,
                    last_debug=last_debug,
                    debug_seconds=args.debug_seconds,
                )
            except Exception as exc:
                print(f"Loop error: {exc}. Refreshing account state on next loop.")

            if args.iterations is not None and iteration >= args.iterations:
                return
            time.sleep(args.sleep_seconds)
    except KeyboardInterrupt:
        print()
        print("Interrupted. Canceling open market-maker orders.")
        cancel_open_bot_orders(
            config=config,
            symbol=symbol,
            base_client_order_id=args.base_client_order_id,
            recv_window_ms=args.recv_window_ms,
            send=args.send,
        )


if __name__ == "__main__":
    main()
