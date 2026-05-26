from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pascal_quickstart.config import PascalConfig
from pascal_quickstart.market_data import decimal_six
from pascal_quickstart.signing import signed_cancel_order_request, signed_place_order_request

Side = Literal["BID", "ASK"]
Slot = tuple[Side, int]
Order = dict[str, Any]

LEVEL_SIZES = (1, 3, 5)
SIDES: tuple[Side, Side] = ("BID", "ASK")
PRICE_STEP = Decimal("0.010000")
CLIENT_ORDER_ID_STRIDE = 10


@dataclass(frozen=True)
class Quote:
    """One desired quote level."""

    side: Side
    level: int
    price: str
    size: int


def account_parts(state: Order, symbol: str) -> tuple[list[Order], Order | None, int]:
    orders = state.get("orders", [])
    open_orders = (
        [order for order in orders if isinstance(order, dict)] if isinstance(orders, list) else []
    )

    positions = state.get("positions", [])
    if not isinstance(positions, list):
        return open_orders, None, 0
    for position in positions:
        if isinstance(position, dict) and position.get("symbol") == symbol:
            return open_orders, position, int(str(position.get("size", "0")))
    return open_orders, None, 0


def all_slots() -> list[Slot]:
    return [(side, level) for side in SIDES for level in range(len(LEVEL_SIZES))]


def slot_offset(side: Side, level: int) -> int:
    return level if side == "BID" else 5 + level


def order_id(order: Order) -> int:
    return int(str(order["client_order_id"]))


def order_slot(order: Order, *, symbol: str, base_client_order_id: int) -> Slot | None:
    if order.get("symbol") != symbol:
        return None
    try:
        client_id = order_id(order)
    except (KeyError, TypeError, ValueError):
        return None
    if client_id < base_client_order_id:
        return None

    side = order.get("side")
    remainder = (client_id - base_client_order_id) % CLIENT_ORDER_ID_STRIDE
    if side == "BID" and 0 <= remainder < len(LEVEL_SIZES):
        return "BID", remainder
    if side == "ASK" and 5 <= remainder < 5 + len(LEVEL_SIZES):
        return "ASK", remainder - 5
    return None


def group_bot_orders(
    open_orders: list[Order], *, symbol: str, base_client_order_id: int
) -> dict[Slot, list[Order]]:
    grouped = {slot: [] for slot in all_slots()}
    for order in open_orders:
        slot = order_slot(order, symbol=symbol, base_client_order_id=base_client_order_id)
        if slot is not None:
            grouped[slot].append(order)
    for orders in grouped.values():
        orders.sort(key=order_id)
    return grouped


def flatten_orders(grouped: dict[Slot, list[Order]]) -> list[Order]:
    return sorted([order for orders in grouped.values() for order in orders], key=order_id)


def seed_next_ids(
    open_orders: list[Order], *, symbol: str, base_client_order_id: int
) -> dict[Slot, int]:
    """Seed per-slot client IDs from open orders so replacements get fresh IDs."""

    grouped = group_bot_orders(
        open_orders, symbol=symbol, base_client_order_id=base_client_order_id
    )
    next_ids: dict[Slot, int] = {}
    for side, level in all_slots():
        default = base_client_order_id + slot_offset(side, level)
        ids = [order_id(order) for order in grouped[(side, level)]]
        next_ids[(side, level)] = max(ids, default=default - CLIENT_ORDER_ID_STRIDE) + (
            CLIENT_ORDER_ID_STRIDE
        )
    return next_ids


def take_next_id(next_ids: dict[Slot, int], side: Side, level: int) -> int:
    slot = (side, level)
    client_id = next_ids[slot]
    next_ids[slot] += CLIENT_ORDER_ID_STRIDE
    return client_id


def price_for_level(best_price: str, *, side: Side, level: int) -> str:
    raw = Decimal(best_price)
    distance = PRICE_STEP * Decimal(level + 1)
    if side == "BID":
        return decimal_six(max(raw - distance, Decimal("0.010000")))
    return decimal_six(min(raw + distance, Decimal("0.990000")))


def sign_place(
    config: PascalConfig,
    *,
    symbol: str,
    quote: Quote,
    client_order_id: int,
    replace_client_order_id: int | None,
    recv_window_ms: int,
) -> Order:
    return signed_place_order_request(
        deployment_id=config.environment.deployment_id,
        owner_public_key=config.owner_public_key,
        trading_private_key=config.trading_private_key,
        client_order_id=client_order_id,
        replace_client_order_id=replace_client_order_id,
        symbol=symbol,
        side=quote.side,
        price=quote.price,
        size=quote.size,
        post_only=True,
        recv_window_ms=recv_window_ms,
    )


def sign_cancel(config: PascalConfig, order: Order, recv_window_ms: int) -> Order:
    return signed_cancel_order_request(
        deployment_id=config.environment.deployment_id,
        owner_public_key=config.owner_public_key,
        trading_private_key=config.trading_private_key,
        client_order_id=order_id(order),
        recv_window_ms=recv_window_ms,
    )


def format_reconcile_row(
    side: Side, level: int, quote: Quote | None, current: Order | None, action: str, reason: str
) -> str:
    quote_price = quote.price if quote is not None else "-"
    quote_size = str(quote.size) if quote is not None else "-"
    current_id = str(current.get("client_order_id", "-")) if current is not None else "-"
    current_px = str(current.get("price", "-")) if current is not None else "-"
    current_size = str(current.get("size_remaining", "-")) if current is not None else "-"
    return (
        f"{side:<4} {level:<3} {quote_price:<10} {quote_size:<4} "
        f"{current_id:<10} {current_px:<10} {current_size:<12} {action:<8} {reason}"
    )


def print_heartbeat(
    best_bid: str | None,
    best_ask: str | None,
    position_size: int,
    bot_orders: list[Order],
    desired_count: int,
    pending_count: int,
) -> None:
    print(
        "heartbeat: "
        f"bbo={best_bid or '-'}/{best_ask or '-'} pos={position_size} "
        f"bot_orders={len(bot_orders)} desired={desired_count} pending={pending_count}"
    )
    print("open bot orders:")
    if not bot_orders:
        print("- none")
    for order in bot_orders:
        print(
            f"- id={order.get('client_order_id')} side={order.get('side')} "
            f"price={order.get('price')} remaining={order.get('size_remaining')}"
        )
