from __future__ import annotations

import argparse

from example_defaults import DEFAULT_CLIENT_ORDER_ID

from pascal_quickstart.config import load_config
from pascal_quickstart.http import post_json, pretty_json
from pascal_quickstart.market_data import choose_symbol
from pascal_quickstart.signing import signed_place_order_request


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and optionally send a signed Pascal order.")
    parser.add_argument("--env", default="prod", help="Pascal environment name.")
    parser.add_argument("--send", action="store_true", help="Actually post the write request.")
    parser.add_argument("--symbol", help="Market symbol. Defaults to the first listed market.")
    parser.add_argument("--side", default="BID", choices=["BID", "ASK"])
    parser.add_argument(
        "--price", default="0.010000", help="Decimal string with 6 fractional digits."
    )
    parser.add_argument("--size", type=int, default=1)
    parser.add_argument("--client-order-id", type=int, default=None)
    parser.add_argument("--tif", default="GTC", choices=["GTC", "GTT", "IOC"])
    parser.add_argument("--expires-ts-ms", type=int)
    parser.add_argument("--post-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--reduce-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--recv-window-ms", type=int, default=5000)
    args = parser.parse_args()

    config = load_config(args.env)
    symbol = args.symbol or choose_symbol(config.environment)
    client_order_id = (
        args.client_order_id if args.client_order_id is not None else DEFAULT_CLIENT_ORDER_ID
    )
    request = signed_place_order_request(
        deployment_id=config.environment.deployment_id,
        owner_public_key=config.owner_public_key,
        trading_private_key=config.trading_private_key,
        client_order_id=client_order_id,
        symbol=symbol,
        side=args.side,
        price=args.price,
        size=args.size,
        tif=args.tif,
        expires_ts_ms=args.expires_ts_ms,
        post_only=args.post_only,
        reduce_only=args.reduce_only,
        recv_window_ms=args.recv_window_ms,
    )
    body = [request]

    print("Request JSON:")
    print(pretty_json(body))

    if not args.send:
        print()
        print("Dry run only. Re-run with --send to post this order.")
        return

    response = post_json(f"{config.environment.write_base_url}/api/v1/orders", body)
    print()
    print("Response JSON:")
    print(pretty_json(response))


if __name__ == "__main__":
    main()
